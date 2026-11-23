"""Lọc gợi ý món dị ứng (diacare.allergy). Câu thật lấy từ bản nháp đã lưu ở docs/results (ca memory_3, người dùng
"bị dị ứng tôm"); phần còn lại là câu tự viết để thử phá luật."""
import pytest

from diacare.allergy import allergens, apply_allergy_rules, filter_allergens
from diacare.rules import apply_rules

TOM = [{"kind": "allergy", "content": "tôm"}]
SEAFOOD = [{"kind": "allergy", "content": "hải sản"}]
Q_FOOD = "Gợi ý cho tôi bữa tối giàu đạm."


@pytest.mark.parametrize("sentence", [
    # bản nháp thật (qwen2.5:7b, Kaggle lần 3)
    "4. **Sò, ốc, và hải sản**: Các loại hải sản như sò, ốc, tôm, cua, và cá cũng là nguồn đạm tốt.",
    "4. **Tôm và cá tôm**: Mặc dù bạn có dị ứng tôm, nhưng cá tôm có thể là một lựa chọn tốt khác.",
    # tự viết
    "Bạn có thể ăn tôm luộc chấm muối tiêu.",
    "Tôm rang thịt là món giàu đạm.",
    "Dù dị ứng tôm, bạn vẫn có thể ăn một ít tôm hấp.",
    "5. Tôm: 100g tôm hấp, giàu đạm và ít chất béo.",  # qwen2.5:3b 2026-11-22
])
def test_allergen_suggestions_removed(sentence):
    draft = f"Gợi ý bữa tối:\n{sentence}\n- Thịt gà luộc: giàu đạm, ít mỡ."
    out, removed = filter_allergens(draft, allergens(TOM))
    assert removed == ["tôm"] and "tôm" not in out.replace("dị ứng tôm", "") and "Thịt gà luộc" in out


@pytest.mark.parametrize("sentence", [
    # bản nháp thật
    "6. **Sò, ốc, và các loại hải sản khác**: Tránh tôm vì bạn có dị ứng, nhưng có thể sử dụng các loại hải sản khác "
    "như sò, ốc, hoặc cá.",
    "Dựa trên thông tin đã biết về người dùng, người dùng có dị ứng với tôm, do đó tôm không nên được sử dụng.",
    "Đây là một gợi ý bữa tối giàu protein, không sử dụng tôm.",
    "Vì vậy, thay vì sử dụng tôm, tôi sẽ gợi ý một bữa tối giàu đạm khác.",
    "Đây là một số gợi ý cho bữa tối giàu đạm mà không cần đến tôm:",  # qwen2.5:3b 2026-11-22, từng bị bỏ nhầm
    # tự viết
    "Hạn chế mì tôm vì nhiều tinh bột và muối.",
    "Bạn nên kiêng tôm và đọc kỹ nhãn nước mắm.",
])
def test_avoidance_sentences_kept(sentence):
    out, removed = filter_allergens(sentence, allergens(TOM))
    assert removed == [] and out == sentence


def test_group_allergy_covers_specific_seafood():
    out, removed = filter_allergens("Mực xào cần tây rất giàu đạm. Ức gà áp chảo cũng tốt.", allergens(SEAFOOD))
    assert removed == ["hải sản"] and out == "Ức gà áp chảo cũng tốt."


def test_multiple_allergens_parsed():
    items = allergens([{"kind": "allergy", "content": "đậu phộng, sữa"}])
    assert [a["label"] for a in items] == ["đậu phộng", "sữa"]
    _, removed = filter_allergens("Ăn kèm một ít lạc rang. Uống sữa chua không đường.", items)
    assert removed == ["đậu phộng", "sữa"]
    # sữa đậu nành không phải sữa bò
    assert filter_allergens("Uống sữa đậu nành không đường.", items)[1] == []


def test_reminder_only_for_food_questions_without_allergy_mention():
    text, flags = apply_allergy_rules("Ức gà, trứng và đậu hũ đều giàu đạm.", TOM, Q_FOOD)
    assert flags == ["allergy_reminder"] and "dị ứng tôm" in text
    assert apply_allergy_rules("Ức gà giàu đạm, không có tôm vì bạn dị ứng.", TOM, Q_FOOD)[1] == []
    assert apply_allergy_rules("Nên đi bộ 30 phút mỗi ngày.", TOM, "Tôi nên tập thể dục thế nào?")[1] == []
    assert apply_allergy_rules("Ức gà giàu đạm.", [], Q_FOOD) == ("Ức gà giàu đạm.", [])


def test_apply_rules_removes_allergen_and_keeps_disclaimer():
    draft = "Gợi ý bữa tối:\n- Tôm hấp: giàu đạm.\n- Cá hồi áp chảo: giàu đạm và omega-3."
    final, flags = apply_rules(0.05, draft, Q_FOOD, memory=TOM)
    assert "allergen_removed" in flags and "Tôm hấp" not in final and "Cá hồi" in final
    assert "Bạn đã cho biết bị dị ứng tôm" in final and final.rstrip().endswith("bác sĩ.")
    assert apply_rules(0.05, draft, Q_FOOD)[0].count("Tôm hấp") == 1  # không có trí nhớ dị ứng: không đổi
