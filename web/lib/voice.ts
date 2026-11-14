// Ghi âm ra WAV 16 kHz ngay trong trình duyệt (máy chủ không cần ffmpeg) và đọc to bằng giọng có sẵn của máy.

export const MAX_SECONDS = 60;
const RATE = 16000;

export function voiceInputSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== "undefined";
}

export type Recording = { stop: () => Promise<Blob>; cancel: () => void };

/** Bắt đầu ghi. Micro chỉ dùng được trên localhost hoặc HTTPS. */
export async function startRecording(onTick?: (seconds: number) => void, onAutoStop?: () => void): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  // ScriptProcessorNode đã cũ nhưng chạy được trên mọi trình duyệt mà không cần tệp worklet riêng
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks: Float32Array[] = [];
  let length = 0;
  node.onaudioprocess = (e) => {
    const data = new Float32Array(e.inputBuffer.getChannelData(0));
    chunks.push(data);
    length += data.length;
    onTick?.(length / ctx.sampleRate);
    if (length / ctx.sampleRate >= MAX_SECONDS) onAutoStop?.();
  };
  source.connect(node);
  node.connect(ctx.destination);

  const release = () => {
    node.disconnect();
    source.disconnect();
    stream.getTracks().forEach((t) => t.stop());
  };

  return {
    cancel: () => {
      release();
      ctx.close();
    },
    stop: async () => {
      release();
      const rate = ctx.sampleRate;
      await ctx.close();
      const merged = new Float32Array(length);
      let off = 0;
      for (const c of chunks) {
        merged.set(c, off);
        off += c.length;
      }
      return encodeWav(await resample(merged, rate, RATE), RATE);
    },
  };
}

async function resample(input: Float32Array, from: number, to: number): Promise<Float32Array> {
  if (from === to || input.length === 0) return input;
  const frames = Math.max(1, Math.round((input.length * to) / from));
  const off = new OfflineAudioContext(1, frames, to);
  const buf = off.createBuffer(1, input.length, from);
  buf.copyToChannel(input as Float32Array<ArrayBuffer>, 0);
  const src = off.createBufferSource();
  src.buffer = buf;
  src.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0);
}

/** WAV PCM 16 bit mono. */
export function encodeWav(samples: Float32Array, rate: number): Blob {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const str = (o: number, s: string) => [...s].forEach((ch, i) => view.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  str(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}

// ---- đọc to -----------------------------------------------------------------------

export function vietnameseVoice(): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  return window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith("vi")) ?? null;
}

/** Bỏ phần chỉ để nhìn (tên tệp nguồn, dấu markdown) trước khi đọc. */
export function speakableText(text: string): string {
  return text
    .replace(/\[[^\]]*\.(txt|md|pdf|json)\]/gi, "")
    .replace(/[*_#`>]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Đọc to bằng giọng tiếng Việt của máy. Trả về false nếu máy không có giọng tiếng Việt. */
export function speak(text: string, onEnd?: () => void): boolean {
  const voice = vietnameseVoice();
  if (!voice) return false;
  const synth = window.speechSynthesis;
  synth.cancel();
  const sentences = speakableText(text).match(/[^.!?\n]+[.!?]?/g) ?? [];
  sentences.forEach((s, i) => {
    const u = new SpeechSynthesisUtterance(s.trim());
    u.lang = voice.lang;
    try {
      u.voice = voice;
    } catch {
      /* một số trình duyệt chỉ nhận lang */
    }
    u.rate = 0.95; // chậm hơn một chút cho người lớn tuổi
    if (i === sentences.length - 1 && onEnd) u.onend = onEnd;
    synth.speak(u);
  });
  return true;
}

export function stopSpeaking() {
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
}

const CONSENT_KEY = "diacare.voiceConsent";
const SPEAK_KEY = "diacare.speakAnswers";

function ls(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
export const hasVoiceConsent = () => ls()?.getItem(CONSENT_KEY) === "1";
export const giveVoiceConsent = () => ls()?.setItem(CONSENT_KEY, "1");
export const getSpeakPref = () => ls()?.getItem(SPEAK_KEY) === "1";
export const setSpeakPref = (on: boolean) => ls()?.setItem(SPEAK_KEY, on ? "1" : "0");
