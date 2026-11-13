"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorText } from "@/components/Notice";
import { api, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = mode === "login" ? await api.login(email, password) : await api.register(email, password, name);
      setToken(r.access_token);
      router.replace("/today");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <span className="brand">DiaCare</span>
      <p className="muted">Trợ lý tự theo dõi đái tháo đường típ 2 giữa hai lần khám.</p>
      <div className="segmented" role="group" aria-label="Chọn đăng nhập hoặc đăng ký" style={{ margin: "18px 0" }}>
        <button type="button" aria-pressed={mode === "login"} onClick={() => setMode("login")}>Đăng nhập</button>
        <button type="button" aria-pressed={mode === "register"} onClick={() => setMode("register")}>Tạo tài khoản</button>
      </div>
      <form className="card stack" onSubmit={submit}>
        {mode === "register" && (
          <label>
            Tên gọi
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={100} />
          </label>
        )}
        <label>
          Email
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
        <label>
          Mật khẩu {mode === "register" && <span className="small">(ít nhất 8 ký tự)</span>}
          <input type="password" required minLength={mode === "register" ? 8 : 1} value={password}
                 onChange={(e) => setPassword(e.target.value)}
                 autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </label>
        <button className="btn-primary" disabled={busy}>
          {busy ? "Đang xử lý..." : mode === "login" ? "Đăng nhập" : "Tạo tài khoản"}
        </button>
        <ErrorText error={error} />
      </form>
      <p className="disclaimer">
        DiaCare không chẩn đoán và không kê đơn. Mọi thay đổi điều trị cần hỏi bác sĩ. Gặp triệu chứng nặng hãy gọi 115.
      </p>
    </main>
  );
}
