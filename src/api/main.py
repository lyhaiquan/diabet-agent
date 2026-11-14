"""Dịch vụ API cho DiaCare (FastAPI). Giao diện web/điện thoại gọi vào đây; Streamlit vẫn chạy riêng để demo.

Chạy:  uvicorn api.main:app --app-dir src --port 8000      (tài liệu tương tác: http://localhost:8000/docs)

Thiết kế:
- Phần AI nặng (Predictor, Retriever, LLM, KG, tiên nghiệm RL) dựng MỘT lần khi khởi động, dùng chung.
- Mỗi request mở một kết nối SQLite riêng (chế độ WAL). Lượt tư vấn và phản hồi 👍/👎 chạy tuần tự dưới một
  khoá: mô hình RL được đọc-sửa-ghi, và Ollama cũng chỉ trả lời từng câu một.
- Mọi tài nguyên đều thuộc về một hồ sơ (patient) của một tài khoản; tài nguyên của người khác trả 404.
"""
import json
import os
import queue
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from api import security
from diacare import journal
from diacare.db import Store
from diacare.factory import DEFAULT_DB_PATH, ROOT, build_parts, orchestrator_from_parts
from diacare.labs import LABELS as LAB_LABELS, LabAgent, classify, parse_lab_file, parse_lab_text
from diacare.memory import KIND_LABELS, has_diagnosis
from diacare.rl import ACTION_LABELS, RLAgent
from diacare.rules import FEATURE_RANGES, SafeStream, risk_band, validate_profile
from diacare.samples import LOW_RISK
from diacare.speech import AudioError, decode_wav, make_transcriber, parse_spoken_reading
from diacare.state import State
from diacare.visit_report import build_visit_pdf

API_VERSION = "0.1.0"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 4 * 1024 * 1024  # 60 giây WAV 16 kHz 16 bit khoảng 1,9 MB
DIAGNOSIS_T2D = "đái tháo đường típ 2"
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ---- dựng ứng dụng ------------------------------------------------------------

def create_app(db_path=None, parts=None, secret=None, clock=None, cors_origins=None, transcriber=None):
    """Tham số để test: db_path (tệp SQLite tạm), parts (LLM giả lập), secret, clock (giờ cố định)."""
    db_path = str(db_path or os.environ.get("DIACARE_DB") or DEFAULT_DB_PATH)

    @asynccontextmanager
    async def lifespan(app):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        boot = Store(db_path)  # tạo bảng, nâng cấp DB cũ: chỉ làm một lần, trước khi nhận request
        boot.enable_wal()
        boot.close()
        if app.state.secret is None:  # đọc khi khởi động, không phải lúc import (test đặt khoá riêng)
            app.state.secret = security.load_secret(ROOT / "data" / "api_secret.key")
        app.state.parts = parts or build_parts()
        yield

    app = FastAPI(title="DiaCare API", version=API_VERSION, lifespan=lifespan,
                  description="Trợ lý tự theo dõi đái tháo đường típ 2 giữa hai lần khám. "
                              "Không chẩn đoán, không kê đơn; không thay thế bác sĩ.")
    app.state.db_path = db_path
    app.state.secret = secret
    app.state.clock = clock or journal.now_vn
    app.state.chat_lock = threading.Lock()
    app.state.transcriber = transcriber  # None: nạp PhoWhisper ở lần nói đầu tiên
    origins = cors_origins if cors_origins is not None else [
        o.strip() for o in os.environ.get("DIACARE_CORS", "http://localhost:3000").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    _routes(app)
    return app


# ---- phụ thuộc dùng chung -----------------------------------------------------

def get_store(request: Request):
    store = Store(request.app.state.db_path, init_schema=False)
    try:
        yield store
    finally:
        store.close()


def now_of(request: Request):
    return journal.to_vn(request.app.state.clock())


def current_user(request: Request, token: str = Depends(oauth2), store: Store = Depends(get_store)):
    try:
        uid = security.decode_token(token, request.app.state.secret)
    except security.TokenError:
        uid = None
    user = store.get_user(uid) if uid is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def owned_patient(patient_id: int, user=Depends(current_user), store: Store = Depends(get_store)):
    """Hồ sơ phải thuộc tài khoản đang đăng nhập; của người khác thì trả 404 như không tồn tại."""
    patient = store.get_patient(patient_id)
    if patient is None or store.patient_owner(patient_id) != user["id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy hồ sơ.")
    return patient


def _not_found(what="Không tìm thấy."):
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


# ---- dữ liệu vào ---------------------------------------------------------------

class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=100)


class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    diagnosed: bool = Field(default=False, description="Đã được bác sĩ chẩn đoán ĐTĐ típ 2")
    profile: dict | None = Field(default=None, description="21 chỉ số BRFSS; thiếu chỉ số nào lấy giá trị mẫu")


class PatientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    profile: dict | None = None


class GlucoseIn(BaseModel):
    value: float = Field(gt=0)
    unit: Literal["mmol/L", "mg/dL"] = "mmol/L"
    context: Literal["fasting", "before_meal", "after_meal", "bedtime", "random"]
    measured_at: datetime | None = Field(default=None, description="Không có múi giờ thì hiểu là giờ Việt Nam")
    note: str | None = Field(default=None, max_length=300)


class BpIn(BaseModel):
    systolic: int
    diastolic: int
    measured_at: datetime | None = None
    note: str | None = Field(default=None, max_length=300)


class WeightIn(BaseModel):
    kg: float
    measured_at: datetime | None = None
    note: str | None = Field(default=None, max_length=300)


class LabTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class AppointmentIn(BaseModel):
    date: date
    place: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=300)


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: int | None = Field(default=None, description="Bỏ trống để mở phiên mới")
    stream: bool = Field(default=False, description="true: trả về luồng Server-Sent Events")


class FeedbackIn(BaseModel):
    value: Literal["up", "down"]


# ---- chuyển đổi ra JSON ---------------------------------------------------------

def _patient_out(store, parts, patient):
    memories = store.list_memories(patient["id"])
    risk = float(parts.predictor.predict(patient["profile"]))
    return {"id": patient["id"], "name": patient["name"], "created_at": patient["created_at"],
            "diagnosed": bool(has_diagnosis(memories)), "profile": patient["profile"],
            "risk": {"probability": round(risk, 4), "band": risk_band(risk),
                     "note": "Ước tính từ 21 câu hỏi lối sống (BRFSS); không có ý nghĩa với người đã chẩn đoán."}}


def _reading_out(r):
    out = {"id": r["id"], "kind": r["kind"], "measured_at": journal.to_vn(r["measured_at"]).isoformat(),
           "note": r["note"]}
    if r["kind"] == "glucose":
        st = journal.classify_glucose(r["value"], r["context"])
        out.update(mgdl=round(r["value"], 1), mmol=round(journal.to_mmol(r["value"]), 1), unit=r["unit"],
                   context=r["context"], context_text=journal.CONTEXTS.get(r["context"]),
                   status=st, status_text=journal.STATUS_TEXT[st])
    elif r["kind"] == "bp":
        st = journal.classify_bp(r["value"], r["value2"])
        out.update(systolic=r["value"], diastolic=r["value2"], status=st, status_text=journal.STATUS_TEXT[st])
    else:
        out.update(kg=r["value"])
    return out


def _messages(items):
    return [{"level": level, "text": text} for level, text in items]


def _when(value, now):
    when = journal.to_vn(value) if value is not None else now
    if when > now + timedelta(minutes=5):
        raise HTTPException(422, "Thời điểm đo không được ở tương lai.")
    return when


def _labs_out(store, patient_id):
    out = []
    diagnosed = has_diagnosis(store.list_memories(patient_id))
    for row in store.list_labs(patient_id):
        c = classify([{"test": row["test"], "value": row["value"], "unit": row["unit"]}])
        if not c:
            continue
        r = c[0]
        if diagnosed and r["test"] == "hba1c":
            judge = "đạt mục tiêu chung (< 7%)" if r["value_std"] < 7 else "cao hơn mục tiêu chung 7%"
        else:
            judge = r["level_text"]
        out.append({"id": row["id"], "test": r["test"], "label": r["label"], "value": r["value_std"],
                    "unit": r["unit_std"], "level": r["level"], "assessment": judge,
                    "source": row["source"], "created_at": journal.to_vn(row["created_at"]).isoformat()})
    return out


def _import_labs(store, patient_id, results):
    saved = LabAgent(store).import_results(patient_id, results, source="import")
    if not saved:
        raise HTTPException(422, "Không tìm thấy chỉ số hợp lệ. Hỗ trợ: HbA1c, đường huyết lúc đói, "
                                 "đường huyết 2 giờ (OGTT), đường huyết bất kỳ.")
    return {"imported": [{"test": r["test"], "label": LAB_LABELS[r["test"]], "value": r["value"],
                          "unit": r.get("unit")} for r in saved],
            "labs": _labs_out(store, patient_id)}


# ---- tư vấn: chạy pipeline 10 agent ----------------------------------------------

def _run_chat(app, user_id, patient_id, question, session_id, emit=None):
    """Chạy một lượt tư vấn trên kết nối SQLite riêng (dùng được trong luồng phụ của SSE) và lưu tin nhắn.
    emit(event, data): báo bước agent và chữ đã qua bộ lọc an toàn trong lúc chạy."""
    store = Store(app.state.db_path, init_schema=False)
    try:
        with app.state.chat_lock:
            patient = store.get_patient(patient_id)
            if session_id is None:
                session_id = store.start_session(patient_id)
            if emit:
                emit("session", {"session_id": session_id})
            orch = orchestrator_from_parts(app.state.parts, store, session_id)
            history = store.get_history(session_id)
            sent = {"n": 0}

            def on_text(shown):  # SafeStream đưa toàn bộ phần đã duyệt; chỉ gửi phần mới
                emit("token", {"text": shown[sent["n"]:]})
                sent["n"] = len(shown)

            stream = SafeStream(on_text) if emit else None
            state = orch.run(State(question=question, profile=patient["profile"], history=history,
                                   patient_id=patient_id),
                             on_token=stream,
                             on_step=(lambda e: emit("step", e)) if emit else None)
            if stream is not None:
                stream.flush()
            rl = state.rl or {}
            store.add_message(session_id, "user", question)
            store.add_message(session_id, "assistant", state.final, rl_event_id=rl.get("event_id"))
            diagnosed = has_diagnosis(store.list_memories(patient_id))
        return {
            "session_id": session_id,
            "answer": state.final,  # câu trả lời cuối đã qua Rules: giao diện phải thay bản nháp bằng câu này
            "sources": [d["source"] for d in state.docs],
            "flags": list(state.flags),
            "risk": None if diagnosed or state.risk is None else {"probability": round(state.risk, 4),
                                                                  "band": risk_band(state.risk)},
            "focus": {"event_id": rl.get("event_id"), "action": rl.get("action"),
                      "label": ACTION_LABELS.get(rl.get("action"))} if rl.get("action") else None,
            "steps": [{"agent": e["agent"], "detail": e["detail"], "ms": e["ms"]} for e in state.trace],
        }
    finally:
        store.close()


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


# ---- các đường dẫn --------------------------------------------------------------

def _routes(app):  # noqa: C901 - danh sách endpoint, đọc tuần tự dễ hơn tách nhỏ

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["hệ thống"])
    def health(request: Request):
        parts = getattr(request.app.state, "parts", None)
        return {"status": "ok", "version": API_VERSION,
                "features": sorted(parts.features) if parts else [],
                "llm": type(parts.llm).__name__ if parts else None}

    # -- tài khoản --
    @app.post("/auth/register", status_code=201, tags=["tài khoản"])
    def register(body: RegisterIn, request: Request, store: Store = Depends(get_store)):
        uid = store.create_user(body.email, security.hash_password(body.password), body.name)
        if uid is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email này đã có tài khoản.")
        return {"access_token": security.create_token(uid, request.app.state.secret), "token_type": "bearer",
                "user": {"id": uid, "email": body.email.strip().lower(), "name": body.name}}

    @app.post("/auth/token", tags=["tài khoản"])
    def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), store: Store = Depends(get_store)):
        """Chuẩn OAuth2 password flow: trường `username` là email. Nút Authorize ở /docs dùng đường này."""
        user = store.get_user_by_email(form.username)
        if user is None or not security.verify_password(form.password, user["password_hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email hoặc mật khẩu không đúng.",
                                headers={"WWW-Authenticate": "Bearer"})
        return {"access_token": security.create_token(user["id"], request.app.state.secret),
                "token_type": "bearer"}

    @app.get("/me", tags=["tài khoản"])
    def me(user=Depends(current_user)):
        return {"id": user["id"], "email": user["email"], "name": user["name"], "created_at": user["created_at"]}

    # -- hồ sơ --
    @app.get("/patients", tags=["hồ sơ"])
    def list_patients(request: Request, user=Depends(current_user), store: Store = Depends(get_store)):
        return [_patient_out(store, request.app.state.parts, p) for p in store.list_patients(user["id"])]

    @app.post("/patients", status_code=201, tags=["hồ sơ"])
    def create_patient(body: PatientIn, request: Request, user=Depends(current_user),
                       store: Store = Depends(get_store)):
        profile = {**LOW_RISK, **(body.profile or {})}
        unknown = set(profile) - set(FEATURE_RANGES)
        errors = validate_profile(profile) + [f"chỉ số không biết: {k}" for k in sorted(unknown)]
        if errors:
            raise HTTPException(422, "; ".join(errors))
        pid = store.save_patient(body.name.strip(), profile, user_id=user["id"])
        if body.diagnosed:
            store.add_memory(pid, "diagnosis", DIAGNOSIS_T2D, source="form")
        return _patient_out(store, request.app.state.parts, store.get_patient(pid))

    @app.get("/patients/{patient_id}", tags=["hồ sơ"])
    def get_patient(request: Request, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        return _patient_out(store, request.app.state.parts, patient)

    @app.patch("/patients/{patient_id}", tags=["hồ sơ"])
    def patch_patient(body: PatientPatch, request: Request, patient=Depends(owned_patient),
                      store: Store = Depends(get_store)):
        profile = None
        if body.profile is not None:
            profile = {**patient["profile"], **body.profile}
            errors = validate_profile(profile) + [f"chỉ số không biết: {k}"
                                                  for k in sorted(set(profile) - set(FEATURE_RANGES))]
            if errors:
                raise HTTPException(422, "; ".join(errors))
        store.update_patient(patient["id"], body.name.strip() if body.name else None, profile)
        return _patient_out(store, request.app.state.parts, store.get_patient(patient["id"]))

    @app.get("/patients/{patient_id}/memories", tags=["hồ sơ"])
    def memories(patient=Depends(owned_patient), store: Store = Depends(get_store)):
        return [{"id": m["id"], "kind": m["kind"], "kind_text": KIND_LABELS.get(m["kind"], m["kind"]),
                 "content": m["content"], "source": m["source"]} for m in store.list_memories(patient["id"])]

    @app.delete("/patients/{patient_id}/memories/{memory_id}", status_code=204, tags=["hồ sơ"])
    def forget(memory_id: int, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        m = store.get_memory(memory_id)
        if m is None or m["patient_id"] != patient["id"]:
            raise _not_found()
        store.deactivate_memory(memory_id)
        return Response(status_code=204)

    # -- nhật ký --
    @app.post("/patients/{patient_id}/readings/glucose", status_code=201, tags=["nhật ký"])
    def add_glucose(body: GlucoseIn, request: Request, patient=Depends(owned_patient),
                    store: Store = Depends(get_store)):
        mgdl, err = journal.validate_glucose(body.value, body.unit)
        if err:
            raise HTTPException(422, err)
        when = _when(body.measured_at, now_of(request))
        rid = store.add_reading(patient["id"], "glucose", mgdl, when, unit=body.unit, context=body.context,
                                note=(body.note or "").strip() or None)
        return {"reading": _reading_out(store.get_reading(rid)),
                **journal.describe_glucose(mgdl, body.context, body.unit)}

    @app.post("/patients/{patient_id}/readings/bp", status_code=201, tags=["nhật ký"])
    def add_bp(body: BpIn, request: Request, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        err = journal.validate_bp(body.systolic, body.diastolic)
        if err:
            raise HTTPException(422, err)
        when = _when(body.measured_at, now_of(request))
        rid = store.add_reading(patient["id"], "bp", body.systolic, when, value2=body.diastolic, unit="mmHg",
                                note=(body.note or "").strip() or None)
        st = journal.classify_bp(body.systolic, body.diastolic)
        return {"reading": _reading_out(store.get_reading(rid)), "status": st,
                "status_text": journal.STATUS_TEXT[st], "target": "dưới 130/80 mmHg",
                "advice": journal.ADVICE["bp_very_high"][1] if st == "very_high" else None}

    @app.post("/patients/{patient_id}/readings/weight", status_code=201, tags=["nhật ký"])
    def add_weight(body: WeightIn, request: Request, patient=Depends(owned_patient),
                   store: Store = Depends(get_store)):
        err = journal.validate_weight(body.kg)
        if err:
            raise HTTPException(422, err)
        when = _when(body.measured_at, now_of(request))
        rid = store.add_reading(patient["id"], "weight", body.kg, when, unit="kg",
                                note=(body.note or "").strip() or None)
        return {"reading": _reading_out(store.get_reading(rid))}

    @app.get("/patients/{patient_id}/readings", tags=["nhật ký"])
    def list_readings(request: Request, kind: Literal["glucose", "bp", "weight"] | None = None,
                      days: int = Query(30, ge=1, le=366), patient=Depends(owned_patient),
                      store: Store = Depends(get_store)):
        start = now_of(request).date() - timedelta(days=days - 1)
        rows = [r for r in store.list_readings(patient["id"], kind) if journal._day(r) >= start]
        return [_reading_out(r) for r in reversed(rows)]

    @app.delete("/patients/{patient_id}/readings/{reading_id}", status_code=204, tags=["nhật ký"])
    def delete_reading(reading_id: int, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        r = store.get_reading(reading_id)
        if r is None or r["patient_id"] != patient["id"]:
            raise _not_found()
        store.delete_reading(reading_id, patient["id"])
        return Response(status_code=204)

    @app.get("/patients/{patient_id}/today", tags=["nhật ký"])
    def today(request: Request, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        """Màn hình Hôm nay: cảnh báo từ lần đo 24 giờ qua, nhắc nhở, số liệu 14 ngày."""
        now = now_of(request)
        readings = store.list_readings(patient["id"])
        s = journal.summarize_glucose(readings, 14, now)
        glu = journal.glucose_rows(readings)
        hba1c = [r for r in _labs_out(store, patient["id"]) if r["test"] == "hba1c"]
        appt = store.get_appointment(patient["id"])
        return {"date": now.date().isoformat(), "name": patient["name"],
                "alerts": _messages(journal.alerts(readings, now=now)),
                "reminders": _messages(journal.reminders(readings, appt, now=now)),
                "last_glucose": _reading_out(glu[-1]) if glu else None,
                "in_target_pct_14d": s["in_target_pct"],
                "fasting_mean_mmol_14d": round(journal.to_mmol(s["by_context"]["fasting"]["mean_mgdl"]), 1)
                if "fasting" in s["by_context"] else None,
                "latest_hba1c": hba1c[-1] if hba1c else None,
                "appointment": appt}

    @app.get("/patients/{patient_id}/summary", tags=["nhật ký"])
    def summary(request: Request, days: int = Query(14, ge=1, le=366), patient=Depends(owned_patient),
                store: Store = Depends(get_store)):
        now = now_of(request)
        readings = store.list_readings(patient["id"])
        g = journal.summarize_glucose(readings, days, now)
        to_mmol = (lambda v: None if v is None else round(journal.to_mmol(v), 1))
        return {
            "days": days,
            "glucose": {**{k: g[k] for k in ("n", "days_measured", "hypo", "very_high", "in_target_pct")},
                        "mean_mmol": to_mmol(g["mean_mgdl"]),
                        "by_context": {c: {"n": v["n"], "mean_mmol": to_mmol(v["mean_mgdl"]),
                                           "min_mmol": to_mmol(v["min_mgdl"]), "max_mmol": to_mmol(v["max_mgdl"]),
                                           "in_target_pct": v["in_target_pct"]} for c, v in g["by_context"].items()}},
            "compare_previous": journal.compare_periods(readings, days, now),
            "bp": journal.summarize_bp(readings, days, now),
            "weight": journal.weight_change(readings, days, now),
            "series": [{"t": t.isoformat(), "mmol": round(journal.to_mmol(v), 1), "context": c}
                       for t, v, c in journal.daily_series(readings, days, now)],
            "targets": {"pre_meal_mmol": [4.4, 7.2], "post_meal_max_mmol": 10.0, "hypo_mmol": 3.9,
                        "source": journal.SOURCE},
        }

    # -- xét nghiệm --
    @app.get("/patients/{patient_id}/labs", tags=["xét nghiệm"])
    def labs(patient=Depends(owned_patient), store: Store = Depends(get_store)):
        return _labs_out(store, patient["id"])

    @app.post("/patients/{patient_id}/labs", status_code=201, tags=["xét nghiệm"])
    def labs_from_text(body: LabTextIn, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        return _import_labs(store, patient["id"], parse_lab_text(body.text))

    @app.post("/patients/{patient_id}/labs/file", status_code=201, tags=["xét nghiệm"])
    def labs_from_file(file: UploadFile = File(...), patient=Depends(owned_patient),
                       store: Store = Depends(get_store)):
        """Ảnh chụp hoặc file phiếu xét nghiệm (.png, .jpg, .pdf, .txt, .csv, .json), tối đa 10 MB."""
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File lớn hơn 10 MB.")
        try:
            results = parse_lab_file(file.filename or "upload.txt", data)
        except Exception as exc:  # file hỏng, định dạng lạ, OCR lỗi
            raise HTTPException(422, f"Không đọc được file ({type(exc).__name__}).") from exc
        return _import_labs(store, patient["id"], results)

    # -- tái khám --
    @app.get("/patients/{patient_id}/appointment", tags=["tái khám"])
    def get_appointment(patient=Depends(owned_patient), store: Store = Depends(get_store)):
        return store.get_appointment(patient["id"])

    @app.put("/patients/{patient_id}/appointment", tags=["tái khám"])
    def set_appointment(body: AppointmentIn, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        store.set_appointment(patient["id"], body.date.isoformat(), (body.place or "").strip() or None,
                              (body.note or "").strip() or None)
        return store.get_appointment(patient["id"])

    @app.get("/patients/{patient_id}/questions", tags=["tái khám"])
    def questions(include_done: bool = False, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        return [{"id": q["id"], "text": q["text"], "done": bool(q["done"]), "created_at": q["created_at"]}
                for q in store.list_doctor_questions(patient["id"], include_done)]

    @app.post("/patients/{patient_id}/questions", status_code=201, tags=["tái khám"])
    def add_question(body: QuestionIn, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        if not body.text.strip():
            raise HTTPException(422, "Câu hỏi trống.")
        qid = store.add_doctor_question(patient["id"], body.text)
        q = store.get_doctor_question(qid)
        return {"id": q["id"], "text": q["text"], "done": False, "created_at": q["created_at"]}

    @app.post("/patients/{patient_id}/questions/{question_id}/done", tags=["tái khám"])
    def question_done(question_id: int, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        q = store.get_doctor_question(question_id)
        if q is None or q["patient_id"] != patient["id"]:
            raise _not_found()
        store.mark_doctor_question(question_id)
        return {"id": question_id, "done": True}

    @app.get("/patients/{patient_id}/visit-report.pdf", tags=["tái khám"],
             response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
    def visit_report(request: Request, days: int = Query(28, ge=7, le=180), patient=Depends(owned_patient),
                     store: Store = Depends(get_store)):
        now = now_of(request)
        pdf = build_visit_pdf(store, patient["id"], days=days, now=now)
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="tom_tat_tai_kham_{now:%Y%m%d}.pdf"'})

    # -- tư vấn --
    @app.get("/patients/{patient_id}/sessions", tags=["tư vấn"])
    def sessions(patient=Depends(owned_patient), store: Store = Depends(get_store)):
        return store.list_sessions(patient["id"])

    @app.get("/patients/{patient_id}/sessions/{session_id}/messages", tags=["tư vấn"])
    def session_messages(session_id: int, patient=Depends(owned_patient), store: Store = Depends(get_store)):
        s = store.get_session(session_id)
        if s is None or s["patient_id"] != patient["id"]:
            raise _not_found("Không tìm thấy phiên.")
        out = []
        for m in store.get_history(session_id, limit=500):
            item = {"role": m["role"], "content": m["content"]}
            if m.get("rl_event_id"):
                ev = store.get_rl_event(m["rl_event_id"])
                item["focus"] = {"event_id": m["rl_event_id"], "action": m["rl_action"],
                                 "label": ACTION_LABELS.get(m["rl_action"]),
                                 "rated": None if ev is None or ev["reward"] is None
                                 else ("up" if ev["reward"] > 0 else "down")}
            out.append(item)
        return out

    @app.post("/patients/{patient_id}/chat", tags=["tư vấn"])
    def chat(body: ChatIn, request: Request, user=Depends(current_user), patient=Depends(owned_patient),
             store: Store = Depends(get_store)):
        """Hỏi trợ lý. `stream=false`: trả JSON khi xong. `stream=true`: luồng SSE với các sự kiện
        `session`, `step` (từng agent), `token` (phần chữ mới, đã qua bộ lọc an toàn), `done` (kết quả cuối,
        giống JSON ở chế độ thường; giao diện phải thay phần chữ đã hiện bằng `answer`), `error`."""
        if body.session_id is not None:
            s = store.get_session(body.session_id)
            if s is None or s["patient_id"] != patient["id"]:
                raise _not_found("Không tìm thấy phiên.")
        app_ = request.app
        if not body.stream:
            return _run_chat(app_, user["id"], patient["id"], body.question, body.session_id)

        events = queue.Queue()

        def worker():
            try:
                result = _run_chat(app_, user["id"], patient["id"], body.question, body.session_id,
                                   emit=lambda ev, data: events.put((ev, data)))
                events.put(("done", result))
            except Exception as exc:  # lỗi trong pipeline: báo cho giao diện, không treo luồng
                events.put(("error", {"message": f"Lỗi hệ thống ({type(exc).__name__}). Vui lòng thử lại."}))
            finally:
                events.put(None)

        # Luồng phụ chạy đến hết và lưu tin nhắn kể cả khi người dùng đóng trang giữa chừng.
        threading.Thread(target=worker, daemon=True).start()

        def gen():
            while (item := events.get()) is not None:
                yield _sse(*item)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/transcribe", tags=["giọng nói"])
    def transcribe(request: Request, audio: UploadFile = File(..., description="WAV PCM 16 bit, tối đa 60 giây"),
                   user=Depends(current_user)):
        """Chuyển lời nói tiếng Việt thành chữ. Âm thanh không được lưu lại.
        `reading` là số đo nghe được trong câu (nếu có), chỉ để giao diện hỏi lại người dùng trước khi lưu."""
        data = audio.file.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Đoạn ghi âm quá dài.")
        try:
            samples = decode_wav(data)
        except AudioError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            del data
        if request.app.state.transcriber is None:
            request.app.state.transcriber = make_transcriber()
        t0 = time.perf_counter()
        text = request.app.state.transcriber(samples)
        return {"text": text, "reading": parse_spoken_reading(text) if text else None,
                "seconds": round(time.perf_counter() - t0, 2), "audio_seconds": round(len(samples) / 16000, 1)}

    @app.post("/feedback/{event_id}", tags=["tư vấn"])
    def feedback(event_id: int, body: FeedbackIn, request: Request, user=Depends(current_user),
                 store: Store = Depends(get_store)):
        """👍/👎 cho trọng tâm tư vấn mà agent học tăng cường đã chọn; agent học ngay từ phản hồi này."""
        ev = store.get_rl_event(event_id)
        s = store.get_session(ev["session_id"]) if ev and ev["session_id"] is not None else None
        if s is None or s["patient_id"] is None or store.patient_owner(s["patient_id"]) != user["id"]:
            raise _not_found("Không tìm thấy lượt tư vấn.")
        parts = request.app.state.parts
        if parts.rl_prior is None:
            raise HTTPException(409, "Agent học tăng cường đang tắt.")
        with request.app.state.chat_lock:
            res = RLAgent(prior=parts.rl_prior, store=store, epsilon=0).feedback(event_id, body.value)
        if res is None:
            raise HTTPException(409, "Lượt này đã được chấm rồi.")
        return res


app = create_app()
