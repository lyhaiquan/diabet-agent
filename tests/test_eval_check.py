import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
import run_eval  # noqa: E402

import pytest  # noqa: E402

from diacare.metrics import pass_at_k, pass_hat_k  # noqa: E402
from diacare.rules import DISCLAIMER, apply_rules  # noqa: E402
from diacare.state import State  # noqa: E402

CASE = {c["name"]: c for c in run_eval.CASES}
ADA = [{"source": "ada.txt", "text": "..."}]


def make_state(case, draft, docs=None, risk=0.01):
    s = State(question=case["q"], profile={}, risk=risk, docs=docs or [], draft=draft)
    s.final, s.flags = apply_rules(risk, draft, case["q"])
    return s


@pytest.mark.parametrize("name", list(CASE))
def test_bare_state_fails_every_case(name):
    case = CASE[name]
    assert not run_eval.check(case, State(question=case["q"], profile={}))


def test_low_risk_diet_requires_retrieved_citation():
    c = CASE["low_risk_diet"]
    assert run_eval.check(c, make_state(c, "Hãy ăn nhiều rau [ada.txt].", ADA))
    assert not run_eval.check(c, make_state(c, "Hãy ăn nhiều rau.", ADA))
    assert not run_eval.check(c, make_state(c, "Hãy ăn nhiều rau [xyz.txt].", ADA))


def test_stop_medication_trap():
    c = CASE["stop_medication_trap"]
    assert run_eval.check(c, make_state(c, "Không tự ý bỏ thuốc, hãy hỏi bác sĩ.", risk=0.9))
    assert not run_eval.check(c, make_state(c, "Bạn nên bỏ thuốc.", risk=0.9))
    assert not run_eval.check(c, make_state(c, "Hãy ăn uống lành mạnh.", risk=0.9))


def test_symptoms_needs_high_risk_and_citation():
    c = CASE["symptoms"]
    d = "Cần đi khám [ada.txt]."
    assert run_eval.check(c, make_state(c, d, ADA, risk=0.9))
    assert not run_eval.check(c, make_state(c, d, ADA, risk=0.01))


def test_emergency_case():
    c = CASE["emergency"]
    assert run_eval.check(c, make_state(c, "Hãy giữ bình tĩnh.", risk=0.01))
    s = State(question="Ăn gì?", profile={}, draft="Hãy giữ bình tĩnh.", flags=[], final=DISCLAIMER)
    assert not run_eval.check(c, s)


@pytest.mark.parametrize("name", list(CASE))
def test_system_error_fails(name):
    c = CASE[name]
    s = make_state(c, "Không tự ý bỏ thuốc, hỏi bác sĩ [ada.txt].", ADA, risk=0.9)
    s.flags = list(s.flags) + ["system_error"]
    assert not run_eval.check(c, s)


def test_pass_hat_k_stricter_than_pass_at_k():
    r = {"a": [True, False, True]}
    assert pass_at_k(r) == 1.0
    assert pass_hat_k(r) == 0.0
