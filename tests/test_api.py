import base64
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from api import security
from api.main import create_app
from diacare import journal
from diacare.db import Store
from diacare.factory import build_parts
from diacare.llm import DemoLLM, hash_embed_fn

NOW = datetime(2026, 11, 13, 20, 0, tzinfo=journal.VN_TZ)
SECRET = b"s" * 40


# ---- mật khẩu và token ----

def test_password_hash_roundtrip():
    h = security.hash_password("mật khẩu dài 123")
    assert h.startswith("scrypt$") and "mật khẩu" not in h
    assert security.verify_password("mật khẩu dài 123", h)
    assert not security.verify_password("sai", h)
    assert not security.verify_password("x", "rác")
    assert security.hash_password("a") != security.hash_password("a")  # muối khác nhau


def test_token_roundtrip_and_rejections():
    t = security.create_token(7, SECRET, ttl=60, now=1000)
    assert security.decode_token(t, SECRET, now=1010) == 7
    with pytest.raises(security.TokenError):
        security.decode_token(t, SECRET, now=1061)  # hết hạn
    with pytest.raises(security.TokenError):
        security.decode_token(t, b"k" * 40, now=1010)  # sai khoá
    h, p, sig = t.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"sub": "8", "iat": 1000, "exp": 9999}).encode()).rstrip(b"=")
    with pytest.raises(security.TokenError):
        security.decode_token(f"{h}.{forged.decode()}.{sig}", SECRET, now=1010)  # sửa nội dung
    none_hdr = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    with pytest.raises(security.TokenError):
        security.decode_token(f"{none_hdr}.{p}.", SECRET, now=1010)  # alg none
    for junk in ("", "a.b", "a.b.c", "....."):
        with pytest.raises(security.TokenError):
            security.decode_token(junk, SECRET, now=1010)


def test_secret_loading(tmp_path, monkeypatch):
    monkeypatch.delenv("DIACARE_API_SECRET", raising=False)
    path = tmp_path / "k" / "secret.key"
    a = security.load_secret(path)
    assert path.exists() and len(a) >= 32 and security.load_secret(path) == a
    monkeypatch.setenv("DIACARE_API_SECRET", "ngắn")
    with pytest.raises(ValueError):
        security.load_secret(path)


# ---- dịch vụ ----

@pytest.fixture(scope="module")
def parts(tmp_path_factory):
    kb = tmp_path_factory.mktemp("kb")
    (kb / "ada.txt").write_text("Ăn nhiều rau xanh và hạn chế đường.", encoding="utf-8")
    log = tmp_path_factory.mktemp("log") / "runs.jsonl"
    return build_parts(kb_dir=kb, log_path=log, llm=DemoLLM(), embed_fn=hash_embed_fn(), min_score=0.0)


def test_secret_file_sits_next_to_db(tmp_path, parts, monkeypatch):
    """Docker gắn volume dữ liệu vào thư mục của DB: khoá ký token phải nằm cùng chỗ, không ở data/ của ảnh."""
    monkeypatch.delenv("DIACARE_API_SECRET", raising=False)
    db = tmp_path / "var" / "api.db"
    with TestClient(create_app(db_path=db, parts=parts)) as c:
        assert c.get("/health").status_code == 200
    assert (db.parent / "api_secret.key").exists()


@pytest.fixture
def client(tmp_path, parts):
    app = create_app(db_path=tmp_path / "api.db", parts=parts, secret=SECRET, clock=lambda: NOW,
                     cors_origins=["http://localhost:3000"])
    with TestClient(app) as c:
        c.db_path = tmp_path / "api.db"
        yield c


def register(client, email="an@example.com", password="matkhau123"):
    r = client.post("/auth/register", json={"email": email, "password": password, "name": "An"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def new_patient(client, auth, diagnosed=True, name="Cô Hường"):
    r = client.post("/patients", json={"name": name, "diagnosed": diagnosed}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_health_and_docs(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200


def test_register_login_me(client):
    auth = register(client)
    assert client.post("/auth/register", json={"email": "AN@example.com", "password": "matkhau123"}).status_code == 409
    assert client.get("/me", headers=auth).json()["email"] == "an@example.com"
    ok = client.post("/auth/token", data={"username": "an@example.com", "password": "matkhau123"})
    assert ok.status_code == 200 and ok.json()["token_type"] == "bearer"
    bad_pw = client.post("/auth/token", data={"username": "an@example.com", "password": "sai"})
    no_user = client.post("/auth/token", data={"username": "khong@co.vn", "password": "sai"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()  # không lộ email nào đã có tài khoản
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer khong-hop-le"}).status_code == 401
    short = client.post("/auth/register", json={"email": "b@example.com", "password": "123"})
    assert short.status_code == 422


def test_password_not_stored_in_plain_text(client):
    register(client, password="matkhau-bi-mat")
    store = Store(client.db_path)
    assert "matkhau-bi-mat" not in store.get_user_by_email("an@example.com")["password_hash"]


def test_patient_crud_and_validation(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    p = client.get(f"/patients/{pid}", headers=auth).json()
    assert p["diagnosed"] is True and p["risk"]["band"] in ("thấp", "trung bình", "cao")
    assert [x["id"] for x in client.get("/patients", headers=auth).json()] == [pid]
    r = client.patch(f"/patients/{pid}", json={"profile": {"BMI": 31.5, "HighBP": 1}}, headers=auth)
    assert r.status_code == 200 and r.json()["profile"]["BMI"] == 31.5
    assert client.patch(f"/patients/{pid}", json={"profile": {"BMI": 500}}, headers=auth).status_code == 422
    assert client.post("/patients", json={"name": "X", "profile": {"Lạ": 1}}, headers=auth).status_code == 422
    mem = client.get(f"/patients/{pid}/memories", headers=auth).json()
    assert mem[0]["content"] == "đái tháo đường típ 2"


def test_other_users_data_is_invisible(client):
    a = register(client, "a@example.com")
    b = register(client, "b@example.com")
    pid = new_patient(client, a)
    rid = client.post(f"/patients/{pid}/readings/glucose", json={"value": 6.0, "context": "fasting"},
                      headers=a).json()["reading"]["id"]
    qid = client.post(f"/patients/{pid}/questions", json={"text": "Hỏi gì?"}, headers=a).json()["id"]
    mid = client.get(f"/patients/{pid}/memories", headers=a).json()[0]["id"]
    chat = client.post(f"/patients/{pid}/chat", json={"question": "Nên ăn rau không?"}, headers=a).json()
    sid, eid = chat["session_id"], chat["focus"]["event_id"]
    pid_b = new_patient(client, b)
    assert client.get("/patients", headers=b).json()[0]["id"] == pid_b
    for method, url in [("get", f"/patients/{pid}"), ("get", f"/patients/{pid}/today"),
                        ("get", f"/patients/{pid}/readings"), ("delete", f"/patients/{pid}/readings/{rid}"),
                        ("get", f"/patients/{pid}/visit-report.pdf"), ("delete", f"/patients/{pid}/memories/{mid}"),
                        ("post", f"/patients/{pid}/questions/{qid}/done"),
                        ("get", f"/patients/{pid}/sessions/{sid}/messages")]:
        assert getattr(client, method)(url, headers=b).status_code == 404, url
    # id của A gắn vào hồ sơ của B cũng không được
    assert client.delete(f"/patients/{pid_b}/readings/{rid}", headers=b).status_code == 404
    assert client.post(f"/patients/{pid_b}/questions/{qid}/done", headers=b).status_code == 404
    assert client.delete(f"/patients/{pid_b}/memories/{mid}", headers=b).status_code == 404
    assert client.get(f"/patients/{pid_b}/sessions/{sid}/messages", headers=b).status_code == 404
    assert client.post(f"/patients/{pid_b}/chat", json={"question": "hi", "session_id": sid},
                       headers=b).status_code == 404
    assert client.post(f"/feedback/{eid}", json={"value": "up"}, headers=b).status_code == 404
    # dữ liệu của A còn nguyên
    assert len(client.get(f"/patients/{pid}/readings", headers=a).json()) == 1
    assert client.get(f"/patients/{pid}/questions", headers=a).json()[0]["done"] is False


def test_glucose_bp_weight(client):
    auth = register(client)
    pid = new_patient(client, auth)
    r = client.post(f"/patients/{pid}/readings/glucose",
                    json={"value": 2.8, "context": "random", "measured_at": "2026-11-13T19:00:00"}, headers=auth)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "hypo_2" and "115" in body["advice"] and body["reading"]["mmol"] == 2.8
    assert body["reading"]["measured_at"].startswith("2026-11-13T19:00:00+07:00")
    wrong_unit = client.post(f"/patients/{pid}/readings/glucose", json={"value": 120, "context": "fasting"},
                             headers=auth)
    assert wrong_unit.status_code == 422 and "đơn vị" in wrong_unit.json()["detail"]
    ok_mgdl = client.post(f"/patients/{pid}/readings/glucose",
                          json={"value": 120, "unit": "mg/dL", "context": "fasting"}, headers=auth)
    assert ok_mgdl.json()["status"] == "in_target"
    future = client.post(f"/patients/{pid}/readings/glucose",
                         json={"value": 6, "context": "fasting", "measured_at": "2026-11-14T09:00:00+07:00"},
                         headers=auth)
    assert future.status_code == 422
    assert client.post(f"/patients/{pid}/readings/glucose", json={"value": 6, "context": "lạ"},
                       headers=auth).status_code == 422
    bp = client.post(f"/patients/{pid}/readings/bp", json={"systolic": 190, "diastolic": 100}, headers=auth)
    assert bp.json()["status"] == "very_high" and "cấp cứu" in bp.json()["advice"]
    assert client.post(f"/patients/{pid}/readings/bp", json={"systolic": 80, "diastolic": 90},
                       headers=auth).status_code == 422
    assert client.post(f"/patients/{pid}/readings/weight", json={"kg": 61.5}, headers=auth).status_code == 201
    assert client.post(f"/patients/{pid}/readings/weight", json={"kg": 5}, headers=auth).status_code == 422
    allr = client.get(f"/patients/{pid}/readings", headers=auth).json()
    assert [x["kind"] for x in allr].count("glucose") == 2 and len(allr) == 4
    glu = client.get(f"/patients/{pid}/readings?kind=glucose", headers=auth).json()
    assert {x["kind"] for x in glu} == {"glucose"}
    assert client.delete(f"/patients/{pid}/readings/{glu[0]['id']}", headers=auth).status_code == 204
    assert len(client.get(f"/patients/{pid}/readings?kind=glucose", headers=auth).json()) == 1


def test_today_and_summary(client):
    auth = register(client)
    pid = new_patient(client, auth)
    t = client.get(f"/patients/{pid}/today", headers=auth).json()
    assert any("chưa ghi đường huyết" in m["text"] for m in t["reminders"]) and t["alerts"] == []
    for d in range(1, 6):
        when = (NOW - timedelta(days=d)).replace(hour=6).isoformat()
        client.post(f"/patients/{pid}/readings/glucose", json={"value": 6.5, "context": "fasting",
                                                                "measured_at": when}, headers=auth)
    client.post(f"/patients/{pid}/readings/glucose", json={"value": 3.5, "context": "after_meal"}, headers=auth)
    client.put(f"/patients/{pid}/appointment", json={"date": "2026-11-16", "place": "BV Bạch Mai"}, headers=auth)
    t = client.get(f"/patients/{pid}/today", headers=auth).json()
    assert t["alerts"][0]["level"] == "warning" and "15" in t["alerts"][0]["text"]
    assert any("Còn 3 ngày" in m["text"] for m in t["reminders"])
    assert t["fasting_mean_mmol_14d"] == 6.5 and t["last_glucose"]["mmol"] == 3.5
    s = client.get(f"/patients/{pid}/summary?days=14", headers=auth).json()
    assert s["glucose"]["n"] == 6 and s["glucose"]["hypo"] == 1 and len(s["series"]) == 6
    assert s["glucose"]["by_context"]["fasting"]["in_target_pct"] == 100


def test_labs_text_and_file(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    r = client.post(f"/patients/{pid}/labs", json={"text": "HbA1c: 7.8 %\nGlucose lúc đói: 7.4 mmol/L"},
                    headers=auth)
    assert r.status_code == 201 and len(r.json()["imported"]) == 2
    a1c = next(x for x in r.json()["labs"] if x["test"] == "hba1c")
    assert a1c["assessment"] == "cao hơn mục tiêu chung 7%"  # đã chẩn đoán: so mục tiêu, không phải ngưỡng
    assert client.post(f"/patients/{pid}/labs", json={"text": "không có số"}, headers=auth).status_code == 422
    f = client.post(f"/patients/{pid}/labs/file", files={"file": ("kq.txt", "HbA1c 6.9%".encode(), "text/plain")},
                    headers=auth)
    assert f.status_code == 201 and f.json()["imported"][0]["value"] == 6.9
    assert len(client.get(f"/patients/{pid}/labs", headers=auth).json()) == 3


def test_lab_upload_limits(client):
    """Ảnh bom giải nén và PDF quá dài bị từ chối 413, không làm treo máy chủ."""
    import io
    import fitz
    from PIL import Image
    auth = register(client)
    pid = new_patient(client, auth)
    buf = io.BytesIO()
    Image.new("1", (20000, 20000), 1).save(buf, format="PNG", optimize=True)
    r = client.post(f"/patients/{pid}/labs/file", files={"file": ("kq.png", buf.getvalue(), "image/png")},
                    headers=auth)
    assert r.status_code == 413 and "quá lớn" in r.json()["detail"]
    doc = fitz.open()
    for _ in range(11):
        doc.new_page()
    r = client.post(f"/patients/{pid}/labs/file", files={"file": ("kq.pdf", doc.tobytes(), "application/pdf")},
                    headers=auth)
    assert r.status_code == 413 and "11 trang" in r.json()["detail"]


def test_questions_appointment_and_pdf(client):
    auth = register(client)
    pid = new_patient(client, auth)
    assert client.get(f"/patients/{pid}/appointment", headers=auth).json() is None
    client.put(f"/patients/{pid}/appointment", json={"date": "2026-11-20", "place": "BV Nội tiết"}, headers=auth)
    assert client.get(f"/patients/{pid}/appointment", headers=auth).json()["place"] == "BV Nội tiết"
    q = client.post(f"/patients/{pid}/questions", json={"text": "Có cần đổi giờ uống thuốc?"}, headers=auth).json()
    client.post(f"/patients/{pid}/questions", json={"text": "Đã hỏi rồi"}, headers=auth)
    client.post(f"/patients/{pid}/questions/{q['id'] + 1}/done", headers=auth)
    assert [x["text"] for x in client.get(f"/patients/{pid}/questions", headers=auth).json()] == [q["text"]]
    assert len(client.get(f"/patients/{pid}/questions?include_done=true", headers=auth).json()) == 2
    client.post(f"/patients/{pid}/readings/glucose", json={"value": 6.8, "context": "fasting"}, headers=auth)
    r = client.get(f"/patients/{pid}/visit-report.pdf?days=28", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "tom_tat_tai_kham_20261113.pdf" in r.headers["content-disposition"]
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    assert "Cô Hường" in text and "Có cần đổi giờ uống thuốc?" in text and "Đã hỏi rồi" not in text


def test_chat_json_session_and_feedback(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    r = client.post(f"/patients/{pid}/chat", json={"question": "Nên ăn rau không?"}, headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()
    assert "ada.txt" in out["sources"] and out["answer"] and out["risk"] is None  # đã chẩn đoán: ẩn nguy cơ BRFSS
    assert out["steps"][0]["agent"] == "Memory" and out["steps"][-1]["agent"] == "Rules"
    sid = out["session_id"]
    r2 = client.post(f"/patients/{pid}/chat", json={"question": "Còn tập thể dục?", "session_id": sid},
                     headers=auth).json()
    assert r2["session_id"] == sid
    msgs = client.get(f"/patients/{pid}/sessions/{sid}/messages", headers=auth).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[1]["content"] == out["answer"]
    assert client.get(f"/patients/{pid}/sessions", headers=auth).json()[0]["n_messages"] == 4
    eid = out["focus"]["event_id"]
    fb = client.post(f"/feedback/{eid}", json={"value": "up"}, headers=auth)
    assert fb.status_code == 200 and fb.json()["reward"] == 1.0
    assert client.post(f"/feedback/{eid}", json={"value": "down"}, headers=auth).status_code == 409
    msgs = client.get(f"/patients/{pid}/sessions/{sid}/messages", headers=auth).json()
    assert msgs[1]["focus"]["rated"] == "up"
    assert client.post("/feedback/99999", json={"value": "up"}, headers=auth).status_code == 404


def test_chat_learns_memory_into_patient(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=False)
    client.post(f"/patients/{pid}/chat", json={"question": "Tôi bị dị ứng tôm."}, headers=auth)
    mem = client.get(f"/patients/{pid}/memories", headers=auth).json()
    assert [m["content"] for m in mem] == ["tôm"]  # lưu vào DB thật, không phải DB tạm trong bộ nhớ


def _events(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_chat_stream_sse(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=False)
    with client.stream("POST", f"/patients/{pid}/chat", json={"question": "Nên ăn rau không?", "stream": True},
                       headers=auth) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = _events(r.read().decode("utf-8"))
    kinds = [e for e, _ in events]
    assert kinds[0] == "session" and kinds[-1] == "done" and "step" in kinds
    done = events[-1][1]
    assert done["risk"] is not None  # chưa chẩn đoán: có ước tính nguy cơ
    streamed = "".join(d["text"] for e, d in events if e == "token")
    assert "token" in kinds and streamed.strip()  # chữ hiện dần (bản nháp đã qua bộ lọc từng câu)
    msgs = client.get(f"/patients/{pid}/sessions/{done['session_id']}/messages", headers=auth).json()
    assert msgs[-1]["content"] == done["answer"]


def test_cors_only_allows_configured_origin(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options("/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


# ---- giọng nói ----

def _wav(seconds=1.0):
    import wave as _wave
    import numpy as _np
    n = int(seconds * 16000)
    pcm = (0.3 * _np.sin(2 * _np.pi * 220 * _np.arange(n) / 16000) * 32767).astype("<i2")
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


@pytest.fixture
def voice_client(tmp_path, parts):
    from diacare.speech import DemoTranscriber
    app = create_app(db_path=tmp_path / "api.db", parts=parts, secret=SECRET, clock=lambda: NOW,
                     transcriber=DemoTranscriber("Đường huyết sáng nay lúc đói sáu phẩy tám"))
    with TestClient(app) as c:
        yield c


def test_transcribe_returns_text_and_reading_without_saving(voice_client):
    auth = register(voice_client)
    pid = new_patient(voice_client, auth)
    r = voice_client.post("/transcribe", files={"audio": ("noi.wav", _wav(), "audio/wav")}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "Đường huyết sáng nay lúc đói sáu phẩy tám"
    assert body["reading"]["value"] == 6.8 and body["reading"]["context"] == "fasting"
    assert body["audio_seconds"] == 1.0
    # chỉ là đề xuất: chưa có số đo nào được lưu khi người dùng chưa xác nhận
    assert voice_client.get(f"/patients/{pid}/readings", headers=auth).json() == []


def test_transcribe_rejects_bad_audio_and_requires_login(voice_client):
    auth = register(voice_client)
    assert voice_client.post("/transcribe", files={"audio": ("a.wav", _wav(), "audio/wav")}).status_code == 401
    bad = voice_client.post("/transcribe", files={"audio": ("a.wav", b"rac", "audio/wav")}, headers=auth)
    assert bad.status_code == 422 and "WAV" in bad.json()["detail"]
    big = voice_client.post("/transcribe", files={"audio": ("a.wav", b"0" * (4 * 1024 * 1024 + 10), "audio/wav")},
                            headers=auth)
    assert big.status_code == 413


def test_chat_reads_journal(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    client.post(f"/patients/{pid}/readings/glucose", json={"value": 9.5, "context": "fasting"}, headers=auth)
    out = client.post(f"/patients/{pid}/chat", json={"question": "Đường huyết của tôi thế nào?"},
                      headers=auth).json()
    step = next(s for s in out["steps"] if s["agent"] == "Journal")
    assert "1 lần đo đường huyết" in step["detail"]


def test_targets_default_custom_reset(client):
    auth = register(client)
    pid = new_patient(client, auth)
    t = client.get(f"/patients/{pid}/targets", headers=auth).json()
    assert not t["custom"] and t["pre_meal_mmol"] == [4.4, 7.2] and t["post_meal_max_mmol"] == 10.0
    r = client.post(f"/patients/{pid}/readings/glucose", json={"value": 7.8, "context": "fasting"}, headers=auth).json()
    assert r["status"] == "above_target"

    bad = client.put(f"/patients/{pid}/targets", headers=auth,
                     json={"pre_meal_low": 3.0, "pre_meal_high": 7.2, "post_meal_max": 10.0})
    assert bad.status_code == 422 and "3,9" in bad.json()["detail"]
    t = client.put(f"/patients/{pid}/targets", headers=auth,
                   json={"pre_meal_low": 5.0, "pre_meal_high": 8.3, "post_meal_max": 11.0, "note": "BS Minh"}).json()
    assert t["custom"] and t["pre_meal_mmol"] == [5.0, 8.3] and t["note"] == "BS Minh"
    assert t["default"]["pre_meal_mmol"] == [4.4, 7.2]

    # số đo cũ được xếp lại theo mục tiêu mới; số đo mới báo "mục tiêu bác sĩ đặt"
    rows = client.get(f"/patients/{pid}/readings", headers=auth).json()
    assert rows[0]["status"] == "in_target"
    r = client.post(f"/patients/{pid}/readings/glucose", json={"value": 8.0, "context": "fasting"}, headers=auth).json()
    assert r["status"] == "in_target" and "mục tiêu bác sĩ đặt 5,0 mmol/L–8,3 mmol/L" in r["message"]
    today = client.get(f"/patients/{pid}/today", headers=auth).json()
    assert today["in_target_pct_14d"] == 100 and today["targets"]["custom"]
    assert client.get(f"/patients/{pid}/summary", headers=auth).json()["targets"]["pre_meal_mmol"] == [5.0, 8.3]
    # mg/dL cũng nhận
    t = client.put(f"/patients/{pid}/targets", headers=auth,
                   json={"pre_meal_low": 90, "pre_meal_high": 140, "post_meal_max": 190, "unit": "mg/dL"}).json()
    assert t["pre_meal_mmol"] == [5.0, 7.8]
    # hạ đường huyết không đổi theo mục tiêu riêng
    r = client.post(f"/patients/{pid}/readings/glucose", json={"value": 3.5, "context": "fasting"}, headers=auth).json()
    assert r["status"] == "hypo_1"

    t = client.delete(f"/patients/{pid}/targets", headers=auth).json()
    assert not t["custom"] and t["pre_meal_mmol"] == [4.4, 7.2]


def test_targets_are_private_to_owner(client):
    auth = register(client)
    pid = new_patient(client, auth)
    other = register(client, "khac@example.com")
    assert client.get(f"/patients/{pid}/targets", headers=other).status_code == 404
    assert client.put(f"/patients/{pid}/targets", headers=other,
                      json={"pre_meal_low": 5.0, "pre_meal_high": 8.3, "post_meal_max": 11.0}).status_code == 404
    assert client.get(f"/patients/{pid}/targets").status_code == 401


def test_risk_models_compares_mlp_and_multisource(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=False)
    r = client.get(f"/patients/{pid}/risk-models", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert [m["kind"] for m in body["models"]] == ["v1", "multisource"]
    assert body["current"] == "multisource"
    assert client.get(f"/patients/{pid}/risk-models").status_code == 401


def test_login_throttled_after_repeated_failures(tmp_path, parts):
    """Sai 5 lần cho một email: lần thứ 6 bị 429 kể cả mật khẩu đúng; hết 15 phút thì đăng nhập lại được."""
    now = [NOW]
    app = create_app(db_path=tmp_path / "api.db", parts=parts, secret=SECRET, clock=lambda: now[0])
    with TestClient(app) as c:
        register(c)
        login = lambda email, pw: c.post("/auth/token", data={"username": email, "password": pw})  # noqa: E731
        for _ in range(5):
            assert login("an@example.com", "sai-mat-khau").status_code == 401
        r = login("an@example.com", "matkhau123")
        assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
        # email chưa có tài khoản bị đối xử y hệt: không lộ email nào tồn tại
        for _ in range(5):
            assert login("ma@example.com", "x").status_code == 401
        assert login("ma@example.com", "x").status_code == 429
        now[0] = NOW + timedelta(minutes=16)
        assert login("an@example.com", "matkhau123").status_code == 200


def test_login_throttled_per_ip_and_register_limited(tmp_path, parts):
    app = create_app(db_path=tmp_path / "api.db", parts=parts, secret=SECRET, clock=lambda: NOW)
    with TestClient(app) as c:
        for i in range(30):  # dò nhiều email, mỗi email 1 lần
            assert c.post("/auth/token", data={"username": f"u{i}@x.vn", "password": "x"}).status_code == 401
        assert c.post("/auth/token", data={"username": "khac@x.vn", "password": "x"}).status_code == 429
        for i in range(20):
            assert c.post("/auth/register", json={"email": f"r{i}@x.vn", "password": "matkhau123"}).status_code == 201
        assert c.post("/auth/register", json={"email": "r99@x.vn", "password": "matkhau123"}).status_code == 429


def test_successful_login_resets_email_counter(tmp_path, parts):
    app = create_app(db_path=tmp_path / "api.db", parts=parts, secret=SECRET, clock=lambda: NOW)
    with TestClient(app) as c:
        register(c)
        for _ in range(2):
            for _ in range(4):
                assert c.post("/auth/token", data={"username": "an@example.com", "password": "sai"}).status_code == 401
            assert c.post("/auth/token", data={"username": "an@example.com",
                                               "password": "matkhau123"}).status_code == 200


# ---- nhiều người hỏi cùng lúc ----

class _GateLLM(DemoLLM):
    """LLM giả: ghi số lượt đang chạy cùng lúc; `gate` (nếu có) chặn tới khi test mở."""

    def __init__(self, hold=0.0, gate=None, barrier=None):
        super().__init__()
        self.hold, self.gate, self.barrier = hold, gate, barrier
        self.active = self.peak = 0
        self._lock = __import__("threading").Lock()

    def __call__(self, messages, on_token=None):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.barrier is not None:
                self.barrier.wait(timeout=10)  # chỉ qua được khi đủ số lượt CÙNG đang chạy
            if self.gate is not None:
                self.gate.wait(timeout=10)
            __import__("time").sleep(self.hold)
            return super().__call__(messages, on_token)
        finally:
            with self._lock:
                self.active -= 1


def _gate_client(tmp_path, llm):
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "ada.txt").write_text("Ăn nhiều rau xanh và hạn chế đường.", encoding="utf-8")
    p = build_parts(kb_dir=kb, log_path=tmp_path / "runs.jsonl", llm=llm, embed_fn=hash_embed_fn(), min_score=0.0,
                    features="v1")
    return TestClient(create_app(db_path=tmp_path / "api.db", parts=p, secret=SECRET, clock=lambda: NOW))


def _in_threads(*fns):
    import threading
    out = [None] * len(fns)
    threads = [threading.Thread(target=lambda i=i, f=f: out.__setitem__(i, f())) for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


def test_chats_of_different_users_run_in_parallel(tmp_path):
    """Không còn khoá chung: hai người hỏi cùng lúc thì cả hai cùng ở trong LLM (barrier 2 chỉ qua khi song song)."""
    import threading
    llm = _GateLLM(barrier=threading.Barrier(2))
    with _gate_client(tmp_path, llm) as c:
        a, b = register(c, "a@x.vn"), register(c, "b@x.vn")
        pa, pb = new_patient(c, a), new_patient(c, b)
        ra, rb = _in_threads(lambda: c.post(f"/patients/{pa}/chat", json={"question": "Nên ăn gì?"}, headers=a),
                             lambda: c.post(f"/patients/{pb}/chat", json={"question": "Nên ăn gì?"}, headers=b))
        assert ra.status_code == 200 and rb.status_code == 200 and llm.peak == 2


def test_same_session_turns_run_one_after_another(tmp_path):
    llm = _GateLLM(hold=0.3)
    with _gate_client(tmp_path, llm) as c:
        auth = register(c)
        pid = new_patient(c, auth)
        sid = c.post(f"/patients/{pid}/chat", json={"question": "Chào"}, headers=auth).json()["session_id"]
        ask = lambda q: lambda: c.post(f"/patients/{pid}/chat", json={"question": q, "session_id": sid},  # noqa: E731
                                       headers=auth)
        r1, r2 = _in_threads(ask("Câu một?"), ask("Câu hai?"))
        assert r1.status_code == 200 and r2.status_code == 200 and llm.peak == 1
        roles = [m["role"] for m in c.get(f"/patients/{pid}/sessions/{sid}/messages", headers=auth).json()]
        assert roles == ["user", "assistant"] * 3  # không chen tin nhắn của hai lượt


def test_chat_returns_503_when_all_slots_busy(tmp_path):
    import threading
    import time
    gate = threading.Event()
    llm = _GateLLM(gate=gate)
    with _gate_client(tmp_path, llm) as c:
        c.app.state.chat_slots = threading.BoundedSemaphore(1)
        c.app.state.chat_wait = 0.2
        a, b = register(c, "a@x.vn"), register(c, "b@x.vn")
        pa, pb = new_patient(c, a), new_patient(c, b)
        first = threading.Thread(target=lambda: c.post(f"/patients/{pa}/chat", json={"question": "Nên ăn gì?"},
                                                       headers=a))
        first.start()
        while llm.active == 0:
            time.sleep(0.01)
        r = c.post(f"/patients/{pb}/chat", json={"question": "Nên ăn gì?", "stream": True}, headers=b)
        assert r.status_code == 503 and r.headers["Retry-After"]
        gate.set()
        first.join(10)
        # suất được trả lại sau khi lượt đầu xong (kể cả khi lỗi): lượt mới chạy được
        assert c.post(f"/patients/{pb}/chat", json={"question": "Nên ăn gì?"}, headers=b).status_code == 200


# ---- lời nhắc Q-learning hôm nay + 👍/👎 ----

def test_today_nudge_and_feedback(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    n = client.get(f"/patients/{pid}/today", headers=auth).json()["nudge"]
    assert n["text"] and n["label"] and n["rated"] is None
    r = client.post(f"/patients/{pid}/nudge/feedback", json={"value": "down"}, headers=auth)
    assert r.status_code == 200 and r.json()["value"] == "down"
    assert client.get(f"/patients/{pid}/today", headers=auth).json()["nudge"]["rated"] == "down"
    assert client.post(f"/patients/{pid}/nudge/feedback", json={"value": "meh"}, headers=auth).status_code == 422
    other = register(client, email="b@example.com")
    assert client.post(f"/patients/{pid}/nudge/feedback", json={"value": "up"}, headers=other).status_code == 404


def test_no_nudge_for_undiagnosed(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=False)
    assert client.get(f"/patients/{pid}/today", headers=auth).json()["nudge"] is None
    assert client.post(f"/patients/{pid}/nudge/feedback", json={"value": "up"}, headers=auth).status_code == 404


# ---- trợ lý chủ động hỏi trên web (cùng logic với Streamlit) ----

def test_checkin_flow_reading_needs_confirmation(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    r = client.post(f"/patients/{pid}/checkin/open", json={}, headers=auth).json()
    assert r["opened"] and r["pending"]
    sid = r["session_id"]
    msgs = client.get(f"/patients/{pid}/sessions/{sid}/messages", headers=auth).json()
    assert len(msgs) == 1 and msgs[0]["role"] == "assistant" and "chưa thấy số đường huyết" in msgs[0]["content"]
    # gọi lần hai không kèm phiên (React dev chạy effect hai lần, hoặc tab khác): trả về đúng phiên đang đợi
    assert client.post(f"/patients/{pid}/checkin/open", json={}, headers=auth).json() == {
        "session_id": sid, "opened": False, "pending": True}
    # mở lại trang: không hỏi lần hai trong ngày
    again = client.post(f"/patients/{pid}/checkin/open", json={"session_id": sid}, headers=auth).json()
    assert not again["opened"] and again["pending"]
    # "chưa đo" -> câu soạn sẵn, lượt hỏi vẫn mở
    r = client.post(f"/patients/{pid}/checkin/reply", json={"session_id": sid, "text": "chưa đo"}, headers=auth).json()
    assert r["handled"] and "Không sao" in r["reply"] and r["pending"]
    # số đo -> thẻ xác nhận, CHƯA lưu
    r = client.post(f"/patients/{pid}/checkin/reply", json={"session_id": sid, "text": "sáu phẩy năm lúc đói"},
                    headers=auth).json()
    card = r["card"]
    assert r["handled"] and card["reading"]["value"] == 6.5 and card["reading"]["context"] == "fasting"
    assert client.get(f"/patients/{pid}/readings", headers=auth).json() == []
    bad = dict(card["reading"], value=65)  # sửa tay thành số vô lý: máy chủ kiểm tra lại
    assert client.post(f"/patients/{pid}/checkin/save", json={"session_id": sid, "reading": bad,
                       "measured_at": card["measured_at"]}, headers=auth).status_code == 422
    r = client.post(f"/patients/{pid}/checkin/save", json={"session_id": sid, "reading": card["reading"],
                    "measured_at": card["measured_at"], "context": "fasting"}, headers=auth)
    assert r.status_code == 201 and "Mình đã ghi 6,5 mmol/L" in r.json()["reply"]
    readings = client.get(f"/patients/{pid}/readings", headers=auth).json()
    assert len(readings) == 1 and readings[0]["context"] == "fasting"
    # lượt hỏi đã đóng: câu sau đi vào pipeline tư vấn
    r = client.post(f"/patients/{pid}/checkin/reply", json={"session_id": sid, "text": "7,0"}, headers=auth).json()
    assert r == {"handled": False, "pending": False}


def test_checkin_question_goes_to_chat_and_others_blocked(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    sid = client.post(f"/patients/{pid}/checkin/open", json={}, headers=auth).json()["session_id"]
    other = register(client, email="b@example.com")
    assert client.post(f"/patients/{pid}/checkin/reply", json={"session_id": sid, "text": "6,5"},
                       headers=other).status_code == 404
    r = client.post(f"/patients/{pid}/checkin/reply", json={"session_id": sid, "text": "Ăn chuối có sao không?"},
                    headers=auth).json()
    assert r == {"handled": False, "pending": False}
    assert client.post(f"/patients/{pid}/checkin/cancel", json={"session_id": sid}, headers=auth).json()["reply"]


def test_checkin_not_opened_for_undiagnosed(client):
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=False)
    r = client.post(f"/patients/{pid}/checkin/open", json={}, headers=auth).json()
    assert r == {"session_id": None, "opened": False, "pending": False}


# ---- bữa ăn trên web ----

def test_meal_scan_estimate_save_list(client, monkeypatch):
    from diacare import meal_scan
    scan = json.loads((Path(__file__).parent / "fixtures" / "calo_scan_B212.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(meal_scan, "scan", lambda data, name, ctype: scan)
    auth = register(client)
    pid = new_patient(client, auth, diagnosed=True)
    dishes = client.get("/meals/dishes", headers=auth).json()
    assert any(d["cls"] == "pho_bo" and d["manual"] for d in dishes) and any(d["cls"] == "rice" for d in dishes)
    r = client.post("/meals/scan", files={"image": ("khay.jpg", b"\xff\xd8fake", "image/jpeg")}, headers=auth)
    assert r.status_code == 200 and r.json()["items"]
    items = [{"cls": it["cls"], "grams": it["grams"], "model_grams": it["grams"], "gram_method": it["gram_method"]}
             for it in r.json()["items"] if it["cls"]]
    est = client.post(f"/patients/{pid}/meals/estimate", json={"items": items}, headers=auth).json()
    assert est["carb_low"] <= est["carb_g"] <= est["carb_high"] and "tinh bột" in est["text"] and "**" not in est["text"]
    # tự thêm một bát phở (không có gram mô hình) -> gram người dùng
    items.append({"cls": "pho_bo", "grams": 600})
    est2 = client.post(f"/patients/{pid}/meals/estimate", json={"items": items}, headers=auth).json()
    assert est2["carb_g"] > est["carb_g"] + 50
    assert client.post(f"/patients/{pid}/meals/estimate", json={"items": [{"cls": "khong_co", "grams": 1}]},
                       headers=auth).status_code == 422
    eaten = (NOW - timedelta(hours=1)).isoformat()
    r = client.post(f"/patients/{pid}/meals", json={"items": items, "eaten_at": eaten, "slot": "dinner"}, headers=auth)
    assert r.status_code == 201
    client.post(f"/patients/{pid}/readings/glucose", json={"value": 9.0, "context": "after_meal",
                "measured_at": (NOW - timedelta(minutes=5)).isoformat()}, headers=auth)
    meals = client.get(f"/patients/{pid}/meals", headers=auth).json()
    assert len(meals) == 1 and "9 mmol/L sau 55 phút" in meals[0]["after_meal"].replace(",0", "")
    other = register(client, email="b@example.com")
    assert client.get(f"/patients/{pid}/meals", headers=other).status_code == 404
    assert client.delete(f"/patients/{pid}/meals/{meals[0]['id']}", headers=auth).status_code == 204
    assert client.get(f"/patients/{pid}/meals", headers=auth).json() == []


def test_meal_scan_service_down(client, monkeypatch):
    from diacare import meal_scan

    def down(*a, **k):
        raise meal_scan.CaloKhayError("Chưa kết nối được dịch vụ nhận diện món.")
    monkeypatch.setattr(meal_scan, "scan", down)
    auth = register(client)
    r = client.post("/meals/scan", files={"image": ("k.jpg", b"x", "image/jpeg")}, headers=auth)
    assert r.status_code == 503 and "dịch vụ nhận diện" in r.json()["detail"]
