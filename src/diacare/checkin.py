"""Trợ lý chủ động hỏi: mỗi ngày một lần, khi người đã chẩn đoán mở trang Tư vấn, trợ lý mở lời trước dựa trên
nhật ký (chưa đo hôm nay, vừa có số đo nguy hiểm, mấy hôm cao liền) kèm lời nhắc hôm nay của agent Q-learning, rồi
nhận câu trả lời gõ chữ.

Mọi câu ở đây là câu soạn sẵn từ dữ liệu nhật ký, không do LLM viết: lời mở đầu, lời xác nhận đã ghi, và cảnh báo
khi số đo nguy hiểm (lấy từ journal.ADVICE) phải đúng và giống nhau mọi lần. Câu trả lời không phải số đo thì
app.py chuyển cho pipeline tư vấn thường (orchestrator), có lời mở đầu trong lịch sử để LLM hiểu ngữ cảnh.
Không có gì ở đây chạy trong orchestrator.run, nên benchmark không đổi.

Số đo đọc được từ câu trả lời chỉ là đề xuất: app.py hiện thẻ xác nhận (giá trị, đơn vị, thời điểm đo, ngày giờ)
và chỉ lưu khi người dùng bấm Lưu.
"""
import re
import unicodedata
from datetime import datetime, time, timedelta

from diacare import journal
from diacare.speech import guess_context, parse_spoken_reading

# Câu hỏi thì để LLM trả lời, kể cả khi có số ("8,5 lúc đói có cao không?"): không bắt nhầm thành số đo để lưu
_QUESTION = re.compile(r"\?|\b(có\s+\S+(\s+\S+)?\s+không|sao|thế nào|như thế nào|bao nhiêu|là gì|nên|được không|"
                       r"có phải|tại sao|vì sao|làm gì)\b")
# "Chưa đo": chỉ các câu từ chối việc đo. "không" đứng một mình không đủ: "không ổn, run tay" là kể triệu chứng
_NOT_YET = re.compile(r"\b(chưa|quên|hết que)\b|\b(không|ko|k)\s+(có\s+)?(đo|kịp)\b|^\s*(không|ko|k)\s*[.!]*\s*$")
# Triệu chứng khi trợ lý vừa hỏi "bây giờ bạn thấy trong người thế nào" sau số đo nguy hiểm
_SYMPTOM = re.compile(r"\b(run|vã mồ hôi|mồ hôi|chóng mặt|hoa mắt|mệt lả|lả|ngất|xỉu|tim đập nhanh|hồi hộp|"
                      r"khó thở|lú lẫn|mờ mắt|khát nhiều|buồn nôn|nôn|không ổn|không khỏe|không khoẻ)\b")
_STARTS_WITH_NUMBER = re.compile(r"^\s*(?:khoảng|tầm|được|là)?\s*\d")
_TIME = re.compile(r"(?:lúc\s*)?\b(\d{1,2})\s*(?:h|giờ|:)\s*(\d{1,2})?\b")


def _norm(text):
    return unicodedata.normalize("NFC", text or "").lower().strip()


def _fmt_time(dt):
    return f"{dt:%H:%M}"


def _day_word(dt, now):
    days = (now.date() - dt.date()).days
    return "hôm nay" if days == 0 else "hôm qua" if days == 1 else f"ngày {dt:%d/%m}"


def plan_topic(readings, now=None, targets=None):
    """Chọn MỘT điều đáng hỏi nhất hôm nay. Trả về dict: kind, question (câu hỏi), expects ("glucose" nếu đợi
    người dùng gõ số đường huyết, None nếu câu trả lời là lời kể tự do), context (thời điểm đo gợi ý)."""
    now = journal.to_vn(now or journal.now_vn())
    rows = journal.glucose_rows(readings)
    recent = [r for r in rows if now - timedelta(hours=24) <= journal.to_vn(r["measured_at"]) <= now]
    for r in reversed(recent):
        status = journal.classify_glucose(r["value"], r["context"], targets)
        if status in ("hypo_1", "hypo_2", "very_high"):
            when = journal.to_vn(r["measured_at"])
            return {
                "kind": "alert", "status": status, "expects": "glucose", "context": None,
                "question": (f"Lúc {_fmt_time(when)} {_day_word(when, now)} bạn đo được "
                             f"{journal.fmt_glucose(r['value'], r.get('unit') or 'mmol/L')}, "
                             f"{journal.STATUS_TEXT[status]}. Bây giờ bạn thấy trong người thế nào? "
                             "Nếu đã đo lại thì gõ số cho mình nhé."),
            }
    if not any(journal._day(r) == now.date() for r in rows):
        if 4 <= now.hour < 10:
            return {"kind": "missing", "expects": "glucose", "context": "fasting",
                    "question": "Sáng nay bạn đã đo đường huyết lúc đói chưa? Đo rồi thì gõ số cho mình, "
                                "ví dụ \"6,5\", mình ghi vào nhật ký giúp bạn."}
        return {"kind": "missing", "expects": "glucose", "context": None,
                "question": "Hôm nay mình chưa thấy số đường huyết nào của bạn. Bạn đo được lúc nào thì gõ cho "
                            "mình nhé, ví dụ \"7,8 sau ăn trưa\"."}
    if journal.high_streak(readings, now, targets=targets):
        return {"kind": "streak", "expects": None, "context": None,
                "question": "Mấy hôm nay đường huyết lúc đói của bạn cao hơn mục tiêu. Tối qua bạn ăn gì, có ăn "
                            "khuya hay quên thuốc không? Kể mình nghe để mình gợi ý cách điều chỉnh."}
    last = rows[-1]
    status = journal.classify_glucose(last["value"], last["context"], targets)
    return {"kind": "ok", "expects": None, "context": None,
            "question": (f"Hôm nay bạn đã ghi {journal.fmt_glucose(last['value'], last.get('unit') or 'mmol/L')} "
                         f"{journal.CONTEXTS.get(last['context'], '')}, {journal.STATUS_TEXT[status]}. "
                         "Hôm nay bạn có muốn hỏi gì về bữa ăn, vận động hay thuốc không?")}


def opener_text(name, topic, nudge_text=None):
    first = (name or "").strip()
    text = f"Chào {first}! {topic['question']}" if first else f"Chào bạn! {topic['question']}"
    if nudge_text:
        text += f"\n\n**Lời nhắc hôm nay:** {nudge_text}"
    return text


def _when_from_text(text, now):
    """Ngày giờ đo đoán từ câu ("hôm qua", "lúc 7h30"); không nói giờ thì là bây giờ. Chỉ là giá trị mặc định
    trên thẻ xác nhận, người dùng sửa được."""
    t = _norm(text)
    day = now.date() - timedelta(days=1) if "hôm qua" in t or "tối qua" in t else now.date()
    m = _TIME.search(t)
    if m and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2) or 0) <= 59:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if hour < 12 and re.search(r"\b(chiều|tối)\b", t):
            hour += 12
        when = datetime.combine(day, time(hour, minute), tzinfo=journal.VN_TZ)
    else:
        when = now if day == now.date() else datetime.combine(day, time(now.hour, now.minute), tzinfo=journal.VN_TZ)
    return min(when, now)


def route_reply(text, topic, now=None):
    """Quyết định MỘT cách xử lý câu người dùng vừa gõ khi trợ lý đang đợi trả lời câu hỏi chủ động.
    Trả về {"route": "reading", "reading": ..., "when": datetime} | {"route": "not_yet"} | {"route": "ask"}."""
    now = journal.to_vn(now or journal.now_vn())
    t = _norm(text)
    if topic and topic.get("kind") == "alert" and _SYMPTOM.search(t) and not re.search(r"\d", t):
        return {"route": "symptom"}
    if not topic or topic.get("expects") != "glucose" or _QUESTION.search(t):
        return {"route": "ask"}
    reading = parse_spoken_reading(text)
    if reading is None:
        # Trả lời gọn cho câu hỏi đường huyết, không có chữ "đường huyết": "6,5", "6,5 lúc đói", "tối qua 9 giờ đo
        # 8,1". Bỏ phần giờ đi rồi chỉ nhận khi còn đúng một số trông như đường huyết (số thập phân, hoặc số nguyên
        # 40-400 mg/dL, hoặc có đơn vị), để "tối qua ăn 2 bát cơm" không thành số đo.
        rest = _TIME.sub(" ", t)
        nums = re.findall(r"\d+(?:[.,]\d+)?", rest)
        if len(nums) == 1 and (_STARTS_WITH_NUMBER.search(rest) or re.search(r"\bđo\b", rest)):
            n = nums[0]
            unit = re.search(r"mmol|mg", rest)
            if "," in n or "." in n or unit or 40 <= int(n) <= 400:
                reading = parse_spoken_reading("đường huyết " + rest[rest.index(n):])
                if reading is not None:  # thời điểm đo có thể nằm trước con số ("sau ăn 7,8")
                    reading["context"] = reading.get("context") or guess_context(text)
    if reading is not None:
        if reading["kind"] == "glucose" and not reading.get("context"):
            reading["context"] = topic.get("context") or _guess_context(now)
        return {"route": "reading", "reading": reading, "when": _when_from_text(text, now)}
    if _NOT_YET.search(t) and not re.search(r"\d", t):
        return {"route": "not_yet"}
    return {"route": "ask"}


def _guess_context(now):
    h = now.hour
    if 4 <= h < 9:
        return "fasting"
    if 21 <= h or h < 4:
        return "bedtime"
    return "before_meal"


NOT_YET_REPLY = ("Không sao. Khi nào đo xong, bạn gõ số vào đây, mình ghi vào nhật ký giúp bạn. "
                 "Nếu bạn thấy run tay, vã mồ hôi, chóng mặt thì đo ngay nhé.")
def symptom_reply(topic):
    """Người dùng kể triệu chứng ngay sau số đo nguy hiểm: nhắc lời khuyên an toàn soạn sẵn, không qua LLM."""
    advice = journal.ADVICE.get(topic.get("status"), journal.ADVICE["hypo_1"])[1]
    return (f"Bạn đang có triệu chứng, nên làm ngay nhé: {advice} Nếu thấy lả đi, lơ mơ hoặc không tự ăn uống được, "
            "người nhà cần gọi 115 ngay. Đo lại được thì gõ số cho mình.")


CANCEL_REPLY = "Vậy bạn gõ lại giúp mình số đo và thời điểm đo nhé, ví dụ \"6,5 lúc đói\"."


def saved_reply(reading, targets=None):
    """Câu xác nhận sau khi lưu số đo, kèm lời khuyên an toàn soạn sẵn nếu số đo ngoài mục tiêu."""
    if reading["kind"] == "glucose":
        mgdl = journal.to_mgdl(reading["value"], reading["unit"])
        status = journal.classify_glucose(mgdl, reading["context"], targets)
        text = (f"Mình đã ghi {journal.fmt_glucose(mgdl, reading['unit'])} "
                f"({journal.CONTEXTS[reading['context']]}) vào nhật ký: {journal.STATUS_TEXT[status]}, "
                f"{journal.target_text(reading['context'], targets)}.")
        if status in journal.ADVICE:
            text += " " + journal.ADVICE[status][1]
        elif status == "in_target":
            text += " Tốt lắm, bạn cứ giữ nhịp ăn uống và đo đều như vậy nhé."
        elif status == "above_target":
            text += (" Một lần cao chưa nói lên nhiều; nếu cao lặp lại vài ngày thì nên báo bác sĩ. "
                     "Bạn kể mình nghe bữa trước đó ăn gì nhé.")
        return text
    if reading["kind"] == "bp":
        status = journal.classify_bp(reading["systolic"], reading["diastolic"])
        text = (f"Mình đã ghi huyết áp {reading['systolic']}/{reading['diastolic']} mmHg: "
                f"{journal.STATUS_TEXT[status]} (mục tiêu dưới 130/80).")
        if status == "very_high":
            text += " " + journal.ADVICE["bp_very_high"][1]
        return text
    kg = f"{reading['kg']:g}".replace(".", ",")
    return f"Mình đã ghi cân nặng {kg} kg vào nhật ký."
