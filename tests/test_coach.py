"""Agent Q-learning nhắc việc hằng ngày (diacare.coach) và người bệnh mô phỏng (diacare.coach_sim)."""
from datetime import date, datetime, time, timedelta

import numpy as np

from diacare.coach import (CHOICES, DEFAULT_COACH_PATH, NUDGES, QCoach, STATES, day_reward, day_state, load_coach,
                           today_nudge)
from diacare.coach_sim import behavior_policy, evaluate, make_patients, rule_policy, run_episode
from diacare.journal import VN_TZ
from diacare.rl import ACTION_IDS

D = date(2026, 11, 20)


def g(day, value, context="fasting", hh=7):
    return {"kind": "glucose", "value": value, "context": context,
            "measured_at": datetime.combine(day, time(hh, 0), tzinfo=VN_TZ).isoformat()}


def test_state_from_last_three_days_only():
    readings = [g(D - timedelta(days=1), 110), g(D - timedelta(days=2), 120), g(D, 300)]  # số đo hôm nay không tính
    s = day_state(readings, D, prev_action="weight_diet")
    assert (s["adherence"], s["control"], s["prev"], s["urgent"]) == ("vừa", "đạt", "lối sống", False)
    assert day_state([], D)["control"] == "chưa đo" and day_state([], D)["adherence"] == "ít"
    assert len(STATES) == 36


def test_danger_yesterday_triggers_mask():
    s = day_state([g(D - timedelta(days=1), 62)], D)
    assert s["urgent"] and s["control"] == "nguy hiểm"
    assert QCoach().act(s) == ("urgent_eval", 1.0, "mặt nạ an toàn")


def test_reward_missing_is_worse_than_high_and_repeat_penalized():
    missed = day_reward([], D, "weight_diet")
    high = day_reward([g(D, 190)], D, "weight_diet")
    good = day_reward([g(D, 110)], D, "weight_diet")
    hypo = day_reward([g(D, 60)], D, "weight_diet")
    assert missed < hypo < high < good  # bỏ đo luôn tệ nhất, để agent không học cách che hạ đường huyết
    assert day_reward([g(D, 50)], D, "weight_diet") > missed
    assert day_reward([g(D, 110)], D, "weight_diet", prev_action="weight_diet") < good


def test_q_learning_learns_simple_preference_and_never_explores_urgent():
    s = {"adherence": "vừa", "control": "cao", "prev": "không", "urgent": False}
    tr = [{"state": s, "action": a, "reward": 1.0 if a == "physical_activity" else -0.5, "next_state": None}
          for a in CHOICES for _ in range(5)]
    coach = QCoach(gamma=0.9)
    coach.fit(tr, epochs=50)
    assert coach.act(s)[0] == "physical_activity"
    rng = np.random.default_rng(0)
    picks = {coach.act(s, epsilon=1.0, rng=rng)[0] for _ in range(300)}
    assert "urgent_eval" not in picks and picks == set(CHOICES)


def test_gamma_propagates_future_reward():
    s1 = {"adherence": "ít", "control": "chưa đo", "prev": "không", "urgent": False}
    s2 = {"adherence": "vừa", "control": "đạt", "prev": "theo dõi", "urgent": False}
    tr = [{"state": s1, "action": "glycemic_followup", "reward": 0.0, "next_state": s2},
          {"state": s1, "action": "weight_diet", "reward": 0.2, "next_state": None},
          {"state": s2, "action": "preventive_habit", "reward": 2.0, "next_state": None}]
    far, near = QCoach(gamma=0.9), QCoach(gamma=0.0)
    far.fit(tr, epochs=300)
    near.fit(tr, epochs=300)
    assert far.act(s1)[0] == "glycemic_followup" and near.act(s1)[0] == "weight_diet"


def test_simulated_cohort_shape_and_reproducible():
    pts = make_patients(30, seed=7)
    assert len(pts) == 30 and all(14 <= p["days"] <= 28 for p in pts)
    assert all(p["name"].startswith("Bệnh nhân mẫu") for p in pts)
    a = run_episode(pts[0], behavior_policy(0.6), D, np.random.default_rng(1))
    b = run_episode(pts[0], behavior_policy(0.6), D, np.random.default_rng(1))
    assert a == b and len(a[1]) == pts[0]["days"] and a[1][-1]["next_state"] is None
    assert all(0 < st["propensity"] <= 1 for st in a[1])


def test_evaluate_reports_ci():
    r = evaluate(rule_policy, make_patients(10, seed=3), D, seed=1, days=7)
    assert r["n"] == 10 and r["ci95"][0] <= r["mean_return"] <= r["ci95"][1]


def test_shipped_model_is_marked_synthetic_and_gives_a_nudge():
    coach = load_coach(DEFAULT_COACH_PATH)
    assert coach is not None and "mô phỏng" in coach.meta["source"] and coach.gamma == 0.9
    assert coach.q.shape == (len(STATES), len(ACTION_IDS))
    n = today_nudge(coach, [g(D - timedelta(days=1), 150)], D)
    assert n["action"] in CHOICES and n["text"] == NUDGES[n["action"]]
    assert "liều" not in " ".join(NUDGES.values())


def test_daily_nudge_chosen_once_per_day_and_feeds_tomorrow(tmp_path):
    from diacare.coach import daily_nudge, history_rewards
    from diacare.db import Store
    from diacare.samples import HIGH_RISK
    store = Store(str(tmp_path / "c.db"))
    pid = store.save_patient("Bệnh nhân mẫu", HIGH_RISK)
    store.add_reading(pid, "glucose", 150, datetime.combine(D - timedelta(days=1), time(7), tzinfo=VN_TZ),
                      unit="mg/dL", context="fasting")
    coach = load_coach(DEFAULT_COACH_PATH)
    first = daily_nudge(store, coach, pid, D)
    again = daily_nudge(store, coach, pid, D)
    assert again["action"] == first["action"] and len(store.coach_events(pid)) == 1
    nxt = daily_nudge(store, coach, pid, D + timedelta(days=1))
    assert nxt["state"]["prev_action"] == first["action"]
    hist = history_rewards(store, pid)
    assert [h["day"] for h in hist] == [str(D), str(D + timedelta(days=1))] and hist[0]["reward"] == -1.0
    assert [h["day"] for h in history_rewards(store, pid, today=D + timedelta(days=1))] == [str(D)]
