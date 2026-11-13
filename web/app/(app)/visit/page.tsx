"use client";

import { useEffect, useState } from "react";
import { ErrorText, Notice } from "@/components/Notice";
import { api, fmtDate, nowLocalVN, type Appointment, type Question } from "@/lib/api";
import { usePatient } from "@/lib/session";

function daysUntil(iso: string) {
  const today = new Date(`${nowLocalVN().slice(0, 10)}T00:00:00Z`).getTime();
  return Math.round((new Date(`${iso}T00:00:00Z`).getTime() - today) / 86400000);
}

export default function VisitPage() {
  const patient = usePatient();
  const [appt, setAppt] = useState<Appointment>(null);
  const [date, setDate] = useState("");
  const [place, setPlace] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [newQ, setNewQ] = useState("");
  const [days, setDays] = useState(28);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([api.appointment(patient.id), api.questions(patient.id)])
      .then(([a, q]) => {
        setAppt(a);
        setDate(a?.date ?? "");
        setPlace(a?.place ?? "");
        setQuestions(q);
      })
      .catch((e) => setError(e.message));
  }, [patient.id]);

  async function saveAppt(e: React.FormEvent) {
    e.preventDefault();
    try {
      setAppt(await api.setAppointment(patient.id, date, place.trim()));
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function addQuestion(e: React.FormEvent) {
    e.preventDefault();
    if (!newQ.trim()) return;
    try {
      const q = await api.addQuestion(patient.id, newQ);
      setQuestions((xs) => [...xs, q]);
      setNewQ("");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function done(id: number) {
    try {
      await api.questionDone(patient.id, id);
      setQuestions((xs) => xs.filter((q) => q.id !== id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.visitReport(patient.id, days);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tom_tat_tai_kham_${nowLocalVN().slice(0, 10).replaceAll("-", "")}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const left = appt ? daysUntil(appt.date) : null;
  return (
    <>
      <div className="page-title">
        <h1>Tái khám</h1>
        <p>Chuẩn bị cho buổi gặp bác sĩ: lịch hẹn, câu muốn hỏi, và bản tóm tắt một trang.</p>
      </div>
      <ErrorText error={error} />

      <form className="card stack" onSubmit={saveAppt}>
        <h2 style={{ margin: 0 }}>Lịch tái khám</h2>
        {appt && (
          <p className="small muted" style={{ margin: 0 }}>
            Lịch hiện tại: {fmtDate(appt.date)}{appt.place ? ` tại ${appt.place}` : ""}
            {left !== null && (left > 0 ? ` · còn ${left} ngày` : left === 0 ? " · hôm nay" : " · đã qua")}
          </p>
        )}
        <div className="row">
          <label>Ngày<input type="date" required value={date} onChange={(e) => { setDate(e.target.value); setSaved(false); }} /></label>
          <label style={{ flex: "2 1 200px" }}>Nơi khám
            <input value={place} maxLength={200} placeholder="vd Bệnh viện Bạch Mai"
                   onChange={(e) => { setPlace(e.target.value); setSaved(false); }} />
          </label>
        </div>
        <button className="btn-primary" disabled={!date}>Lưu lịch</button>
        {saved && <Notice level="success">Đã lưu lịch tái khám.</Notice>}
      </form>

      <section className="card">
        <h2>Câu hỏi muốn hỏi bác sĩ</h2>
        <p className="small muted">Ghi lại ngay khi nghĩ ra; tới hôm khám các câu này nằm sẵn trong bản tóm tắt.</p>
        {questions.length > 0 && (
          <ul className="list">
            {questions.map((q) => (
              <li key={q.id}>
                <div className="main">{q.text}</div>
                <button className="btn-small" style={{ flex: "0 0 auto" }} onClick={() => done(q.id)}>Đã hỏi</button>
              </li>
            ))}
          </ul>
        )}
        <form className="row" onSubmit={addQuestion} style={{ marginTop: 10 }}>
          <label style={{ flex: "3 1 220px" }}>
            Câu hỏi mới
            <input value={newQ} maxLength={500} placeholder="vd Sáng hay bị hạ đường huyết, có cần đổi giờ uống thuốc?"
                   onChange={(e) => setNewQ(e.target.value)} />
          </label>
          <button style={{ flex: "0 0 auto" }} disabled={!newQ.trim()}>Thêm</button>
        </form>
      </section>

      <section className="card stack">
        <h2 style={{ margin: 0 }}>Bản tóm tắt mang đi khám</h2>
        <p className="small muted" style={{ margin: 0 }}>
          Một trang A4: đường huyết theo thời điểm đo, biểu đồ, huyết áp, cân nặng, xét nghiệm, thuốc, câu hỏi. In ra hoặc
          mở trên điện thoại cho bác sĩ xem.
        </p>
        <div className="segmented" role="group" aria-label="Khoảng thời gian tóm tắt" style={{ alignSelf: "flex-start" }}>
          {[14, 28, 90].map((d) => (
            <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d} ngày</button>
          ))}
        </div>
        <button className="btn-primary" onClick={download} disabled={busy}>{busy ? "Đang tạo..." : "Tải PDF"}</button>
      </section>
    </>
  );
}
