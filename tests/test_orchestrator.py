import json

from diacare.orchestrator import Orchestrator
from diacare.samples import LOW_RISK
from diacare.state import State


class FakePredictor:
    def __init__(self, risk):
        self.risk = risk
        self.calls = 0

    def predict(self, profile):
        self.calls += 1
        return self.risk


class FakeRetriever:
    def search(self, query, k=4):
        return [{"source": "ada.txt", "text": "Hạn chế đường."}]


def make(risk=0.9, reply="Hãy giảm đường [ada.txt].", tmp_path=None):
    calls = []

    def llm(messages):
        calls.append(messages)
        return reply

    log = tmp_path / "run.jsonl" if tmp_path else None
    return Orchestrator(FakePredictor(risk), FakeRetriever(), llm, log_path=log), calls


def test_full_flow_high_risk(tmp_path):
    orch, _ = make(0.9, tmp_path=tmp_path)
    state = orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    assert state.risk == 0.9
    assert "high_risk_referral" in state.flags
    assert "bác sĩ" in state.final
    assert len(state.history) == 2
    lines = (tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["sources"] == ["ada.txt"] and record["risk"] == 0.9


def test_unsafe_llm_output_is_blocked():
    orch, _ = make(0.1, reply="Bạn nên bỏ thuốc.")
    state = orch.run(State(question="Có nên bỏ thuốc?", profile=LOW_RISK))
    assert "unsafe_advice_blocked" in state.flags
    assert "bỏ thuốc" not in state.final.lower()


def test_invalid_profile_short_circuits():
    orch, calls = make()
    state = orch.run(State(question="?", profile=dict(LOW_RISK, BMI=500)))
    assert state.flags == ["invalid_input"]
    assert calls == [] and orch.predictor.calls == 0


def test_missing_feature_short_circuits():
    profile = dict(LOW_RISK)
    del profile["Income"]
    orch, calls = make()
    state = orch.run(State(question="?", profile=profile))
    assert state.flags == ["invalid_input"]
    assert calls == [] and orch.predictor.calls == 0


def test_llm_failure_returns_system_error(tmp_path):
    def bad_llm(messages):
        raise RuntimeError("boom")

    orch = Orchestrator(FakePredictor(0.5), FakeRetriever(), bad_llm, log_path=tmp_path / "run.jsonl")
    state = orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    assert state.flags == ["system_error"]
    assert "sự cố" in state.final
    assert state.history == []
    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["error"] == "RuntimeError"


def test_predictor_failure_returns_system_error():
    class BadPredictor:
        def predict(self, profile):
            raise ValueError("x")

    orch = Orchestrator(BadPredictor(), FakeRetriever(), lambda m: "ok")
    state = orch.run(State(question="?", profile=LOW_RISK))
    assert state.flags == ["system_error"]
