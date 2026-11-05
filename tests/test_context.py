import math

import pytest
from diacare import context
from diacare.context import (
    ANSWER_RESERVE_TOKENS,
    CHARS_PER_TOKEN,
    DOC_LABEL_TOKENS,
    HISTORY_TOKEN_BUDGET,
    SYSTEM_RESERVE_TOKENS,
    build_context,
    estimate_tokens,
)
from diacare.state import State


def make_state(**kw):
    return State(question="Tôi nên ăn gì?", profile={"BMI": 30}, **kw)


def doc_cost(d):
    return estimate_tokens(d["text"]) + DOC_LABEL_TOKENS


def test_predictor_sees_only_profile():
    ctx = build_context("predictor", make_state())
    assert ctx == {"profile": {"BMI": 30}}


def test_estimate_tokens_uses_chars_per_token():
    assert estimate_tokens("a" * 25) == math.ceil(25 / context.CHARS_PER_TOKEN)


def test_advisor_drops_doc_over_budget_and_stops():
    docs = [{"source": "a", "text": "x" * 100}, {"source": "b", "text": "y" * 100},
            {"source": "c", "text": "z" * 5}]
    state = make_state(docs=docs, risk=0.4)
    fixed = ANSWER_RESERVE_TOKENS + SYSTEM_RESERVE_TOKENS + estimate_tokens(state.question)
    num_ctx = fixed + doc_cost(docs[0]) + 1  # vừa đủ doc đầu, doc thứ hai không vừa
    ctx = build_context("advisor", state, num_ctx=num_ctx)
    assert ctx["docs"] == [docs[0]]  # doc "c" nhỏ cũng không được nhảy cóc
    assert ctx["risk"] == 0.4


def test_advisor_trims_history_by_tokens():
    n = math.ceil(HISTORY_TOKEN_BUDGET * CHARS_PER_TOKEN / 4)
    history = [{"role": "user", "content": f"{i:02d}" + "x" * (n - 2)} for i in range(20)]
    ctx = build_context("advisor", make_state(history=history))
    kept = ctx["history"]
    assert 1 <= len(kept) < 20
    assert kept == history[-len(kept):]


def test_advisor_budget_exhausted_gives_no_docs():
    docs = [{"source": "a", "text": "x"}]
    ctx = build_context("advisor", make_state(docs=docs), num_ctx=ANSWER_RESERVE_TOKENS)
    assert ctx["docs"] == []


def test_advisor_est_tokens_adds_up():
    docs = [{"source": "a", "text": "x" * 100}, {"source": "b", "text": "y" * 50}]
    history = [{"role": "user", "content": "hello" * 10}, {"role": "assistant", "content": "ok"}]
    state = make_state(docs=docs, history=history)
    ctx = build_context("advisor", state)
    assert ctx["docs"] == docs
    expected = (SYSTEM_RESERVE_TOKENS + estimate_tokens(state.question)
                + sum(estimate_tokens(m["content"]) for m in history)
                + sum(doc_cost(d) for d in docs))
    assert ctx["est_tokens"] == expected


def test_rule_gets_risk_and_draft():
    ctx = build_context("rule", make_state(risk=0.9, draft="abc"))
    assert ctx["risk"] == 0.9 and ctx["draft"] == "abc"


def test_unknown_agent_raises():
    with pytest.raises(ValueError):
        build_context("nope", make_state())
