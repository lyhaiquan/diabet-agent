import sqlite3

import pytest

from diacare.crypto import PREFIX, FieldCipher, NoCipher, cipher_for, key_path
from diacare.db import Store
from diacare.state import State


def _raw(path, sql):
    con = sqlite3.connect(str(path))
    try:
        return [r[0] for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def test_sensitive_columns_are_encrypted_on_disk_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("DIACARE_DB_KEY", raising=False)
    monkeypatch.delenv("DIACARE_DB_ENCRYPT", raising=False)
    db = tmp_path / "d.db"
    s = Store(db)
    pid = s.save_patient("Nguyễn Văn A", {"BMI": 31.5, "HighBP": 1})
    sid = s.start_session(pid)
    s.add_message(sid, "user", "Tôi đang dùng metformin 500 mg.")
    s.add_memory(pid, "medication", "metformin")
    s.add_doctor_question(pid, "Có cần đổi thuốc không?")
    s.save_summary(sid, 3, "Người dùng bị tiểu đường típ 2.")
    s.set_appointment(pid, "2026-12-01", place="Bệnh viện Bạch Mai", note="mang sổ")
    s.log_run(sid, State(question="HbA1c 7% có cao không?", profile={}, draft="nháp", final="cuối"))
    s.close()

    raw = (_raw(db, "SELECT name FROM patients") + _raw(db, "SELECT profile_json FROM patients")
           + _raw(db, "SELECT content FROM messages") + _raw(db, "SELECT content FROM memories")
           + _raw(db, "SELECT text FROM doctor_questions") + _raw(db, "SELECT content FROM summaries")
           + _raw(db, "SELECT place FROM appointments") + _raw(db, "SELECT question FROM runs")
           + _raw(db, "SELECT final FROM runs"))
    assert raw and all(v.startswith(PREFIX) for v in raw)
    assert "metformin" not in db.read_bytes().decode("latin-1")
    assert key_path(db).exists()

    s = Store(db)   # mở lại: đọc được bằng khoá trong tệp cạnh DB
    assert s.get_patient(pid)["name"] == "Nguyễn Văn A" and s.get_patient(pid)["profile"]["BMI"] == 31.5
    assert s.get_history(sid)[0]["content"] == "Tôi đang dùng metformin 500 mg."
    assert [m["content"] for m in s.list_memories(pid)] == ["metformin"]
    assert s.get_summary(sid)["content"].startswith("Người dùng")
    assert s.get_appointment(pid)["place"] == "Bệnh viện Bạch Mai"
    assert s.runs()[0]["question"] == "HbA1c 7% có cao không?"
    # so sánh trùng / tắt theo nội dung vẫn đúng dù mỗi lần mã hoá ra chuỗi khác nhau
    assert s.add_memory(pid, "medication", "Metformin") == s.list_memories(pid)[0]["id"]
    assert s.deactivate_memory_by_content(pid, "medication", "METFORMIN") == 1
    s.close()


def test_old_plaintext_rows_still_readable(tmp_path, monkeypatch):
    monkeypatch.delenv("DIACARE_DB_KEY", raising=False)
    db = tmp_path / "old.db"
    Store(db, cipher=NoCipher()).save_patient("Cũ", {"BMI": 22})   # DB của bản trước khi có mã hoá
    s = Store(db)
    assert s.get_patient(1)["name"] == "Cũ"
    s.save_patient("Mới", {"BMI": 25})
    assert [p["name"] for p in s.list_patients()] == ["Mới", "Cũ"]


def test_wrong_key_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.delenv("DIACARE_DB_KEY", raising=False)
    db = tmp_path / "k.db"
    Store(db).save_patient("A", {"BMI": 22})
    key_path(db).write_bytes(__import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key())
    with pytest.raises(ValueError, match="khoá"):
        Store(db).get_patient(1)


def test_env_key_and_disable(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    k = Fernet.generate_key().decode()
    monkeypatch.setenv("DIACARE_DB_KEY", k)
    c = cipher_for(tmp_path / "x.db")
    assert isinstance(c, FieldCipher) and not key_path(tmp_path / "x.db").exists()
    assert c.dec(c.enc("xin chào")) == "xin chào" and c.enc("a") != c.enc("a")
    monkeypatch.setenv("DIACARE_DB_ENCRYPT", "0")
    assert isinstance(cipher_for(tmp_path / "x.db"), NoCipher)
