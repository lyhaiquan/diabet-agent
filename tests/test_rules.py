import unicodedata

import pytest

from diacare.rules import (
    DISCLAIMER,
    SAFE_REPLACEMENT,
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
    (0.05, "thấp"), (0.1, "trung bình"), (0.2, "trung bình"), (0.3, "cao"), (0.9, "cao"),
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


from diacare.rules import is_small_talk  # noqa: E402


@pytest.mark.parametrize("q", ["chào bạn", "Xin chào!", "hello", "Hi bot", "cảm ơn nhé", "cám ơn bạn nhiều",
                               "chào em ạ", "alo", "tạm biệt", "ok cảm ơn", "Chào buổi sáng"])
def test_small_talk_detected(q):
    assert is_small_talk(q)


@pytest.mark.parametrize("q", ["chào bạn, tôi bị tiểu đường típ 2", "chào, nên ăn gì buổi sáng?",
                               "tôi khát nước nhiều", "Nguy cơ của tôi thế nào?", "", "cảm ơn, còn tập thể dục thì sao"])
def test_real_questions_are_not_small_talk(q):
    assert not is_small_talk(q)


def test_high_risk_referral_can_be_skipped():
    final, flags = apply_rules(0.9, "Hãy ăn rau.", "Ăn gì?", remind_risk=False)
    assert "high_risk_referral" not in flags
    assert "Nguy cơ của bạn ở mức cao" not in final


def test_safe_stream_releases_sentences_and_blocks_unsafe():
    from diacare.rules import SafeStream
    shown = []
    s = SafeStream(shown.append)
    for piece in ["Ăn nhiều ", "rau xanh. Bạn nên ", "ngừng uống ", "metformin. Và tập thể dục."]:
        s(piece)
    s.flush()
    assert shown == ["Ăn nhiều rau xanh.", "Ăn nhiều rau xanh. Và tập thể dục."]
    assert all("metformin" not in x for x in shown)
    assert s.blocked


def test_safe_stream_no_double_space_after_dropped_tail():
    from diacare.rules import SafeStream
    shown = []
    s = SafeStream(shown.append)
    s("Ăn rau. Hãy ngừng insulin.")
    s(" Đi bộ.")
    assert shown[-1] == "Ăn rau. Đi bộ."


LONG_DRAFT = (
    "Đường huyết lúc đói trung bình 7,0 mmol/L, cao hơn mục tiêu 4,4–7,2 [ada_2024].\n"
    "- Ăn bữa tối sớm hơn và giảm cơm trắng.\n"
    "- Bạn có thể giảm liều metformin vào buổi tối.\n"
    "- Đi bộ 30 phút sau bữa ăn. Ghi lại đường huyết mỗi sáng."
)


def test_unsafe_sentence_removed_rest_kept():
    final, flags = apply_rules(0.1, LONG_DRAFT, diagnosed=True)
    assert "unsafe_advice_blocked" in flags
    assert "metformin" not in final
    assert "giảm cơm trắng" in final and "Đi bộ 30 phút" in final and "[ada_2024]" in final
    assert SAFE_REPLACEMENT in final and DISCLAIMER in final
    assert not is_unsafe_advice(final)


def test_strip_unsafe_keeps_decimal_and_layout():
    from diacare.rules import strip_unsafe
    kept, n = strip_unsafe("Chỉ số 7.8 mmol/L hơi cao. Nên ngừng insulin.\nĂn rau.")
    assert n == 1 and kept == "Chỉ số 7.8 mmol/L hơi cao.\nĂn rau."


def test_unsafe_mostly_unsafe_replaced_whole():
    final, _ = apply_rules(0.1, "Ăn rau. Bạn nên ngừng insulin. Và giảm liều metformin.")
    assert final.startswith(SAFE_REPLACEMENT)
    assert "Ăn rau" not in final


def test_safe_stream_flushes_tail_without_punctuation():
    from diacare.rules import SafeStream
    shown = []
    s = SafeStream(shown.append)
    s("Đi bộ 30 phút. Uống đủ nước")
    assert shown == ["Đi bộ 30 phút."]
    s.flush()
    assert shown[-1] == "Đi bộ 30 phút. Uống đủ nước" and not s.blocked


def test_strip_unsafe_keeps_list_breaks():
    from diacare.rules import strip_unsafe
    text = "4. Kiểm tra thuốc: hỏi bác sĩ. Điều này có thể bao gồm việc tăng liều insulin.\n\n5. Ăn ít đường."
    kept, n = strip_unsafe(text)
    assert n == 1 and kept == "4. Kiểm tra thuốc: hỏi bác sĩ.\n\n5. Ăn ít đường."



# Bản nháp thật của qwen2.5:3b khi đọc nhật ký (2026-11-15): sau khi chỉ bỏ câu "tăng liều insulin",
# câu tự điều chỉnh liều ở ý 5 (is_unsafe_advice không bắt) không được lọt ra.
BLOCKED_JOURNAL_DRAFT = (
    "Đường huyết sau ăn có 5/8 lần vượt mục tiêu dưới 10,0 mmol/L.\n\n"
    "1. **Ăn uống**: Dùng carbohydrate phức tạp thay vì đường đơn và ăn đều bữa.\n\n"
    "4. **Kiểm tra thuốc**: Nếu bác sĩ thấy cần, họ có thể điều chỉnh liều lượng hoặc loại thuốc bạn đang sử dụng. "
    "Điều này có thể bao gồm việc thay đổi thuốc hoặc tăng liều insulin.\n\n"
    "5. **Hạn chế đường**: Nếu bạn đang sử dụng insulin, hãy chắc chắn rằng bạn đang theo dõi lượng đường "
    "trong khẩu phần ăn của mình và điều chỉnh liều insulin nếu cần.\n\n"
    "6. **Vận động**: Đi bộ 30 phút sau bữa ăn."
)


def test_blocked_draft_also_drops_self_dose_adjustment():
    final, flags = apply_rules(0.1, BLOCKED_JOURNAL_DRAFT, diagnosed=True)
    assert "unsafe_advice_blocked" in flags
    assert "tăng liều insulin" not in final
    assert "điều chỉnh liều insulin nếu cần" not in final
    assert "Nếu bác sĩ thấy cần, họ có thể điều chỉnh liều lượng" in final
    assert "Đi bộ 30 phút" in final and SAFE_REPLACEMENT in final
    assert "\n\n6. **Vận động**" in final


def test_safe_stream_after_block_drops_self_dose_adjustment():
    from diacare.rules import SafeStream
    shown = []
    s = SafeStream(shown.append)
    s(BLOCKED_JOURNAL_DRAFT)
    s.flush()
    assert "điều chỉnh liều insulin nếu cần" not in shown[-1] and "Đi bộ 30 phút" in shown[-1]


def test_dose_adjust_alone_not_blocked():
    # Không có câu bị chặn thì lớp lọc thêm không chạy: bộ phát hiện giữ nguyên như trước.
    text = "Hãy liên hệ bác sĩ để điều chỉnh liều insulin. Ăn nhiều rau xanh và đi bộ mỗi ngày nhé."
    final, flags = apply_rules(0.1, text)
    assert "unsafe_advice_blocked" not in flags and text in final
