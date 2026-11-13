"use client";

import { useCallback, useEffect, useState } from "react";
import { GlucoseChart } from "@/components/GlucoseChart";
import { GlucoseForm } from "@/components/GlucoseForm";
import { ErrorText, Notice } from "@/components/Notice";
import { api, CONTEXTS, fmtDate, fmtMmol, fmtTime, nowLocalVN, parseNum, vnIso,
         type Context, type Lab, type Reading, type Summary } from "@/lib/api";
import { usePatient } from "@/lib/session";

const PERIODS = [7, 14, 30, 90];
type Tab = "glucose" | "body" | "labs";

export default function JournalPage() {
  const patient = usePatient();
  const [tab, setTab] = useState<Tab>("glucose");
  const [days, setDays] = useState(14);
  return (
    <>
      <div className="page-title">
        <h1>Nhật ký</h1>
      </div>
      <div className="row" style={{ marginBottom: 14, alignItems: "center" }}>
        <div className="segmented" role="group" aria-label="Loại số liệu" style={{ flex: "0 1 auto" }}>
          <button aria-pressed={tab === "glucose"} onClick={() => setTab("glucose")}>Đường huyết</button>
          <button aria-pressed={tab === "body"} onClick={() => setTab("body")}>Huyết áp, cân nặng</button>
          <button aria-pressed={tab === "labs"} onClick={() => setTab("labs")}>Xét nghiệm</button>
        </div>
        {tab !== "labs" && (
          <div className="segmented" role="group" aria-label="Khoảng thời gian" style={{ flex: "0 0 auto" }}>
            {PERIODS.map((d) => (
              <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d} ngày</button>
            ))}
          </div>
        )}
      </div>
      {tab === "glucose" && <GlucoseTab pid={patient.id} days={days} />}
      {tab === "body" && <BodyTab pid={patient.id} days={days} />}
      {tab === "labs" && <LabsTab pid={patient.id} />}
    </>
  );
}

function useReadings(pid: number, days: number, kind?: string) {
  const [rows, setRows] = useState<Reading[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const [r, s] = await Promise.all([api.readings(pid, days, kind), api.summary(pid, days)]);
      setRows(r);
      setSummary(s);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [pid, days, kind]);
  useEffect(() => {
    load();
  }, [load]);
  const remove = async (rid: number) => {
    if (!window.confirm("Xoá lần ghi này?")) return;
    try {
      await api.deleteReading(pid, rid);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return { rows, summary, error, load, remove };
}

function DeleteButton({ onClick }: { onClick: () => void }) {
  return <button className="btn-ghost btn-small" onClick={onClick} aria-label="Xoá lần ghi">Xoá</button>;
}

function GlucoseTab({ pid, days }: { pid: number; days: number }) {
  const { rows, summary, error, load, remove } = useReadings(pid, days, "glucose");
  const [adding, setAdding] = useState(false);
  const g = summary?.glucose;
  const today = nowLocalVN().slice(0, 10);
  return (
    <>
      <ErrorText error={error} />
      <section className="card">
        <div className="row" style={{ alignItems: "center", marginBottom: adding ? 12 : 0 }}>
          <h2 style={{ margin: 0 }}>Ghi thêm</h2>
          <span className="spacer" />
          <button className="btn-small" style={{ flex: "0 0 auto" }} onClick={() => setAdding(!adding)} aria-expanded={adding}>
            {adding ? "Đóng" : "Mở"}
          </button>
        </div>
        {adding && <GlucoseForm patientId={pid} onSaved={load} />}
      </section>
      {summary && g && (
        <section className="card">
          {g.n ? (
            <>
              <GlucoseChart series={summary.series} days={days} endDate={today} />
              <p className="small muted" style={{ marginTop: 10 }}>
                {g.n} lần đo trong {g.days_measured}/{days} ngày · {g.in_target_pct}% trong mục tiêu · hạ đường huyết {g.hypo} lần
                · rất cao {g.very_high} lần
              </p>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Đo lúc</th><th>Số lần</th><th>Trung bình</th><th>Thấp – cao</th><th>Trong mục tiêu</th></tr></thead>
                  <tbody>
                    {Object.entries(g.by_context).map(([c, v]) => (
                      <tr key={c}>
                        <td>{CONTEXTS[c as Context]}</td><td>{v.n}</td><td>{fmtMmol(v.mean_mmol)}</td>
                        <td>{fmtMmol(v.min_mmol)} – {fmtMmol(v.max_mmol)}</td><td>{v.in_target_pct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted">Chưa có lần đo nào trong {days} ngày qua.</p>
          )}
        </section>
      )}
      {rows.length > 0 && (
        <section className="card">
          <h2>Các lần đo (mmol/L)</h2>
          <ul className="list">
            {rows.map((r) => (
              <li key={r.id}>
                <span className="num" style={{ width: 44 }}>{fmtMmol(r.mmol)}</span>
                <div className="main">
                  <div>{r.context_text} <span className={`badge st-${r.status}`}>{r.status_text}</span></div>
                  <div className="small muted">{fmtTime(r.measured_at)}{r.note ? ` · ${r.note}` : ""}</div>
                </div>
                <DeleteButton onClick={() => remove(r.id)} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function BodyTab({ pid, days }: { pid: number; days: number }) {
  const { rows, summary, error, load, remove } = useReadings(pid, days);
  const body = rows.filter((r) => r.kind !== "glucose");
  const [sys, setSys] = useState("");
  const [dia, setDia] = useState("");
  const [kg, setKg] = useState("");
  const [msg, setMsg] = useState<{ level: "success" | "warning" | "error" | "info"; text: string; advice?: string } | null>(null);

  async function saveBp(e: React.FormEvent) {
    e.preventDefault();
    const s = parseNum(sys), d = parseNum(dia);
    if (s === null || d === null) return setMsg({ level: "error", text: "Nhập đủ hai số huyết áp, ví dụ 125 và 80." });
    try {
      const r = await api.addBp(pid, { systolic: Math.round(s), diastolic: Math.round(d), measured_at: vnIso(nowLocalVN()) });
      setMsg({ level: r.status === "in_target" ? "success" : r.status === "very_high" ? "error" : "info",
               text: `Đã lưu ${Math.round(s)}/${Math.round(d)} mmHg: ${r.status_text} (mục tiêu dưới 130/80).`,
               advice: r.advice ?? undefined });
      setSys("");
      setDia("");
      load();
    } catch (err) {
      setMsg({ level: "error", text: (err as Error).message });
    }
  }

  async function saveKg(e: React.FormEvent) {
    e.preventDefault();
    const v = parseNum(kg);
    if (v === null) return setMsg({ level: "error", text: "Nhập cân nặng, ví dụ 62,5." });
    try {
      await api.addWeight(pid, { kg: v, measured_at: vnIso(nowLocalVN()) });
      setMsg({ level: "success", text: `Đã lưu ${v} kg.` });
      setKg("");
      load();
    } catch (err) {
      setMsg({ level: "error", text: (err as Error).message });
    }
  }

  return (
    <>
      <ErrorText error={error} />
      <div className="row" style={{ alignItems: "stretch" }}>
        <form className="card stack" onSubmit={saveBp} style={{ marginBottom: 0 }}>
          <h2 style={{ margin: 0 }}>Huyết áp</h2>
          <div className="row">
            <label>Tâm thu<input inputMode="numeric" placeholder="125" value={sys} onChange={(e) => setSys(e.target.value)} /></label>
            <label>Tâm trương<input inputMode="numeric" placeholder="80" value={dia} onChange={(e) => setDia(e.target.value)} /></label>
          </div>
          <button className="btn-primary">Lưu huyết áp</button>
        </form>
        <form className="card stack" onSubmit={saveKg} style={{ marginBottom: 0 }}>
          <h2 style={{ margin: 0 }}>Cân nặng</h2>
          <label>Kg<input inputMode="decimal" placeholder="62,5" value={kg} onChange={(e) => setKg(e.target.value)} /></label>
          <button className="btn-primary">Lưu cân nặng</button>
        </form>
      </div>
      <div style={{ height: 14 }} />
      {msg && <Notice level={msg.level}>{msg.text}{msg.advice && <p>{msg.advice}</p>}</Notice>}
      {summary && (summary.bp || summary.weight) && (
        <section className="card small">
          {summary.bp && (
            <p>Huyết áp trung bình {Math.round(summary.bp.systolic)}/{Math.round(summary.bp.diastolic)} mmHg qua {summary.bp.n} lần
              đo; {summary.bp.above_target} lần từ 130/80 trở lên.</p>
          )}
          {summary.weight && (
            <p>Cân nặng {summary.weight.first.toFixed(1)} → {summary.weight.last.toFixed(1)} kg
              ({summary.weight.delta >= 0 ? "+" : ""}{summary.weight.delta.toFixed(1)} kg).</p>
          )}
        </section>
      )}
      {body.length > 0 && (
        <section className="card">
          <ul className="list">
            {body.map((r) => (
              <li key={r.id}>
                <span className="num" style={{ minWidth: 76 }}>{r.kind === "bp" ? `${r.systolic}/${r.diastolic}` : `${r.kg} kg`}</span>
                <div className="main">
                  <div>{r.kind === "bp" ? "Huyết áp" : "Cân nặng"} {r.status && <span className={`badge st-${r.status}`}>{r.status_text}</span>}</div>
                  <div className="small muted">{fmtTime(r.measured_at)}</div>
                </div>
                <DeleteButton onClick={() => remove(r.id)} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function LabsTab({ pid }: { pid: number }) {
  const [labs, setLabs] = useState<Lab[]>([]);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ level: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    api.labs(pid).then(setLabs).catch((e) => setMsg({ level: "error", text: e.message }));
  }, [pid]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file && !text.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = file ? await api.labsFromFile(pid, file) : await api.labsFromText(pid, text);
      setLabs(r.labs);
      setMsg({ level: "success", text: `Đã nhập ${r.imported.length} chỉ số.` });
      setText("");
      setFile(null);
    } catch (err) {
      setMsg({ level: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card">
        <h2>Kết quả đã nhập</h2>
        {labs.length ? (
          <ul className="list">
            {[...labs].reverse().map((l) => (
              <li key={l.id}>
                <span className="num" style={{ minWidth: 76 }}>{l.value} {l.unit}</span>
                <div className="main">
                  <div>{l.label}</div>
                  <div className="small muted">{fmtDate(l.created_at)} · {l.assessment}</div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Chưa có kết quả.</p>
        )}
      </section>
      <form className="card stack" onSubmit={submit}>
        <h2 style={{ margin: 0 }}>Nhập phiếu xét nghiệm</h2>
        <label>
          Chụp ảnh hoặc chọn file (.jpg, .png, .pdf, .txt; tối đa 10 MB)
          <input type="file" accept="image/*,.pdf,.txt,.csv,.json" capture="environment"
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label>
          Hoặc gõ kết quả
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={"HbA1c: 6.8 %\nGlucose lúc đói: 7.4 mmol/L"} />
        </label>
        <button className="btn-primary" disabled={busy || (!file && !text.trim())}>{busy ? "Đang đọc..." : "Nhập kết quả"}</button>
        {msg && <Notice level={msg.level}>{msg.text}</Notice>}
        <p className="small muted">Hỗ trợ HbA1c, đường huyết lúc đói, đường huyết 2 giờ (OGTT), đường huyết bất kỳ. Đây là đối
          chiếu với ngưỡng tham khảo ADA 2024, không phải chẩn đoán.</p>
      </form>
    </>
  );
}
