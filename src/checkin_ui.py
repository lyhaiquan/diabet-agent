"""Trợ lý chủ động hỏi trên trang Tư vấn (dùng trong app.py). Phần quyết định nằm ở diacare.checkin; ở đây chỉ
lưu tin nhắn và vẽ thẻ xác nhận số đo."""
import hashlib
import json
import os
import re
from datetime import datetime

import streamlit as st

from diacare import journal
from diacare.speech import AudioError, decode_wav, make_transcriber
from diacare.checkin import (CANCEL_REPLY, NOT_YET_REPLY, opener_text, plan_topic, route_reply, saved_reply,
                             symptom_reply)
from diacare.coach import daily_nudge
from journal_ui import _coach

CARD = "checkin_card"


def maybe_open(store, patient, session_id, diagnosed):
    """Mở lời một lần mỗi ngày cho người đã chẩn đoán. Lượt hỏi giữ bằng một dòng trong bảng checkins (không chỉ
    session_state) nên chạy lại trang hay mở tab khác cũng không hỏi lại."""
    if not diagnosed or session_id is None:
        return
    now = journal.now_vn()
    if store.get_checkin(patient["id"], now.date()) is not None:
        return
    targets = journal.resolve_targets(store.get_targets(patient["id"]))
    topic = plan_topic(store.list_readings(patient["id"]), now, targets)
    coach = _coach()
    # cùng lời nhắc với tab Hôm nay: daily_nudge chỉ chọn một lần mỗi ngày (bảng coach_events)
    nudge = daily_nudge(store, coach, patient["id"], now.date())["text"] if coach is not None else None
    # Bảng checkins không mã hoá: chỉ lưu loại câu hỏi, không lưu câu hỏi (có số đo và nhận định sức khoẻ)
    stored = {k: topic.get(k) for k in ("kind", "expects", "context", "status")}
    if store.claim_checkin(patient["id"], now.date(), session_id, stored):
        store.add_message(session_id, "assistant", opener_text(patient["name"], topic, nudge))


def _pending_topic(store, patient_id, session_id):
    c = store.get_checkin(patient_id, journal.now_vn().date())
    if c and c["status"] == "open" and c["session_id"] == session_id:
        return c["topic"]
    return None


def handle_input(store, patient, session_id, text):
    """True nếu câu vừa gõ là câu trả lời cho câu hỏi chủ động và đã xử lý ở đây (số đo -> thẻ xác nhận, "chưa đo"
    -> câu soạn sẵn). False: để app.py gửi cho pipeline tư vấn như mọi câu hỏi khác."""
    topic = _pending_topic(store, patient["id"], session_id)
    if topic is None:
        return False
    r = route_reply(text, topic)
    if r["route"] == "ask":
        store.close_checkin(patient["id"], journal.now_vn().date(), "answered")
        st.session_state.pop(CARD, None)  # thẻ số đo cũ không còn hợp ngữ cảnh
        return False
    store.add_message(session_id, "user", text)
    if r["route"] == "symptom":  # lượt hỏi vẫn mở để lát nữa gõ số đo lại
        store.add_message(session_id, "assistant", symptom_reply(topic))
        return True
    if r["route"] == "not_yet":
        # vẫn để lượt hỏi mở: lát nữa người dùng gõ số thì vẫn ghi được
        store.add_message(session_id, "assistant", NOT_YET_REPLY)
        return True
    n = st.session_state.get("checkin_card_n", 0) + 1
    st.session_state["checkin_card_n"] = n
    st.session_state[CARD] = {"n": n, "reading": r["reading"], "when": r["when"].isoformat()}
    return True


def _save(store, patient, session_id, card):
    ss, n, reading = st.session_state, card["n"], dict(card["reading"])
    when = datetime.combine(ss[f"ci_date_{n}"], ss[f"ci_time_{n}"], tzinfo=journal.VN_TZ)
    pid = patient["id"]
    if reading["kind"] == "glucose":
        if reading.get("alternative") and ss.get(f"ci_alt_{n}") == 1:
            reading.update(value=reading["alternative"]["value"], unit=reading["alternative"]["unit"])
        reading["context"] = ss[f"ci_ctx_{n}"]
        mgdl, err = journal.validate_glucose(reading["value"], reading["unit"])
        if err:
            ss[f"ci_err_{n}"] = err
            return
        store.add_reading(pid, "glucose", mgdl, when, unit=reading["unit"], context=reading["context"],
                          note="ghi qua trò chuyện")
    elif reading["kind"] == "bp":
        err = journal.validate_bp(reading["systolic"], reading["diastolic"])
        if err:
            ss[f"ci_err_{n}"] = err
            return
        store.add_reading(pid, "bp", reading["systolic"], when, value2=reading["diastolic"], unit="mmHg")
    else:
        err = journal.validate_weight(reading["kg"])
        if err:
            ss[f"ci_err_{n}"] = err
            return
        store.add_reading(pid, "weight", reading["kg"], when, unit="kg")
    targets = journal.resolve_targets(store.get_targets(pid))
    store.add_message(session_id, "assistant", saved_reply(reading, targets))
    store.close_checkin(pid, journal.now_vn().date(), "done")
    ss.pop(CARD, None)


def _cancel(store, session_id):
    store.add_message(session_id, "assistant", CANCEL_REPLY)
    st.session_state.pop(CARD, None)


def render_card(store, patient, session_id):
    """Thẻ xác nhận số đo vừa đọc được trong câu trả lời: chỉ lưu khi người dùng bấm Lưu."""
    card = st.session_state.get(CARD)
    if not card:
        return
    n, reading = card["n"], card["reading"]
    when = journal.to_vn(card["when"])
    with st.container(border=True):
        st.markdown("**Mình ghi vào nhật ký như thế này nhé?**")
        if reading["kind"] == "glucose":
            if reading.get("alternative"):
                st.radio("Bạn định gõ số nào?", [0, 1], key=f"ci_alt_{n}", horizontal=True,
                         format_func=lambda i: (reading["summary"], reading["alternative"]["summary"])[i])
            else:
                st.markdown(reading["summary"])
            ctxs = list(journal.CONTEXTS)
            st.selectbox("Đo lúc", ctxs, index=ctxs.index(reading.get("context") or "random"),
                         format_func=journal.CONTEXTS.get, key=f"ci_ctx_{n}")
        else:
            st.markdown(reading["summary"])
        c1, c2 = st.columns(2)
        c1.date_input("Ngày đo", value=when.date(), max_value=journal.now_vn().date(), key=f"ci_date_{n}",
                      format="DD/MM/YYYY")
        c2.time_input("Giờ đo", value=when.time().replace(second=0, microsecond=0, tzinfo=None),
                      key=f"ci_time_{n}", step=300)
        if st.session_state.get(f"ci_err_{n}"):
            st.error(st.session_state[f"ci_err_{n}"])
        b1, b2 = st.columns(2)
        b1.button("Lưu vào nhật ký", type="primary", key=f"ci_save_{n}", on_click=_save,
                  args=(store, patient, session_id, card))
        b2.button("Không đúng", key=f"ci_cancel_{n}", on_click=_cancel, args=(store, session_id))


# ---- trả lời bằng giọng nói --------------------------------------------------
# Ghi âm trên trình duyệt (st.audio_input, WAV 16 kHz), nhận dạng bằng PhoWhisper chạy trên máy (diacare.speech), rồi
# đi đúng đường của câu gõ chữ (handle_input): số đo vẫn phải bấm Lưu trên thẻ xác nhận. Âm thanh không được lưu.

@st.cache_resource
def _cached_transcriber(kind, model, demo_text):  # khoá theo cấu hình: đổi biến môi trường thì nạp lại
    return make_transcriber(kind)


def _transcriber():
    env = os.environ
    return _cached_transcriber(env.get("DIACARE_ASR"), env.get("DIACARE_ASR_MODEL"), env.get("DIACARE_ASR_DEMO_TEXT"))


def _opener(store, session_id):
    for m in store.get_history(session_id):
        if m["role"] == "assistant" and m["content"].startswith("Chào "):
            return m["content"]
    return None


def _speak_button(text):
    """Nút đọc to câu hỏi bằng giọng tiếng Việt có sẵn của máy (Web Speech API), không gửi chữ đi đâu."""
    plain = re.sub(r"[*_`#]", "", text)
    # câu hỏi có tên người dùng: không để "</script>" trong tên đóng thẻ script
    js_text = json.dumps(plain).replace("</", "<\\/")
    st.iframe(f"""
<button id="b" style="font:14px sans-serif;padding:6px 12px;border-radius:8px;border:1px solid #888;
 background:transparent;color:inherit;cursor:pointer">🔊 Đọc câu hỏi</button>
<span id="m" style="font:12px sans-serif;margin-left:8px;opacity:.75"></span>
<script>
const text = {js_text};
const synth = window.speechSynthesis;
document.getElementById("b").onclick = () => {{
  if (!synth) {{ document.getElementById("m").textContent = "Trình duyệt không hỗ trợ đọc to."; return; }}
  const vi = synth.getVoices().find(v => v.lang.toLowerCase().startsWith("vi"));
  if (!vi) {{ document.getElementById("m").textContent = "Máy chưa có giọng Tiếng Việt (Cài đặt > Giọng nói)."; }}
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "vi-VN"; if (vi) u.voice = vi;
  synth.speak(u);
}};
</script>""", height=44)


HEARD = "ci_heard"


def _transcribe_new(audio):
    """Nhận dạng đoạn ghi âm MỚI (đoạn cũ còn trong ô thì bỏ qua). Trả về chữ hoặc None."""
    data = audio.getvalue()
    digest = hashlib.sha1(data).hexdigest()
    if st.session_state.get("ci_voice_done") == digest:
        return None
    st.session_state["ci_voice_done"] = digest
    try:
        samples = decode_wav(data)
    except AudioError as e:
        st.warning(str(e))
        return None
    finally:
        del data
    with st.spinner("Đang nghe (lần đầu mất khoảng 30 giây để nạp mô hình)..."):
        text = _transcriber()(samples)
    if not text:
        st.warning("Mình chưa nghe rõ, bạn nói lại hoặc gõ chữ giúp mình nhé.")
    return text or None


def voice_reply(store, patient, session_id):
    """Khi trợ lý đang đợi trả lời câu hỏi chủ động: ô ghi âm + nút đọc to câu hỏi. Chữ nghe được hiện trong ô để
    người dùng sửa rồi bấm Gửi (Whisper có thể "bịa" câu khi gặp tiếng ồn, nên không gửi thẳng). Trả về câu đã
    bấm Gửi, hoặc None."""
    if _pending_topic(store, patient["id"], session_id) is None:
        st.session_state.pop(HEARD, None)
        return None
    with st.container(border=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        audio = c1.audio_input("Hoặc trả lời bằng giọng nói", key="ci_voice")
        opener = _opener(store, session_id)
        if opener:
            with c2:
                _speak_button(opener)
        if audio is not None:
            text = _transcribe_new(audio)
            if text:
                n = st.session_state.get("ci_heard_n", 0) + 1
                st.session_state["ci_heard_n"] = n
                st.session_state[HEARD] = {"n": n, "text": text}
        heard = st.session_state.get(HEARD)
        if not heard:
            return None
        n = heard["n"]
        edited = st.text_input("Mình nghe được như sau, sửa nếu sai rồi bấm Gửi:", value=heard["text"],
                               key=f"ci_heard_text_{n}")
        b1, b2 = st.columns(2)
        send = b1.button("Gửi", type="primary", key=f"ci_heard_send_{n}")
        if b2.button("Bỏ", key=f"ci_heard_drop_{n}"):
            st.session_state.pop(HEARD, None)
            st.rerun()
    if send and edited.strip():
        st.session_state.pop(HEARD, None)
        return edited.strip()
    return None
