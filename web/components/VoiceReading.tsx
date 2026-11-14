"use client";

import { useState } from "react";
import { api, CONTEXTS, guessContext, nowLocalVN, vnIso, type Context, type SpokenReading, type Transcript } from "@/lib/api";
import { MicButton } from "./MicButton";
import { Notice } from "./Notice";

/** Nói số đo ("đường huyết lúc đói sáu phẩy tám") -> hiện chữ nghe được -> người dùng bấm xác nhận mới lưu. */
export function VoiceReading({ patientId, onSaved }: { patientId: number; onSaved: () => void }) {
  const [heard, setHeard] = useState<Transcript | null>(null);
  const [context, setContext] = useState<Context>(guessContext);
  const [msg, setMsg] = useState<{ level: "success" | "error" | "warning" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  function onResult(t: Transcript) {
    setHeard(t);
    setMsg(null);
    if (t.reading?.kind === "glucose" && t.reading.context) setContext(t.reading.context);
  }

  async function save(r: SpokenReading, alt = false) {
    setBusy(true);
    try {
      const when = vnIso(nowLocalVN());
      if (r.kind === "glucose") {
        const v = alt && r.alternative ? r.alternative : r;
        const res = await api.addGlucose(patientId, { value: v.value, unit: v.unit, context, measured_at: when,
                                                      note: "ghi bằng giọng nói" });
        setMsg({ level: res.status === "in_target" ? "success" : res.advice_level ?? "info", text: res.message });
      } else if (r.kind === "bp") {
        const res = await api.addBp(patientId, { systolic: r.systolic, diastolic: r.diastolic, measured_at: when });
        setMsg({ level: res.status === "very_high" ? "error" : "success", text: `Đã lưu ${r.summary}: ${res.status_text}.` });
      } else {
        await api.addWeight(patientId, { kg: r.kg, measured_at: when });
        setMsg({ level: "success", text: `Đã lưu ${r.summary}.` });
      }
      setHeard(null);
      onSaved();
    } catch (e) {
      setMsg({ level: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const r = heard?.reading;
  return (
    <div className="stack">
      <div className="row" style={{ alignItems: "center" }}>
        <MicButton onResult={onResult} label="Nói số đo" />
        <span className="small muted" style={{ flex: "1 1 200px" }}>
          Ví dụ: “đường huyết lúc đói sáu phẩy tám”, “huyết áp một trăm hai mươi lăm trên tám mươi”.
        </span>
      </div>
      {heard && (
        <div className="notice notice-info" role="status">
          <div className="small">Nghe được: “{heard.text || "(không rõ)"}”</div>
          {r ? (
            <div className="stack" style={{ marginTop: 10, color: "var(--text)" }}>
              {r.kind === "glucose" && (
                <div className="chips" role="group" aria-label="Thời điểm đo">
                  {(Object.keys(CONTEXTS) as Context[]).map((c) => (
                    <button type="button" key={c} className="chip" aria-pressed={context === c} onClick={() => setContext(c)}>
                      {CONTEXTS[c]}
                    </button>
                  ))}
                </div>
              )}
              <div className="row">
                <button className="btn-primary" disabled={busy} onClick={() => save(r)}>
                  Ghi {r.summary}{r.kind === "glucose" ? `, ${CONTEXTS[context].toLowerCase()}` : ""}
                </button>
                {r.kind === "glucose" && r.alternative && (
                  <button disabled={busy} onClick={() => save(r, true)}>Ý tôi là {r.alternative.summary}</button>
                )}
                <button className="btn-ghost" onClick={() => setHeard(null)} style={{ flex: "0 0 auto" }}>Bỏ</button>
              </div>
            </div>
          ) : (
            <p>Không nghe ra số đo. Hãy nói rõ loại và con số, hoặc nhập tay ở ô bên dưới.</p>
          )}
        </div>
      )}
      {msg && <Notice level={msg.level}>{msg.text}</Notice>}
    </div>
  );
}
