// Gọi dịch vụ API DiaCare (src/api/main.py). Token JWT giữ trong localStorage của trình duyệt.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "diacare.token";
const PATIENT_KEY = "diacare.patient";

// ---- kiểu dữ liệu trả về --------------------------------------------------

export type Level = "error" | "warning" | "info" | "success";
export type Msg = { level: Level; text: string };
export type Context = "fasting" | "before_meal" | "after_meal" | "bedtime" | "random";

export const CONTEXTS: Record<Context, string> = {
  fasting: "Lúc đói (sáng)",
  before_meal: "Trước bữa ăn",
  after_meal: "1–2 giờ sau ăn",
  bedtime: "Trước khi ngủ",
  random: "Bất kỳ",
};

export type User = { id: number; email: string; name: string | null };
export type Patient = {
  id: number;
  name: string;
  diagnosed: boolean;
  profile: Record<string, number>;
  risk: { probability: number; band: string; note: string };
};
export type Reading = {
  id: number;
  kind: "glucose" | "bp" | "weight";
  measured_at: string;
  note: string | null;
  mmol?: number;
  mgdl?: number;
  context?: Context;
  context_text?: string;
  systolic?: number;
  diastolic?: number;
  kg?: number;
  status?: string;
  status_text?: string;
};
export type GlucoseResult = {
  reading: Reading;
  status: string;
  status_text: string;
  message: string;
  advice: string | null;
  advice_level: Level | null;
};
export type Lab = {
  id: number;
  test: string;
  label: string;
  value: number;
  unit: string;
  level: string;
  assessment: string;
  created_at: string;
};
export type Appointment = { id: number; date: string; place: string | null; note: string | null } | null;
export type Today = {
  date: string;
  name: string;
  alerts: Msg[];
  reminders: Msg[];
  last_glucose: Reading | null;
  in_target_pct_14d: number | null;
  fasting_mean_mmol_14d: number | null;
  latest_hba1c: Lab | null;
  appointment: Appointment;
};
export type SeriesPoint = { t: string; mmol: number; context: Context };
export type Summary = {
  days: number;
  glucose: {
    n: number;
    days_measured: number;
    hypo: number;
    very_high: number;
    in_target_pct: number | null;
    mean_mmol: number | null;
    by_context: Record<string, { n: number; mean_mmol: number; min_mmol: number; max_mmol: number; in_target_pct: number }>;
  };
  bp: { n: number; systolic: number; diastolic: number; above_target: number } | null;
  weight: { first: number; last: number; delta: number; n: number } | null;
  series: SeriesPoint[];
  targets: { pre_meal_mmol: [number, number]; post_meal_max_mmol: number; hypo_mmol: number; source: string };
};
export type Question = { id: number; text: string; done: boolean; created_at: string };
export type Focus = { event_id: number | null; action: string; label: string; rated?: "up" | "down" | null } | null;
export type ChatResult = {
  session_id: number;
  answer: string;
  sources: string[];
  flags: string[];
  risk: { probability: number; band: string } | null;
  focus: Focus;
  steps: { agent: string; detail: string; ms: number }[];
};
export type ChatMessage = { role: "user" | "assistant"; content: string; focus?: Focus };
export type Memory = { id: number; kind: string; kind_text: string; content: string };

// ---- token, hồ sơ đang chọn ----------------------------------------------

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // chế độ riêng tư chặn localStorage
  }
}

export const getToken = () => storage()?.getItem(TOKEN_KEY) ?? null;
export const setToken = (t: string | null) => {
  const s = storage();
  if (!s) return;
  if (t) s.setItem(TOKEN_KEY, t);
  else s.removeItem(TOKEN_KEY);
};
export const getSavedPatient = () => Number(storage()?.getItem(PATIENT_KEY)) || null;
export const savePatient = (id: number | null) => {
  const s = storage();
  if (!s) return;
  if (id) s.setItem(PATIENT_KEY, String(id));
  else s.removeItem(PATIENT_KEY);
};

// ---- gọi API ---------------------------------------------------------------

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detailText(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return "Dữ liệu chưa hợp lệ: " + d.map((e) => e?.msg ?? "").join("; ");
  if (status === 0) return "Không kết nối được máy chủ API.";
  return `Lỗi ${status}`;
}

export const UNAUTHORIZED_EVENT = "diacare:unauthorized";

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(API_URL + path, { ...init, headers });
  } catch {
    throw new ApiError(0, `Không kết nối được máy chủ API (${API_URL}). Hãy chạy: uvicorn api.main:app --app-dir src --port 8000`);
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* không phải JSON */
    }
    if (res.status === 401 && token) {
      setToken(null);
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(res.status, detailText(body, res.status));
  }
  return res;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await request(path, init);
  return (res.status === 204 ? null : await res.json()) as T;
}

const post = <T,>(path: string, body: unknown) => json<T>(path, { method: "POST", body: JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) => json<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const api = {
  register: (email: string, password: string, name?: string) =>
    post<{ access_token: string }>("/auth/register", { email, password, name: name || null }),
  login: (email: string, password: string) =>
    json<{ access_token: string }>("/auth/token", {
      method: "POST",
      body: new URLSearchParams({ username: email, password }),
    }),
  me: () => json<User>("/me"),

  patients: () => json<Patient[]>("/patients"),
  createPatient: (name: string, diagnosed: boolean) => post<Patient>("/patients", { name, diagnosed }),
  memories: (pid: number) => json<Memory[]>(`/patients/${pid}/memories`),
  forget: (pid: number, mid: number) => json<null>(`/patients/${pid}/memories/${mid}`, { method: "DELETE" }),

  today: (pid: number) => json<Today>(`/patients/${pid}/today`),
  summary: (pid: number, days: number) => json<Summary>(`/patients/${pid}/summary?days=${days}`),
  readings: (pid: number, days: number, kind?: string) =>
    json<Reading[]>(`/patients/${pid}/readings?days=${days}${kind ? `&kind=${kind}` : ""}`),
  addGlucose: (pid: number, b: { value: number; unit: string; context: Context; measured_at?: string; note?: string }) =>
    post<GlucoseResult>(`/patients/${pid}/readings/glucose`, b),
  addBp: (pid: number, b: { systolic: number; diastolic: number; measured_at?: string }) =>
    post<{ status: string; status_text: string; advice: string | null }>(`/patients/${pid}/readings/bp`, b),
  addWeight: (pid: number, b: { kg: number; measured_at?: string }) => post<{ reading: Reading }>(`/patients/${pid}/readings/weight`, b),
  deleteReading: (pid: number, rid: number) => json<null>(`/patients/${pid}/readings/${rid}`, { method: "DELETE" }),

  labs: (pid: number) => json<Lab[]>(`/patients/${pid}/labs`),
  labsFromText: (pid: number, text: string) => post<{ imported: unknown[]; labs: Lab[] }>(`/patients/${pid}/labs`, { text }),
  labsFromFile: (pid: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return json<{ imported: unknown[]; labs: Lab[] }>(`/patients/${pid}/labs/file`, { method: "POST", body: fd });
  },

  appointment: (pid: number) => json<Appointment>(`/patients/${pid}/appointment`),
  setAppointment: (pid: number, date: string, place: string) =>
    put<Appointment>(`/patients/${pid}/appointment`, { date, place: place || null }),
  questions: (pid: number) => json<Question[]>(`/patients/${pid}/questions`),
  addQuestion: (pid: number, text: string) => post<Question>(`/patients/${pid}/questions`, { text }),
  questionDone: (pid: number, qid: number) => json<unknown>(`/patients/${pid}/questions/${qid}/done`, { method: "POST" }),
  visitReport: async (pid: number, days: number) => (await request(`/patients/${pid}/visit-report.pdf?days=${days}`)).blob(),

  sessions: (pid: number) => json<{ id: number; created_at: string; n_messages: number }[]>(`/patients/${pid}/sessions`),
  messages: (pid: number, sid: number) => json<ChatMessage[]>(`/patients/${pid}/sessions/${sid}/messages`),
  feedback: (eventId: number, value: "up" | "down") => post<unknown>(`/feedback/${eventId}`, { value }),

  transcribe: (wav: Blob) => {
    const fd = new FormData();
    fd.append("audio", wav, "noi.wav");
    return json<Transcript>("/transcribe", { method: "POST", body: fd });
  },
};

export type SpokenReading =
  | { kind: "glucose"; value: number; unit: "mmol/L" | "mg/dL"; context: Context | null; summary: string;
      alternative?: { value: number; unit: "mmol/L"; summary: string } }
  | { kind: "bp"; systolic: number; diastolic: number; summary: string }
  | { kind: "weight"; kg: number; summary: string };
export type Transcript = { text: string; reading: SpokenReading | null; seconds: number; audio_seconds: number };

// ---- tư vấn qua luồng SSE ----------------------------------------------------

export type ChatEvents = {
  onSession?: (sessionId: number) => void;
  onStep?: (step: { agent: string; detail: string; ms: number }) => void;
  onToken?: (text: string) => void;
};

/** Tách các sự kiện SSE hoàn chỉnh khỏi bộ đệm; trả về phần còn dở. */
export function parseSse(buffer: string, emit: (event: string, data: unknown) => void): string {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) data.push(line.slice(6));
    }
    if (data.length) emit(event, JSON.parse(data.join("\n")));
  }
  return rest;
}

/** EventSource chỉ gửi được GET, nên đọc luồng SSE từ fetch POST. Trả về kết quả cuối (sự kiện done). */
export async function chatStream(pid: number, question: string, sessionId: number | null, ev: ChatEvents): Promise<ChatResult> {
  const res = await request(`/patients/${pid}/chat`, {
    method: "POST",
    body: JSON.stringify({ question, session_id: sessionId, stream: true }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ChatResult | null = null;
  let error: string | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer = parseSse(buffer + decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n"), (event, data) => {
      const d = data as Record<string, unknown>;
      if (event === "session") ev.onSession?.(d.session_id as number);
      else if (event === "step") ev.onStep?.(d as never);
      else if (event === "token") ev.onToken?.(d.text as string);
      else if (event === "done") result = d as unknown as ChatResult;
      else if (event === "error") error = d.message as string;
    });
  }
  if (error) throw new ApiError(500, error);
  if (!result) throw new ApiError(500, "Mất kết nối giữa chừng. Câu trả lời vẫn được lưu, hãy tải lại phiên.");
  return result;
}

// ---- tiện ích hiển thị ---------------------------------------------------------

export const fmtMmol = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(1).replace(".", ","));
export const parseNum = (s: string) => {
  const v = Number(s.trim().replace(",", "."));
  return s.trim() === "" || Number.isNaN(v) ? null : v;
};
export const fmtTime = (iso: string) => {
  const d = new Date(iso);
  return d.toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
};
export const fmtDate = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
};
/** Giờ hiện tại theo giờ Việt Nam, dạng cho ô datetime-local (YYYY-MM-DDTHH:mm). */
export function nowLocalVN(): string {
  const p = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date());
  return p.replace(" ", "T");
}
export function guessContext(): Context {
  const h = Number(nowLocalVN().slice(11, 13));
  if (h >= 4 && h < 9) return "fasting";
  if (h >= 21 || h < 4) return "bedtime";
  return "before_meal";
}
/** Ô datetime-local không có múi giờ: gắn +07:00 để API hiểu là giờ Việt Nam. */
export const vnIso = (local: string) => (local ? `${local}:00+07:00` : undefined);
