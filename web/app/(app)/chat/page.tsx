"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorText } from "@/components/Notice";
import { api, chatStream, type ChatMessage, type ChatResult, type Focus } from "@/lib/api";
import { usePatient } from "@/lib/session";

const SUGGESTIONS = [
  "Bữa sáng ăn bánh mì trứng có ổn không?",
  "Đường huyết sau ăn của tôi hay cao, nên làm gì?",
  "Đi bộ bao lâu mỗi ngày là đủ?",
  "Quên uống thuốc buổi sáng thì sao?",
];

type Item = ChatMessage & { result?: ChatResult; pending?: boolean; steps?: string[] };

function FocusFeedback({ focus }: { focus: Focus }) {
  const [rated, setRated] = useState(focus?.rated ?? null);
  const [error, setError] = useState<string | null>(null);
  if (!focus || focus.event_id == null) return null;
  async function rate(v: "up" | "down") {
    try {
      await api.feedback(focus!.event_id!, v);
      setRated(v);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className="bubble-meta">
      Trọng tâm lần này: <b>{focus.label}</b>.{" "}
      {rated ? (
        <span>Bạn đã chấm {rated === "up" ? "👍" : "👎"}. Cảm ơn!</span>
      ) : (
        <>
          Có hợp với bạn không?{" "}
          <button className="btn-ghost btn-small" onClick={() => rate("up")} aria-label="Hợp">👍</button>
          <button className="btn-ghost btn-small" onClick={() => rate("down")} aria-label="Không hợp">👎</button>
        </>
      )}
      {error && <span> {error}</span>}
    </div>
  );
}

export default function ChatPage() {
  const patient = usePatient();
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Mở lại phiên gần nhất nếu có
  useEffect(() => {
    api.sessions(patient.id).then(async (list) => {
      const last = list.find((s) => s.n_messages > 0);
      if (last) {
        setSessionId(last.id);
        setItems(await api.messages(patient.id, last.id));
      }
    }).catch((e) => setError(e.message));
  }, [patient.id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items]);

  function patchLast(fn: (it: Item) => Item) {
    setItems((xs) => [...xs.slice(0, -1), fn(xs[xs.length - 1])]);
  }

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    setInput("");
    setItems((xs) => [...xs, { role: "user", content: q }, { role: "assistant", content: "", pending: true, steps: [] }]);
    try {
      const result = await chatStream(patient.id, q, sessionId, {
        onSession: setSessionId,
        onStep: (s) => patchLast((it) => ({ ...it, steps: [...(it.steps ?? []), s.agent] })),
        onToken: (t) => patchLast((it) => ({ ...it, content: it.content + t })),
      });
      // Thay bản nháp đang hiện bằng câu trả lời cuối đã qua luật an toàn
      patchLast((it) => ({ ...it, content: result.answer, result, focus: result.focus, pending: false }));
    } catch (e) {
      setError((e as Error).message);
      setItems((xs) => xs.slice(0, -1));
    } finally {
      setBusy(false);
    }
  }

  function newSession() {
    setSessionId(null);
    setItems([]);
  }

  return (
    <>
      <div className="page-title row" style={{ alignItems: "center" }}>
        <div>
          <h1>Tư vấn</h1>
          <p className="small">Hỏi về ăn uống, vận động, thuốc, kết quả xét nghiệm. Trợ lý không chẩn đoán và không khuyên đổi thuốc.</p>
        </div>
        {items.length > 0 && <button className="btn-small" style={{ flex: "0 0 auto" }} onClick={newSession}>Cuộc trò chuyện mới</button>}
      </div>
      <div className="chat" aria-live="polite">
        {items.length === 0 && (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip" onClick={() => ask(s)}>{s}</button>
            ))}
          </div>
        )}
        {items.map((m, i) => (
          <div key={i} className={`bubble ${m.role === "user" ? "bubble-user" : "bubble-bot"}`}>
            {m.content || (m.pending ? "Đang suy nghĩ..." : "")}
            {m.pending && m.steps && m.steps.length > 0 && (
              <div className="steps">Các agent đã chạy: {m.steps.join(" → ")}</div>
            )}
            {m.result && m.result.sources.length > 0 && (
              <div className="bubble-meta">Nguồn: {Array.from(new Set(m.result.sources)).join(", ")}</div>
            )}
            {m.role === "assistant" && !m.pending && <FocusFeedback focus={m.focus ?? null} />}
          </div>
        ))}
        <ErrorText error={error} />
        <div ref={endRef} style={{ scrollMarginBottom: 170 }} />
      </div>
      <div className="composer">
        <form onSubmit={(e) => { e.preventDefault(); ask(input); }}>
          <textarea aria-label="Câu hỏi" placeholder="Nhập câu hỏi..." value={input} maxLength={2000}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }} />
          <button className="btn-primary" style={{ flex: "0 0 auto" }} disabled={busy || !input.trim()}>Gửi</button>
        </form>
      </div>
    </>
  );
}
