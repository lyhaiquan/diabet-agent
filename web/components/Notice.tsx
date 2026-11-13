import type { Msg } from "@/lib/api";

export function Notice({ level, children }: { level: Msg["level"]; children: React.ReactNode }) {
  return (
    <div className={`notice notice-${level}`} role={level === "error" || level === "warning" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Notices({ items }: { items: Msg[] }) {
  return (
    <>
      {items.map((m, i) => (
        <Notice key={i} level={m.level}>
          {m.text}
        </Notice>
      ))}
    </>
  );
}

export function ErrorText({ error }: { error: string | null }) {
  return error ? <Notice level="error">{error}</Notice> : null;
}
