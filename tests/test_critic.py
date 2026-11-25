from diacare.critic import allowed_tags, check_grounding, describe
from diacare.orchestrator import Orchestrator
from diacare.samples import LOW_RISK
from diacare.state import State

CTX = {
    "question": "HbA1c 6,8% của tôi có cao không?",
    "docs": [{"source": "medlineplus_diabetes.txt", "text": "An A1C of 6.5% or higher means diabetes. Walk 150 minutes a week."}],
    "lab_text": "Kết quả xét nghiệm: HbA1c 6,8 % → ngưỡng đái tháo đường (từ 6,5 %) [ada_2024]",
    "journal_text": "Đường huyết lúc đói trung bình 7,4 mmol/L.",
    "history": [],
}


def test_grounded_draft_has_no_flags():
    g = check_grounding("HbA1c 6,8% của bạn ở ngưỡng đái tháo đường, tức từ 6,5% trở lên [ada_2024]. "
                        "Nên đi bộ 150 phút mỗi tuần [medlineplus_diabetes].", CTX)
    assert g["grounded"] and g["flags"] == []
    assert g["sentences"] == 2 and g["cited_sentences"] == 2 and g["numbers"] == 3
    assert "2/2" in describe(g)


def test_invented_number_is_flagged():
    g = check_grounding("Bạn nên giữ HbA1c dưới 5,2% và ăn không quá 40 g đường mỗi ngày [ada_2024].", CTX)
    assert g["flags"] == ["unsupported_number"]
    assert g["unsupported_numbers"] == ["5,2 %", "40 g"]
    assert "5,2 %" in describe(g)


def test_invented_source_is_flagged():
    g = check_grounding("Theo hướng dẫn mới thì bạn cần đi khám sớm [who_guideline_2025].", CTX)
    assert g["flags"] == ["unknown_source_cited"] and g["unknown_sources"] == ["who_guideline_2025"]


def test_glucose_unit_conversion_counts_as_supported():
    # 7,4 mmol/L trong nhật ký = 133 mg/dL
    assert check_grounding("Đường huyết lúc đói trung bình của bạn khoảng 133 mg/dL.", CTX)["grounded"]
    assert not check_grounding("Đường huyết lúc đói trung bình của bạn khoảng 160 mg/dL.", CTX)["grounded"]


def test_bare_integers_list_markers_and_names_are_not_claims():
    g = check_grounding("1. Ăn 3 bữa chính mỗi ngày nhé bạn.\n2. Hỏi bác sĩ về HbA1c và típ 2.\n- [ ] Ghi lại bữa ăn hằng ngày.", CTX)
    assert g["numbers"] == 0 and g["grounded"]


def test_allowed_tags_cover_doc_sources_with_and_without_extension():
    tags = allowed_tags(CTX)
    assert {"medlineplus_diabetes.txt", "medlineplus_diabetes", "ada_2024"} <= tags


class _P:
    def predict(self, profile):
        return 0.05


class _R:
    def search(self, q, k=4):
        return [{"source": "ada.txt", "text": "Hạn chế đường."}]


def test_orchestrator_records_grounding_and_flags_without_changing_answer():
    ok = Orchestrator(_P(), _R(), lambda m: "Bạn nên hạn chế đường trong bữa ăn [ada.txt].").run(
        State(question="Nên ăn gì?", profile=dict(LOW_RISK)))
    assert ok.grounding["grounded"] and "unsupported_number" not in ok.flags
    assert "Critic" in [e["agent"] for e in ok.trace]

    bad = Orchestrator(_P(), _R(), lambda m: "Bạn nên ăn dưới 25 g đường mỗi ngày [sach_dinh_duong].").run(
        State(question="Nên ăn gì?", profile=dict(LOW_RISK)))
    assert {"unsupported_number", "unknown_source_cited"} <= set(bad.flags)
    assert "25 g đường" in bad.final          # Critic không sửa câu trả lời


def test_ranges_attached_units_and_han_gram_are_checked():
    """V4.9: ba kiểu số bản cũ bỏ sót, đều có trong bản nháp benchmark thật."""
    g = check_grounding("Mỗi bữa chính nên có khoảng 45-60 gram tinh bột cho người lớn.", CTX)
    assert g["unsupported_numbers"] == ["45 gram", "60 gram"] and g["numbers"] == 2
    g = check_grounding("Bữa sáng có thể gồm 100g ngũ cốc nguyên hạt và rau xanh.", CTX)
    assert g["unsupported_numbers"] == ["100 g"]
    g = check_grounding("Một lon nước ngọt có ga chứa 32.8克糖 theo nhà sản xuất.", CTX)
    assert g["unsupported_numbers"] == ["32.8 克"]
    # khoảng có trong ngữ cảnh: cả hai đầu đều có căn cứ
    assert check_grounding("Bạn nên giữ đường huyết lúc đói khoảng 6,5–7,4 mmol/L mỗi sáng.", CTX)["grounded"]
    # khoảng không đơn vị toàn số nguyên ("1-2 lần", năm) vẫn không tính; chữ dính số ("100gạo") không phải đơn vị
    g = check_grounding("Đi bộ 1-2 lần mỗi ngày từ 2020-2025 và ăn 100gạo lứt nhé.", CTX)
    assert g["numbers"] == 0
