import base64
import io
import json
from datetime import datetime, timedelta

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
