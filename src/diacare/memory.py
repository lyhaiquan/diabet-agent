"""Trí nhớ dài hạn về bệnh nhân (trích xuất theo luật) và nén lịch sử hội thoại bằng tóm tắt."""
import re
import unicodedata

from diacare.nutrition import strip_accents

KIND_LABELS = {
    "diagnosis": "chẩn đoán",
    "medication": "thuốc đang dùng",
    "allergy": "dị ứng",
    "diet": "chế độ ăn",
    "condition": "bệnh kèm theo",
}
MEMORY_HEADER = "Thông tin đã biết về người dùng (từ các phiên trước):"
UNTYPED_DIABETES = "đái tháo đường (chưa rõ típ)"
DIABETES_TYPES = ("đái tháo đường típ 1", "đái tháo đường típ 2", UNTYPED_DIABETES)
DRUGS = ("metformin", "insulin", "gliclazide", "sitagliptin", "empagliflozin", "dapagliflozin")

SUMMARY_SYSTEM = (
    "Tóm tắt ngắn gọn (tối đa 80 từ) cuộc hội thoại sau, giữ lại thông tin sức khỏe quan trọng "
    "của người dùng và lời khuyên đã đưa ra; không thêm thông tin mới."
)
SUMMARY_PREFIX = "Tóm tắt hội thoại trước: "

# ---------- trích xuất theo luật ----------
# Mẫu viết có dấu; bản không dấu được suy ra bằng strip_accents(mẫu) nên mọi mẫu khớp ở cả hai dạng.

_I = r"(?<!\w)(?:tôi|mình|em)(?!\w)"
_SICK = r"(?:tiểu đường|đái tháo đường)"
_TYPE = r"(?:típ|tuýp|type|tip|loại)"
_DIAG_TRIGGER = (
    rf"(?:{_I}\s+(?:đã\s+)?(?:bị|mắc)"
    rf"|{_I}\s+(?:đã\s+)?được\s+chẩn đoán(?:\s+(?:là|bị|mắc))?"
    rf"|bác sĩ\s+(?:đã\s+)?(?:nói|bảo|kết luận)\s+{_I}\s+(?:bị|mắc)"
    rf"|bác sĩ\s+(?:đã\s+)?chẩn đoán\s+{_I}(?:\s+(?:là|bị|mắc))?)"
)
# Người khác (mẹ tôi, vợ em, con tôi...) không phải người dùng: đại từ sau danh từ quan hệ bị thay bằng "xxkhac".
_KIN = (r"(?<!\w)(?:mẹ|bố|cha|ba|má|ông|bà|anh|chị|em trai|em gái|vợ|chồng|con|cháu|bạn|chú|bác|cô|dì|cậu|mợ|thím"
        r"|người nhà|người thân|hàng xóm|đồng nghiệp)(?:\s+(?:nội|ngoại|ruột))?\s+(?:tôi|mình|em)(?!\w)")
_DIAG = (rf"{_DIAG_TRIGGER}\s+(?:bệnh\s+)?(tiền\s+)?{_SICK}(?:\s+{_TYPE}\s*([12]))?(?!\w)"
         r"(?!\s*(?:không|chưa)[\s.!]*$)(?![^.!;\n,?]*\?)")
_MED = (
    rf"(?:{_I}\s+(?:(?:đang|vẫn|hiện đang)\s+)?|{_I}[^?.!;\n]*?\bvà\s+(?:đang\s+)?)"
    rf"(?:dùng|uống|tiêm|sử dụng)\s+({'|'.join(DRUGS)})(?!\w)"
)
_STOP_WORDS = (
    "nên", "nhưng", "thì", "khi", "mà", "vậy", "rồi", "nhé", "ạ", "vì", "nếu", "còn", "có", "không",
    "được", "cho", "giúp", "hãy", "với", "để", "nhưng", "và hay", "gợi", "xin", "làm", "thế",
)
_ALLERGY = rf"{_I}\s+(?:bị\s+)?dị ứng\s+(?:với\s+)?(\w+(?:\s+\w+){{0,2}})"
_DIET_VEG = rf"{_I}\s+ăn chay(?!\w)"
_DIET_NO = rf"{_I}\s+không\s+ăn\s+(?:được\s+)?(\w+(?:\s+\w+)?)"
_BP = r"(?:huyết áp cao|tăng huyết áp|cao huyết áp)"
_LIPID = r"(?:mỡ máu cao|rối loạn mỡ máu|máu nhiễm mỡ)"
_ONE_COND = rf"(?:bệnh\s+)?(?:{_BP}|{_LIPID})(?!\w)"
_CONDS = rf"{_I}\s+(?:bị|có)\s+({_ONE_COND}(?:\s*(?:,|và)\s*{_ONE_COND})*)"


def _both(pattern):
    return [re.compile(pattern), re.compile(strip_accents(pattern))]


_RE = {name: _both(p) for name, p in {
    "diag": _DIAG, "med": _MED, "allergy": _ALLERGY, "veg": _DIET_VEG, "noeat": _DIET_NO,
    "conds": _CONDS, "bp": rf"(?<!\w){_BP}", "lipid": rf"(?<!\w){_LIPID}", "kin": _KIN,
}.items()}
_STOP = frozenset(_STOP_WORDS) | frozenset(strip_accents(w) for w in _STOP_WORDS)


def _norm(text):
    return unicodedata.normalize("NFC", text).lower()


def _words(raw, limit):
    out = []
    for w in raw.split():
        if w in _STOP:
            break
        out.append(w)
    return " ".join(out[:limit])


def extract_facts(text):
    """Trích (kind, content) từ một câu nói của người dùng; chỉ nhận câu khai báo ngôi thứ nhất."""
    text = _norm(text or "")
    facts = []

    def add(kind, content):
        if content and (kind, content) not in facts and not any(
                k == kind and strip_accents(c) == strip_accents(content) for k, c in facts):
            facts.append((kind, content))

    for accented in (True, False):
        i = 0 if accented else 1
        t = text if accented else strip_accents(text)
        t = _RE["kin"][i].sub(" xxkhac ", t)
        for m in _RE["diag"][i].finditer(t):
            if m.group(1):
                add("diagnosis", "tiền đái tháo đường")
            elif m.group(2):
                add("diagnosis", f"đái tháo đường típ {m.group(2)}")
            else:
                add("diagnosis", UNTYPED_DIABETES)
        for m in _RE["med"][i].finditer(t):
            add("medication", m.group(1))
        for m in _RE["allergy"][i].finditer(t):
            add("allergy", _words(m.group(1), 3))
        if _RE["veg"][i].search(t):
            add("diet", "ăn chay")
        for m in _RE["noeat"][i].finditer(t):
            words = _words(m.group(1), 2)
            if words:
                add("diet", f"không ăn {words}")
        for m in _RE["conds"][i].finditer(t):
            if _RE["bp"][i].search(m.group(1)):
                add("condition", "tăng huyết áp")
            if _RE["lipid"][i].search(m.group(1)):
                add("condition", "rối loạn mỡ máu")
    if any(k == "diagnosis" and c in DIABETES_TYPES[:2] for k, c in facts):
        facts = [f for f in facts if f != ("diagnosis", UNTYPED_DIABETES)]
    return facts


def format_memory(facts):
    lines = [MEMORY_HEADER]
    for f in facts:
        lines.append(f"- {KIND_LABELS.get(f['kind'], f['kind'])}: {f['content']}")
    return "\n".join(lines)


def has_diagnosis(facts):
    return any(f["kind"] == "diagnosis" and f["content"] in DIABETES_TYPES for f in facts)


class MemoryAgent:
    def __init__(self, store):
        self.store = store

    def observe(self, patient_id, text):
        facts = extract_facts(text)
        for kind, content in facts:
            self.store.add_memory(patient_id, kind, content, source="rule")
        return facts

    def recall(self, patient_id):
        return self.store.list_memories(patient_id)

    def is_diagnosed(self, patient_id):
        return has_diagnosis(self.recall(patient_id))


# ---------- tóm tắt hội thoại ----------

def _render(messages):
    names = {"user": "Người dùng", "assistant": "Trợ lý"}
    return "\n".join(f"{names.get(m['role'], m['role'])}: {m['content']}" for m in messages)


def summarise_history(messages, llm):
    reply = llm([{"role": "system", "content": SUMMARY_SYSTEM},
                 {"role": "user", "content": _render(messages)}])
    return reply.strip()


def compress_history(history, llm, budget_tokens, estimate):
    """Nếu lịch sử vượt ngân sách: giữ tin mới nhất vừa nửa ngân sách, tóm tắt phần cũ."""
    if sum(estimate(m["content"]) for m in history) <= budget_tokens:
        return history, False
    kept, used = [], 0
    for m in reversed(history):
        cost = estimate(m["content"])
        if used + cost > budget_tokens // 2:
            break
        kept.insert(0, m)
        used += cost
    older = history[:len(history) - len(kept)]
    if not older:
        return history, False
    summary = summarise_history(older, llm)
    return [{"role": "system", "content": SUMMARY_PREFIX + summary}] + kept, True
