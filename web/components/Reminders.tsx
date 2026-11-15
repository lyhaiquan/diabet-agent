"use client";

import { useEffect, useState } from "react";
import { Notice } from "@/components/Notice";
import { api } from "@/lib/api";
import {
  dueTimes, firedToday, loadConfig, markFired, MAX_TIMES, notificationsSupported, notify, RECENT_MINUTES,
  registerWorker, saveConfig, validTime, type ReminderConfig,
} from "@/lib/reminders";

/** Chạy ngầm ở mọi trang: mỗi 30 giây xem có mốc nhắc nào tới hạn; vừa đo xong thì không nhắc. */
export function ReminderScheduler({ patientId, patientName }: { patientId: number; patientName: string }) {
  useEffect(() => {
    let stopped = false;
    async function tick() {
      const cfg = loadConfig(patientId);
      if (!cfg.enabled || !notificationsSupported() || Notification.permission !== "granted") return;
      const now = new Date();
      const due = dueTimes(cfg.times, now, firedToday(patientId, now));
      if (!due.length) return;
      markFired(patientId, now, due); // đánh dấu trước: hai tab cùng mở không nhắc hai lần
      try {
        const rows = await api.readings(patientId, 1, "glucose");
        const recent = rows.some((r) => now.getTime() - new Date(r.measured_at).getTime() < RECENT_MINUTES * 60000);
        if (recent || stopped) return;
      } catch {
        /* không hỏi được máy chủ thì vẫn nhắc */
      }
      await notify("Đến giờ đo đường huyết", `Nhắc cho ${patientName} (mốc ${due[due.length - 1]}). Bấm để mở DiaCare và ghi số đo.`);
    }
    registerWorker();
    tick();
    const id = window.setInterval(tick, 30000);
    return () => {
      stopped = true;
      window.clearInterval(id);
    };
  }, [patientId, patientName]);
  return null;
}

/** Thẻ cài giờ nhắc ở trang Hôm nay. */
export function Reminders({ patientId }: { patientId: number }) {
  const [cfg, setCfg] = useState<ReminderConfig>({ enabled: false, times: [] });
  const [time, setTime] = useState("06:30");
  const [permission, setPermission] = useState<string>("default");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setCfg(loadConfig(patientId));
    setPermission(notificationsSupported() ? Notification.permission : "unsupported");
  }, [patientId]);

  function update(next: ReminderConfig) {
    setCfg(next);
    saveConfig(patientId, next);
  }

  function addTime(e: React.FormEvent) {
    e.preventDefault();
    if (!validTime(time) || cfg.times.includes(time) || cfg.times.length >= MAX_TIMES) return;
    update({ ...cfg, times: [...cfg.times, time].sort() });
  }

  async function toggle() {
    setMessage(null);
    if (cfg.enabled) {
      update({ ...cfg, enabled: false });
      return;
    }
    if (!notificationsSupported()) return;
    const p = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    setPermission(p);
    if (p !== "granted") {
      setMessage("Trình duyệt đang chặn thông báo của trang này. Hãy cho phép trong cài đặt trang rồi bật lại.");
      return;
    }
    await registerWorker();
    update({ ...cfg, enabled: true });
    await notify("DiaCare sẽ nhắc bạn đo đường huyết", "Thông báo thử: lời nhắc sẽ hiện như thế này.");
  }

  return (
    <section className="card stack">
      <h2 style={{ margin: 0 }}>Nhắc đo đường huyết</h2>
      {permission === "unsupported" ? (
        <p className="small muted" style={{ margin: 0 }}>Trình duyệt này không hỗ trợ thông báo.</p>
      ) : (
        <>
          <p className="small muted" style={{ margin: 0 }}>
            Chọn tối đa {MAX_TIMES} mốc giờ trong ngày. Tới giờ mà trong 2 giờ trước đó chưa có số đo nào, DiaCare hiện
            thông báo. Lời nhắc chỉ hoạt động khi DiaCare đang mở trên trình duyệt (để ở tab nền cũng được) và giờ nhắc
            lưu riêng trên máy này.
          </p>
          {cfg.times.length > 0 && (
            <ul className="list">
              {cfg.times.map((t) => (
                <li key={t}>
                  <div className="main">{t}</div>
                  <button className="btn-small" style={{ flex: "0 0 auto" }} aria-label={`Bỏ mốc ${t}`}
                          onClick={() => update({ ...cfg, times: cfg.times.filter((x) => x !== t) })}>Bỏ</button>
                </li>
              ))}
            </ul>
          )}
          <form className="row" onSubmit={addTime}>
            <label>Giờ nhắc
              <input type="time" required value={time} onChange={(e) => setTime(e.target.value)} />
            </label>
            <button style={{ flex: "0 0 auto" }} disabled={cfg.times.length >= MAX_TIMES || cfg.times.includes(time)}>Thêm mốc</button>
          </form>
          <button className={cfg.enabled ? "" : "btn-primary"} style={{ alignSelf: "flex-start" }}
                  disabled={!cfg.enabled && cfg.times.length === 0} aria-pressed={cfg.enabled} onClick={toggle}>
            {cfg.enabled ? "Tắt nhắc" : "Bật nhắc"}
          </button>
          {cfg.enabled && <Notice level="success">Đang bật nhắc lúc {cfg.times.join(", ") || "(chưa có mốc nào)"}.</Notice>}
          {message && <Notice level="warning">{message}</Notice>}
        </>
      )}
    </section>
  );
}
