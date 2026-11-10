"""Lab agent: đọc kết quả xét nghiệm (HbA1c, đường huyết) và đối chiếu ngưỡng tham khảo.

Ngưỡng theo American Diabetes Association, Standards of Care in Diabetes 2024, mục 2
(Diagnosis and Classification of Diabetes), và mức hạ đường huyết < 70 mg/dL (mục 6).
Đây là ĐỐI CHIẾU NGƯỠNG, không phải chẩn đoán: chẩn đoán cần bác sĩ và thường cần xét nghiệm lặp lại.
"""
import json
import re

from diacare.nutrition import strip_accents
from diacare.ocr import IMAGE_EXTENSIONS, clean_ocr_text, extract_pdf_text, ocr_image

SOURCE_TAG = "[ada_2024]"
MGDL_PER_MMOL = 18.0

LABELS = {
    "hba1c": "HbA1c",
    "fpg": "Đường huyết lúc đói",
    "ogtt_2h": "Đường huyết 2 giờ sau nghiệm pháp dung nạp glucose",
    "random": "Đường huyết bất kỳ",
}
LEVEL_TEXT = {
    "normal": "trong khoảng bình thường",
    "prediabetes": "ở mức tiền đái tháo đường",
    "diabetes": "ở ngưỡng chẩn đoán đái tháo đường",
    "low": "thấp (hạ đường huyết)",
    "unclassified": "chưa đủ để phân loại",
}
# (tiền ĐTĐ từ, ngưỡng ĐTĐ từ) theo đơn vị chuẩn: % cho HbA1c, mg/dL cho đường huyết
THRESHOLDS = {"hba1c": (5.7, 6.5), "fpg": (100, 126), "ogtt_2h": (140, 200), "random": (None, 200)}
LOW_GLUCOSE_MGDL = 70
PLAUSIBLE = {"hba1c": (3.0, 20.0), "glucose": (10.0, 1000.0)}

# Tên xét nghiệm, so trên chữ thường đã bỏ dấu
_PATTERNS = [
    ("hba1c", re.compile(r"\bhb\s*a1c\b|\ba1c\b|hemoglobin a1c|glycated h\w*|huyet sac to glycat\w*")),
    ("ogtt_2h", re.compile(r"\bogtt\b|nghiem phap dung nap(?: glucose)?|dung nap glucose"
                           r"|(?:glucose|duong huyet) (?:sau )?2\s*(?:h|gio)\b")),
    ("random", re.compile(r"(?:duong huyet|glucose|duong mau)\s*(?:mau\s*)?(?:bat ky|ngau nhien)"
                          r"|random (?:plasma )?glucose")),
    ("fpg", re.compile(r"\bfpg\b|fasting (?:plasma )?glucose"
                       r"|(?:duong huyet|glucose|duong mau|\bglu)\s*\(?\s*(?:luc\s*)?doi")),
]
_NUMBER = re.compile(r"(?<![\d/.])(\d+(?:[.,]\d+)?)(?![\d/])")
_UNIT = re.compile(r"\s*,?\s*(%|mmol\s*/\s*mol|mg\s*/\s*dl|mmol\s*/\s*l|mmol)")
_NOT_A_RESULT = re.compile(r"\s*(?:h|gio|g|gam|tuoi|ngay|lan|phut)\b")  # "75g", "2h", "2 giờ"
_WINDOW = 60


def _norm(text):
    return strip_accents(text).lower()


def parse_lab_text(text):
    """Trả danh sách {test, value, unit} (unit đã chuẩn hóa, có thể None) theo thứ tự xuất hiện."""
    if not text:
        return []
    t = _norm(clean_ocr_text(text))
    matches = []
    for test, pat in _PATTERNS:
        for m in pat.finditer(t):
            matches.append((m.start(), m.end(), test))
    matches.sort()
    kept = []
    for m in matches:  # bỏ tên chồng lấn (vd "dung nap glucose" trong "nghiem phap dung nap glucose")
        if kept and m[0] < kept[-1][1]:
            continue
        kept.append(m)
    out, seen = [], set()
    for i, (_, end, test) in enumerate(kept):
        stop = min(kept[i + 1][0] if i + 1 < len(kept) else len(t), end + _WINDOW)
        nl = t.find("\n", end)
        if nl != -1:
            stop = min(stop, nl)
        window = t[end:stop]
        for num in _NUMBER.finditer(window):
            after = window[num.end():]
            if _NOT_A_RESULT.match(after):
                continue
            unit = _UNIT.match(after)
            unit = re.sub(r"\s+", "", unit.group(1)) if unit else None
            if unit == "mmol":
                unit = "mmol/l"
            if test not in seen:
                seen.add(test)
                out.append({"test": test, "value": float(num.group(1).replace(",", ".")), "unit": unit})
            break
    return out


def _flatten_json(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten_json(v, f"{prefix} {k}".strip())
    elif isinstance(obj, list):
        for v in obj:
            yield from _flatten_json(v, prefix)
    else:
        yield f"{prefix}: {obj}"


def parse_lab_file(filename, data, ocr_fn=None):
    """Đọc file kết quả (.txt, .csv, .json, .pdf có chữ hoặc PDF scan/ảnh chụp) rồi trích chỉ số."""
    name = filename.lower()
    if name.endswith(".pdf"):
        text = extract_pdf_text(data, ocr_fn=ocr_fn)
    elif name.endswith(IMAGE_EXTENSIONS):
        text = ocr_image(data, ocr_fn=ocr_fn)
    else:
        text = data.decode("utf-8-sig", errors="replace")
        if name.endswith(".json"):
            text = "\n".join(_flatten_json(json.loads(text)))
    return parse_lab_text(text)


def _standardise(test, value, unit):
    """Trả (giá trị chuẩn, đơn vị chuẩn) hoặc None nếu ngoài khoảng hợp lý."""
    if test == "hba1c":
        if unit == "mmol/mol" or (unit is None and value > 20):
            value = value / 10.929 + 2.15  # IFCC mmol/mol -> NGSP %
        elif unit not in (None, "%"):
            return None
        lo, hi = PLAUSIBLE["hba1c"]
        return (round(value, 1), "%") if lo <= value <= hi else None
    if unit in ("mmol/l",) or (unit is None and value < 35):
        value = value * MGDL_PER_MMOL
    elif unit not in (None, "mg/dl"):
        return None
    lo, hi = PLAUSIBLE["glucose"]
    return (round(value), "mg/dL") if lo <= value <= hi else None


def classify(results):
    out = []
    for r in results:
        std = _standardise(r["test"], r["value"], r.get("unit"))
        if std is None:
            continue
        value, unit = std
        pre, dia = THRESHOLDS[r["test"]]
        if r["test"] != "hba1c" and value < LOW_GLUCOSE_MGDL:
            level = "low"
        elif value >= dia:
            level = "diabetes"
        elif pre is not None and value >= pre:
            level = "prediabetes"
        elif pre is None:
            level = "unclassified"
        else:
            level = "normal"
        ref = (f"bình thường < {pre} {unit}; tiền đái tháo đường {pre}–{_below(dia, unit)} {unit}; "
               f"ngưỡng đái tháo đường ≥ {dia} {unit}") if pre is not None else (
            f"≥ {dia} {unit} kèm triệu chứng tăng đường huyết là ngưỡng đái tháo đường")
        out.append(dict(r, label=LABELS[r["test"]], value_std=value, unit_std=unit, level=level,
                        level_text=LEVEL_TEXT[level], reference=ref))
    return out


def _below(threshold, unit):
    return f"{threshold - 0.1:.1f}" if unit == "%" else f"{threshold - 1}"


def format_labs(classified):
    if not classified:
        return ""
    lines = [f"Kết quả xét nghiệm của người dùng, đối chiếu ngưỡng tham khảo ADA 2024 {SOURCE_TAG} "
             "(chỉ là đối chiếu, không phải chẩn đoán; chẩn đoán cần bác sĩ và thường cần xét nghiệm lặp lại):"]
    for r in classified:
        lines.append(f"- {r['label']}: {r['value_std']:g} {r['unit_std']} -> {r['level_text']} ({r['reference']})")
    return "\n".join(lines)


def worst_level(classified):
    order = ["low", "diabetes", "prediabetes", "unclassified", "normal"]
    levels = {r["level"] for r in classified}
    return next((lv for lv in order if lv in levels), None)


class LabAgent:
    """Gom kết quả xét nghiệm đã lưu của bệnh nhân + giá trị người dùng gõ trong câu hỏi (giá trị mới ghi đè)."""

    def __init__(self, store=None):
        self.store = store

    def import_results(self, patient_id, results, source="import"):
        saved = []
        for r in results:
            if classify([r]):  # chỉ lưu giá trị hợp lý
                self.store.add_lab(patient_id, r["test"], r["value"], r.get("unit"), source=source)
                saved.append(r)
        return saved

    def collect(self, patient_id, question):
        from_question = parse_lab_text(question)
        if self.store is not None and patient_id is not None and from_question:
            self.import_results(patient_id, from_question, source="chat")
        merged = {}
        if self.store is not None and patient_id is not None:
            for r in self.store.latest_labs(patient_id):
                merged[r["test"]] = {"test": r["test"], "value": r["value"], "unit": r["unit"]}
        for r in from_question:
            merged[r["test"]] = r
        return classify(list(merged.values()))
