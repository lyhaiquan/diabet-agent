from datetime import datetime, timedelta

import pytest

from diacare import journal
from diacare.checkin import (NOT_YET_REPLY, opener_text, plan_topic, route_reply, saved_reply,
                             symptom_reply, unprompted_reading)

NOW = datetime(2026, 11, 24, 7, 30, tzinfo=journal.VN_TZ)


def g(mgdl, hours_ago, context="fasting"):
    return {"kind": "glucose", "value": mgdl, "context": context, "unit": "mmol/L",
            "measured_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_morning_without_reading_asks_fasting():
    t = plan_topic([g(110, 24 * 2)], NOW)
    assert t["kind"] == "missing" and t["expects"] == "glucose" and t["context"] == "fasting"
    assert "lúc đói" in t["question"]


def test_afternoon_without_reading_has_no_fixed_context():
    t = plan_topic([], NOW.replace(hour=15))
    assert t["kind"] == "missing" and t["context"] is None


def test_recent_hypo_comes_first():
    t = plan_topic([g(60, 10, "bedtime"), g(110, 1)], NOW)
    assert t["kind"] == "alert" and t["status"] == "hypo_1"
    assert "3,3" in t["question"] and "hôm qua" in t["question"]


def test_streak_asks_about_food():
    rows = [g(160, 24 * d) for d in range(3)]
    t = plan_topic(rows, NOW)
    assert t["kind"] == "streak" and t["expects"] is None


def test_ok_day():
    t = plan_topic([g(110, 1)], NOW)
    assert t["kind"] == "ok" and "trong mục tiêu" in t["question"]


def test_opener_includes_nudge():
    text = opener_text("Lan", {"question": "Q?"}, "Đo đường huyết nhé.")
    assert text.startswith("Chào Lan! Q?") and "**Lời nhắc hôm nay:** Đo đường huyết nhé." in text


MISSING = {"kind": "missing", "expects": "glucose", "context": "fasting"}


@pytest.mark.parametrize("text,value,unit", [
    ("6,5", 6.5, "mmol/L"),
    ("6.5 mmol", 6.5, "mmol/L"),
    ("đo rồi, đường huyết 7,2", 7.2, "mmol/L"),
    ("120 mg", 120.0, "mg/dL"),
])
def test_reply_with_number_becomes_reading(text, value, unit):
    r = route_reply(text, MISSING, NOW)
    assert r["route"] == "reading"
    assert r["reading"]["value"] == value and r["reading"]["unit"] == unit
    assert r["reading"]["context"] == "fasting"
    assert r["when"] == NOW


def test_context_in_text_wins_and_time_is_read():
    r = route_reply("7,8 sau ăn lúc 6h15", MISSING, NOW)
    assert r["reading"]["context"] == "after_meal"
    assert (r["when"].hour, r["when"].minute) == (6, 15)


def test_yesterday_evening():
    r = route_reply("tối qua 9 giờ đo 8,1", MISSING, NOW)
    assert r["route"] == "reading" and r["reading"]["value"] == 8.1
    assert r["when"].date() == NOW.date() - timedelta(days=1) and r["when"].hour == 21


def test_time_never_in_future():
    assert route_reply("6,5 lúc 9h", MISSING, NOW)["when"] == NOW


def test_ambiguous_number_keeps_alternative():
    r = route_reply("68", MISSING, NOW)
    assert r["reading"]["unit"] == "mg/dL" and r["reading"]["alternative"]["value"] == 6.8


@pytest.mark.parametrize("text", ["chưa", "chưa đo", "quên mất rồi", "ko", "ko đo", "không kịp đo", "Không."])
def test_not_yet(text):
    assert route_reply(text, MISSING, NOW) == {"route": "not_yet"}


@pytest.mark.parametrize("text", [
    "8,5 lúc đói có cao không?",          # câu hỏi có số: để LLM trả lời, không lưu
    "đường huyết bao nhiêu là tốt",
    "tối qua ăn 2 bát cơm",              # có số nhưng không phải số đo
    "hôm nay mệt quá",
])
def test_questions_and_stories_go_to_llm(text):
    assert route_reply(text, MISSING, NOW) == {"route": "ask"}


def test_no_pending_question_always_asks():
    assert route_reply("6,5", None, NOW) == {"route": "ask"}
    assert route_reply("6,5", {"expects": None}, NOW) == {"route": "ask"}


def test_saved_reply_uses_fixed_advice_for_hypo():
    text = saved_reply({"kind": "glucose", "value": 3.5, "unit": "mmol/L", "context": "fasting"})
    assert "hạ đường huyết" in text and journal.ADVICE["hypo_1"][1] in text


def test_saved_reply_in_target():
    text = saved_reply({"kind": "glucose", "value": 6.0, "unit": "mmol/L", "context": "fasting"})
    assert "6,0 mmol/L" in text and "trong mục tiêu" in text


def test_saved_reply_bp_weight():
    assert "185/125" in saved_reply({"kind": "bp", "systolic": 185, "diastolic": 125})
    assert "62,5 kg" in saved_reply({"kind": "weight", "kg": 62.5})
    assert NOT_YET_REPLY


ALERT = {"kind": "alert", "status": "hypo_1", "expects": "glucose", "context": None}


@pytest.mark.parametrize("text", ["không ổn, run tay vã mồ hôi", "không khỏe", "hơi chóng mặt"])
def test_symptoms_after_alert_get_safety_advice(text):
    assert route_reply(text, ALERT, NOW) == {"route": "symptom"}
    reply = symptom_reply(ALERT)
    assert journal.ADVICE["hypo_1"][1] in reply and "115" in reply


@pytest.mark.parametrize("text", ["không ổn lắm", "không khỏe"])
def test_symptom_words_never_mean_not_yet(text):
    assert route_reply(text, MISSING, NOW)["route"] != "not_yet"


def test_alert_reply_with_number_is_still_reading():
    assert route_reply("đo lại 4,8 rồi, hết run", ALERT, NOW)["route"] == "reading"


@pytest.mark.parametrize("text,value", [("sáu phẩy năm", 6.5), ("bảy rưỡi sau ăn", 7.5), ("tối qua chín giờ đo tám phẩy một", 8.1)])
def test_spoken_numbers_become_readings(text, value):
    r = route_reply(text, MISSING, NOW)
    assert r["route"] == "reading" and r["reading"]["value"] == value


@pytest.mark.parametrize("text, kind", [
    ("Mình vừa đo đường huyết được 7,2", "glucose"),
    ("đường huyết sáng nay lúc đói sáu phẩy tám", "glucose"),
    ("huyết áp 130 trên 85", "bp"),
    ("tôi nặng 62 ký", "weight"),
])
def test_unprompted_reading_found(text, kind):
    found = unprompted_reading(text, NOW)
    assert found["reading"]["kind"] == kind and found["when"] <= NOW
    if kind == "glucose":
        assert found["reading"]["context"] in journal.CONTEXTS


@pytest.mark.parametrize("text", [
    "đường huyết 7,2 có cao không?",   # câu hỏi: sang tư vấn
    "đường huyết bao nhiêu là tốt",
    "mỗi ngày ăn 50 g đường được không",
    "tôi ăn 2 bát cơm",
    "Ăn chuối có sao không?",
])
def test_unprompted_reading_ignores_questions(text):
    assert unprompted_reading(text, NOW) is None
