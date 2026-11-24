"use client";

import { useState } from "react";
import { api, CONTEXTS, type Context, type SpokenReading } from "@/lib/api";
import { ErrorText } from "./Notice";

/** Thẻ xác nhận số đo đọc được từ câu trả lời cho câu hỏi chủ động: chỉ lưu khi người dùng bấm Lưu. */
export function CheckinCard({ patientId, sessionId, reading, measuredAt, onDone }: {
  patientId: number;
  sessionId: number;
  reading: SpokenReading;
  measuredAt: string;
  onDone: (reply: string, saved: boolean) => void;
}) {
  const [context, setContext] = useState<Context>((reading.kind === "glucose" && reading.context) || "random");
  const [alt, setAlt] = useState(false);
  // giờ đo dạng ô datetime-local, theo giờ Việt Nam (API trả ISO kèm +07:00)
  const [when, setWhen] = useState(measuredAt.slice(0, 16));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.checkinSave(patientId, {
        session_id: sessionId, reading, measured_at: `${when}:00+07:00`,
        context: reading.kind === "glucose" ? context : undefined, use_alternative: alt,
      });
      onDone(r.reply, true);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      onDone((await api.checkinCancel(patientId, sessionId)).reply, false);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="card stack" role="group" aria-label="Xác nhận số đo">
      <b>Mình ghi vào nhật ký như thế này nhé?</b>
      {reading.kind === "glucose" && reading.alternative ? (
        <div className="chips" role="group" aria-label="Bạn định gõ số nào?">
          <button type="button" className="chip" aria-pressed={!alt} onClick={() => setAlt(false)}>{reading.summary}</button>
          <button type="button" className="chip" aria-pressed={alt} onClick={() => setAlt(true)}>{reading.alternative.summary}</button>
        </div>
      ) : (
        <div>{reading.summary}</div>
      )}
      {reading.kind === "glucose" && (
        <div className="chips" role="group" aria-label="Thời điểm đo">
          {(Object.keys(CONTEXTS) as Context[]).map((c) => (
            <button type="button" key={c} className="chip" aria-pressed={context === c} onClick={() => setContext(c)}>
              {CONTEXTS[c]}
            </button>
          ))}
        </div>
      )}
      <label>
        Ngày giờ đo
        <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
      </label>
      <div className="row">
        <button className="btn-primary" disabled={busy || !when} onClick={save}>Lưu vào nhật ký</button>
        <button className="btn-ghost" disabled={busy} onClick={cancel}>Không đúng</button>
      </div>
      <ErrorText error={error} />
    </div>
  );
}
