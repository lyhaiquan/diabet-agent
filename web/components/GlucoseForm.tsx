"use client";

import { useState } from "react";
import { api, CONTEXTS, guessContext, nowLocalVN, parseNum, vnIso, type Context, type GlucoseResult } from "@/lib/api";
import { ErrorText, Notice } from "./Notice";

const LEVEL: Record<string, "success" | "info" | "warning"> = {
  in_target: "success", above_target: "info", below_target: "info",
};

/** Ô ghi đường huyết: số lớn dễ bấm trên điện thoại, mặc định mmol/L (máy đo ở Việt Nam thường dùng). */
/** showAdvice=false: trang Hôm nay đã hiện lời khuyên này trong khung cảnh báo ở đầu trang. */
export function GlucoseForm({ patientId, onSaved, showAdvice = true }: { patientId: number; onSaved?: (r: GlucoseResult) => void; showAdvice?: boolean }) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState<"mmol/L" | "mg/dL">("mmol/L");
  const [context, setContext] = useState<Context>(guessContext);
  const [when, setWhen] = useState(nowLocalVN);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GlucoseResult | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const v = parseNum(value);
    if (v === null) {
      setError("Hãy nhập số đường huyết, ví dụ 6,5.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.addGlucose(patientId, { value: v, unit, context, measured_at: vnIso(when), note: note.trim() || undefined });
      setResult(r);
      setValue("");
      setNote("");
      setWhen(nowLocalVN());
      onSaved?.(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack" aria-label="Ghi đường huyết">
      <div className="row">
        <label style={{ flex: "2 1 160px" }}>
          Đường huyết
          <input className="big-input" inputMode="decimal" autoComplete="off" placeholder={unit === "mmol/L" ? "6,5" : "117"}
                 value={value} onChange={(e) => setValue(e.target.value)} aria-describedby="unit-hint" />
        </label>
        <label style={{ flex: "1 1 110px" }}>
          Đơn vị
          <select value={unit} onChange={(e) => setUnit(e.target.value as "mmol/L" | "mg/dL")}>
            <option>mmol/L</option>
            <option>mg/dL</option>
          </select>
        </label>
      </div>
      <div>
        <div className="small muted" style={{ marginBottom: 6 }}>Đo lúc</div>
        <div className="chips" role="group" aria-label="Thời điểm đo">
          {(Object.keys(CONTEXTS) as Context[]).map((c) => (
            <button type="button" key={c} className="chip" aria-pressed={context === c} onClick={() => setContext(c)}>
              {CONTEXTS[c]}
            </button>
          ))}
        </div>
      </div>
      <div className="row">
        <label>
          Thời gian đo
          <input type="datetime-local" value={when} max={nowLocalVN()} onChange={(e) => setWhen(e.target.value)} />
        </label>
        <label>
          Ghi chú
          <input value={note} maxLength={300} placeholder="vd ăn phở sáng" onChange={(e) => setNote(e.target.value)} />
        </label>
      </div>
      <button className="btn-primary" disabled={busy}>{busy ? "Đang lưu..." : "Lưu"}</button>
      <ErrorText error={error} />
      {result && (
        <Notice level={LEVEL[result.status] ?? "warning"}>
          {result.message}
          {showAdvice && result.advice && <p>{result.advice}</p>}
        </Notice>
      )}
    </form>
  );
}
