"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Transcript } from "@/lib/api";
import { giveVoiceConsent, hasVoiceConsent, MAX_SECONDS, startRecording, voiceInputSupported, type Recording } from "@/lib/voice";
import { Notice } from "./Notice";

type State = "idle" | "consent" | "recording" | "working";

/** Bấm để nói, bấm lần nữa để dừng. Âm thanh được chuyển thành chữ trên máy chủ rồi bỏ đi, không lưu. */
export function MicButton({ onResult, label = "Nói", compact = false }:
  { onResult: (t: Transcript) => void; label?: string; compact?: boolean }) {
  const [state, setState] = useState<State>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<Recording | null>(null);
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    setSupported(voiceInputSupported());
    return () => rec.current?.cancel();
  }, []);

  async function begin() {
    setError(null);
    try {
      rec.current = await startRecording(setSeconds, () => finish());
      setSeconds(0);
      setState("recording");
    } catch (e) {
      const name = (e as Error).name;
      setError(name === "NotAllowedError" ? "Trình duyệt chưa cho dùng micro. Bấm biểu tượng ổ khoá trên thanh địa chỉ để cho phép."
        : name === "NotFoundError" ? "Không tìm thấy micro." : "Không bật được micro.");
      setState("idle");
    }
  }

  async function finish() {
    const r = rec.current;
    if (!r) return;
    rec.current = null;
    setState("working");
    try {
      const wav = await r.stop();
      onResult(await api.transcribe(wav));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setState("idle");
    }
  }

  function click() {
    if (state === "recording") finish();
    else if (state === "idle") {
      if (hasVoiceConsent()) begin();
      else setState("consent");
    }
  }

  if (!supported) return null;
  const text = state === "recording" ? `Dừng (${Math.floor(seconds)}s/${MAX_SECONDS}s)`
    : state === "working" ? "Đang nghe..." : label;
  return (
    <>
      <button type="button" onClick={click} disabled={state === "working" || state === "consent"}
              className={state === "recording" ? "mic mic-on" : "mic"} aria-pressed={state === "recording"}
              aria-label={state === "recording" ? "Dừng ghi âm" : "Bấm để nói"} style={{ flex: "0 0 auto" }}>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" aria-hidden="true">
          <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
        </svg>
        {!compact && <span>{text}</span>}
        {compact && state === "recording" && <span>{Math.floor(seconds)}s</span>}
      </button>
      {(state === "consent" || error) && (
        // nằm trong hàng flex: chiếm trọn một dòng phía trên
        <div style={{ flexBasis: "100%", order: -1 }}>
      {state === "consent" && (
        <Notice level="info">
          Giọng nói của bạn được gửi tới máy chủ DiaCare, chuyển thành chữ rồi xoá ngay; không lưu tệp âm thanh. Chữ nghe
          được sẽ hiện ra để bạn kiểm tra trước khi gửi hoặc lưu.
          <p>
            <button type="button" className="btn-primary btn-small" onClick={() => { giveVoiceConsent(); begin(); }}>Đồng ý, bắt đầu nói</button>{" "}
            <button type="button" className="btn-ghost btn-small" onClick={() => setState("idle")}>Để sau</button>
          </p>
        </Notice>
      )}
      {error && <Notice level="error">{error}</Notice>}
        </div>
      )}
    </>
  );
}
