"""Bước nhận câu ngoài chủ đề (diacare.scope). Các câu dưới đây KHÔNG lấy từ bộ benchmark (eval/cases.json): chúng
là bộ kiểm tra riêng, để bước này không chỉ khớp 4 câu ngoài chủ đề của benchmark."""
import pytest

from diacare.scope import OUT_OF_SCOPE_REPLY, RECIPE_REPLY, classify

# Trong chủ đề, gồm cả câu dễ bị từ chối nhầm (không có chữ "tiểu đường", nói về món ăn, câu ngắn).
IN_SCOPE = [
    "Phở bò có nhiều tinh bột không?",
    "Một bát bún chả bao nhiêu calo?",
    "Sáng nay tôi ăn xôi có sao không?",
    "Bánh mì hay cơm thì tốt hơn?",
    "Tôi có nên uống cà phê không?",
    "Uống bia mỗi tuần một lần được không?",
    "Đi bộ buổi tối hay buổi sáng tốt hơn?",
    "Tôi hay bị chuột rút ở chân về đêm.",
    "Dạo này tôi hay mệt và buồn ngủ sau bữa trưa.",
    "Mẹ tôi 65 tuổi có nên đi khám định kỳ không?",
    "Tôi đang mang thai 5 tháng, cần lưu ý gì?",
    "Nên ăn mấy quả chuối một ngày?",
    "Trà xanh có giúp giảm cân không?",
    "Nhịn ăn gián đoạn có tốt không?",
    "Tôi bị dị ứng hải sản thì ăn gì thay?",
    "Chỉ số 180 sau ăn là cao không?",
    "Tôi nên mua máy đo loại nào?",
    "Huyết áp 140/90 có đáng lo không?",
    "Tập gym có giúp gì cho tôi không?",
    "Làm sao để bớt thèm đồ ngọt?",
    "Ăn khuya có hại không?",
    "Có nên ăn trái cây sấy không?",
    "Tôi bỏ bữa sáng thường xuyên, có sao không?",
    "Sữa đậu nành có hợp với tôi không?",
    "Tôi bị tê đầu ngón tay, có liên quan gì không?",
    "Uống nhiều nước có tốt không?",
    "Tôi mất ngủ mấy tuần nay.",
    "Hút thuốc có làm tăng nguy cơ không?",
    "Cách nấu cháo yến mạch cho người tiểu đường?",   # xin công thức nhưng có nói tới bệnh
    "Công thức làm sữa chua ít đường?",
    "Mỗi ngày tôi nên tập bao lâu?",
    "Gạo lứt với gạo trắng khác nhau thế nào?",
]
OUT_OF_SCOPE = [
    "Ai là tổng thống đầu tiên của Mỹ?",
    "Viết giúp tôi một bài thơ tình.",
    "Tỷ giá đô la hôm nay thế nào?",
    "Kết quả bóng đá tối qua ra sao?",
    "Ngày mai Hà Nội có mưa không?",
    "Giải giúp tôi phương trình x mũ hai trừ bốn bằng không.",
    "Viết code Python đảo ngược chuỗi.",
    "Kể cho tôi nghe một truyện cười.",
    "Dịch câu này sang tiếng Anh: tôi yêu Hà Nội.",
    "Nên mua cổ phiếu nào bây giờ?",
    "Thủ đô của Nhật Bản là gì?",
    "Gợi ý cho tôi một bộ phim hay.",
    "Làm sao để đổi mật khẩu wifi?",
    "Ai hát bài Nối vòng tay lớn?",
]
RECIPE = [
    "Chỉ tôi cách nấu bún bò Huế.",
    "Công thức làm bánh flan?",
    "Hướng dẫn cách kho cá.",
]


@pytest.mark.parametrize("q", IN_SCOPE)
def test_in_scope_questions_pass(q):
    assert classify(q) is None


@pytest.mark.parametrize("q", OUT_OF_SCOPE)
def test_out_of_scope_questions_refused(q):
    assert classify(q) == "out_of_scope"


@pytest.mark.parametrize("q", RECIPE)
def test_recipe_without_health_gets_recipe_reply(q):
    assert classify(q) == "recipe"


HISTORY = [{"role": "user", "content": "Tôi bị tiểu đường típ 2."}, {"role": "assistant", "content": "..."}]


@pytest.mark.parametrize("q", ["Thế còn buổi tối?", "Tôi nên làm gì để kiểm soát tốt hơn?", "Vậy tôi nên làm gì?",
                               "Còn bánh mì thì sao?", "Cảm ơn, thế còn cuối tuần?"])
def test_follow_ups_in_a_conversation_pass(q):
    assert classify(q, HISTORY) is None
    assert classify(q, []) in (None, "out_of_scope")  # không có lịch sử thì có thể bị từ chối; không lỗi


def test_clear_off_topic_refused_even_mid_conversation():
    assert classify("Viết cho tôi một bài thơ về mùa thu.", HISTORY) == "out_of_scope"
    assert classify("Giá vàng hôm nay bao nhiêu?", HISTORY) == "out_of_scope"
    # có từ về sức khoẻ thì không từ chối, kể cả khi có dấu hiệu ngoài chủ đề
    assert classify("Viết một bài thơ nhắc tôi uống thuốc đúng giờ.", HISTORY) is None


def test_unaccented_input_only_refused_on_clear_markers():
    assert classify("1 bat pho co bao nhieu carb?") is None
    assert classify("toi nen an gi") is None
    assert classify("thoi tiet ha noi ngay mai") is None or classify("thoi tiet ha noi ngay mai") == "out_of_scope"
    assert classify("viet cho toi bai tho ve mua thu") == "out_of_scope"
    assert classify("gia vang hom nay") == "out_of_scope"
    assert classify("gia vang anh huong suc khoe khong") is None


def test_food_table_counts_as_in_scope():
    assert classify("Nem chua thì sao?", find_foods=lambda q: ["nem chua"]) is None
    assert classify("Nem chua thì sao?", find_foods=lambda q: []) == "out_of_scope"
    assert classify("Nem chua thì sao?", find_foods=lambda q: 1 / 0) is None  # bảng món ăn lỗi: nghiêng về cho qua


def test_replies_say_out_of_scope():
    assert "nằm ngoài phạm vi" in OUT_OF_SCOPE_REPLY and "nằm ngoài phạm vi" in RECIPE_REPLY
    assert classify("") is None and classify("   ") is None


# Câu kể triệu chứng / cấp cứu không bao giờ bị từ chối: lấy thẳng danh sách của Rules (không phải từ benchmark),
# vì từ chối ở bước này làm mất lời khuyên đi khám / gọi 115.
from diacare.rules import EMERGENCY_TERMS, SYMPTOM_TERMS  # noqa: E402


@pytest.mark.parametrize("term", SYMPTOM_TERMS + EMERGENCY_TERMS)
def test_rules_symptom_and_emergency_terms_are_in_scope(term):
    assert classify(f"Tôi bị {term}.") is None
    assert classify(f"Dạo này {term} quá.") is None


@pytest.mark.parametrize("q", ["Dạo này tôi đái nhiều quá.", "Tôi bị sụt ký nhanh.", "Tôi bị sụt cân nhanh.",
                               "Tôi hay khô miệng.", "Tôi hay bị nhìn mờ.", "Hơi thở có mùi lạ.",
                               "Vết loét lâu không lành.", "Nước tiểu có kiến bu."])
def test_symptom_phrasings_are_in_scope(q):
    assert classify(q) is None
