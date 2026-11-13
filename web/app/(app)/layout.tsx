"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorText } from "@/components/Notice";
import { api } from "@/lib/api";
import { SessionProvider, useSession } from "@/lib/session";

const ICONS = {
  today: "M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  journal: "M4 19h16M6 16V9m5 7V5m5 11v-5m4 5V8",
  chat: "M4 5h16v11H8l-4 4z",
  visit: "M7 3v3m10-3v3M4 8h16M5 5h14v15H5zM9 13h6m-6 4h4",
};
const NAV: { href: string; label: string; icon: keyof typeof ICONS }[] = [
  { href: "/today", label: "Hôm nay", icon: "today" },
  { href: "/journal", label: "Nhật ký", icon: "journal" },
  { href: "/chat", label: "Tư vấn", icon: "chat" },
  { href: "/visit", label: "Tái khám", icon: "visit" },
];

function Redirect({ to }: { to: string }) {
  const router = useRouter();
  useEffect(() => router.replace(to), [router, to]);
  return <div className="center">Đang chuyển...</div>;
}

function FirstPatient() {
  const { refreshPatients, logout, user } = useSession();
  const [name, setName] = useState(user.name ?? "");
  const [diagnosed, setDiagnosed] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const p = await api.createPatient(name.trim(), diagnosed);
      await refreshPatients(p.id);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <h1>Tạo hồ sơ theo dõi</h1>
      <p className="muted">Một tài khoản có thể theo dõi cho chính bạn hoặc cho người thân (bố, mẹ...).</p>
      <form className="card stack" onSubmit={submit}>
        <label>
          Tên người được theo dõi
          <input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="vd Mẹ Hường" />
        </label>
        <label className="check">
          <input type="checkbox" checked={diagnosed} onChange={(e) => setDiagnosed(e.target.checked)} />
          Đã được bác sĩ chẩn đoán đái tháo đường típ 2
        </label>
        <button className="btn-primary" disabled={busy || !name.trim()}>Tạo hồ sơ</button>
        <ErrorText error={error} />
      </form>
      <button className="btn-ghost" onClick={logout}>Đăng xuất</button>
    </main>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { patient, patients, choosePatient, logout } = useSession();
  const pathname = usePathname();
  if (!patient) return <FirstPatient />;
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link href="/today" className="brand">DiaCare</Link>
          <select aria-label="Hồ sơ đang theo dõi" value={patient.id} onChange={(e) => choosePatient(Number(e.target.value))}>
            {patients.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <button className="btn-ghost" onClick={logout}>Thoát</button>
        </div>
      </header>
      <nav className="nav" aria-label="Trang chính">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} aria-current={pathname.startsWith(n.href) ? "page" : undefined}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
                 strokeLinejoin="round" aria-hidden="true">
              <path d={ICONS[n.icon]} />
            </svg>
            {n.label}
          </Link>
        ))}
      </nav>
      {/* key: đổi hồ sơ thì các trang tải lại dữ liệu từ đầu */}
      <main className="shell" key={patient.id}>{children}</main>
    </>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider
      fallback={(status, error) =>
        status === "anonymous" ? <Redirect to="/login" /> :
        status === "error" ? <main className="auth"><ErrorText error={error} /><a href="/login">Đăng nhập lại</a></main> :
        <div className="center">Đang tải...</div>}
    >
      {() => <Shell>{children}</Shell>}
    </SessionProvider>
  );
}
