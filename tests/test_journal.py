import io
from datetime import datetime, timedelta

import pytest
from pypdf import PdfReader

from diacare import journal
from diacare.db import Store
from diacare.visit_report import build_visit_pdf, collect

NOW = datetime(2026, 11, 13, 20, 0, tzinfo=journal.VN_TZ)


def mmol(x):
    return x * 18.0


def reading(value, context="fasting", at=NOW, kind="glucose", value2=None):
    return {"kind": kind, "value": value, "value2": value2, "context": context, "measured_at": at.isoformat()}


# ---- phân loại theo mục tiêu điều trị (không phải ngưỡng chẩn đoán) ----

@pytest.mark.parametrize("mgdl,context,expected", [
    (50, "fasting", "hypo_2"), (65, "after_meal", "hypo_1"), (75, "fasting", "below_target"),
    (110, "fasting", "in_target"), (130, "before_meal", "in_target"), (140, "fasting", "above_target"),
    (170, "after_meal", "in_target"), (185, "after_meal", "above_target"), (260, "random", "very_high"),
    (75, "after_meal", "in_target"),
])
def test_classify_glucose(mgdl, context, expected):
    assert journal.classify_glucose(mgdl, context) == expected


def test_units_and_validation():
    assert journal.to_mgdl(7.2, "mmol/L") == pytest.approx(129.6)
    assert journal.to_mgdl(130, "mg/dL") == 130
    assert journal.fmt_glucose(126) == "7,0 mmol/L"
    mgdl, err = journal.validate_glucose(6.5, "mmol/L")
    assert err is None and mgdl == pytest.approx(117)
    # gõ 120 nhưng để đơn vị mmol/L: 2160 mg/dL là không hợp lý, phải nhắc kiểm tra đơn vị
    mgdl, err = journal.validate_glucose(120, "mmol/L")
    assert mgdl is None and "đơn vị" in err


def test_classify_bp():
    assert journal.classify_bp(120, 75) == "in_target"
    assert journal.classify_bp(132, 78) == "above_target"
    assert journal.classify_bp(185, 100) == "very_high"


def test_day_uses_vietnam_time():
    # 23:30 UTC ngày 12 là 6:30 sáng ngày 13 ở Việt Nam
    r = {"kind": "glucose", "value": 110, "context": "fasting", "measured_at": "2026-11-12T23:30:00+00:00"}
    s = journal.summarize_glucose([r], days=1, now=NOW)
    assert s["n"] == 1 and s["days_measured"] == 1
    assert not any("chưa ghi" in t for _, t in journal.reminders([r], now=NOW))


def test_summarize_glucose_by_context():
    rows = [reading(mmol(6.0), at=NOW - timedelta(days=d)) for d in range(5)]
    rows += [reading(mmol(12.0), "after_meal", at=NOW - timedelta(days=1)), reading(mmol(3.5), "random")]
    rows.append(reading(mmol(6.0), at=NOW - timedelta(days=30)))  # ngoài khoảng 14 ngày
    s = journal.summarize_glucose(rows, 14, NOW)
    assert s["n"] == 7 and s["hypo"] == 1 and s["very_high"] == 0
    assert s["by_context"]["fasting"]["n"] == 5 and s["by_context"]["fasting"]["in_target_pct"] == 100
    assert s["by_context"]["after_meal"]["in_target_pct"] == 0
    assert s["in_target_pct"] == round(100 * 5 / 7)


def test_compare_periods_needs_enough_data():
    rows = [reading(mmol(8.0), at=NOW - timedelta(days=d)) for d in range(3)]
    assert journal.compare_periods(rows, 14, NOW) is None
    rows += [reading(mmol(7.0), at=NOW - timedelta(days=14 + d)) for d in range(3)]
    c = journal.compare_periods(rows, 14, NOW)
    assert c["delta_mgdl"] == pytest.approx(18.0)


def test_alerts_recent_only_and_hypo_2_supersedes_hypo_1():
    rows = [reading(50, "random", NOW - timedelta(hours=1)), reading(65, "random", NOW - timedelta(hours=2)),
            reading(40, "random", NOW - timedelta(days=3))]
    out = journal.alerts(rows, now=NOW)
    assert len(out) == 1 and out[0][0] == "error" and "115" in out[0][1]
    assert journal.alerts([reading(300, "after_meal")], now=NOW)[0][1].startswith("Đường huyết rất cao")
    bp = journal.alerts([reading(190, kind="bp", value2=110, context=None)], now=NOW)
    assert "cấp cứu" in bp[0][1]


def test_advice_never_tells_to_change_dose():
    for _, text in journal.ADVICE.values():
        assert "tăng liều" not in text.replace("Không tự tăng liều", "")


def test_reminders():
    assert ("info", "Hôm nay bạn chưa ghi đường huyết.") in journal.reminders([], now=NOW)
    streak = [reading(mmol(8.5), at=NOW - timedelta(days=d)) for d in range(3)]
    assert any("3 ngày liền" in t for _, t in journal.reminders(streak, now=NOW))
    mixed = streak + [reading(mmol(6.0), at=NOW - timedelta(days=1))]
    assert journal.high_streak(mixed, now=NOW)  # mỗi ngày có ít nhất một lần cao
    ok = [reading(mmol(6.0), at=NOW - timedelta(days=d)) for d in range(3)]
    assert not journal.high_streak(ok, now=NOW)
    appt = {"date": "2026-11-16", "place": "BV Bạch Mai"}
    assert any("Còn 3 ngày" in t and "Bạch Mai" in t for _, t in journal.reminders(ok, appt, now=NOW))
    assert any("Hôm nay có lịch" in t for _, t in journal.reminders(ok, {"date": "2026-11-13"}, now=NOW))
    assert any("đã qua 2 ngày" in t for _, t in journal.reminders(ok, {"date": "2026-11-11"}, now=NOW))
    assert len(journal.reminders(ok, {"date": "2026-12-30"}, now=NOW)) == 0


# ---- lưu trữ ----

def test_store_readings_questions_appointments():
    s = Store()
    pid = s.save_patient("An", {})
    other = s.save_patient("Bình", {})
    rid = s.add_reading(pid, "glucose", 120, NOW, unit="mmol/L", context="fasting", note="sau tập")
    s.add_reading(pid, "bp", 128, NOW - timedelta(days=1), value2=82, unit="mmHg")
    s.add_reading(pid, "weight", 60.5, NOW - timedelta(days=2))
    assert [r["kind"] for r in s.list_readings(pid)] == ["weight", "bp", "glucose"]  # theo thời điểm đo
    assert s.list_readings(pid, "bp")[0]["value2"] == 82
    s.delete_reading(rid, other)  # không xoá được bản ghi của người khác
    assert len(s.list_readings(pid)) == 3
    s.delete_reading(rid, pid)
    assert len(s.list_readings(pid)) == 2
    q = s.add_doctor_question(pid, "  Có nên đổi giờ uống thuốc?  ")
    assert [x["text"] for x in s.list_doctor_questions(pid)] == ["Có nên đổi giờ uống thuốc?"]
    s.mark_doctor_question(q)
    assert s.list_doctor_questions(pid) == [] and len(s.list_doctor_questions(pid, include_done=True)) == 1
    assert s.get_appointment(pid) is None
    s.set_appointment(pid, "2026-11-20", "BV A")
    s.set_appointment(pid, "2026-12-01", None)
    assert s.get_appointment(pid)["date"] == "2026-12-01"


# ---- bản tóm tắt tái khám ----

def _seed(store):
    pid = store.save_patient("Nguyễn Thị Hường", {})
    for d in range(28):
        store.add_reading(pid, "glucose", mmol(7.5), NOW - timedelta(days=d, hours=12), context="fasting")
        store.add_reading(pid, "glucose", mmol(9.0), NOW - timedelta(days=d, hours=6), context="after_meal")
    store.add_reading(pid, "glucose", mmol(3.4), NOW - timedelta(hours=1), context="random")
    store.add_reading(pid, "bp", 138, NOW, value2=86)
    store.add_reading(pid, "weight", 68.5, NOW - timedelta(days=20))
    store.add_reading(pid, "weight", 67.0, NOW)
    store.add_lab(pid, "hba1c", 7.8, "%")
    store.add_memory(pid, "medication", "metformin")
    store.add_memory(pid, "diagnosis", "đái tháo đường típ 2")
    store.add_doctor_question(pid, "Hay hạ đường huyết buổi chiều, có cần chỉnh thuốc?")
    store.set_appointment(pid, "2026-11-18", "Bệnh viện Nội tiết <TW>")
    return pid


def test_collect_visit_data():
    s = Store()
    pid = _seed(s)
    d = collect(s, pid, days=28, now=NOW)
    assert d["glucose"]["hypo"] == 1 and d["glucose"]["n"] == 57
    assert d["medications"] == ["metformin"] and d["conditions"] == ["đái tháo đường típ 2"]
    assert d["weight"]["delta"] == pytest.approx(-1.5)
    assert d["labs"][0]["test"] == "hba1c"


def test_visit_pdf_one_page_with_vietnamese_text():
    s = Store()
    pid = _seed(s)
    pdf = build_visit_pdf(s, pid, days=28, now=NOW)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    # phông nhúng phải giữ đủ dấu tiếng Việt và ký tự đặc biệt người dùng gõ
    for needle in ("Nguyễn Thị Hường", "17/10/2026", "13/11/2026", "Hạ đường huyết", "metformin",
                   "Hay hạ đường huyết buổi chiều", "Bệnh viện Nội tiết <TW>", "18/11/2026", "HbA1c",
                   "không phải chẩn đoán"):
        assert needle in text, needle


def test_visit_pdf_empty_patient():
    s = Store()
    pid = s.save_patient("Trống", {})
    text = PdfReader(io.BytesIO(build_visit_pdf(s, pid, now=NOW))).pages[0].extract_text()
    assert "Chưa có lần đo nào" in text and "(chưa có)" in text
