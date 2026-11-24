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
from diacare.checkin import cancel_card, handle_reply, open_for_day, pending_topic, save_reading
from diacare.coach import daily_nudge
from journal_ui import _coach

CARD = "checkin_card"


def maybe_open(store, patient, session_id, diagnosed):
    """Mở lời một lần mỗi ngày cho người đã chẩn đoán (lượt hỏi giữ trong bảng checkins, xem checkin.open_for_day)."""
    if not diagnosed or session_id is None:
        return
    now = journal.now_vn()
    if store.get_checkin(patient["id"], now.date()) is not None:
        return
    coach = _coach()
    # cùng lời nhắc với tab Hôm nay: daily_nudge chỉ chọn một lần mỗi ngày (bảng coach_events)
    nudge = daily_nudge(store, coach, patient["id"], now.date())["text"] if coach is not None else None
    open_for_day(store, patient, session_id, now, nudge)


def handle_input(store, patient, session_id, text):
    """True nếu câu vừa gõ là câu trả lời cho câu hỏi chủ động và đã xử lý ở đây (số đo -> thẻ xác nhận, "chưa đo"
    -> câu soạn sẵn). False: để app.py gửi cho pipeline tư vấn như mọi câu hỏi khác."""
    r = handle_reply(store, patient, session_id, text, journal.now_vn())
    if not r["handled"]:
        st.session_state.pop(CARD, None)  # thẻ số đo cũ không còn hợp ngữ cảnh
        return False
    if r.get("card"):
        n = st.session_state.get("checkin_card_n", 0) + 1
        st.session_state["checkin_card_n"] = n
        st.session_state[CARD] = {"n": n, "reading": r["card"]["reading"], "when": r["card"]["when"].isoformat()}
    return True


def _save(store, patient, session_id, card):
    ss, n = st.session_state, card["n"]
    when = datetime.combine(ss[f"ci_date_{n}"], ss[f"ci_time_{n}"], tzinfo=journal.VN_TZ)
    _, err = save_reading(store, patient["id"], session_id, card["reading"], when, journal.now_vn(),
                          context=ss.get(f"ci_ctx_{n}"), use_alternative=ss.get(f"ci_alt_{n}") == 1)
    if err:
        ss[f"ci_err_{n}"] = err
        return
    ss.pop(CARD, None)


def _cancel(store, session_id):
    cancel_card(store, session_id)
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
    if pending_topic(store, patient["id"], session_id, journal.now_vn()) is None:
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
