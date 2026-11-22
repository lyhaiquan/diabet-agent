"""Nhận ra câu hỏi ngoài chủ đề trước khi gọi LLM, như câu chào hỏi (rules.is_small_talk).

Vì sao: benchmark 2026-11-22 (qwen2.5:3b) nhóm `out_of_scope` chỉ đạt 4/12: mô hình trả lời thủ đô nước Pháp, làm thơ,
chỉ cách nấu phở dù prompt dặn chỉ dùng tài liệu. Nhờ mô hình nhỏ tự từ chối không chắc; một bước tất định thì kiểm
thử được, và không tốn một lượt gọi LLM.

Nguyên tắc: thà để lọt một câu ngoài chủ đề (LLM vẫn trả lời, Rules vẫn chạy) còn hơn từ chối nhầm một câu về sức
khoẻ. Vì vậy có ba mức thận trọng:

1. Câu có dấu, không có lịch sử hội thoại: ngoài chủ đề khi KHÔNG có từ nào về sức khoẻ / tiểu đường / ăn uống /
   vận động và không nhắc món ăn nào trong bảng dinh dưỡng.
2. Đã có lịch sử hội thoại: câu nối tiếp ("thế còn buổi tối?", "tôi nên làm gì để kiểm soát tốt hơn?") thường không
   có từ khoá, nên chỉ từ chối khi có dấu hiệu ngoài chủ đề rõ (làm thơ, giá vàng, bóng đá...) và không có từ về
   sức khoẻ.
3. Câu gõ không dấu: từ khoá không dấu dễ trùng nghĩa, nên cũng chỉ từ chối khi có dấu hiệu ngoài chủ đề rõ.

Riêng câu xin công thức nấu ăn ("hướng dẫn tôi cách nấu phở bò") mà không nói gì tới sức khoẻ: trả lời rằng DiaCare
không hướng dẫn nấu ăn nhưng có thể nói lượng tinh bột, calo của món đó.
"""
import re
import unicodedata

from diacare.nutrition import has_diacritics, strip_accents
from diacare.rules import mentions_emergency, mentions_symptom

OUT_OF_SCOPE_REPLY = (
    "Câu hỏi này nằm ngoài phạm vi của DiaCare. Mình chỉ hỗ trợ thông tin về phòng ngừa và chăm sóc bệnh tiểu "
    "đường: ăn uống, vận động, đường huyết, thuốc, xét nghiệm và khi nào cần đi khám. Bạn muốn hỏi gì về những "
    "chủ đề đó?"
)
RECIPE_REPLY = (
    "Hướng dẫn nấu ăn nằm ngoài phạm vi của DiaCare. Mình có thể cho bạn biết món đó có khoảng bao nhiêu calo, "
    "tinh bột và đường, hoặc cách ăn món đó phù hợp với người có nguy cơ hay đang bị tiểu đường. Bạn muốn biết "
    "điều gì?"
)

# Từ cho thấy câu hỏi về sức khoẻ / tiểu đường (kể cả khía cạnh dinh dưỡng của món ăn).
_HEALTH = (
    "tiểu đường", "đái tháo đường", "đường huyết", "glucose", "insulin", "hba1c", "a1c", "metformin", "thuốc",
    "bệnh", "sức khỏe", "sức khoẻ", "khỏe", "khoẻ", "bác sĩ", "khám", "tái khám", "xét nghiệm", "chẩn đoán",
    "triệu chứng", "biến chứng", "nguy cơ", "cấp cứu", "đau", "mệt", "chóng mặt", "buồn nôn", "sốt", "run",
    "huyết áp", "mỡ máu", "cholesterol", "tim mạch", "thận", "mắt", "bàn chân", "vết thương", "tê", "ngất",
    "hôn mê", "co giật", "khó thở", "lú lẫn", "khát", "tiểu", "cân nặng", "béo", "giảm cân", "tăng cân", "bmi",
    "vòng eo", "ngủ", "giấc ngủ", "căng thẳng", "stress", "hút thuốc", "rượu", "bia", "mang thai", "thai",
    "carb", "tinh bột", "calo", "kcal", "đường", "chất béo", "đạm", "protein", "chất xơ", "dinh dưỡng",
    "khẩu phần", "ăn kiêng", "chỉ số", "đo", "nhật ký", "mmol", "mg/dl", "dị ứng", "tiêm", "vitamin",
    # bộ phận cơ thể và triệu chứng thường gặp (lần kiểm tra đầu bỏ sót "chuột rút ở chân")
    # cụm cụ thể, không dùng "đầu", "tay", "chân" đứng một mình ("đầu tiên", "vòng tay")
    "ở chân", "ở tay", "bàn tay", "cánh tay", "tay chân", "chân tay", "đau đầu", "nhức đầu", "đầu ngón", "ngón",
    "bụng", "da", "răng", "nướu", "chuột rút", "ngứa", "sưng", "phù", "ho",
    "tiêu chảy", "táo bón", "đi ngoài", "tuổi",
    # cách nói triệu chứng ngoài danh sách của Rules (rà soát 2026-11-22)
    "đái", "sụt", "gầy", "khô miệng", "nhìn mờ", "mờ", "hơi thở", "loét", "lâu lành", "nhiễm trùng", "ngất xỉu",
)
# Ăn uống, vận động, món ăn thường gặp: trong chủ đề, nhưng không đủ để biến câu xin công thức thành câu sức khoẻ.
_LIFESTYLE = (
    "ăn", "uống", "món", "bữa", "thực đơn", "thức ăn", "đồ ăn", "rau", "trái cây", "hoa quả", "ngọt",
    "cơm", "gạo", "bánh", "phở", "bún", "miến", "mì", "xôi", "cháo", "sữa", "trà", "cà phê", "nước", "thịt",
    "cá", "trứng", "tôm", "cua", "quả", "khoai", "ngô", "đậu", "tập", "thể dục", "vận động", "đi bộ", "chạy bộ", "bơi",
    "gym", "yoga", "đạp xe",
)
# Dấu hiệu ngoài chủ đề rõ ràng (dùng cho câu không dấu và câu giữa hội thoại).
_OFF_TOPIC = (
    "bài thơ", "làm thơ", "viết thơ", "bài hát", "lời bài hát", "kể chuyện", "truyện cười", "viết truyện",
    "viết code", "lập trình", "python", "javascript", "dịch sang", "thủ đô", "giá vàng", "giá xăng",
    "chứng khoán", "cổ phiếu", "bitcoin", "tỷ giá", "tỉ giá", "bóng đá", "thời tiết", "xổ số", "bộ phim",
    "ca sĩ", "trò chơi", "giải phương trình", "bài toán",
)
_RECIPE = re.compile(r"\b(?:cách|công thức|hướng dẫn(?: tôi| mình)?(?: cách)?) (?:nấu|làm|chế biến|pha|nướng|kho)\b")


def _norm(text):
    return unicodedata.normalize("NFC", text or "").lower().strip()


def _has_any(text, words):
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) for w in words)


_HEALTH_ASCII = tuple(dict.fromkeys(strip_accents(w) for w in _HEALTH if len(strip_accents(w)) >= 5 or " " in w))
_OFF_TOPIC_ASCII = tuple(strip_accents(w) for w in _OFF_TOPIC)


def classify(question, history=None, find_foods=None):
    """Trả None (trong chủ đề), "out_of_scope" hoặc "recipe".
    find_foods(question) -> danh sách món tìm thấy trong bảng dinh dưỡng (NutritionAgent.find_foods), có thể None."""
    q = _norm(question)
    if not q:
        return None
    # Câu kể triệu chứng hay dấu hiệu cấp cứu luôn trong chủ đề, dùng ĐÚNG tiêu chí của Rules: từ chối ở đây sẽ làm
    # mất lời khuyên đi khám / gọi 115 mà Rules gắn vào câu trả lời.
    if mentions_symptom(q) or mentions_emergency(q):
        return None
    if not has_diacritics(q):  # câu không dấu: chỉ từ chối khi dấu hiệu rõ
        a = strip_accents(q)
        return "out_of_scope" if _has_any(a, _OFF_TOPIC_ASCII) and not _has_any(a, _HEALTH_ASCII) else None
    health = _has_any(q, _HEALTH)
    if health:
        return None
    if _RECIPE.search(q):
        return "recipe"
    if history:  # câu nối tiếp trong hội thoại: chỉ từ chối khi dấu hiệu rõ
        return "out_of_scope" if _has_any(q, _OFF_TOPIC) else None
    if _has_any(q, _OFF_TOPIC):
        return "out_of_scope"
    if _has_any(q, _LIFESTYLE):
        return None
    try:
        if find_foods is not None and find_foods(question):
            return None
    except Exception:  # bảng món ăn lỗi thì coi như không biết, nghiêng về trong chủ đề
        return None
    return "out_of_scope"


def reply_for(kind):
    return RECIPE_REPLY if kind == "recipe" else OUT_OF_SCOPE_REPLY
