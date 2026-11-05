import json

import pytest

from diacare.labs import classify, format_labs, parse_lab_file, parse_lab_text


def values(text):
    return {r["test"]: (r["value"], r["unit"]) for r in parse_lab_text(text)}


def test_parse_common_report_lines():
    text = ("Ngày 05/11/2026\n"
            "HbA1c: 7.2 %\n"
            "Glucose lúc đói: 130 mg/dL\n"
            "Nghiệm pháp dung nạp glucose 75g - 2h: 210 mg/dL\n")
    assert values(text) == {"hba1c": (7.2, "%"), "fpg": (130.0, "mg/dl"), "ogtt_2h": (210.0, "mg/dl")}


def test_parse_inline_and_vietnamese_names():
    assert values("đường huyết lúc đói 7,5 mmol/L; HbA1c 6.1%") == {"fpg": (7.5, "mmol/l"), "hba1c": (6.1, "%")}
    assert values("Tôi đo đường huyết bất kỳ được 250 mg/dl") == {"random": (250.0, "mg/dl")}
    assert values("FPG 98") == {"fpg": (98.0, None)}


def test_parse_csv_and_json():
    assert values("test,value,unit\nHbA1c,5.4,%\nFPG,5.2,mmol/L") == {"hba1c": (5.4, "%"), "fpg": (5.2, "mmol/l")}
    data = json.dumps({"HbA1c": "48 mmol/mol", "Glucose đói": 120}).encode()
    got = {r["test"]: (r["value"], r["unit"]) for r in parse_lab_file("kq.json", data)}
    assert got == {"hba1c": (48.0, "mmol/mol"), "fpg": (120.0, None)}


def test_parse_ignores_text_without_values():
    assert parse_lab_text("Tôi nên ăn uống thế nào để giữ đường huyết ổn định?") == []
    assert parse_lab_text("HbA1c là gì?") == []
    assert parse_lab_text("") == []


@pytest.mark.parametrize("test,value,unit,level", [
    ("hba1c", 5.6, "%", "normal"), ("hba1c", 5.7, "%", "prediabetes"), ("hba1c", 6.4, "%", "prediabetes"),
    ("hba1c", 6.5, "%", "diabetes"), ("hba1c", 48, "mmol/mol", "diabetes"), ("hba1c", 38, "mmol/mol", "normal"),
    ("fpg", 99, "mg/dl", "normal"), ("fpg", 100, "mg/dl", "prediabetes"), ("fpg", 125, "mg/dl", "prediabetes"),
    ("fpg", 126, "mg/dl", "diabetes"), ("fpg", 7.0, "mmol/l", "diabetes"), ("fpg", 6.0, "mmol/l", "prediabetes"),
    ("fpg", 5.0, None, "normal"), ("fpg", 130, None, "diabetes"),
    ("ogtt_2h", 139, "mg/dl", "normal"), ("ogtt_2h", 140, "mg/dl", "prediabetes"),
    ("ogtt_2h", 200, "mg/dl", "diabetes"), ("ogtt_2h", 11.1, "mmol/l", "diabetes"),
    ("random", 250, "mg/dl", "diabetes"), ("random", 150, "mg/dl", "unclassified"),
    ("fpg", 60, "mg/dl", "low"), ("random", 3.0, "mmol/l", "low"),
])
def test_classify_thresholds(test, value, unit, level):
    [r] = classify([{"test": test, "value": value, "unit": unit}])
    assert r["level"] == level, r


def test_classify_rejects_implausible_values():
    assert classify([{"test": "hba1c", "value": 72, "unit": "%"}]) == []
    assert classify([{"test": "fpg", "value": 5000, "unit": "mg/dl"}]) == []


def test_format_labs_cites_reference_and_disclaims():
    text = format_labs(classify(parse_lab_text("HbA1c 7.2%")))
    assert "[ada_2024]" in text
    assert "7.2" in text and "6.5" in text
    assert "không phải chẩn đoán" in text
    assert format_labs([]) == ""


# ---------- lưu trữ + LabAgent ----------
from diacare.db import Store  # noqa: E402
from diacare.labs import LabAgent  # noqa: E402


def test_store_keeps_latest_value_per_test():
    s = Store()
    pid = s.save_patient("An", {})
    s.add_lab(pid, "hba1c", 6.0, "%", source="import")
    s.add_lab(pid, "hba1c", 7.1, "%", source="import")
    s.add_lab(pid, "fpg", 110, "mg/dl", source="chat")
    latest = {r["test"]: r["value"] for r in s.latest_labs(pid)}
    assert latest == {"hba1c": 7.1, "fpg": 110}
    assert len(s.list_labs(pid)) == 3
    s.clear_labs(pid)
    assert s.latest_labs(pid) == []


def test_lab_agent_merges_stored_and_question_values_and_saves_chat_values():
    s = Store()
    pid = s.save_patient("An", {})
    agent = LabAgent(s)
    agent.import_results(pid, parse_lab_text("HbA1c 5.5%\nFPG 95 mg/dL"), source="import")
    got = {r["test"]: r["level"] for r in agent.collect(pid, "HbA1c mới nhất của tôi là 6.8% thì sao?")}
    assert got == {"hba1c": "diabetes", "fpg": "normal"}
    assert {r["test"]: r["value"] for r in s.latest_labs(pid)}["hba1c"] == 6.8


def test_lab_agent_without_patient_uses_question_only():
    agent = LabAgent(None)
    assert [r["test"] for r in agent.collect(None, "đường huyết lúc đói 130 mg/dL")] == ["fpg"]
    assert agent.collect(None, "Nên ăn gì?") == []
