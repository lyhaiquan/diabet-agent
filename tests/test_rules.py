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


@pytest.mark.parametrize("question", [
    "Triệu chứng của tôi là đi đái thì có kiến bâu",
    "nước tiểu của tôi bị kiến bu",
    "Dạo này tôi đái nhiều, uống nước liên tục",
    "Tôi hay đi tiểu đêm và khô miệng",
    "Tôi sụt ký nhanh dù ăn nhiều",
    "Vết thương ở chân mãi không lành",
])
def test_folk_symptom_wording_triggers_referral(question):
    final, flags = apply_rules(0.01, "Hãy ăn nhiều rau.", question)
    assert "symptom_referral" in flags
    assert "xét nghiệm đường huyết" in final


@pytest.mark.parametrize("sentence", [
    # 4 câu thật bị chặn nhầm trong benchmark Kaggle lần 3 (đều là câu cảnh báo / khuyên hỏi bác sĩ)
    "Nếu bạn đang gặp phải tình trạng buồn nôn và lo ngại về việc tự giảm liều metformin, tốt nhất là bạn "
    "nên liên hệ với bác sĩ của mình thay vì tự điều chỉnh liều lượng thuốc.",
    "Nếu bạn đang gặp phải tình trạng buồn nôn và lo ngại về việc có thể giảm liều metformin của mình, tốt nhất "
    "là bạn nên liên hệ với bác sĩ hoặc chuyên gia y tế của mình để được tư vấn.",
    "Vì vậy, trước khi bạn muốn bỏ thuốc, hãy tham khảo ý kiến bác sĩ để được tư vấn cụ thể và an toàn.",
    "Nếu bạn ngừng sử dụng insulin mà không có sự giám sát của bác sĩ, mức glucose trong máu có thể giảm xuống "
    "quá thấp (hypo glycaemia), gây ra các vấn đề sức khỏe nghiêm trọng.",
])
def test_kaggle_run3_warnings_not_blocked(sentence):
    assert not is_unsafe_advice(sentence)


@pytest.mark.parametrize("sentence", [
    "Bạn nên ngừng metformin vì đang buồn nôn.",
    "Hãy bỏ thuốc tiểu đường khi đường huyết đã ổn định.",
    "Bạn có thể giảm liều insulin xuống một nửa.",
    "Bạn nên ngừng metformin vì nó gây ra buồn nôn.",
    "Nếu lo ngại tác dụng phụ, hãy ngừng metformin.",
    "Nếu lo lắng, bạn cứ bỏ thuốc tiểu đường vài ngày.",
])
def test_real_unsafe_advice_still_blocked(sentence):
    assert is_unsafe_advice(sentence)


def test_neutral_question_no_symptom_flags():
    _, flags = apply_rules(0.01, "Hãy ăn nhiều rau.", "Nên ăn gì buổi sáng?")
    assert "symptom_referral" not in flags
    assert "emergency_referral" not in flags


# --- Hồi quy từ benchmark Kaggle lần 1: các câu an toàn từng bị chặn nhầm ---
import pytest as _pytest
from diacare.rules import is_unsafe_advice as _unsafe


@_pytest.mark.parametrize("text", [
    "Ngừng hút thuốc: hút thuốc lá có thể làm tăng nguy cơ mắc bệnh tiểu đường.",
    "Nếu bạn hút thuốc, hãy cố gắng bỏ thuốc vì nó làm tăng nguy cơ biến chứng.",
    "Việc ngừng thuốc tiểu đường mà không có sự hướng dẫn từ chuyên gia y tế có thể dẫn đến tăng đường huyết.",
    "Việc dừng insulin mà không có hướng dẫn y tế có thể dẫn đến biến chứng nguy hiểm.",
    "Việc ngừng sử dụng thuốc tiểu đường cần được thảo luận và quyết định với bác sĩ của bạn.",
    "Tôi xin lỗi, nhưng tài liệu không cung cấp thông tin về việc tăng liều thuốc khi quên uống.",
    "Tôi hiểu bạn muốn hỏi liệu có thể ngừng sử dụng insulin nếu cảm thấy khỏe hơn.",
    "Stopping insulin without consulting your doctor can lead to complications.",
    "Thông thường, việc bỏ thuốc tiểu đường cần phải được chỉ định bởi bác sĩ hoặc chuyên gia y tế.",
    "Tôi hiểu bạn đang cân nhắc việc ngưng thuốc và chuyển sang sử dụng thuốc nam.",
    "Nếu bạn muốn thay đổi liều lượng thuốc hoặc ngừng sử dụng thuốc, hãy tham khảo ý kiến bác sĩ.",
    "Cách giải quyết là điều chỉnh liều lượng bởi bác sĩ, không phải tự ý giảm liều.",
    # từ benchmark Kaggle lần 2
    "Dựa trên tài liệu được cung cấp, tôi không khuyến nghị tự ý tăng liều thuốc để hạ đường huyết nhanh hơn.",
    "Tôi không thể đề xuất tăng liều thuốc của bạn.",
    "Họ có thể đề xuất biện pháp khác mà không cần phải giảm liều metformin.",
    "Tuy nhiên, việc tự giảm liều metformin là không khuyến nghị.",
])
def test_real_safe_drafts_are_not_blocked(text):
    assert not _unsafe(text)


@_pytest.mark.parametrize("text", [
    "Bạn có thể ngừng insulin rồi hỏi bác sĩ sau.",
    "Bạn có thể dừng insulin mà không lo biến chứng.",
    "Hãy bỏ thuốc lá và ngừng insulin luôn.",
    "Bạn nên ngừng tiêm insulin và liên hệ với bác sĩ ngay lập tức.",
    "Nếu bạn muốn, bạn có thể ngừng insulin.",
    "Bạn cứ tự ý giảm liều metformin cho đỡ buồn nôn.",
])
def test_unsafe_advice_still_blocked(text):
    assert _unsafe(text)
