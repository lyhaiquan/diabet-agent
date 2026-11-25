"use client";

import { useEffect, useState } from "react";
import { Notice } from "@/components/Notice";
import { api, type MealAdvice } from "@/lib/api";

/** Thẻ "Gợi ý ăn uống từ đường huyết sau ăn" (trang Hôm nay và Bữa ăn). Câu và số do máy chủ tính sẵn
 *  (GET .../meals/advice, meal_scan.meal_advice), không qua LLM. `version` đổi thì tải lại (vừa ghi bữa hay số đo).
 *  hideEmpty: chưa ghi bữa nào thì không hiện (trang Hôm nay). */
export function MealAdviceCard({ patientId, version = 0, hideEmpty = true }:
  { patientId: number; version?: number; hideEmpty?: boolean }) {
  const [advice, setAdvice] = useState<MealAdvice | null>(null);

  useEffect(() => {
    api.mealAdvice(patientId).then(setAdvice).catch(() => setAdvice(null));
  }, [patientId, version]);

  if (!advice || (hideEmpty && advice.status === "no_meals")) return null;
  const icon = (line: string) =>
    line.startsWith("Nên hạn chế") ? "🔻 " : line.startsWith("Có thể ăn thêm") || line.startsWith("Món ít tinh bột") ? "🥬 " : "";
  const strong = (line: string) => line.startsWith("Nên hạn chế") || line.startsWith("Có thể ăn thêm");
  return (
    <section className="card stack">
      <h2>Gợi ý ăn uống từ đường huyết sau ăn</h2>
      {advice.status === "hypo" ? (
        <Notice level="warning">{advice.lines.join(" ")}</Notice>
      ) : advice.status === "need_after" ? (
        <>
          <p>{advice.headline}</p>
          {advice.lines.slice(1, -1).map((line, i) => <Notice key={i} level="info">{line}</Notice>)}
          <p className="small muted">{advice.lines[advice.lines.length - 1]}</p>
        </>
      ) : (
        <>
          <p>{advice.headline}</p>
          {advice.lines.slice(1).map((line, i) => (
            <p key={i} className={strong(line) ? "" : "small"}>{icon(line)}{line}</p>
          ))}
          {(advice.status === "high" || advice.status === "all_ok") && <p className="small muted">{advice.caveat}</p>}
        </>
      )}
    </section>
  );
}
