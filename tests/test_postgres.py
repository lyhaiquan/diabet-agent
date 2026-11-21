"""Kiểm tra riêng đường PostgreSQL: Store/API nhận URL thật (không qua lớp chuyển đổi trong conftest), khoá
advisory, độ chính xác số thực, và công cụ chuyển dữ liệu từ SQLite. Cần DIACARE_TEST_PG_URL (xem conftest.py)."""
import importlib.util
import os
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

PG_URL = os.environ.get("DIACARE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="cần DIACARE_TEST_PG_URL trỏ tới một máy chủ PostgreSQL")

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pg_url():
    """URL tới một schema PostgreSQL trống, xoá sau test."""
    import psycopg
    schema = f"t_{uuid.uuid4().hex[:16]}"
    admin = psycopg.connect(PG_URL, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    sep = "&" if "?" in PG_URL else "?"
    try:
        yield f"{PG_URL}{sep}options=-csearch_path%3D{schema}"
    finally:
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


@pytest.fixture
def key_dir(tmp_path, monkeypatch):
    d = tmp_path / "keys"
    monkeypatch.setenv("DIACARE_KEY_DIR", str(d))
    monkeypatch.delenv("DIACARE_DB_KEY", raising=False)
    monkeypatch.delenv("DIACARE_DB_ENCRYPT", raising=False)
    monkeypatch.delenv("DIACARE_API_SECRET", raising=False)
    return d


def test_store_on_url_keeps_key_out_of_url_and_encrypts(pg_url, key_dir):
    import psycopg
    from diacare.db import Store
    from diacare.state import State
    s = Store(pg_url)
    assert s.dialect == "postgres" and s.enable_wal() == "postgres"
    pid = s.save_patient("Nguyễn Văn A", {"BMI": 31.5})
    sid = s.start_session(pid)
    s.add_message(sid, "user", "metformin 500 mg")
    run = State(question="q", profile={}, draft="d", final="f")
    run.risk = 0.123456789012
    s.log_run(sid, run)
    s.close()
    assert (key_dir / "diacare_db.key").exists()
    assert not any("postgresql" in p.name for p in key_dir.parent.rglob("*"))  # URL (có mật khẩu) không thành tên tệp
    with psycopg.connect(pg_url) as raw:
        assert raw.execute("SELECT content FROM messages").fetchone()[0].startswith("enc1:")
    s = Store(pg_url, init_schema=False)
    assert s.get_history(sid)[0]["content"] == "metformin 500 mg"
    assert s.runs()[0]["risk"] == 0.123456789012  # DOUBLE PRECISION, không phải float4
    s.close()


def test_types_and_unique_email(pg_url, key_dir):
    from diacare.db import Store
    s = Store(pg_url)
    rid = s.add_rl_event(None, None, {"state": {"a": np.float64(1.5)}, "action": "diet", "propensity": np.float64(0.9),
                                      "explored": True, "mode": "x", "policy_version": "p"})
    assert s.get_rl_event(rid)["explored"] in (1, True)
    assert s.add_reading(1, "glucose", np.float32(126.0), "2026-11-20T07:00:00+07:00") > 0
    assert s.create_user("a@x.vn", "h") is not None
    assert s.create_user("A@x.vn ", "h") is None  # trùng email: trả None như SQLite, kết nối vẫn dùng tiếp được
    assert s.get_user_by_email("a@x.vn")["email"] == "a@x.vn"
    s.close()


def test_advisory_lock_excludes_across_connections(pg_url, key_dir):
    from diacare.db import Store
    a, b = Store(pg_url), Store(pg_url, init_schema=False)
    order = []
    with a.exclusive("rl-model"):
        t = threading.Thread(target=lambda: (b.exclusive("rl-model").__enter__(), order.append("b")))
        t.start()
        time.sleep(0.5)
        order.append("a-done")
    t.join(5)
    assert order == ["a-done", "b"]
    b.conn.advisory_unlock("rl-model")
    a.close()
    b.close()


def test_api_on_postgres_url(pg_url, key_dir):
    from fastapi.testclient import TestClient
    from api.main import create_app
    from diacare.factory import build_parts
    from diacare.llm import DemoLLM, hash_embed_fn
    kb = key_dir.parent / "kb"
    kb.mkdir()
    (kb / "ada.txt").write_text("Ăn nhiều rau xanh và hạn chế đường.", encoding="utf-8")
    parts = build_parts(kb_dir=kb, log_path=key_dir.parent / "runs.jsonl", llm=DemoLLM(), embed_fn=hash_embed_fn(),
                        min_score=0.0)
    with TestClient(create_app(db_path=pg_url, parts=parts)) as c:
        tok = c.post("/auth/register", json={"email": "an@x.vn", "password": "matkhau123"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {tok}"}
        pid = c.post("/patients", json={"name": "An", "diagnosed": True}, headers=auth).json()["id"]
        r = c.post(f"/patients/{pid}/chat", json={"question": "Nên ăn gì?"}, headers=auth)
        assert r.status_code == 200 and r.json()["answer"]
        assert len(c.get(f"/patients/{pid}/sessions/{r.json()['session_id']}/messages", headers=auth).json()) == 2
    assert (key_dir / "api_secret.key").exists() and (key_dir / "diacare_db.key").exists()


def _load_tool():
    spec = importlib.util.spec_from_file_location("sqlite_to_postgres", ROOT / "tools" / "sqlite_to_postgres.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrate_sqlite_to_postgres(tmp_path, pg_url, key_dir):
    from diacare.crypto import cipher_for
    tool = _load_tool()
    src = tmp_path / "old" / "diacare.db"
    src.parent.mkdir()
    (src.parent / "api_secret.key").write_text("s" * 48, encoding="utf-8")
    import sqlite3
    old = _sqlite_store(src, cipher_for(src))  # DB SQLite thật, không qua lớp chuyển đổi của conftest
    pid = old.save_patient("Bà Lan", {"BMI": 27.25})
    old.add_reading(pid, "glucose", 135.5, "2026-11-20T07:00:00+07:00")
    uid = old.create_user("lan@x.vn", "hash")
    old.conn.execute("UPDATE patients SET user_id = ? WHERE id = ?", (uid, pid))
    old.conn.commit()
    old.conn.close()
    assert sqlite3.connect(src).execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1

    counts = tool.migrate(src, pg_url, key_dir=key_dir, log=lambda m: None)
    assert counts["patients"] == 1 and counts["readings"] == 1 and counts["users"] == 1
    assert (key_dir / "api_secret.key").read_text() == "s" * 48
    from diacare.db import Store
    s = Store(pg_url)  # dùng khoá đã chép sang key_dir
    assert s.get_patient(pid)["name"] == "Bà Lan" and s.patient_owner(pid) == uid
    assert s.list_readings(pid)[0]["value"] == 135.5
    assert s.save_patient("Mới", {}) == pid + 1  # bộ đếm id đã đặt lại
    s.close()
    with pytest.raises(SystemExit, match="đã có dữ liệu"):
        tool.migrate(src, pg_url, log=lambda m: None)
    assert tool.migrate(src, pg_url, replace=True, log=lambda m: None)["patients"] == 1
    (key_dir / "diacare_db.key").write_bytes(b"khac")
    with pytest.raises(SystemExit, match="không ghi đè khoá"):
        tool.migrate(src, pg_url, key_dir=key_dir, replace=True, log=lambda m: None)


def _sqlite_store(path, cipher):
    """Store SQLite thật, kể cả khi conftest đang chuyển mọi Store sang PostgreSQL."""
    import sqlite3
    from diacare.db import Store
    s = Store.__new__(Store)
    s.path, s.cipher, s.dialect = str(path), cipher, "sqlite"
    s.conn = sqlite3.connect(str(path), check_same_thread=False)
    s.conn.row_factory = sqlite3.Row
    s._migrate()
    return s
