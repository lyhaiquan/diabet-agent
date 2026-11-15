"use client";

import { useEffect, useState } from "react";
import { ErrorText, Notice } from "@/components/Notice";
import { api, fmtMmol, parseNum, type Targets } from "@/lib/api";

/** Mục tiêu đường huyết: mặc định là mục tiêu chung ADA 2024; người dùng nhập mục tiêu riêng theo lời bác sĩ.
 *  Máy chủ kiểm tra giới hạn; ngưỡng hạ đường huyết (3,9) và rất cao (13,9) không đổi theo mục tiêu riêng. */
export function TargetsCard({ patientId }: { patientId: number }) {
  const [t, setT] = useState<Targets | null>(null);
  const [lo, setLo] = useState("");
  const [hi, setHi] = useState("");
  const [post, setPost] = useState("");
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function show(v: Targets) {
    setT(v);
    setLo(fmtMmol(v.pre_meal_mmol[0]));
    setHi(fmtMmol(v.pre_meal_mmol[1]));
    setPost(fmtMmol(v.post_meal_max_mmol));
    setNote(v.note ?? "");
  }

  useEffect(() => {
    api.targets(patientId).then(show).catch((e) => setError(e.message));
  }, [patientId]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    const [a, b, c] = [parseNum(lo), parseNum(hi), parseNum(post)];
    if (a == null || b == null || c == null) {
      setError("Hãy nhập đủ ba con số (mmol/L).");
      return;
    }
    try {
      show(await api.setTargets(patientId, { pre_meal_low: a, pre_meal_high: b, post_meal_max: c, note: note.trim() || undefined }));
      setSaved("Đã lưu mục tiêu bác sĩ đặt. Các số đo cũ được xếp lại theo mục tiêu này.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function reset() {
    setError(null);
    try {
      show(await api.clearTargets(patientId));
      setSaved("Đã quay về mục tiêu chung.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card stack">
      <h2 style={{ margin: 0 }}>Mục tiêu đường huyết</h2>
      {t && (
        <p className="small muted" style={{ margin: 0 }}>
          {t.custom ? "Đang dùng mục tiêu bác sĩ đặt" : "Đang dùng mục tiêu chung (ADA 2024)"}: trước ăn{" "}
          {fmtMmol(t.pre_meal_mmol[0])}–{fmtMmol(t.pre_meal_mmol[1])}, sau ăn dưới {fmtMmol(t.post_meal_max_mmol)} mmol/L
          {t.custom && t.note ? ` (${t.note})` : ""}. Nếu bác sĩ dặn con số khác, nhập vào đây.
        </p>
      )}
      <ErrorText error={error} />
      {saved && <Notice level="success">{saved}</Notice>}
      {!open ? (
        <button style={{ alignSelf: "flex-start" }} onClick={() => setOpen(true)} aria-expanded={false}>
          Đặt mục tiêu theo lời bác sĩ
        </button>
      ) : (
        <form className="stack" onSubmit={save}>
          <div className="row">
            <label>Trước ăn, từ
              <input inputMode="decimal" required value={lo} onChange={(e) => setLo(e.target.value)} aria-label="Cận dưới trước ăn, mmol/L" />
            </label>
            <label>Trước ăn, đến
              <input inputMode="decimal" required value={hi} onChange={(e) => setHi(e.target.value)} aria-label="Cận trên trước ăn, mmol/L" />
            </label>
            <label>Sau ăn, dưới
              <input inputMode="decimal" required value={post} onChange={(e) => setPost(e.target.value)} aria-label="Mức tối đa sau ăn, mmol/L" />
            </label>
          </div>
          <label>Ghi chú
            <input value={note} maxLength={200} placeholder="vd BS Minh dặn ngày 12/11" onChange={(e) => setNote(e.target.value)} />
          </label>
          <p className="small muted" style={{ margin: 0 }}>
            Đơn vị mmol/L. Chỉ nhập con số bác sĩ đã dặn, đừng tự nới mục tiêu. Ngưỡng hạ đường huyết (dưới 3,9) không đổi.
          </p>
          <div className="row">
            <button className="btn-primary">Lưu mục tiêu</button>
            {t?.custom && <button type="button" onClick={reset}>Dùng lại mục tiêu chung</button>}
          </div>
        </form>
      )}
    </section>
  );
}
