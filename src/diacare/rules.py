HIGH_RISK_THRESHOLD = 0.5
BANNED_PHRASES = [
    "ngừng insulin", "ngưng insulin", "bỏ thuốc", "ngưng thuốc",
    "tự ý tăng liều", "tự ý giảm liều",
]
DISCLAIMER = "Đây chỉ là thông tin tham khảo, không thay thế tư vấn của bác sĩ."
SAFE_REPLACEMENT = (
    "Mình không thể đưa ra lời khuyên về việc thay đổi thuốc hoặc insulin. "
    "Vui lòng hỏi bác sĩ điều trị của bạn."
)


def validate_profile(profile):
    errors = []
    bmi = profile.get("BMI")
    if bmi is not None and not (10 <= bmi <= 80):
        errors.append(f"BMI không hợp lệ: {bmi}")
    return errors


def apply_rules(risk, draft):
    flags = []
    text = draft
    if any(p in draft.lower() for p in BANNED_PHRASES):
        flags.append("unsafe_advice_blocked")
        text = SAFE_REPLACEMENT
    if risk >= HIGH_RISK_THRESHOLD:
        flags.append("high_risk_referral")
        text += (
            "\n\nNguy cơ của bạn ở mức cao: hãy đặt lịch khám và xét nghiệm "
            "đường huyết (HbA1c hoặc glucose lúc đói)."
        )
    text += "\n\n" + DISCLAIMER
    return text, flags
