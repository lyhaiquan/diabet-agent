"""Nhật ký tự theo dõi cho người đã được chẩn đoán đái tháo đường típ 2: đường huyết, huyết áp, cân nặng.

Khác Lab agent: Lab agent đối chiếu NGƯỠNG CHẨN ĐOÁN (FPG >= 126 mg/dL...). Ở đây người dùng đã có chẩn đoán,
nên chỉ số đo tại nhà được so với MỤC TIÊU KIỂM SOÁT chung cho người lớn không mang thai:
- ADA, Standards of Care in Diabetes 2024, mục 6 (Glycemic Goals and Hypoglycemia):
  trước ăn / lúc đói 80–130 mg/dL (4,4–7,2 mmol/L); đỉnh sau ăn < 180 mg/dL (10,0 mmol/L);
  hạ đường huyết mức 1 < 70 mg/dL (3,9 mmol/L), mức 2 < 54 mg/dL (3,0 mmol/L).
- ADA 2024, mục 10 (Cardiovascular Disease and Risk Management): huyết áp mục tiêu < 130/80 mmHg.
Đây là mục tiêu chung; bác sĩ có thể đặt mục tiêu riêng cho từng người. Mức "rất cao" (>= 250 mg/dL,
huyết áp >= 180/120) chỉ để nhắc đo lại và liên hệ bác sĩ, không phải chẩn đoán.

Mọi hàm có tham số now= để kiểm thử được; ngày được tính theo giờ Việt Nam (UTC+7, không đổi giờ mùa hè).
"""
from datetime import date, datetime, timedelta, timezone

from diacare.labs import MGDL_PER_MMOL

VN_TZ = timezone(timedelta(hours=7), "ICT")
SOURCE = "ADA Standards of Care 2024, mục 6 và 10"

CONTEXTS = {
    "fasting": "lúc đói (sáng, chưa ăn)",
    "before_meal": "trước bữa ăn",
    "after_meal": "1–2 giờ sau ăn",
    "bedtime": "trước khi ngủ",
    "random": "bất kỳ lúc nào",
}
PRE_MEAL = ("fasting", "before_meal")

HYPO_2 = 54
HYPO_1 = 70
PRE_MEAL_TARGET = (80, 130)
POST_MEAL_MAX = 180
VERY_HIGH = 250
BP_TARGET = (130, 80)
BP_CRISIS = (180, 120)
PLAUSIBLE = {"glucose": (20, 600), "systolic": (60, 260), "diastolic": (30, 160), "weight": (20, 300)}

STATUS_TEXT = {
    "hypo_2": "hạ đường huyết nặng",
    "hypo_1": "hạ đường huyết",
    "below_target": "thấp hơn mục tiêu",
    "in_target": "trong mục tiêu",
    "above_target": "cao hơn mục tiêu",
    "very_high": "rất cao",
}
STATUS_ICON = {"hypo_2": "🔵", "hypo_1": "🔵", "below_target": "🟡", "in_target": "🟢",
               "above_target": "🟡", "very_high": "🔴"}


def now_vn():
    return datetime.now(VN_TZ)


def to_vn(dt):
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ)


def to_mgdl(value, unit):
    """Đổi về mg/dL. Máy đo ở Việt Nam thường hiện mmol/L."""
    value = float(value)
    return value * MGDL_PER_MMOL if (unit or "").lower().startswith("mmol") else value


def to_mmol(mgdl):
    return mgdl / MGDL_PER_MMOL


def fmt_glucose(mgdl, unit="mmol/L"):
    if unit.lower().startswith("mmol"):
        return f"{to_mmol(mgdl):.1f}".replace(".", ",") + " mmol/L"
    return f"{mgdl:.0f} mg/dL"


def validate_glucose(value, unit):
    mgdl = to_mgdl(value, unit)
    lo, hi = PLAUSIBLE["glucose"]
    if not lo <= mgdl <= hi:
        return None, (f"Giá trị {value} {unit} không hợp lý. Kiểm tra lại đơn vị: máy đo ở Việt Nam thường hiện "
                      "mmol/L (vd 6,5), còn mg/dL là số lớn hơn (vd 117).")
    return mgdl, None


def validate_bp(systolic, diastolic):
    """Trả về thông báo lỗi, hoặc None nếu hợp lý."""
    lo_s, hi_s = PLAUSIBLE["systolic"]
    lo_d, hi_d = PLAUSIBLE["diastolic"]
    if systolic is None or diastolic is None or not (lo_s <= systolic <= hi_s and lo_d <= diastolic <= hi_d) \
            or diastolic >= systolic:
        return "Số huyết áp chưa hợp lý (vd 125/80: tâm thu lớn hơn tâm trương)."
    return None


def validate_weight(kg):
    lo, hi = PLAUSIBLE["weight"]
    return None if kg is not None and lo <= kg <= hi else "Cân nặng chưa hợp lý."


def describe_glucose(mgdl, context, unit="mmol/L"):
    """Kết quả một lần đo như người dùng thấy: mức, câu mô tả, lời khuyên (nếu có)."""
    status = classify_glucose(mgdl, context)
    level, advice = ADVICE.get(status, (None, None))
    return {"status": status, "status_text": STATUS_TEXT[status], "target": target_text(context),
            "message": f"Đã lưu {fmt_glucose(mgdl, unit)} ({CONTEXTS[context]}): {STATUS_TEXT[status]}, "
                       f"{target_text(context)}.",
            "advice": advice, "advice_level": level}


def classify_glucose(mgdl, context):
    if mgdl < HYPO_2:
        return "hypo_2"
    if mgdl < HYPO_1:
        return "hypo_1"
    if mgdl >= VERY_HIGH:
        return "very_high"
    if context in PRE_MEAL:
        lo, hi = PRE_MEAL_TARGET
        if mgdl < lo:
            return "below_target"
        return "in_target" if mgdl <= hi else "above_target"
    return "in_target" if mgdl < POST_MEAL_MAX else "above_target"


def target_text(context):
    if context in PRE_MEAL:
        lo, hi = PRE_MEAL_TARGET
        return f"mục tiêu {fmt_glucose(lo)}–{fmt_glucose(hi)}"
    return f"mục tiêu dưới {fmt_glucose(POST_MEAL_MAX)}"


def classify_bp(systolic, diastolic):
    if systolic >= BP_CRISIS[0] or diastolic >= BP_CRISIS[1]:
        return "very_high"
    if systolic >= BP_TARGET[0] or diastolic >= BP_TARGET[1]:
        return "above_target"
    return "in_target"


# Lời nhắn cho từng mức. Không bao giờ khuyên đổi liều thuốc.
ADVICE = {
    "hypo_2": ("error", "Đường huyết rất thấp. Ăn hoặc uống ngay khoảng 15 g đường nhanh (nửa cốc nước ngọt, "
                        "3–4 viên kẹo đường), đo lại sau 15 phút. Nếu lơ mơ, không tự ăn uống được: gọi 115 "
                        "hoặc nhờ người đưa đi cấp cứu."),
    "hypo_1": ("warning", "Hạ đường huyết. Quy tắc 15–15: ăn khoảng 15 g đường nhanh, đo lại sau 15 phút, lặp lại "
                          "nếu vẫn dưới 3,9 mmol/L. Báo bác sĩ ở lần khám tới, vì có thể cần chỉnh thuốc."),
    "very_high": ("error", "Đường huyết rất cao. Đo lại để chắc chắn. Nếu vẫn cao hoặc kèm khát nhiều, tiểu nhiều, "
                           "mệt lả, buồn nôn: liên hệ bác sĩ hoặc đi khám ngay. Không tự tăng liều thuốc."),
    "bp_very_high": ("error", "Huyết áp rất cao. Ngồi nghỉ 5 phút rồi đo lại. Nếu vẫn từ 180/120 trở lên, hoặc có "
                              "đau ngực, khó thở, yếu tay chân, nói khó: đi cấp cứu ngay."),
}


# ---- thống kê --------------------------------------------------------------

def _day(r):
    return to_vn(r["measured_at"]).date()


def glucose_rows(readings):
    return [r for r in readings if r["kind"] == "glucose"]


def summarize_glucose(readings, days=14, now=None):
    """Thống kê đường huyết trong `days` ngày gần nhất, theo từng thời điểm đo."""
    now = to_vn(now or now_vn())
    start = now.date() - timedelta(days=days - 1)
    rows = [r for r in glucose_rows(readings) if start <= _day(r) <= now.date()]
    out = {"days": days, "n": len(rows), "by_context": {}, "hypo": 0, "very_high": 0, "in_target_pct": None,
           "mean_mgdl": None, "days_measured": len({_day(r) for r in rows})}
    if not rows:
        return out
    statuses = [classify_glucose(r["value"], r["context"]) for r in rows]
    out["hypo"] = sum(s in ("hypo_1", "hypo_2") for s in statuses)
    out["very_high"] = statuses.count("very_high")
    out["in_target_pct"] = round(100 * statuses.count("in_target") / len(rows))
    out["mean_mgdl"] = sum(r["value"] for r in rows) / len(rows)
    for ctx in CONTEXTS:
        vals = [r["value"] for r in rows if r["context"] == ctx]
        if vals:
            st = [classify_glucose(v, ctx) for v in vals]
            out["by_context"][ctx] = {"n": len(vals), "mean_mgdl": sum(vals) / len(vals),
                                      "min_mgdl": min(vals), "max_mgdl": max(vals),
                                      "in_target_pct": round(100 * st.count("in_target") / len(vals))}
    return out


def compare_periods(readings, days=14, now=None):
    """Trung bình đường huyết lúc đói/trước ăn kỳ này so với kỳ trước (cùng độ dài). None nếu thiếu dữ liệu."""
    now = to_vn(now or now_vn())

    def mean_in(end):
        start = end - timedelta(days=days - 1)
        vals = [r["value"] for r in glucose_rows(readings)
                if r["context"] in PRE_MEAL and start <= _day(r) <= end]
        return sum(vals) / len(vals) if len(vals) >= 3 else None

    cur, prev = mean_in(now.date()), mean_in(now.date() - timedelta(days=days))
    if cur is None or prev is None:
        return None
    return {"current_mgdl": cur, "previous_mgdl": prev, "delta_mgdl": cur - prev}


def summarize_bp(readings, days=14, now=None):
    now = to_vn(now or now_vn())
    start = now.date() - timedelta(days=days - 1)
    rows = [r for r in readings if r["kind"] == "bp" and start <= _day(r) <= now.date()]
    if not rows:
        return None
    sys_ = sum(r["value"] for r in rows) / len(rows)
    dia = sum(r["value2"] for r in rows) / len(rows)
    above = sum(classify_bp(r["value"], r["value2"]) != "in_target" for r in rows)
    return {"n": len(rows), "systolic": sys_, "diastolic": dia, "above_target": above}


def weight_change(readings, days=30, now=None):
    now = to_vn(now or now_vn())
    start = now.date() - timedelta(days=days - 1)
    rows = sorted((r for r in readings if r["kind"] == "weight" and start <= _day(r) <= now.date()),
                  key=lambda r: r["measured_at"])
    if not rows:
        return None
    return {"first": rows[0]["value"], "last": rows[-1]["value"], "delta": rows[-1]["value"] - rows[0]["value"],
            "n": len(rows)}


# ---- cảnh báo và nhắc nhở hiện khi mở ứng dụng ----------------------------

def alerts(readings, now=None, hours=24):
    """Cảnh báo từ các lần đo trong `hours` giờ qua: (mức streamlit, nội dung). Mỗi loại một lần, mới nhất trước."""
    now = to_vn(now or now_vn())
    recent = sorted((r for r in readings if now - timedelta(hours=hours) <= to_vn(r["measured_at"]) <= now),
                    key=lambda r: r["measured_at"], reverse=True)
    out, seen = [], set()
    for r in recent:
        if r["kind"] == "glucose":
            key = classify_glucose(r["value"], r["context"])
        elif r["kind"] == "bp":
            key = "bp_very_high" if classify_bp(r["value"], r["value2"]) == "very_high" else None
        else:
            key = None
        if key in ADVICE and key not in seen:
            seen.add(key)
            level, text = ADVICE[key]
            when = to_vn(r["measured_at"]).strftime("%H:%M %d/%m")
            out.append((level, f"{text} (lần đo lúc {when})"))
    # cùng một cảnh báo hạ đường huyết nặng thì không cần hiện thêm mức nhẹ
    if "hypo_2" in seen:
        out = [a for a in out if not a[1].startswith(ADVICE["hypo_1"][1])]
    return out


def high_streak(readings, now=None, days=3):
    """True nếu lúc đói/trước ăn vượt mục tiêu ở MỌI ngày có đo trong `days` ngày qua (ít nhất `days` ngày đo)."""
    now = to_vn(now or now_vn())
    by_day = {}
    for r in glucose_rows(readings):
        d = _day(r)
        if r["context"] in PRE_MEAL and now.date() - timedelta(days=days - 1) <= d <= now.date():
            by_day.setdefault(d, []).append(classify_glucose(r["value"], r["context"]))
    return len(by_day) >= days and all(
        any(s in ("above_target", "very_high") for s in v) for v in by_day.values())


def reminders(readings, appointment=None, now=None):
    """Nhắc nhở hiện trong ứng dụng khi người dùng mở ra (Streamlit không gửi được thông báo khi đóng tab)."""
    now = to_vn(now or now_vn())
    out = []
    if not any(_day(r) == now.date() for r in glucose_rows(readings)):
        out.append(("info", "Hôm nay bạn chưa ghi đường huyết."))
    if high_streak(readings, now):
        out.append(("warning", "Đường huyết lúc đói hoặc trước ăn cao hơn mục tiêu 3 ngày liền. Nên hẹn bác sĩ "
                               "sớm hơn lịch, mang theo nhật ký này."))
    if appointment:
        d = date.fromisoformat(appointment["date"])
        left = (d - now.date()).days
        place = f" tại {appointment['place']}" if appointment.get("place") else ""
        if left < 0:
            out.append(("warning", f"Lịch tái khám {d:%d/%m/%Y}{place} đã qua {-left} ngày. Cập nhật lịch mới "
                                   "ở trang Tái khám."))
        elif left == 0:
            out.append(("warning", f"Hôm nay có lịch tái khám{place}. Nhớ tải bản tóm tắt ở trang Tái khám."))
        elif left <= 7:
            out.append(("info", f"Còn {left} ngày nữa tới lịch tái khám ({d:%d/%m/%Y}){place}. "
                                "Nhớ nhịn ăn nếu bác sĩ có hẹn xét nghiệm máu lúc đói."))
    return out


def daily_series(readings, days=14, now=None):
    """Các điểm đường huyết (thời điểm VN, mg/dL, thời điểm đo) trong `days` ngày để vẽ biểu đồ."""
    now = to_vn(now or now_vn())
    start = now.date() - timedelta(days=days - 1)
    return sorted(((to_vn(r["measured_at"]), r["value"], r["context"]) for r in glucose_rows(readings)
                   if start <= _day(r) <= now.date()), key=lambda t: t[0])
