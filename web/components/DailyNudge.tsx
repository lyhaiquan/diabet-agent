"use client";

import { useState } from "react";
import { api, type Nudge } from "@/lib/api";

/** Lời nhắc hôm nay của agent Q-learning, kèm 👍/👎. Phiếu chấm là phần thưởng phụ khi agent học ngày này. */
export function DailyNudge({ patientId, nudge }: { patientId: number; nudge: Nudge }) {
  const [rated, setRated] = useState<"up" | "down" | null>(nudge.rated);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function rate(v: "up" | "down") {
    setBusy(true);
    setError(null);
    try {
      await api.nudgeFeedback(patientId, v);
      setRated(v);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="notice notice-info" role="note">
      <b>Lời nhắc hôm nay.</b>
      <p>{nudge.text}</p>
      <div className="bubble-meta" style={{ marginTop: 8 }}>
        {rated ? (
          <span>Bạn đã chấm {rated === "up" ? "👍" : "👎"}. Lời nhắc ngày mai sẽ tính cả ý kiến này.</span>
        ) : (
          <>
            Lời nhắc này có hợp với bạn không?{" "}
            <button className="btn-ghost btn-small" disabled={busy} onClick={() => rate("up")} aria-label="Hợp">👍</button>
            <button className="btn-ghost btn-small" disabled={busy} onClick={() => rate("down")} aria-label="Không hợp">👎</button>
          </>
        )}
        {error && <span> {error}</span>}
      </div>
    </div>
  );
}
