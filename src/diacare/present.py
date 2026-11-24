"""Trình bày câu trả lời cho người bệnh: đổi nhãn nguồn thành chú thích, tách lời miễn trừ ra khỏi thân bài.

Chỉ đổi cách hiển thị. Câu trả lời cuối (`state.final`) giữ nguyên từng ký tự vì benchmark, test và nhật ký chấm
trên chuỗi đó: nhãn `[medlineplus_diabetic_diet.txt]` là thứ benchmark đếm khi đo tỉ lệ trích nguồn.

Vì sao cần: từ khi Advisor được dặn ghi nhãn sau mỗi đoạn (advisor.citation_reminder), câu trả lời có dạng
"... [medlineplus_diabetic_diet.txt] ... [medlineplus_diabetic_diet.txt]", đọc như log của lập trình viên.
Ở đây nhãn thành số mũ ¹ ², nhãn lặp liền nhau trong một đoạn gộp lại, và cuối bài có dòng nguồn tên dễ đọc.
"""
import re

from diacare.rules import DISCLAIMER

# Nhãn nguồn -> tên hiển thị. Nhãn lạ (mô hình tự bịa) để nguyên, không đoán.
TITLES = {
    "medlineplus_blood_sugar": "MedlinePlus – Đường huyết",
    "medlineplus_diabetes": "MedlinePlus – Bệnh đái tháo đường",
    "medlineplus_diabetes_complications": "MedlinePlus – Biến chứng đái tháo đường",
    "medlineplus_diabetes_medicines": "MedlinePlus – Thuốc điều trị đái tháo đường",
    "medlineplus_diabetic_diet": "MedlinePlus – Chế độ ăn cho người đái tháo đường",
    "medlineplus_diabetic_eye": "MedlinePlus – Biến chứng mắt",
    "medlineplus_diabetic_foot": "MedlinePlus – Chăm sóc bàn chân",
    "medlineplus_diabetic_kidney": "MedlinePlus – Biến chứng thận",
    "medlineplus_diabetic_nerve": "MedlinePlus – Biến chứng thần kinh",
    "medlineplus_hyperglycemia": "MedlinePlus – Tăng đường huyết",
    "medlineplus_hypoglycemia": "MedlinePlus – Hạ đường huyết",
    "medlineplus_prediabetes": "MedlinePlus – Tiền đái tháo đường",
    "medlineplus_type2_diabetes": "MedlinePlus – Đái tháo đường típ 2",
    "who_diabetes_factsheet": "WHO – Thông tin về bệnh đái tháo đường",
    "usda_fdc": "USDA FoodData Central – Thành phần dinh dưỡng (ước lượng)",
    "ada_2024": "ADA 2024 – Tiêu chuẩn chẩn đoán đái tháo đường",
}
_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
# Một cụm nhãn: "[a.txt]", "[a.txt], [b.txt]", "[a.txt][b]". Khoảng trắng phía trước đi cùng cụm.
_GROUP = re.compile(r"[ \t]*\[[^\[\]\n]{1,80}\](?:[ \t]*,?[ \t]*\[[^\[\]\n]{1,80}\])*")
_LABEL = re.compile(r"\[([^\[\]\n]{1,80})\]")
_OPEN_TAIL = re.compile(r"[ \t]*\[[^\]\n]*$")


def _key(label):
    k = label.strip().lower()
    return k[:-4] if k.endswith(".txt") else k


def _known(group):
    keys = [_key(x) for x in _LABEL.findall(group)]
    return keys if keys and all(k in TITLES for k in keys) else None


def split_disclaimer(text):
    """(thân bài, có lời miễn trừ hay không). Chỉ bỏ đúng câu DISCLAIMER ở cuối bài."""
    body = text.rstrip()
    if body.endswith(DISCLAIMER):
        return body[: -len(DISCLAIMER)].rstrip(), True
    return body, False


def present(text):
    """Trả (thân bài đã đổi nhãn thành chú thích, danh sách (số, tên nguồn), có lời miễn trừ hay không)."""
    body, has_disclaimer = split_disclaimer(text or "")
    order = []  # khóa nguồn theo thứ tự xuất hiện lần đầu
    paragraphs = []
    for para in body.split("\n\n"):
        hits = [(m, _known(m.group())) for m in _GROUP.finditer(para)]
        hits = [(m, keys) for m, keys in hits if keys]
        out, pos = [], 0
        for i, (m, keys) in enumerate(hits):
            for k in keys:
                if k not in order:
                    order.append(k)
            nums = sorted({order.index(k) + 1 for k in keys})
            marker = "".join(str(n).translate(_SUP) for n in nums)
            nxt = hits[i + 1][1] if i + 1 < len(hits) else None
            same_next = nxt is not None and sorted({order.index(k) + 1 if k in order else -1 for k in nxt}) == nums
            out.append(para[pos:m.start()])
            if not same_next:  # cùng nguồn với cụm kế tiếp trong đoạn: chỉ giữ chú thích ở cụm sau
                out.append(marker)
            pos = m.end()
        out.append(para[pos:])
        paragraphs.append("".join(out))
    notes = [(i + 1, TITLES[k]) for i, k in enumerate(order)]
    return "\n\n".join(paragraphs), notes, has_disclaimer


def sources_line(notes):
    return "Nguồn: " + "; ".join(f"{str(n).translate(_SUP)} {title}" for n, title in notes) if notes else ""


def streaming_view(text):
    """Lúc đang stream: bỏ nhãn nguồn đã biết và nhãn đang gõ dở, để không thoáng hiện tên tệp."""
    text = _GROUP.sub(lambda m: "" if _known(m.group()) else m.group(), text or "")
    return _OPEN_TAIL.sub("", text)
