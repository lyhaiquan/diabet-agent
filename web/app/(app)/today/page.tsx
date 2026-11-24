"use client";

import { useCallback, useEffect, useState } from "react";
import { GlucoseChart } from "@/components/GlucoseChart";
import { GlucoseForm } from "@/components/GlucoseForm";
import { VoiceReading } from "@/components/VoiceReading";
import { ErrorText, Notices } from "@/components/Notice";
import { DailyNudge } from "@/components/DailyNudge";
import { Reminders } from "@/components/Reminders";
import { api, fmtDate, fmtMmol, fmtTime, type Summary, type Today } from "@/lib/api";
import { usePatient } from "@/lib/session";

export default function TodayPage() {
  const patient = usePatient();
  const [today, setToday] = useState<Today | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([api.today(patient.id), api.summary(patient.id, 14)]);
      setToday(t);
      setSummary(s);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [patient.id]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <div className="page-title">
        <h1>Chào {patient.name}</h1>
        <p>{today ? fmtDate(today.date) : ""}</p>
      </div>
      <ErrorText error={error} />
      {today && <Notices items={[...today.alerts, ...today.reminders]} />}
      {today?.nudge && <DailyNudge patientId={patient.id} nudge={today.nudge} />}

      <section className="card">
        <h2>Ghi đường huyết</h2>
        <VoiceReading patientId={patient.id} onSaved={load} />
        <div style={{ height: 14 }} />
        <GlucoseForm patientId={patient.id} onSaved={load} showAdvice={false} />
      </section>

      {today && summary && (
        <>
          <h2 style={{ margin: "18px 0 10px" }}>14 ngày qua</h2>
          <div className="stats">
            <div className="stat">
              <div className="label">Lần đo gần nhất</div>
              <div className="value">{fmtMmol(today.last_glucose?.mmol)}</div>
              <div className="sub">{today.last_glucose ? `${today.last_glucose.context_text}, ${fmtTime(today.last_glucose.measured_at)}` : "chưa có"}</div>
            </div>
            <div className="stat">
              <div className="label">Trong mục tiêu</div>
              <div className="value">{today.in_target_pct_14d == null ? "–" : `${today.in_target_pct_14d}%`}</div>
              <div className="sub">{summary.glucose.n} lần đo</div>
            </div>
            <div className="stat">
              <div className="label">TB lúc đói</div>
              <div className="value">{fmtMmol(today.fasting_mean_mmol_14d)}</div>
              <div className="sub">
                {today.targets.custom ? "bác sĩ đặt " : "mục tiêu "}
                {fmtMmol(today.targets.pre_meal_mmol[0])}–{fmtMmol(today.targets.pre_meal_mmol[1])}
              </div>
            </div>
            <div className="stat">
              <div className="label">HbA1c gần nhất</div>
              <div className="value">{today.latest_hba1c ? `${today.latest_hba1c.value}%` : "–"}</div>
              <div className="sub">mục tiêu chung &lt; 7%</div>
            </div>
          </div>
          <section className="card">
            {summary.series.length ? (
              <GlucoseChart series={summary.series} days={14} endDate={today.date} targets={today.targets} />
            ) : (
              <p className="muted">Chưa có lần đo nào. Ghi lần đầu ở ô phía trên.</p>
            )}
          </section>
        </>
      )}
      <Reminders patientId={patient.id} />
      <p className="disclaimer">
        {today?.targets.custom
          ? "Đang so với mục tiêu bạn nhập theo lời bác sĩ (đổi ở trang Tái khám)."
          : "Mục tiêu tham khảo theo ADA Standards of Care 2024; nếu bác sĩ dặn mục tiêu khác, nhập ở trang Tái khám."}{" "}
        DiaCare không thay thế bác sĩ.
      </p>
    </>
  );
}
