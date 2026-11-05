import math
import re
import unicodedata

HIGH_RISK_THRESHOLD = 0.5
LOW_RISK_THRESHOLD = 0.2
DISCLAIMER = "Đây chỉ là thông tin tham khảo, không thay thế tư vấn của bác sĩ."
SAFE_REPLACEMENT = (
    "Mình không thể đưa ra lời khuyên về việc thay đổi thuốc hoặc insulin. "
    "Vui lòng hỏi bác sĩ điều trị của bạn."
)
SYMPTOM_NOTE = (
    "Các triệu chứng bạn mô tả cần được bác sĩ đánh giá và xét nghiệm đường huyết."
)
EMERGENCY_NOTE = (
    "Nếu có dấu hiệu nguy hiểm (lú lẫn, khó thở, đau ngực, ngất, co giật), "
    "hãy gọi cấp cứu 115 hoặc đến cơ sở y tế gần nhất ngay."
)

BINARY_FEATURES = (
    "HighBP", "HighChol", "CholCheck", "Smoker", "Stroke", "HeartDiseaseorAttack",
    "PhysActivity", "Fruits", "Veggies", "HvyAlcoholConsump", "AnyHealthcare",
    "NoDocbcCost", "DiffWalk", "Sex",
)
FEATURE_RANGES = {
    **{f: (0, 1) for f in BINARY_FEATURES},
    "BMI": (10, 80), "GenHlth": (1, 5), "MentHlth": (0, 30), "PhysHlth": (0, 30),
    "Age": (1, 13), "Education": (1, 6), "Income": (1, 8),
}

SYMPTOM_TERMS = (
    "khát nước", "khát nhiều", "tiểu nhiều", "đi tiểu nhiều", "sụt cân",
    "nhìn mờ", "mờ mắt", "vết thương lâu lành", "tê bì",
    # cách nói dân gian
    "kiến bâu", "kiến bu", "đái nhiều", "tiểu đêm", "khô miệng", "sụt ký", "sụt cân nhanh",
    "uống nước liên tục", "uống nhiều nước",
)
# Triệu chứng nói vòng: "vết thương ... không lành", "nước tiểu ... kiến".
_SYMPTOM_PATTERN = re.compile(r"vết (?:thương|loét)\b.*\b(?:không|chậm|lâu) lành|nước tiểu\b.*\bkiến\b")
EMERGENCY_TERMS = (
    "hôn mê", "lú lẫn", "khó thở", "đau ngực", "co giật", "ngất",
    "hạ đường huyết", "đường huyết thấp", "hơi thở có mùi",
)

_STOP = (
    r"(?:dừng|ngừng|ngưng|bỏ|thôi|giảm liều|tăng liều|tự ý|stop|skip|discontinue|"
    r"quit|reduce your dose|increase your dose)"
)
_DRUG = r"(?:insulin|thuốc|metformin|medication|medicine)"
_UNSAFE = re.compile(rf"\b{_STOP}\b(?:\W+\w+){{0,3}}?\W+{_DRUG}\b")
_ALONE = ("tự ý tăng liều", "tự ý giảm liều")
_NEGATION = re.compile(
    r"\b(?:không được|đừng|không nên|tuyệt đối không|không tự ý|chớ|"
    r"không khuyến nghị|không khuyên|không thể đề xuất|không đề xuất|không cần phải|"
    r"do not|don't|never|should not|shouldn't|not recommend)\b"
)
# Câu cảnh báo / nhắc lại câu hỏi / nói tài liệu không có thông tin: không phải lời khuyên đổi thuốc.
# (Rút ra từ các bản nháp thật của benchmark Kaggle lần 1, xem docs/results/2026-11-05_kaggle_run1.)
_CAUTION = re.compile(
    r"(?:mà không|khi chưa|nếu không|nếu chưa) (?:có )?(?:sự )?"
    r"(?:hướng dẫn|chỉ định|tư vấn|ý kiến|chỉ dẫn|đồng ý|hỏi|tham khảo|giám sát|theo dõi)"
    r"|có thể (?:dẫn đến|gây)"
    # nhắc lại nỗi lo của người hỏi / khuyên hỏi bác sĩ trước (benchmark Kaggle lần 3)
    r"|\blo (?:ngại|lắng) về việc\b|thay vì tự|trước khi (?:bạn )?(?:muốn|định|quyết định)"
    r"|nguy hiểm"
    r"|cần (?:phải )?(?:được )?(?:thảo luận|quyết định|trao đổi|tham khảo|chỉ định)"
    r"|(?:được )?chỉ định bởi bác sĩ|không phải tự ý"
    r"|(?:nếu|dù) bạn (?:có )?muốn.*bác sĩ"
    r"|\bliệu (?:có|tôi|bạn)\b|bạn muốn hỏi|bạn đang cân nhắc"
    r"|không (?:cung cấp|có|chứa|đề cập)(?: đủ)? thông tin"
    r"|without (?:consulting|talking|medical|your doctor)|can (?:lead to|cause)|dangerous"
)
# "thuốc" còn có nghĩa thuốc lá: bỏ/ngừng hút thuốc là lời khuyên tốt.
_SMOKING = re.compile(r"hút thuốc|thuốc lá|\bsmok")
_MEDICAL_DRUG = re.compile(r"\b(?:insulin|metformin|medication|medicine)\b|thuốc (?:tiểu đường|điều trị|hạ đường)")


def _norm(text):
    return unicodedata.normalize("NFC", text).lower()


def is_unsafe_advice(text):
    """True nếu câu khuyên dừng/giảm/tăng liều thuốc, không phủ định, không phải câu cảnh báo."""
    for sentence in re.split(r"[.!?;\n]+", _norm(text)):
        if _NEGATION.search(sentence) or _CAUTION.search(sentence):
            continue
        if _SMOKING.search(sentence) and not _MEDICAL_DRUG.search(sentence):
            continue
        if _UNSAFE.search(sentence) or any(p in sentence for p in _ALONE):
            return True
    return False


def risk_band(risk):
    if risk < LOW_RISK_THRESHOLD:
        return "thấp"
    if risk < HIGH_RISK_THRESHOLD:
        return "trung bình"
    return "cao"


def validate_profile(profile):
    errors = []
    for name, (lo, hi) in FEATURE_RANGES.items():
        if name not in profile:
            errors.append(f"thiếu {name}")
            continue
        v = profile[name]
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            errors.append(f"{name} không phải số hợp lệ: {v!r}")
        elif not lo <= v <= hi:
            errors.append(f"{name} ngoài khoảng {lo}-{hi}: {v}")
        elif name != "BMI" and v != int(v):
            errors.append(f"{name} phải là số nguyên: {v}")
    return errors


HIGH_RISK_NOTE = (
    "Nguy cơ của bạn ở mức cao: hãy đặt lịch khám và xét nghiệm "
    "đường huyết (HbA1c hoặc glucose lúc đói)."
)
SMALL_TALK_REPLY = (
    "Chào bạn! Mình là trợ lý DiaCare, hỗ trợ thông tin về phòng ngừa và chăm sóc bệnh tiểu đường: "
    "ăn uống, vận động, dấu hiệu cần đi khám, dinh dưỡng món ăn. Bạn muốn hỏi gì?"
)
# Chào hỏi / cảm ơn thuần túy (không kèm câu hỏi) thì không chạy dự đoán nguy cơ hay LLM.
_GREETING = re.compile(
    r"\b(?:xin chào|chào|hello|hi|hey|alo|cảm ơn|cám ơn|thanks|thank you|tạm biệt|bye)\b")
_FILLER = frozenset(
    "bạn em anh chị ạ nhé nha nhá nhiều bot shop ad ok oke vâng dạ buổi sáng trưa chiều tối mọi người "
    "rất lắm cả nhà you".split())


def is_small_talk(question):
    q = _norm(question).strip()
    if not q or not _GREETING.search(q):
        return False
    rest = re.findall(r"\w+", _GREETING.sub(" ", q))
    return all(w in _FILLER for w in rest)


LAB_NOTES = {
    "low": ("Kết quả đường huyết của bạn dưới 70 mg/dL (3,9 mmol/L), mức hạ đường huyết. Nếu có run, vã mồ hôi, "
            "lú lẫn hoặc ngất, hãy gọi cấp cứu 115 và báo bác sĩ điều trị."),
    "diabetes": ("Kết quả xét nghiệm của bạn ở ngưỡng chẩn đoán đái tháo đường theo ADA. Chỉ bác sĩ mới chẩn đoán "
                 "được, thường cần xét nghiệm lặp lại: hãy mang kết quả này đi khám sớm."),
    "prediabetes": ("Kết quả xét nghiệm của bạn ở mức tiền đái tháo đường theo ADA: nên khám để được tư vấn "
                    "thay đổi lối sống và hẹn xét nghiệm lại."),
}


DIAGNOSED_NOTE = (
    "Bạn đã được chẩn đoán đái tháo đường: hãy theo dõi đường huyết và tái khám theo lịch của bác sĩ điều trị."
)


def apply_rules(risk, draft, question="", diagnosed=False, remind_risk=True, labs=None):
    """remind_risk=False: không lặp lời nhắc nguy cơ cao (đã nhắc trước đó trong phiên)."""
    flags = []
    text = draft
    if is_unsafe_advice(draft):
        flags.append("unsafe_advice_blocked")
        text = SAFE_REPLACEMENT
    q = _norm(question)
    if diagnosed:
        flags.append("diagnosed_followup")
        text += "\n\n" + DIAGNOSED_NOTE
    elif risk >= HIGH_RISK_THRESHOLD and remind_risk:
        flags.append("high_risk_referral")
        text += "\n\n" + HIGH_RISK_NOTE
    levels = {r["level"] for r in labs or ()}
    if "low" in levels:
        flags.append("lab_low_glucose")
        text += "\n\n" + LAB_NOTES["low"]
    if "diabetes" in levels and not diagnosed:
        flags.append("lab_diabetes_range")
        text += "\n\n" + LAB_NOTES["diabetes"]
    elif "prediabetes" in levels and not diagnosed:
        flags.append("lab_prediabetes_range")
        text += "\n\n" + LAB_NOTES["prediabetes"]
    if any(t in q for t in SYMPTOM_TERMS) or _SYMPTOM_PATTERN.search(q):
        flags.append("symptom_referral")
        text += "\n\n" + SYMPTOM_NOTE
    if any(t in q for t in EMERGENCY_TERMS):
        flags.append("emergency_referral")
        text += "\n\n" + EMERGENCY_NOTE
    text += "\n\n" + DISCLAIMER
    return text, flags
