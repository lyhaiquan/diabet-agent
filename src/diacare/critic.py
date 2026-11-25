"""CriticAgent: kiểm tra bản nháp của Advisor có căn cứ trong ngữ cảnh đã cấp hay không.

Không gọi LLM. Hai phép kiểm tra tất định, làm trên đúng ngữ cảnh Advisor đã nhận (build_context("advisor")):

1. Nguồn trích: mọi nhãn `[tên]` trong bản nháp phải là nguồn của một tài liệu đã truy hồi hoặc một nhãn có trong
   ngữ cảnh (vd `[ada_2024]` ở khối xét nghiệm). Nhãn lạ nghĩa là mô hình tự bịa nguồn.
2. Con số: mọi con số có đơn vị hoặc có phần thập phân trong bản nháp phải xuất hiện trong ngữ cảnh hoặc trong câu
   hỏi (chấp nhận đổi đơn vị đường huyết mg/dL <-> mmol/L). Số không có trong ngữ cảnh là số mô hình tự đưa ra từ
   trí nhớ của nó; có thể đúng, nhưng hệ thống không có căn cứ để bảo đảm.

Kết quả chỉ để đo và gắn cờ (`unknown_source_cited`, `unsupported_number`); Critic không sửa câu trả lời. Phép kiểm tra
này không phát hiện được câu sai mà không chứa số và không trích nguồn, nên nó là cận dưới của ảo giác, không phải
phép đo đầy đủ.
"""
import re

from diacare.rules import _SENTENCE_SPLIT

_TAG = re.compile(r"\[([^\[\]\n]{1,60})\]")
# Chỉ đơn vị đo lường; số đếm ("3 bữa", "2 lần", "5 ngày") quá phổ biến trong lời khuyên chung nên không xét.
# Đơn vị chữ Latin phải đứng riêng ("100g ngũ cốc" được, "100gạo" thì không); "克" (gam, khi mô hình 3B xen chữ Hán
# như "32.8克糖") không cần ranh giới từ vì chữ Hán viết liền.
_UNIT = r"(?:%|mg/dl|mmol/l|mmhg|kcal|calo|kg|gam|gram|g|ml|lít|phút|giờ|tiếng|đơn vị)(?![\w/])|克"
_NUMBER = r"\d+(?:[.,]\d+)?"
# số: 6,8 | 126 | 1.500 | khoảng "45-60 gram", "4,4–7,2 mmol/L", "5 đến 7 kg" (đơn vị đứng sau số thứ hai áp cho cả
# hai số). Không bắt số nằm trong từ / mã (HbA1c, qwen2.5) hay ngày tháng (20/11).
# V4.9: bản cũ bỏ sót khoảng (số đầu đứng trước "-" không có đơn vị, số sau bị chặn vì đứng sau "-"), số dính liền
# đơn vị ("100g") và "克"; ba kiểu này có trong bản nháp benchmark (docs/results/2026-11-24_numfix_3b).
_NUM = re.compile(rf"(?<![\w.,/\-])({_NUMBER})(?:\s*(?:-|–|—|đến|tới)\s*({_NUMBER}))?"
                  rf"(?:\s*({_UNIT})|(?![\w/]|[.,]\d))", re.IGNORECASE)
_ANY_NUM = re.compile(r"\d+(?:[.,]\d+)?")
MIN_WORDS = 4            # câu ngắn hơn (tiêu đề, lời chào) không tính là một phát biểu
GLUCOSE_FACTOR = 18.0    # mg/dL = mmol/L x 18
REL_TOL = 0.03


def _val(text):
    return float(text.replace(",", "."))


def _context_text(ctx):
    parts = [ctx.get("question") or ""]
    parts += [ctx.get(k) or "" for k in ("memory_text", "lab_text", "journal_text", "nutrition_text", "kg_text", "rl_text")]
    parts += [f"[{d['source']}]\n{d['text']}" for d in ctx.get("docs") or []]
    parts += [m.get("content", "") for m in ctx.get("history") or []]
    return "\n".join(parts)


def allowed_tags(ctx):
    tags = set()
    for d in ctx.get("docs") or []:
        src = str(d["source"]).lower()
        tags |= {src, src.rsplit(".", 1)[0]}
    tags |= {t.strip().lower() for t in _TAG.findall(_context_text(ctx))}
    return tags


def _is_source_tag(tag):
    """`[ada_2024]`, `[who_diabetes.txt]` là nhãn nguồn; `[Tên món]`, `[x]` trong danh sách việc cần làm thì không."""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_.\-]*", tag)) and ("_" in tag or "." in tag or tag.isdigit())


def _supported(value, known):
    for k in known:
        for cand in (k, k * GLUCOSE_FACTOR, k / GLUCOSE_FACTOR):
            if abs(value - cand) <= max(REL_TOL * abs(cand), 0.051 if cand < 30 else 0.5):
                return True
    return False


def check_grounding(draft, ctx):
    """Trả {sentences, cited_sentences, numbers, unsupported_numbers, unknown_sources, flags, grounded}."""
    context = _context_text(ctx)
    known_numbers = {_val(n) for n in _ANY_NUM.findall(context)}
    tags_ok = allowed_tags(ctx)

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(draft or "")[::2]]
    sentences = [s for s in sentences if len(re.findall(r"\w+", s)) >= MIN_WORDS]
    cited = 0
    unknown, unsupported, n_numbers = [], [], 0
    for s in sentences:
        tags = [t.strip().lower() for t in _TAG.findall(s)]
        tags = [t for t in tags if _is_source_tag(t)]
        if any(t in tags_ok for t in tags):
            cited += 1
        unknown += [t for t in tags if t not in tags_ok and t not in unknown]
        for m in _NUM.finditer(_TAG.sub(" ", s)):
            unit = m.group(3)
            for num in filter(None, (m.group(1), m.group(2))):
                if not unit and not re.search(r"[.,]", num):   # số nguyên trần (đánh số mục, "3 bữa") không tính
                    continue
                n_numbers += 1
                if not _supported(_val(num), known_numbers):
                    shown = num + (f" {unit}" if unit else "")
                    if shown not in unsupported:
                        unsupported.append(shown)
    flags = []
    if unknown:
        flags.append("unknown_source_cited")
    if unsupported:
        flags.append("unsupported_number")
    return {
        "sentences": len(sentences), "cited_sentences": cited,
        "numbers": n_numbers, "unsupported_numbers": unsupported, "unknown_sources": unknown,
        "flags": flags, "grounded": not flags,
    }


def describe(g):
    if g["grounded"]:
        return (f"{g['cited_sentences']}/{g['sentences']} câu có trích nguồn, "
                f"{g['numbers']} con số đều có trong ngữ cảnh")
    bits = []
    if g["unknown_sources"]:
        bits.append("nguồn không có trong ngữ cảnh: " + ", ".join(g["unknown_sources"][:3]))
    if g["unsupported_numbers"]:
        bits.append("số không có trong ngữ cảnh: " + ", ".join(g["unsupported_numbers"][:4]))
    return "; ".join(bits)
