import json

import numpy as np

from diacare.advisor import build_messages
from diacare.context import RL_TOKEN_BUDGET, build_context, estimate_tokens
from diacare.db import Store
from diacare.factory import parse_features
from diacare.orchestrator import Orchestrator
from diacare.rl import (ACTION_IDS, FEATURE_NAMES, LinearBandit, RLAgent, evaluate_policy, extract_rl_state,
                        format_rl, is_urgent, load_policy, load_state_freq, off_policy_report, prior_reward,
                        sample_state, save_policy, train_policy)
from diacare.samples import HIGH_RISK, LOW_RISK
from diacare.state import State

CALM = {"band": "trung bình", "lab": "none", "diagnosed": False, "overweight": True, "inactive": True,
        "cardio_smoke": False, "topic": "general", "prev_action": None}


def greedy(agent):
    agent.epsilon = 0.0
    return agent


def test_state_distribution_comes_from_brfss():
    freq = load_state_freq()
    assert freq["n"] == 253680 and sum(p["n"] for p in freq["profiles"]) == freq["n"]
    assert abs(sum(freq["topics"].values()) - 1) < 1e-3
    s = sample_state(np.random.default_rng(0), freq)
    assert set(s) >= {"band", "lab", "diagnosed", "overweight", "inactive", "cardio_smoke", "topic"}


def test_prior_reward_is_on_feedback_scale():
    rng = np.random.default_rng(1)
    for _ in range(200):
        s = sample_state(rng)
        assert all(-1.0 <= prior_reward(s, a) <= 1.0 for a in ACTION_IDS)


def test_warm_start_beats_baselines_on_heldout_states():
    m = evaluate_policy(train_policy(n_samples=5000, seed=42), n_eval=1000, seed=7)
    assert m["policy"] > m["random"] + 0.5
    assert m["policy"] > m["always_urgent"] + 0.4
    assert m["policy"] <= m["oracle"]


def test_shipped_policy_loads():
    m = load_policy()
    assert m.A.shape == (len(ACTION_IDS), len(FEATURE_NAMES), len(FEATURE_NAMES))


def test_safety_mask_forces_urgent_eval_without_exploration():
    agent = RLAgent(epsilon=1.0, seed=0)          # thăm dò 100% vẫn không được bỏ "khám sớm"
    for _ in range(20):
        st = State(question="Kết quả này có sao không?", profile=LOW_RISK, risk=0.1,
                   labs=[{"test": "hba1c", "level": "diabetes", "value_std": 8.2, "unit_std": "%", "label": "HbA1c"}])
        rec = agent.recommend(st)
        assert rec["action"] == "urgent_eval" and rec["propensity"] == 1.0 and rec["mode"] == "mặt nạ an toàn"
    rec = agent.recommend(State(question="Tôi khát nước liên tục, tiểu nhiều", profile=LOW_RISK, risk=0.1))
    assert rec["action"] == "urgent_eval"


def test_greedy_choice_follows_modifiable_factors():
    agent = greedy(RLAgent())
    ex = State(question="Tôi nên tập thể dục thế nào?", profile=dict(LOW_RISK, PhysActivity=0, BMI=21.0), risk=0.25)
    assert agent.recommend(ex)["action"] == "physical_activity"
    diet = State(question="Tôi nên ăn uống thế nào để giảm cân?",
                 profile=dict(LOW_RISK, BMI=31.0, PhysActivity=1, Fruits=0, Veggies=0), risk=0.3)
    assert agent.recommend(diet)["action"] == "weight_diet"


def test_exploration_logs_correct_propensity():
    agent = RLAgent(epsilon=0.3, seed=3)
    k = len(ACTION_IDS)
    seen = {agent.recommend(dict(CALM))["propensity"] for _ in range(300)}
    assert seen == {round(1 - 0.3 + 0.3 / k, 4), round(0.3 / k, 4)}


def test_thumbs_up_raises_and_thumbs_down_lowers_shipped_policy():
    for s in (CALM, {**CALM, "topic": "nutrition"}, {**CALM, "band": "cao"}):
        for a in ACTION_IDS:
            up, down = RLAgent(epsilon=0), RLAgent(epsilon=0)
            before = float(up.model.predict(s)[ACTION_IDS.index(a)])
            assert up.update(s, a, +1.0) > 0 or before >= 1.0
            assert down.update(s, a, -1.0) < 0 or before <= -1.0


def test_feedback_is_stored_learned_once_and_survives_restart():
    store = Store(":memory:")
    agent = greedy(RLAgent(store=store))
    rec = agent.recommend(dict(CALM))
    eid = agent.record(rec, session_id=1, run_id=None)
    res = agent.feedback(eid, "down")
    assert res["reward"] == -1.0 and res["delta"] < 0 and agent.model.n_updates == 1
    assert agent.feedback(eid, "up") is None                  # chấm lại không được học lần hai
    assert store.get_rl_event(eid)["reward"] == -1.0
    again = RLAgent(store=store)                               # mở lại ứng dụng: nạp mô hình đã học
    assert again.model.n_updates == 1 and again.version == "prior+1"
    assert np.allclose(again.model.weights(), agent.model.weights())


def test_simulated_user_feedback_shifts_policy():
    """Người dùng mô phỏng luôn thích "vận động" ở trạng thái này và chê mọi trọng tâm khác.
    Sau vài chục lượt phản hồi, chính sách tham lam phải chuyển sang "vận động"."""
    store = Store(":memory:")
    agent = RLAgent(store=store, epsilon=0.3, seed=11)
    s = {**CALM, "topic": "nutrition"}
    assert greedy(RLAgent()).recommend(dict(s))["action"] != "physical_activity"
    for _ in range(200):
        rec = agent.recommend(dict(s))
        eid = agent.record(rec, session_id=1)
        agent.feedback(eid, "up" if rec["action"] == "physical_activity" else "down")
    agent.epsilon = 0.0
    assert agent.recommend(dict(s))["action"] == "physical_activity"
    rep = off_policy_report(store.rl_events(), agent.model)
    assert rep["n_rated"] == 200 and rep["snips"] > rep["logged_mean_reward"]


def test_repeat_penalty_uses_history_from_store():
    store = Store(":memory:")
    agent = greedy(RLAgent(store=store))
    sid = store.start_session()
    first = agent.recommend(dict(CALM))
    store.add_message(sid, "user", "?")
    store.add_message(sid, "assistant", "...", rl_event_id=agent.record(first, sid))
    hist = store.get_history(sid)
    assert hist[-1]["rl_action"] == first["action"]
    st = State(question="Tôi nên làm gì?", profile=dict(LOW_RISK, BMI=31, PhysActivity=0), risk=0.3, history=hist)
    assert extract_rl_state(st)["prev_action"] == first["action"]


def test_save_and_load_policy_roundtrip(tmp_path):
    m = train_policy(n_samples=500, seed=1)
    loaded = load_policy(save_policy(m, tmp_path / "rl_policy.json", meta={"note": "test"}))
    assert np.allclose(loaded.weights(), m.weights())
    assert isinstance(loaded, LinearBandit)


def test_orchestrator_runs_rl_step_records_event_and_feeds_advisor(tmp_path):
    seen = []

    class P:
        def predict(self, profile):
            return 0.65

    class R:
        def search(self, q, k=4):
            return [{"source": "ada.txt", "text": "Đi khám và xét nghiệm HbA1c."}]

    def llm(messages):
        seen.append(messages)
        return "Bạn nên đi khám sớm [ada.txt]."

    store = Store(":memory:")
    sid = store.start_session()
    orch = Orchestrator(P(), R(), llm, log_path=tmp_path / "run.jsonl", store=store, session_id=sid,
                        rl_agent=RLAgent(store=store, epsilon=0))
    state = orch.run(State(question="Nguy cơ của tôi cao thì làm gì?", profile=HIGH_RISK))
    steps = [t["agent"] for t in state.trace]
    assert steps.index("Retriever") < steps.index("RL") < steps.index("Context") < steps.index("Advisor")
    assert state.rl["action"] in ACTION_IDS
    assert "[rl_policy]" in seen[0][-1]["content"]
    ev = store.get_rl_event(state.rl["event_id"])
    assert ev["action"] == state.rl["action"] and ev["run_id"] is not None and ev["reward"] is None
    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["rl_action"] == state.rl["action"]


def test_rl_on_by_default_and_in_context():
    assert "rl" in parse_features(None) or "rl" in parse_features("default")
    assert "rl" in parse_features("v3") and "rl" in parse_features("all") and "rl" in parse_features("v2,rl")
    assert "rl" not in parse_features("v2")
    assert format_rl(None) == ""
    state = State(question="?", profile=LOW_RISK, rl=greedy(RLAgent()).recommend(State(question="?", profile=LOW_RISK, risk=0.1)))
    ctx = build_context("advisor", state)
    assert "[rl_policy]" in ctx["rl_text"]
    assert estimate_tokens(ctx["rl_text"]) <= RL_TOKEN_BUDGET
    assert "[rl_policy]" in build_messages(ctx)[-1]["content"]
    assert not is_urgent(extract_rl_state(state))
