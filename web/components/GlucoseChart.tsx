"use client";

import { useEffect, useRef, useState } from "react";
import type { Context, SeriesPoint } from "@/lib/api";

const COLORS: Record<Context, string> = {
  fasting: "#2563eb",
  before_meal: "#0891b2",
  after_meal: "#16a34a",
  bedtime: "#9333ea",
  random: "#ea580c",
};
const NAMES: Record<Context, string> = {
  fasting: "lúc đói",
  before_meal: "trước ăn",
  after_meal: "sau ăn",
  bedtime: "trước ngủ",
  random: "bất kỳ",
};

/** Biểu đồ đường huyết (mmol/L) theo thời gian; dải xanh = mục tiêu trước ăn 4,4–7,2. Không dùng thư viện. */
export function GlucoseChart({ series, days, endDate }: { series: SeriesPoint[]; days: number; endDate: string }) {
  // Vẽ theo đúng bề rộng thật của khung để chữ trên trục không bị co nhỏ trên điện thoại
  const box = useRef<HTMLElement>(null);
  const [W, setW] = useState(640);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = W < 480 ? 200 : 240, L = 30, R = 6, T = 10, B = 24;
  const end = new Date(`${endDate}T23:59:59+07:00`).getTime();
  const start = end - days * 86400000;
  const vals = series.map((p) => p.mmol);
  const yMin = Math.min(2.5, ...vals.map((v) => v - 0.5));
  const yMax = Math.max(12, ...vals.map((v) => v + 1));
  const x = (t: number) => L + ((t - start) / (end - start)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - yMin) / (yMax - yMin)) * (H - T - B);
  const ticksY = [4, 6, 8, 10, 12, 14, 16, 18, 20].filter((v) => v > yMin && v < yMax);
  const step = Math.max(1, Math.round(days / (W < 480 ? 4 : 7)));
  const ticksX: number[] = [];
  for (let d = days - 1; d >= 0; d -= step) ticksX.push(end - d * 86400000 - 43200000);
  const used = Array.from(new Set(series.map((p) => p.context)));
  const label = (t: number) =>
    new Date(t).toLocaleDateString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", day: "2-digit", month: "2-digit" });

  return (
    <figure style={{ margin: 0 }} ref={box}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Biểu đồ đường huyết ${days} ngày, ${series.length} lần đo`}>
        <rect className="band" x={L} width={W - L - R} y={y(7.2)} height={y(4.4) - y(7.2)} />
        {ticksY.map((v) => (
          <g key={v}>
            <line className="grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} strokeWidth={0.6} />
            <text x={L - 6} y={y(v) + 4} textAnchor="end">{v}</text>
          </g>
        ))}
        <line x1={L} x2={W - R} y1={y(10)} y2={y(10)} stroke="#ea580c" strokeDasharray="5 4" strokeWidth={1} />
        <line x1={L} x2={W - R} y1={y(3.9)} y2={y(3.9)} stroke="#2563eb" strokeDasharray="2 3" strokeWidth={1} />
        {ticksX.map((t) => (
          <text key={t} x={x(t)} y={H - 8} textAnchor="middle">{label(t)}</text>
        ))}
        {series.map((p, i) => {
          const cx = x(new Date(p.t).getTime()), cy = y(p.mmol);
          return p.context === "after_meal" ? (
            <path key={i} d={`M${cx},${cy - 5} L${cx + 5},${cy + 4} L${cx - 5},${cy + 4} Z`} fill={COLORS[p.context]}>
              <title>{`${p.mmol} mmol/L, ${NAMES[p.context]}`}</title>
            </path>
          ) : (
            <circle key={i} cx={cx} cy={cy} r={4.5} fill={COLORS[p.context]}>
              <title>{`${p.mmol} mmol/L, ${NAMES[p.context]}`}</title>
            </circle>
          );
        })}
      </svg>
      <figcaption className="legend">
        <span><i className="dot" style={{ background: "var(--target-band)", border: "1px solid var(--ok)" }} />mục tiêu trước ăn 4,4–7,2</span>
        <span><svg width="18" height="6" aria-hidden="true"><line x1="0" x2="18" y1="3" y2="3" stroke="#ea580c" strokeDasharray="5 4" strokeWidth="2" /></svg>sau ăn &lt; 10,0</span>
        <span><svg width="18" height="6" aria-hidden="true"><line x1="0" x2="18" y1="3" y2="3" stroke="#2563eb" strokeDasharray="2 3" strokeWidth="2" /></svg>hạ đường huyết &lt; 3,9</span>
        {used.map((c) => (
          <span key={c}><i className="dot" style={{ background: COLORS[c] }} />{NAMES[c]}</span>
        ))}
      </figcaption>
    </figure>
  );
}
