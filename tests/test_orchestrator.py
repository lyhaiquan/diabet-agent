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


class FakeLLM:
    def __init__(self, usage=None, reply="Hãy giảm đường [ada.txt]."):
        self.last_usage = usage
        self.reply = reply

    def __call__(self, messages):
        return self.reply


def run_with_usage(usage, tmp_path=None):
    log = tmp_path / "run.jsonl" if tmp_path else None
    orch = Orchestrator(FakePredictor(0.1), FakeRetriever(), FakeLLM(usage), log_path=log)
    return orch.run(State(question="Ăn gì?", profile=LOW_RISK))


def test_usage_copied_to_state_and_log(tmp_path):
    usage = {"prompt_tokens": 120, "completion_tokens": 30, "seconds": 1.5, "num_ctx": 4096}
    state = run_with_usage(usage, tmp_path)
    assert {k: v for k, v in state.usage.items() if k != "est_prompt_tokens"} == usage
    assert state.usage["est_prompt_tokens"] > 0
    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["usage"] == state.usage


def test_context_near_limit_flag_added():
    state = run_with_usage({"prompt_tokens": 3700, "num_ctx": 4096})
    assert "context_near_limit" in state.flags


def test_context_not_near_limit():
    state = run_with_usage({"prompt_tokens": 1000, "num_ctx": 4096})
    assert "context_near_limit" not in state.flags


def test_plain_function_llm_gives_empty_usage(tmp_path):
    orch, _ = make(0.1, tmp_path=tmp_path)
    state = orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    assert state.usage == {}
    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["usage"] == {}


class WindowedRetriever:
    """Mỗi tài liệu chiếm ~60% ngân sách tài liệu của cửa sổ 1000 token, nên chỉ tài liệu đầu vừa."""

    def search(self, query, k=4):
        from diacare import context
        budget = 1000 - context.ANSWER_RESERVE_TOKENS - context.SYSTEM_RESERVE_TOKENS
        words = int(0.6 * budget * context.CHARS_PER_TOKEN) // 5
        return [{"source": "a.txt", "text": "AAAA " * words}, {"source": "b.txt", "text": "BBBB " * words}]


class WindowedLLM:
    num_ctx = 1000

    def __init__(self):
        self.messages = None
        self.last_usage = {"prompt_tokens": 500, "completion_tokens": 50, "seconds": 1.0, "num_ctx": 1000}

    def __call__(self, messages):
        self.messages = messages
        return "Hãy giảm đường [a.txt]."


def test_context_uses_llm_window_and_records_estimate():
    llm = WindowedLLM()
    orch = Orchestrator(FakePredictor(0.1), WindowedRetriever(), llm)
    state = orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    prompt = "\n".join(m["content"] for m in llm.messages)
    assert "AAAA" in prompt and "BBBB" not in prompt
    assert isinstance(state.usage["est_prompt_tokens"], int) and state.usage["est_prompt_tokens"] > 0



from diacare.db import Store  # noqa: E402


def test_store_gets_one_row_per_run():
    store = Store()
    orch = Orchestrator(FakePredictor(0.9), FakeRetriever(), lambda m: "Hãy giảm đường [ada.txt].", store=store)
    orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    rows = store.runs()
    assert len(rows) == 1
    assert rows[0]["question"] == "Ăn gì?" and rows[0]["risk"] == 0.9
    assert "high_risk_referral" in rows[0]["flags"] and rows[0]["sources"] == ["ada.txt"]


def test_store_logs_session_id():
    store = Store()
    sid = store.start_session()
    orch = Orchestrator(FakePredictor(0.1), FakeRetriever(), lambda m: "ok [ada.txt]", store=store, session_id=sid)
    orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    assert store.runs()[0]["session_id"] == sid


def test_store_logs_invalid_input_run():
    store = Store()
    orch = Orchestrator(FakePredictor(0.1), FakeRetriever(), lambda m: "ok", store=store)
    orch.run(State(question="?", profile=dict(LOW_RISK, BMI=500)))
    rows = store.runs()
    assert len(rows) == 1 and rows[0]["flags"] == ["invalid_input"]


def test_store_logs_llm_error():
    def bad_llm(messages):
        raise RuntimeError("boom")

    store = Store()
    Orchestrator(FakePredictor(0.5), FakeRetriever(), bad_llm, store=store).run(State(question="Ăn gì?", profile=LOW_RISK))
    rows = store.runs()
    assert len(rows) == 1 and rows[0]["error"] == "RuntimeError"


def test_failing_store_does_not_break_run():
    class BadStore:
        def log_run(self, session_id, state, error=None):
            raise RuntimeError("db down")

    orch = Orchestrator(FakePredictor(0.1), FakeRetriever(), lambda m: "ok [ada.txt]", store=BadStore())
    state = orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    assert state.final and "system_error" not in state.flags


def test_jsonl_still_written_with_store(tmp_path):
    orch = Orchestrator(
        FakePredictor(0.1), FakeRetriever(), lambda m: "ok [ada.txt]", log_path=tmp_path / "r.jsonl", store=Store()
    )
    orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    assert len((tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_run_does_not_mutate_callers_history_list():
    orch, _ = make(0.1)
    history = [{"role": "user", "content": "chào"}]
    state = orch.run(State(question="Ăn gì?", profile=LOW_RISK, history=history))
    assert history == [{"role": "user", "content": "chào"}]
    assert len(state.history) == 3


def test_greeting_is_not_scored_and_skips_llm(tmp_path):
    orch, calls = make(0.9, tmp_path=tmp_path)
    state = orch.run(State(question="chào bạn", profile=LOW_RISK))
    assert state.flags == ["small_talk"]
    assert state.risk is None
    assert calls == []
    assert orch.predictor.calls == 0
    assert "Chào bạn" in state.final and "nguy cơ" not in state.final.lower().split("hỏi")[0]
    assert len(state.history) == 2


def test_high_risk_reminder_once_per_session(tmp_path):
    orch, _ = make(0.9, tmp_path=tmp_path)
    first = orch.run(State(question="Ăn gì?", profile=LOW_RISK))
    assert "high_risk_referral" in first.flags
    second = orch.run(State(question="Còn tập thể dục?", profile=LOW_RISK, history=first.history))
    assert "high_risk_referral" not in second.flags
    assert second.risk == 0.9
    # hỏi thẳng về nguy cơ thì nhắc lại
    third = orch.run(State(question="Nguy cơ của tôi có cao không?", profile=LOW_RISK, history=second.history))
    assert "high_risk_referral" in third.flags


def test_greeting_first_does_not_suppress_first_reminder(tmp_path):
    orch, _ = make(0.9, tmp_path=tmp_path)
    hi = orch.run(State(question="xin chào", profile=LOW_RISK))
    q = orch.run(State(question="Ăn gì?", profile=LOW_RISK, history=hi.history))
    assert "high_risk_referral" in q.flags


def _lab_orch(reply="Kết quả HbA1c ở ngưỡng [ada_2024]."):
    from diacare.labs import LabAgent
    calls = []

    def llm(messages):
        calls.append(messages)
        return reply

    return Orchestrator(FakePredictor(0.1), FakeRetriever(), llm, lab_agent=LabAgent(None)), calls


def test_lab_values_reach_advisor_and_rules():
    orch, calls = _lab_orch()
    state = orch.run(State(question="HbA1c của tôi là 7.2%, có sao không?", profile=LOW_RISK))
    assert "lab_diabetes_range" in state.flags
    assert [r["test"] for r in state.labs] == ["hba1c"]
    assert "[ada_2024]" in calls[0][-1]["content"]
    assert "bác sĩ" in state.final


def test_prediabetes_and_low_glucose_flags():
    orch, _ = _lab_orch()
    assert "lab_prediabetes_range" in orch.run(State(question="FPG 110 mg/dL", profile=LOW_RISK)).flags
    low = orch.run(State(question="đường huyết lúc đói 55 mg/dL", profile=LOW_RISK))
    assert "lab_low_glucose" in low.flags and "115" in low.final


def test_normal_lab_values_add_no_flag():
    orch, _ = _lab_orch()
    state = orch.run(State(question="HbA1c 5.2% có ổn không?", profile=LOW_RISK))
    assert not [f for f in state.flags if f.startswith("lab_")]


def test_trace_records_each_agent_and_reports_steps():
    from diacare.factory import build_orchestrator
    from diacare.samples import HIGH_RISK
    from diacare.state import State
    import os
    seen = []
    orch = _trace_orch()
    state = orch.run(State(question="Nên ăn gì?", profile=dict(HIGH_RISK)), on_step=seen.append)
    agents = [e["agent"] for e in state.trace]
    assert agents[0] == "Predictor" and agents[-1] == "Rules" and "Advisor" in agents
    assert seen == state.trace
    assert all(e["ms"] >= 0 for e in state.trace)
    pred = next(e for e in state.trace if e["agent"] == "Predictor")
    assert "cao" in pred["detail"]


def test_on_token_receives_streamed_draft():
    from diacare.samples import LOW_RISK
    from diacare.state import State
    pieces = []
    orch = _trace_orch(streaming=True)
    state = orch.run(State(question="Nên ăn gì?", profile=dict(LOW_RISK)), on_token=pieces.append)
    assert "".join(pieces) == state.draft


def test_on_step_error_does_not_break_pipeline():
    from diacare.samples import LOW_RISK
    from diacare.state import State

    def boom(entry):
        raise RuntimeError("ui")
    state = _trace_orch().run(State(question="Nên ăn gì?", profile=dict(LOW_RISK)), on_step=boom)
    assert "system_error" not in state.flags


def _trace_orch(streaming=False):
    from diacare.orchestrator import Orchestrator

    class P:
        def predict(self, profile):
            return 0.9 if profile["BMI"] > 30 else 0.05

    class R:
        def search(self, q):
            return [{"source": "ada.txt", "text": "Ăn rau."}]

    def llm(messages, on_token=None):
        text = "Hãy ăn nhiều rau [ada.txt]. Tập thể dục đều."
        if on_token:
            for w in text.split(" "):
                on_token(w + " ")
            return "".join(w + " " for w in text.split(" "))
        return text

    return Orchestrator(P(), R(), llm if streaming else (lambda messages: "Hãy ăn nhiều rau [ada.txt]."))
