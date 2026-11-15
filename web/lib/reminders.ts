// Nhắc đo đường huyết bằng thông báo của trình duyệt.
// Giờ nhắc lưu trong localStorage của máy này (theo từng hồ sơ), không gửi lên máy chủ. Thông báo chỉ bật được khi
// DiaCare đang mở trên trình duyệt (kể cả tab nền): không có máy chủ đẩy (Web Push), nên đóng hẳn trình duyệt thì
// không nhắc được.

export type ReminderConfig = { enabled: boolean; times: string[] }; // times: "HH:MM", giờ của máy

export const MAX_TIMES = 4;
/** Nhắc muộn nhất bao lâu sau giờ hẹn (vd mở máy lúc 7:10 vẫn nhắc cho mốc 6:30). */
export const LATE_MINUTES = 90;
/** Vừa đo trong khoảng này trước giờ nhắc thì thôi không nhắc. */
export const RECENT_MINUTES = 120;

const key = (pid: number) => `diacare.reminders.${pid}`;
const firedKey = (pid: number) => `diacare.reminders.fired.${pid}`;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export const validTime = (t: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(t);

export function loadConfig(pid: number): ReminderConfig {
  try {
    const raw = JSON.parse(storage()?.getItem(key(pid)) ?? "null");
    if (raw && Array.isArray(raw.times)) {
      return { enabled: Boolean(raw.enabled), times: raw.times.filter(validTime).slice(0, MAX_TIMES).sort() };
    }
  } catch {
    /* dữ liệu hỏng: dùng mặc định */
  }
  return { enabled: false, times: [] };
}

export function saveConfig(pid: number, cfg: ReminderConfig) {
  storage()?.setItem(key(pid), JSON.stringify(cfg));
}

const pad = (n: number) => String(n).padStart(2, "0");
export const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Các mốc tới hạn: đã tới giờ, chưa quá LATE_MINUTES, và hôm nay chưa nhắc. Hàm thuần để dễ kiểm. */
export function dueTimes(times: string[], now: Date, firedToday: string[]): string[] {
  const minutes = now.getHours() * 60 + now.getMinutes();
  return times.filter((t) => {
    const [h, m] = t.split(":").map(Number);
    const late = minutes - (h * 60 + m);
    return late >= 0 && late <= LATE_MINUTES && !firedToday.includes(t);
  });
}

export function firedToday(pid: number, now: Date): string[] {
  try {
    const raw = JSON.parse(storage()?.getItem(firedKey(pid)) ?? "null");
    return raw && raw.day === dayKey(now) && Array.isArray(raw.times) ? raw.times : [];
  } catch {
    return [];
  }
}

export function markFired(pid: number, now: Date, times: string[]) {
  const all = Array.from(new Set([...firedToday(pid, now), ...times]));
  storage()?.setItem(firedKey(pid), JSON.stringify({ day: dayKey(now), times: all }));
}

export const notificationsSupported = () => typeof window !== "undefined" && "Notification" in window;

/** Hiện thông báo; ưu tiên service worker (Chrome trên Android không cho `new Notification`). */
export async function notify(title: string, body: string): Promise<boolean> {
  if (!notificationsSupported() || Notification.permission !== "granted") return false;
  const options = { body, tag: "diacare-do-duong-huyet", icon: "/icon.svg", data: { url: "/today" } };
  try {
    const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : undefined;
    if (reg) {
      await reg.showNotification(title, options);
      return true;
    }
    new Notification(title, options);
    return true;
  } catch {
    return false;
  }
}

export async function registerWorker() {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js");
  } catch {
    /* không đăng ký được thì vẫn dùng `new Notification` trên máy tính */
  }
}
