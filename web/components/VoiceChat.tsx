"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { encodeWav, resample, voiceInputSupported } from "@/lib/voice";

/** Trò chuyện rảnh tay bằng giọng nói (giống chế độ giọng nói của ChatGPT), cùng cách làm với src/voice_ui.py:
 *  bấm nút micro to một lần -> nghe -> tự nhận ra lúc nói xong (0,8 giây im lặng) -> /transcribe?voice=true
 *  -> onText(câu nghe được) trả về câu cần đọc -> /tts (giọng Piper trên máy chủ) -> phát -> nghe tiếp.
 *  Bấm khi trợ lý đang nói: ngắt và nghe luôn. Bấm khi đang nghe: kết thúc. Trong lúc trợ lý nói thì không thu âm,
 *  để loa không lọt vào micro. Âm thanh không được lưu. */
type Phase = "idle" | "listening" | "thinking" | "speaking";
const LABEL: Record<Phase, string> = {
  idle: "Bấm để bắt đầu trò chuyện",
  listening: "Đang nghe… bạn cứ nói, nói xong mình tự gửi (bấm để kết thúc)",
  thinking: "Đang suy nghĩ…",
  speaking: "Đang trả lời… (bấm để ngắt và nói tiếp)",
};
const RATE = 16000;
const END_SILENCE_MS = 800, MAX_MS = 30000, PREROLL_MS = 300, CALIB_MS = 400, MIN_SPEECH_MS = 250;

type Capture = {
  ctx: AudioContext; stream: MediaStream; src: MediaStreamAudioSourceNode; proc: ScriptProcessorNode;
  chunks: Float32Array[]; pre: Float32Array[]; speechMs: number; silenceMs: number; totalMs: number;
  calibMs: number; noise: number; noiseN: number;
};

export function VoiceChat({ onText }: { onText: (text: string) => Promise<string | null> }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [note, setNote] = useState("");
  const [level, setLevel] = useState(0);
  const [supported, setSupported] = useState(true);  // kiểm tra sau khi gắn vào trang (máy chủ không có micro)
  const cap = useRef<Capture | null>(null);
  const phaseRef = useRef<Phase>("idle");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  const go = (p: Phase) => { phaseRef.current = p; setPhase(p); if (p !== "listening") setLevel(0); };

  function resetCapture() {
    const c = cap.current;
    if (c) { c.chunks = []; c.pre = []; c.speechMs = 0; c.silenceMs = 0; c.totalMs = 0; }
  }

  function listen() { resetCapture(); go("listening"); }

  function stopAll() {
    audioRef.current?.pause();
    audioRef.current = null;
    const c = cap.current;
    if (c) {
      c.proc.onaudioprocess = null;
      c.proc.disconnect(); c.src.disconnect();
      c.stream.getTracks().forEach((t) => t.stop());
      c.ctx.close();
    }
    cap.current = null;
    go("idle");
  }

  useEffect(() => { setSupported(voiceInputSupported()); }, []);
  useEffect(() => () => stopAll(), []);  // eslint-disable-line react-hooks/exhaustive-deps

  async function play(text: string) {
    try {
      const wav = await api.tts(text);
      if (!wav || !cap.current) return listen();
      const url = URL.createObjectURL(wav);
      const audio = new Audio(url);
      audioRef.current = audio;
      go("speaking");
      const done = () => { URL.revokeObjectURL(url); if (audioRef.current === audio) { audioRef.current = null; if (cap.current) listen(); } };
      audio.onended = done;
      await audio.play().catch(done);
    } catch (e) {
      setNote((e as Error).message);
      if (cap.current) listen();
    }
  }

  async function handle(chunks: Float32Array[], rate: number) {
    go("thinking");
    setNote("");
    let n = 0; for (const c of chunks) n += c.length;
    const pcm = new Float32Array(n); let o = 0; for (const c of chunks) { pcm.set(c, o); o += c.length; }
    try {
      const t = await api.transcribe(encodeWav(await resample(pcm, rate, RATE), RATE), true);
      if (!t.text) return play("Mình chưa nghe rõ, bạn nói lại giúp mình nhé.");
      setNote(`Bạn: ${t.text}`);
      const reply = await onTextRef.current(t.text);
      if (!cap.current) return;
      if (reply) await play(reply); else listen();
    } catch (e) {
      const msg = (e as Error).message;
      if (/Không nghe thấy/.test(msg)) return play("Mình chưa nghe rõ, bạn nói lại giúp mình nhé.");
      setNote(msg);
      if (cap.current) listen();
    }
  }

  function onAudio(e: AudioProcessingEvent) {
    const c = cap.current;
    if (!c || phaseRef.current !== "listening") return;
    const x = new Float32Array(e.inputBuffer.getChannelData(0));
    const ms = (1000 * x.length) / c.ctx.sampleRate;
    let sum = 0; for (let i = 0; i < x.length; i++) sum += x[i] * x[i];
    const rms = Math.sqrt(sum / x.length);
    if (c.calibMs < CALIB_MS) {  // đo mức ồn nền lúc vừa bật micro
      c.calibMs += ms; c.noise = (c.noise * c.noiseN + rms) / (c.noiseN + 1); c.noiseN++;
      return;
    }
    const thr = Math.max(0.012, c.noise * 3);
    setLevel(Math.min(1, rms * 8));
    if (c.speechMs === 0) {
      c.pre.push(x);
      let preMs = c.pre.length * ms;
      while (preMs > PREROLL_MS && c.pre.length > 1) { c.pre.shift(); preMs -= ms; }
      if (rms >= thr) { c.chunks = c.pre.slice(); c.pre = []; c.speechMs = ms; c.silenceMs = 0; c.totalMs = ms; }
      else if (rms < thr * 0.6) c.noise = c.noise * 0.98 + rms * 0.02;  // ồn nền thay đổi chậm
      return;
    }
    c.chunks.push(x); c.totalMs += ms;
    if (rms >= thr) { c.speechMs += ms; c.silenceMs = 0; } else c.silenceMs += ms;
    if (c.silenceMs >= END_SILENCE_MS || c.totalMs >= MAX_MS) {
      const enough = c.speechMs >= MIN_SPEECH_MS;
      const chunks = c.chunks;
      resetCapture();
      if (enough) handle(chunks, c.ctx.sampleRate);  // tiếng động ngắn (ho, gõ bàn): bỏ qua, nghe tiếp
    }
  }

  async function start() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (err) {
      const e = err as DOMException;
      setNote(e?.name === "NotAllowedError"
        ? "Trình duyệt đang chặn micro. Bấm biểu tượng ổ khoá cạnh địa chỉ trang, cho phép Micro rồi bấm lại."
        : `Không mở được micro: ${e?.message ?? err}`);
      return;
    }
    const ctx = new AudioContext();
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(2048, 1, 1);
    cap.current = { ctx, stream, src, proc, chunks: [], pre: [], speechMs: 0, silenceMs: 0, totalMs: 0,
                    calibMs: 0, noise: 0, noiseN: 0 };
    proc.onaudioprocess = onAudio;
    src.connect(proc); proc.connect(ctx.destination);
    setNote("");
    listen();
  }

  function click() {
    if (!cap.current) return void start();
    if (phaseRef.current === "speaking") { audioRef.current?.pause(); audioRef.current = null; return listen(); }
    if (phaseRef.current === "listening") return stopAll();
  }

  if (!supported) return <p className="small muted">Trình duyệt này không ghi âm được (cần localhost hoặc HTTPS).</p>;
  return (
    <div className="vc" data-phase={phase}>
      <button type="button" className="vc-btn" onClick={click} aria-label="Trò chuyện bằng giọng nói"
              style={{ boxShadow: phase === "listening" ? `0 0 0 ${4 + level * 18}px rgba(15, 118, 110, .25)` : undefined }}>
        <svg viewBox="0 0 24 24" width="46" height="46" fill="none" stroke="currentColor" strokeWidth="1.8"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
        </svg>
      </button>
      <div className="vc-status" aria-live="polite">{LABEL[phase]}</div>
      {note && <div className="vc-note">{note}</div>}
    </div>
  );
}
