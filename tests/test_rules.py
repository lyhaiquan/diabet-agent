import unicodedata

import pytest

from diacare.rules import (
    DISCLAIMER,
    apply_rules,
    is_unsafe_advice,
    risk_band,
    validate_profile,
)
from diacare.samples import LOW_RISK


def test_disclaimer_always_appended():
    final, flags = apply_rules(0.1, "Hãy ăn nhiều rau.")
    assert DISCLAIMER in final
    assert flags == []


def test_high_risk_adds_referral():
    final, flags = apply_rules(0.8, "Hãy ăn nhiều rau.")
    assert "high_risk_referral" in flags
    assert "HbA1c" in final


def test_unsafe_advice_is_replaced():
    final, flags = apply_rules(0.1, "Bạn có thể ngừng insulin vài ngày.")
    assert "unsafe_advice_blocked" in flags
    assert "ngừng insulin" not in final.lower()
    assert "bác sĩ" in final


def test_validate_profile_rejects_absurd_bmi():
    bad = dict(LOW_RISK, BMI=500)
    assert validate_profile(bad) != []
    assert validate_profile(LOW_RISK) == []


@pytest.mark.parametrize("text", [
    "Bạn có thể dừng insulin hoặc thôi uống metformin.",
    "Bạn nên ngừng tiêm insulin.",
    "Hãy giảm liều insulin nhé.",
    "You can stop taking insulin.",
    "Bạn nên tự ý tăng liều.",
    unicodedata.normalize("NFD", "Bạn nên ngừng insulin."),
])
def test_unsafe_advice_detected(text):
    assert is_unsafe_advice(text) is True


@pytest.mark.parametrize("text", [
    "Không được tự ý bỏ thuốc.",
    "Đừng ngừng insulin khi chưa hỏi bác sĩ.",
    "Hãy ăn nhiều rau và tập thể dục.",
    "Do not stop your insulin without asking a doctor.",
])
def test_safe_advice_not_blocked(text):
    assert is_unsafe_advice(text) is False


def test_validate_profile_valid():
    assert validate_profile(LOW_RISK) == []


def test_validate_profile_string_bmi():
    assert validate_profile(dict(LOW_RISK, BMI="30")) != []


def test_validate_profile_string_binary():
    assert validate_profile(dict(LOW_RISK, Smoker="yes")) != []


def test_validate_profile_age_out_of_code_range():
    assert validate_profile(dict(LOW_RISK, Age=45)) != []


def test_validate_profile_non_integer():
    assert validate_profile(dict(LOW_RISK, Age=3.5)) != []


def test_validate_profile_missing_feature():
    p = dict(LOW_RISK)
    del p["Income"]
    errors = validate_profile(p)
    assert any("Income" in e for e in errors)


def test_validate_profile_nan():
    assert validate_profile(dict(LOW_RISK, BMI=float("nan"))) != []


@pytest.mark.parametrize("risk,band", [
    (0.1, "thấp"), (0.3, "trung bình"), (0.5, "cao"), (0.9, "cao"),
])
def test_risk_band(risk, band):
    assert risk_band(risk) == band


def test_symptom_question_adds_referral():
    final, flags = apply_rules(
        0.01, "Hãy ăn nhiều rau.", "Dạo này tôi khát nước nhiều và tiểu nhiều"
    )
    assert "symptom_referral" in flags
    assert "xét nghiệm đường huyết" in final


def test_emergency_question_adds_referral():
    final, flags = apply_rules(0.01, "Hãy nghỉ ngơi.", "Tôi bị lú lẫn và khó thở")
    assert "emergency_referral" in flags
    assert "115" in final


def test_neutral_question_no_symptom_flags():
    _, flags = apply_rules(0.01, "Hãy ăn nhiều rau.", "Nên ăn gì buổi sáng?")
    assert "symptom_referral" not in flags
    assert "emergency_referral" not in flags
