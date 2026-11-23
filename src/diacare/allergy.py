"""Lọc gợi ý món ăn mà người dùng đã khai là bị dị ứng (chạy trong Rules, sau LLM).

Vì sao: trong các lần chạy đã lưu, qwen2.5:7b từng gợi ý "sò, ốc, tôm, cua" cho người đã nói "Tôi bị dị ứng tôm", và
có lượt viết "Mặc dù bạn có dị ứng tôm, nhưng cá tôm có thể là một lựa chọn tốt" (lượt đó benchmark vẫn chấm đạt vì
có chữ "dị ứng"). Mô hình 3B ít gợi ý món dị ứng hơn nhưng hay quên nhắc tới dị ứng. Trí nhớ dài hạn đã có dữ kiện
dị ứng (memory.extract_facts, kind "allergy"), nên kiểm tra được bằng luật như lời khuyên đổi thuốc.

Hai việc:
1. Bỏ câu (hoặc gạch đầu dòng) nhắc tới chất gây dị ứng mà không kèm lời tránh ("tránh", "không chứa", "thay vì",
   "trừ"...), và câu tránh nửa vời kiểu "dù dị ứng ... nhưng vẫn có thể ăn". Cờ `allergen_removed`.
2. Câu hỏi về ăn uống mà câu trả lời không nhắc tới dị ứng: thêm một câu nhắc. Cờ `allergy_reminder`.
"""
import re
import unicodedata

# Nhóm chất: khai "hải sản" thì các món hải sản cụ thể cũng tính.
_GROUPS = {
    "hải sản": ("hải sản", "tôm", "cua", "ghẹ", "sò", "ốc", "mực", "hến", "nghêu", "ngao", "hàu", "bạch tuộc",
                "tôm hùm", "sò điệp"),
    "tôm": ("tôm", "tôm hùm"),
    "sữa": ("sữa", "phô mai", "sữa chua", "váng sữa", "bơ sữa"),
    "đậu phộng": ("đậu phộng", "lạc"),
    "lạc": ("đậu phộng", "lạc"),
    "các loại hạt": ("hạt điều", "óc chó", "hạnh nhân", "hạt dẻ", "hạt mắc ca"),
    "hạt": ("hạt điều", "óc chó", "hạnh nhân", "hạt dẻ", "hạt mắc ca"),
    "lúa mì": ("lúa mì", "bánh mì", "gluten"),
    "gluten": ("lúa mì", "bánh mì", "gluten"),
    "mè": ("mè", "vừng"),
    "vừng": ("mè", "vừng"),
    "đậu nành": ("đậu nành", "đậu hũ", "đậu phụ", "sữa đậu nành", "tàu hũ"),
}
# Cụm chứa tên chất nhưng không phải chất đó.
_NOT_THE_ALLERGEN = {
    "tôm": ("mì tôm",),
    "sữa": ("sữa đậu nành", "sữa hạt", "sữa yến mạch", "sữa hạnh nhân", "sữa gạo"),
    "lạc": ("lạc quan", "liên lạc", "lạc đề"),
}
_AVOID = re.compile(
    r"\b(?:tránh|kiêng|ngoại trừ|trừ|thay (?:vì|thế|cho|bằng)|loại bỏ|bỏ qua|không bao gồm|không có|không chứa|"
    r"không dùng|không ăn|không nên|không sử dụng|không được|không cần|mà không|đừng|dị ứng)\b")
# "Mặc dù bạn có dị ứng tôm, nhưng cá tôm có thể là một lựa chọn tốt": có chữ dị ứng mà vẫn gợi ý. Chỉ tính khi
# phần sau từ nối lại nhắc tới chất dị ứng: "Tránh tôm, nhưng có thể dùng sò, ốc, cá" là lời khuyên đúng.
_CONTRAST = re.compile(r"\b(?:nhưng|tuy nhiên|vẫn)\b")
_FOOD_QUESTION = re.compile(
    r"\b(?:ăn|uống|món|bữa|thực đơn|thức ăn|đồ ăn|nấu|đạm|protein|calo|carb|tinh bột|dinh dưỡng|thực phẩm)\b")
_SENT = re.compile(r"(?<=[.!?;])[ \t]+")

ALLERGY_NOTE = ("Bạn đã cho biết bị dị ứng {items}: mình đã bỏ phần gợi ý có {items}. Hãy kiểm tra thành phần món ăn "
                "và hỏi bác sĩ nếu không chắc.")
ALLERGY_REMINDER = "Lưu ý: bạn đã cho biết bị dị ứng {items}, hãy tránh các món có {items} và kiểm tra thành phần món ăn."


def _norm(text):
    return unicodedata.normalize("NFC", text or "").lower()


def allergens(memory):
    """Danh sách chất dị ứng từ trí nhớ: [{"label": "tôm", "terms": (...)}]."""
    out = []
    for m in memory or ():
        if m.get("kind") != "allergy":
            continue
        for item in re.split(r"\s*(?:,|\bvà\b|\bhay\b|\bhoặc\b)\s*", _norm(m.get("content"))):
            item = item.strip()
            if item and all(a["label"] != item for a in out):
                out.append({"label": item, "terms": _GROUPS.get(item, (item,))})
    return out


def _mentions(text, allergen):
    t = _norm(text)
    for phrase in _NOT_THE_ALLERGEN.get(allergen["label"], ()):
        t = t.replace(phrase, " ")
    for term in allergen["terms"]:
        for phrase in _NOT_THE_ALLERGEN.get(term, ()):
            t = t.replace(phrase, " ")
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", t):
            return True
    return False


def _suggests(sentence, allergen):
    if not _mentions(sentence, allergen):
        return False
    s = _norm(sentence)
    avoid = _AVOID.search(s)
    if not avoid:
        return True
    contrast = _CONTRAST.search(s, avoid.end())
    return bool(contrast) and _mentions(s[contrast.end():], allergen)


def filter_allergens(text, items):
    """Bỏ câu gợi ý chất dị ứng. Trả (văn bản, danh sách nhãn chất đã bị bỏ câu)."""
    removed = []
    lines = []
    for line in text.split("\n"):
        parts = _SENT.split(line)
        kept = []
        for part in parts:
            hit = [a["label"] for a in items if part.strip() and _suggests(part, a)]
            if hit:
                removed += [h for h in hit if h not in removed]
            else:
                kept.append(part)
        new = " ".join(kept)
        if parts and not kept:  # cả dòng bị bỏ (thường là một gạch đầu dòng): bỏ luôn dòng
            continue
        if re.fullmatch(r"\s*(?:[-*+•]|\d+[.)])?\s*(?:\*\*[^*]*\*\*:?)?\s*", new) and new.strip():
            continue  # chỉ còn ký hiệu gạch đầu dòng / tiêu đề trơ trọi
        lines.append(new)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out, removed


def apply_allergy_rules(text, memory, question=""):
    """Trả (văn bản, cờ). Dùng trong rules.apply_rules, trên bản nháp đã qua lọc thuốc, trước các lời nhắc."""
    items = allergens(memory)
    if not items:
        return text, []
    flags = []
    text, removed = filter_allergens(text, items)
    labels = ", ".join(a["label"] for a in items)
    if removed:
        flags.append("allergen_removed")
        text += "\n\n" + ALLERGY_NOTE.format(items=", ".join(removed))
    elif _FOOD_QUESTION.search(_norm(question)) and not re.search(r"\bdị ứng\b", _norm(text)):
        flags.append("allergy_reminder")
        text += "\n\n" + ALLERGY_REMINDER.format(items=labels)
    return text, flags
