import json

from diacare.advisor import build_messages
from diacare.context import RL_TOKEN_BUDGET, build_context, estimate_tokens
from diacare.factory import parse_features
from diacare.orchestrator import Orchestrator
from diacare.rl import (ACTION_IDS, RLAgent, clinical_reward, evaluate_policy, extract_rl_state,
                        format_rl, load_policy, save_policy, train_policy)
from diacare.samples import HIGH_RISK, LOW_RISK
from diacare.state import State


def test_trained_policy_beats_random_baseline():
    weights = train_policy(episodes=1500, seed=42)
    metrics = evaluate_policy(weights, n_eval=500, seed=7)
    assert metrics["q_mean_reward"] > metrics["random_mean_reward"] + 1.0
    assert metrics["improvement"] > 1.0


def test_rl_agent_prioritizes_urgent_eval_for_critical_labs_or_high_risk():
    agent = RLAgent(train_policy(episodes=2000, seed=42))
    st_lab = State(
        question="Kết quả này có sao không?",
        profile=LOW_RISK,
        risk=0.1,
        labs=[{"test": "hba1c", "level": "diabetes", "value_std": 8.2, "unit_std": "%", "label": "HbA1c"}],
    )
    rec = agent.recommend(st_lab)
    assert rec["action"] == "urgent_eval"
    assert len(rec["ranking"]) == 3


def test_rl_agent_prioritizes_lifestyle_for_modifiable_factors():
    agent = RLAgent(train_policy(episodes=2000, seed=42))
    profile_inact = dict(LOW_RISK, PhysActivity=0, BMI=21.0, Fruits=1, Veggies=1)
    st_ex = State(question="Tôi nên tập thể dục thế nào?", profile=profile_inact, risk=0.25)
    assert agent.recommend(st_ex)["action"] == "physical_activity"

    profile_ow = dict(LOW_RISK, BMI=31.0, PhysActivity=1, Fruits=0, Veggies=0)
    st_diet = State(question="Tôi nên ăn uống thế nào để giảm cân?", profile=profile_ow, risk=0.3)
    assert agent.recommend(st_diet)["action"] == "weight_diet"


def test_rl_agent_penalizes_repeating_same_lifestyle_action():
    agent = RLAgent(train_policy(episodes=2000, seed=42))
    s = {
        "band": "trung bình",
        "lab": "none",
        "diagnosed": False,
        "overweight": True,
        "inactive": True,
        "cardio_smoke": False,
        "topic": "general",
        "prev_action": None,
    }
    first = agent.recommend(s)["action"]
    q_before = agent.q_values(s)[ACTION_IDS.index(first)]
    q_after = agent.q_values({**s, "prev_action": first})[ACTION_IDS.index(first)]
    assert round(q_before - q_after, 2) == 0.8


def test_online_update_adjusts_action_q_value():
    agent = RLAgent(train_policy(episodes=500, seed=42), alpha=0.1)
    s = extract_rl_state(State(question="Tôi nên ăn gì?", profile=LOW_RISK, risk=0.1))
    before = float(agent.q_values(s)[ACTION_IDS.index("weight_diet")])
    td = agent.update(s, "weight_diet", reward=5.0)
    after = float(agent.q_values(s)[ACTION_IDS.index("weight_diet")])
    assert td > 0 and after > before


def test_save_and_load_policy_roundtrip(tmp_path):
    w = train_policy(episodes=300, seed=1)
    p = save_policy(w, tmp_path / "rl_policy.json", meta={"note": "test"})
    loaded = load_policy(p)
    assert loaded.shape == w.shape
    assert (loaded == w).all()


def test_orchestrator_runs_rl_step_and_feeds_advisor(tmp_path):
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

    orch = Orchestrator(P(), R(), llm, log_path=tmp_path / "run.jsonl", rl_agent=RLAgent())
    state = orch.run(State(question="Nguy cơ của tôi cao thì làm gì?", profile=HIGH_RISK))
    steps = [t["agent"] for t in state.trace]
    assert steps.index("Retriever") < steps.index("RL") < steps.index("Context") < steps.index("Advisor")
    assert state.rl["action"] in ACTION_IDS
    prompt = seen[0][-1]["content"]
    assert "[rl_policy]" in prompt
    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["rl_action"] == state.rl["action"]


def test_context_and_features_include_rl():
    assert "rl" in parse_features("v3")
    assert "rl" in parse_features("all")
    assert "rl" in parse_features("v2,rl")
    assert "rl" not in parse_features("v2")
    assert format_rl(None) == ""
    state = State(question="?", profile=LOW_RISK, rl=RLAgent().recommend(State(question="?", profile=LOW_RISK, risk=0.1)))
    ctx = build_context("advisor", state)
    assert "[rl_policy]" in ctx["rl_text"]
    assert estimate_tokens(ctx["rl_text"]) <= RL_TOKEN_BUDGET
    assert "[rl_policy]" in build_messages(ctx)[-1]["content"]
    assert clinical_reward(extract_rl_state(state), "preventive_habit") > 0
