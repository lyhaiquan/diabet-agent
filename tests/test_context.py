import pytest
from diacare.context import MAX_DOC_CHARS, MAX_HISTORY_TURNS, build_context
from diacare.state import State


def make_state(**kw):
    return State(question="Tôi nên ăn gì?", profile={"BMI": 30}, **kw)


def test_predictor_sees_only_profile():
    ctx = build_context("predictor", make_state())
    assert ctx == {"profile": {"BMI": 30}}


def test_advisor_respects_doc_budget():
    docs = [{"source": "a", "text": "x" * (MAX_DOC_CHARS - 10)},
            {"source": "b", "text": "y" * 100}]
    ctx = build_context("advisor", make_state(docs=docs, risk=0.4))
    assert [d["source"] for d in ctx["docs"]] == ["a"]
    assert ctx["risk"] == 0.4


def test_advisor_trims_history():
    history = [{"role": "user", "content": str(i)} for i in range(20)]
    ctx = build_context("advisor", make_state(history=history))
    assert len(ctx["history"]) == MAX_HISTORY_TURNS
    assert ctx["history"][-1]["content"] == "19"


def test_rule_gets_risk_and_draft():
    ctx = build_context("rule", make_state(risk=0.9, draft="abc"))
    assert ctx["risk"] == 0.9 and ctx["draft"] == "abc"


def test_unknown_agent_raises():
    with pytest.raises(ValueError):
        build_context("nope", make_state())
