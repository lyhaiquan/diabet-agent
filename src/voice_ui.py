"""Trò chuyện rảnh tay bằng giọng nói trên trang Tư vấn (giống chế độ giọng nói của ChatGPT).

Một nút micro to ở giữa. Bấm một lần để bắt đầu, sau đó:
  nghe -> tự nhận ra lúc người dùng nói xong (đủ 0,8 giây im lặng) -> gửi đoạn ghi âm WAV 16 kHz cho Python
  -> Python nhận dạng (PhoWhisper), trả lời (pipeline tư vấn hoặc trợ lý chủ động hỏi), đọc câu trả lời (Piper)
  -> trình duyệt phát câu trả lời -> nghe tiếp lượt sau.
Bấm khi trợ lý đang nói: ngắt và nghe luôn. Bấm khi đang nghe: kết thúc.

Thành phần viết bằng Streamlit Custom Components v2 (chạy trong trang chính, không trong iframe, nên dùng được micro và
phát âm thanh ngay sau cú bấm đầu). Phát hiện tiếng nói bằng năng lượng (RMS) so với mức ồn đo trong 0,4 giây đầu;
không gửi gì khi chỉ có tiếng ồn, vì PhoWhisper "bịa" câu khi gặp im lặng. Trong lúc trợ lý nói thì không thu âm, để loa
không lọt vào micro. Âm thanh không được lưu.
"""
import streamlit as st

_HTML = """
<div class="vc">
  <button class="vc-btn" type="button" aria-label="Trò chuyện bằng giọng nói">
    <span class="vc-ring"></span>
    <svg viewBox="0 0 24 24" width="46" height="46" fill="none" stroke="currentColor" stroke-width="1.8"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3"></rect><path d="M5 11a7 7 0 0 0 14 0M12 18v3"></path>
    </svg>
  </button>
  <div class="vc-status">Bấm để bắt đầu trò chuyện</div>
  <div class="vc-note"></div>
</div>
"""

_CSS = """
.vc { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 18px 0 8px; }
.vc-btn { position: relative; width: 128px; height: 128px; border-radius: 50%; border: none; cursor: pointer;
  background: var(--st-primary-color); color: #fff; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 24px rgba(0,0,0,.25); transition: transform .15s; }
.vc-btn:active { transform: scale(.96); }
.vc-ring { position: absolute; inset: 0; border-radius: 50%; border: 4px solid var(--st-primary-color);
  opacity: 0; transition: transform .08s linear, opacity .2s; pointer-events: none; }
.vc[data-phase="listening"] .vc-ring { opacity: .55; }
.vc[data-phase="thinking"] .vc-btn { animation: vc-pulse 1.2s ease-in-out infinite; }
.vc[data-phase="speaking"] .vc-btn { background: #2e7d6b; }
.vc[data-phase="idle"] .vc-btn { opacity: .9; }
@keyframes vc-pulse { 50% { transform: scale(.92); opacity: .7; } }
.vc-status { font-size: 1.05rem; color: var(--st-text-color); text-align: center; }
.vc-note { font-size: .85rem; color: var(--st-text-color); opacity: .7; text-align: center; max-width: 520px; }
"""

_JS = """
const STATE = new WeakMap();
const TARGET_RATE = 16000;
const END_SILENCE_MS = 800, MAX_MS = 30000, PREROLL_MS = 300, CALIB_MS = 400, MIN_SPEECH_MS = 250;
const LABEL = {
  idle: "Bấm để bắt đầu trò chuyện",
  listening: "Đang nghe… bạn cứ nói, nói xong mình tự gửi (bấm để kết thúc)",
  thinking: "Đang suy nghĩ…",
  speaking: "Đang trả lời… (bấm để ngắt và nói tiếp)",
};

function b64FromBytes(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

function wavB64(chunks, rate) {
  let n = 0; for (const c of chunks) n += c.length;
  const pcm = new Float32Array(n); let o = 0; for (const c of chunks) { pcm.set(c, o); o += c.length; }
  const outLen = Math.floor(n * TARGET_RATE / rate);  // hạ mẫu xuống 16 kHz (nội suy tuyến tính)
  const buf = new ArrayBuffer(44 + outLen * 2), v = new DataView(buf);
  const w = (p, s) => { for (let i = 0; i < s.length; i++) v.setUint8(p + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + outLen * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, TARGET_RATE, true);
  v.setUint32(28, TARGET_RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, outLen * 2, true);
  for (let i = 0; i < outLen; i++) {
    const x = i * rate / TARGET_RATE, j = Math.floor(x), f = x - j;
    const a = pcm[j] || 0, b = pcm[Math.min(j + 1, n - 1)] || 0;
    const s = Math.max(-1, Math.min(1, a + (b - a) * f));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return { b64: b64FromBytes(new Uint8Array(buf)), seconds: outLen / TARGET_RATE };
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".vc");
  const btn = parentElement.querySelector(".vc-btn");
  const ring = parentElement.querySelector(".vc-ring");
  const status = parentElement.querySelector(".vc-status");
  const note = parentElement.querySelector(".vc-note");
  if (!root || !btn) return;

  let st = STATE.get(parentElement);
  if (!st) {
    st = { active: false, phase: "idle", lastReply: null, chunks: [], pre: [], speechMs: 0, silenceMs: 0,
           totalMs: 0, calibMs: 0, noise: 0, noiseN: 0, audio: null };
    STATE.set(parentElement, st);
  }

  const setPhase = (p, msg) => {
    st.phase = p; root.dataset.phase = p; status.textContent = LABEL[p];
    if (msg !== undefined) note.textContent = msg;
    if (p !== "listening") ring.style.transform = "scale(1)";
  };

  const resetCapture = () => { st.chunks = []; st.pre = []; st.speechMs = 0; st.silenceMs = 0; st.totalMs = 0; };

  const stopAll = () => {
    st.active = false;
    if (st.audio) { st.audio.pause(); st.audio = null; }
    if (st.proc) { st.proc.disconnect(); st.proc.onaudioprocess = null; }
    if (st.src) st.src.disconnect();
    if (st.stream) st.stream.getTracks().forEach(t => t.stop());
    if (st.ctx) st.ctx.close();
    st.proc = st.src = st.stream = st.ctx = null;
    setPhase("idle", "");
  };

  const listen = () => { resetCapture(); setPhase("listening"); };

  const onAudio = (e) => {
    if (!st.active || st.phase !== "listening") return;
    const x = new Float32Array(e.inputBuffer.getChannelData(0));
    const ms = 1000 * x.length / st.ctx.sampleRate;
    let sum = 0; for (let i = 0; i < x.length; i++) sum += x[i] * x[i];
    const rms = Math.sqrt(sum / x.length);
    if (st.calibMs < CALIB_MS) {  // đo mức ồn nền lúc vừa bật micro
      st.calibMs += ms; st.noise = (st.noise * st.noiseN + rms) / (st.noiseN + 1); st.noiseN++;
      return;
    }
    const thr = Math.max(0.012, st.noise * 3);
    ring.style.transform = "scale(" + (1 + Math.min(0.45, rms * 6)) + ")";
    if (st.speechMs === 0) {
      st.pre.push(x); let preMs = st.pre.length * ms;
      while (preMs > PREROLL_MS && st.pre.length > 1) { st.pre.shift(); preMs -= ms; }
      if (rms >= thr) { st.chunks = st.pre.slice(); st.pre = []; st.speechMs = ms; st.silenceMs = 0; st.totalMs = ms; }
      else if (rms < thr * 0.6) st.noise = st.noise * 0.98 + rms * 0.02;  // ồn nền thay đổi chậm
      return;
    }
    st.chunks.push(x); st.totalMs += ms;
    if (rms >= thr) { st.speechMs += ms; st.silenceMs = 0; } else st.silenceMs += ms;
    if (st.silenceMs >= END_SILENCE_MS || st.totalMs >= MAX_MS) {
      const enough = st.speechMs >= MIN_SPEECH_MS;
      const chunks = st.chunks; resetCapture();
      if (!enough) return;  // tiếng động ngắn (ho, gõ bàn): bỏ qua, nghe tiếp
      const wav = wavB64(chunks, st.ctx.sampleRate);
      setPhase("thinking", "");
      setTriggerValue("utterance", { wav: wav.b64, seconds: wav.seconds, at: Date.now() });
    }
  };

  const start = async () => {
    try {
      st.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (err) {
      setPhase("idle", "Không mở được micro: " + (err && err.name === "NotAllowedError"
        ? "trình duyệt đang chặn. Bấm biểu tượng ổ khoá cạnh địa chỉ trang, cho phép Micro rồi bấm lại."
        : (err && err.message) || err));
      return;
    }
    st.ctx = new (window.AudioContext || window.webkitAudioContext)();
    st.src = st.ctx.createMediaStreamSource(st.stream);
    st.proc = st.ctx.createScriptProcessor(2048, 1, 1);
    st.proc.onaudioprocess = onAudio;
    st.src.connect(st.proc); st.proc.connect(st.ctx.destination);
    st.active = true; st.calibMs = 0; st.noise = 0; st.noiseN = 0;
    listen();
  };

  btn.onclick = () => {
    if (!st.active) { start(); return; }
    if (st.phase === "speaking") { if (st.audio) { st.audio.pause(); st.audio = null; } listen(); return; }
    if (st.phase === "listening") { stopAll(); return; }
  };

  // Python trả lời: phát âm thanh (nếu có), xong thì nghe tiếp
  const reply = data && data.reply;
  if (reply && reply.id !== st.lastReply) {
    st.lastReply = reply.id;
    if (st.active) {
      if (reply.audio) {
        setPhase("speaking", reply.note || "");
        if (st.audio) st.audio.pause();
        st.audio = new Audio("data:audio/wav;base64," + reply.audio);
        st.audio.onended = () => { st.audio = null; if (st.active) listen(); };
        st.audio.play().catch(() => { st.audio = null; if (st.active) listen(); });
      } else {
        listen(); note.textContent = reply.note || "";
      }
    }
  }
  if (!st.active && st.phase === "idle" && data && data.hint) note.textContent = data.hint;
  return () => stopAll();
}
"""

_COMPONENT = st.components.v2.component("diacare_voice_chat", html=_HTML, css=_CSS, js=_JS)


def voice_chat(reply=None, hint=None, key="voice_chat"):
    """Gắn nút micro. `reply` = {"id", "audio" (WAV base64 hoặc None), "note"}: đổi `id` thì trình duyệt phát âm thanh
    rồi nghe tiếp. Trả về đoạn ghi âm vừa nói xong ({"wav" base64, "seconds"}) hoặc None."""
    res = _COMPONENT(data={"reply": reply, "hint": hint}, key=key, on_utterance_change=lambda: None)
    return getattr(res, "utterance", None)
