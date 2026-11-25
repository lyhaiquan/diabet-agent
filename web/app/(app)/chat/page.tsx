"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckinCard } from "@/components/CheckinCard";
import { MicButton } from "@/components/MicButton";
import { VoiceChat } from "@/components/VoiceChat";
import { ErrorText, Notice } from "@/components/Notice";
import { api, chatStream, MEAL_SCAN_KEY, type ChatMessage, type ChatResult, type CheckinReply, type Focus } from "@/lib/api";
import { getSpeakPref, setSpeakPref, speak, stopSpeaking } from "@/lib/voice";
import { usePatient } from "@/lib/session";

const SUGGESTIONS = [
  "Bữa sáng ăn bánh mì trứng có ổn không?",
  "Đường huyết sau ăn của tôi hay cao, nên làm gì?",
  "Đi bộ bao lâu mỗi ngày là đủ?",
  "Quên uống thuốc buổi sáng thì sao?",
];

/** Câu soạn sẵn (lời mở đầu của trợ lý) dùng **chữ đậm**; hiện thành chữ đậm thay vì dấu sao. */
function Bold({ text }: { text: string }) {
  return <>{text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))}</>;
}

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
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const photoRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [speakOn, setSpeakOn] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [noVoice, setNoVoice] = useState(false);
  // trợ lý chủ động hỏi: phiên này đang đợi câu trả lời; thẻ xác nhận số đo vừa đọc được (chưa lưu)
  const [checkinPending, setCheckinPending] = useState(false);
  const [card, setCard] = useState<CheckinReply["card"] | null>(null);
  // trò chuyện bằng giọng nói: câu trả lời đọc bằng Piper trên máy chủ (VoiceChat), không dùng giọng của trình duyệt
  const [voiceMode, setVoiceMode] = useState(false);

  useEffect(() => {
    setSpeakOn(getSpeakPref());
    return () => stopSpeaking();
  }, []);

  function readAloud(text: string) {
    const ok = speak(text, () => setSpeaking(false));
    setNoVoice(!ok);
    setSpeaking(ok);
  }

  function toggleSpeak() {
    const on = !speakOn;
    setSpeakOn(on);
    setSpeakPref(on);
    if (!on) {
      stopSpeaking();
      setSpeaking(false);
    }
  }

  // Mở lại phiên gần nhất nếu có, rồi để trợ lý mở lời (mỗi ngày một lần, chỉ với người đã chẩn đoán)
  useEffect(() => {
    let alive = true;
    (async () => {
      const list = await api.sessions(patient.id);
      const last = list.find((s) => s.n_messages > 0);
      const ci = await api.checkinOpen(patient.id, last?.id ?? null);
      if (!alive) return;
      setCheckinPending(ci.pending);
      setCard(null);
      const sid = ci.session_id ?? last?.id ?? null;
      setSessionId(sid);
      setItems(sid ? await api.messages(patient.id, sid) : []);
    })().catch((e) => setError(e.message));
    return () => { alive = false; };
  }, [patient.id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items]);

  function patchLast(fn: (it: Item) => Item) {
    setItems((xs) => [...xs.slice(0, -1), fn(xs[xs.length - 1])]);
  }

  /** Gửi câu hỏi. voice=true: câu nói ra ở chế độ trò chuyện bằng giọng nói (trả lời ngắn, kiểu nói). Trả về câu
   *  cần đọc to (VoiceChat đọc bằng Piper), hoặc null. */
  async function ask(question: string, voice = false): Promise<string | null> {
    const q = question.trim();
    if (!q || busy) return null;
    setBusy(true);
    setError(null);
    setInput("");
    stopSpeaking();
    setSpeaking(false);
    setCard(null);
    try {
      if (sessionId != null) {
        // câu trả lời cho câu hỏi chủ động, hoặc số đo kể ra lúc trợ lý không hỏi ("vừa đo đường huyết 7,2"):
        // số đo -> thẻ xác nhận, "chưa đo"/triệu chứng -> câu soạn sẵn; câu hỏi thường -> handled=false, gửi /chat
        const r = await api.checkinReply(patient.id, sessionId, q);
        setCheckinPending(r.pending);
        if (r.handled) {
          setItems((xs) => [...xs, { role: "user", content: q }, ...(r.reply ? [{ role: "assistant" as const, content: r.reply }] : [])]);
          if (r.card) setCard(r.card);
          else if (r.reply && speakOn && !voice) readAloud(r.reply);
          setBusy(false);
          if (r.card) return `Mình nghe được ${r.card.reading.summary}. Bạn kiểm tra thẻ bên dưới rồi bấm Lưu vào nhật ký nhé.`;
          return r.reply ?? null;
        }
      }
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
      return null;
    }
    setItems((xs) => [...xs, { role: "user", content: q }, { role: "assistant", content: "", pending: true, steps: [] }]);
    try {
      const result = await chatStream(patient.id, q, sessionId, {
        onSession: setSessionId,
        onStep: (s) => patchLast((it) => ({ ...it, steps: [...(it.steps ?? []), s.agent] })),
        onToken: (t) => patchLast((it) => ({ ...it, content: it.content + t })),
      }, voice);
      // Thay bản nháp đang hiện bằng câu trả lời cuối đã qua luật an toàn
      patchLast((it) => ({ ...it, content: result.answer, result, focus: result.focus, pending: false }));
      // Chỉ đọc câu trả lời CUỐI (đã qua luật an toàn), không đọc bản nháp đang stream
      if (speakOn && !voice) readAloud(result.answer);
      return result.answer;
    } catch (e) {
      setError((e as Error).message);
      setItems((xs) => xs.slice(0, -1));
      return null;
    } finally {
      setBusy(false);
    }
  }

  // Ảnh gửi ở ô chat: phiếu xét nghiệm thì lưu ngay; ảnh bữa ăn thì sang trang Bữa ăn để xác nhận món (như Streamlit)
  async function sendPhoto(file: File | null) {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.chatPhoto(patient.id, file, file.name || "anh.jpg");
      if (r.kind === "labs") {
        const names = r.imported.map((x) => `${x.label} ${x.value}${x.unit ? " " + x.unit : ""}`).join(", ");
        setItems((xs) => [...xs, { role: "user", content: "📷 (ảnh)" },
          { role: "assistant", content: `Ảnh này là phiếu xét nghiệm: mình đã lưu ${r.imported.length} chỉ số (${names}) vào Nhật ký → Xét nghiệm. Bạn có thể hỏi mình ý nghĩa các chỉ số này.` }]);
      } else {
        sessionStorage.setItem(MEAL_SCAN_KEY, JSON.stringify(r));
        router.push("/meals");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (photoRef.current) photoRef.current.value = "";
    }
  }

  function newSession() {
    setSessionId(null);
    setItems([]);
    setCard(null);
    setCheckinPending(false);
  }

  function cardDone(reply: string, saved: boolean) {
    setCard(null);
    setCheckinPending(!saved); // bấm "Không đúng" thì vẫn đợi người dùng gõ lại số đo
    setItems((xs) => [...xs, { role: "assistant", content: reply }]);
    if (speakOn && !voiceMode) readAloud(reply);
  }

  return (
    <>
      <div className="page-title row" style={{ alignItems: "center" }}>
        <div>
          <h1>Tư vấn</h1>
          <p className="small">Hỏi về ăn uống, vận động, thuốc, kết quả xét nghiệm. Trợ lý không chẩn đoán và không khuyên đổi thuốc.</p>
        </div>
        <div className="toolbar">
          <button className="btn-small" aria-pressed={voiceMode} onClick={() => { stopSpeaking(); setSpeaking(false); setVoiceMode((v) => !v); }}
                  title="Nói chuyện rảnh tay: bấm nút micro to, cứ nói, trợ lý tự trả lời và đọc to rồi nghe tiếp">
            {voiceMode ? "🎙️ Tắt trò chuyện bằng giọng nói" : "🎙️ Trò chuyện bằng giọng nói"}</button>
          <button className="btn-small" aria-pressed={speakOn} onClick={toggleSpeak}
                  title="Đọc to câu trả lời bằng giọng tiếng Việt của máy">{speakOn ? "🔊 Đang bật đọc to" : "🔈 Đọc to"}</button>
          {speaking && <button className="btn-small" onClick={() => { stopSpeaking(); setSpeaking(false); }}>Dừng đọc</button>}
          {items.length > 0 && <button className="btn-small" onClick={newSession}>Cuộc trò chuyện mới</button>}
        </div>
      </div>
      {noVoice && (
        <Notice level="warning">
          Máy này chưa có giọng đọc tiếng Việt. Trên Windows: Cài đặt → Thời gian và ngôn ngữ → Giọng nói → thêm giọng
          Tiếng Việt. Trên điện thoại: cài giọng Tiếng Việt trong phần Chuyển văn bản thành giọng nói.
        </Notice>
      )}
      {voiceMode && (
        <section className="card">
          <VoiceChat onText={(t) => ask(t, true)} />
          <p className="small muted" style={{ textAlign: "center" }}>
            Lần đầu có thể chờ khoảng 30 giây để máy chủ nạp mô hình nghe. Số đo nói ra vẫn hiện thẻ để bạn bấm Lưu.
          </p>
        </section>
      )}
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
            {m.content ? <Bold text={m.content} /> : m.pending ? "Đang suy nghĩ..." : ""}
            {m.pending && m.steps && m.steps.length > 0 && (
              <div className="steps">Các agent đã chạy: {m.steps.join(" → ")}</div>
            )}
            {m.result && m.result.sources.length > 0 && (
              <div className="bubble-meta">Nguồn: {Array.from(new Set(m.result.sources)).join(", ")}</div>
            )}
            {m.role === "assistant" && !m.pending && <FocusFeedback focus={m.focus ?? null} />}
            {m.role === "assistant" && !m.pending && m.content && (
              <button className="btn-ghost btn-small" onClick={() => readAloud(m.content)} aria-label="Đọc to câu trả lời này">🔈 Đọc</button>
            )}
          </div>
        ))}
        {card && sessionId != null && (
          <CheckinCard patientId={patient.id} sessionId={sessionId} reading={card.reading} measuredAt={card.measured_at}
                       onDone={cardDone} />
        )}
        <ErrorText error={error} />
        <div ref={endRef} style={{ scrollMarginBottom: 170 }} />
      </div>
      <div className="composer">
        <form onSubmit={(e) => { e.preventDefault(); ask(input); }}>
          <MicButton compact onResult={(t) => {
            // Không tự gửi: hiện chữ nghe được trong ô để người dùng sửa rồi mới bấm Gửi
            setInput((prev) => (prev.trim() ? `${prev.trim()} ${t.text}` : t.text));
            inputRef.current?.focus();
          }} />
          <input ref={photoRef} type="file" accept="image/jpeg,image/png,image/webp" hidden
                 onChange={(e) => sendPhoto(e.target.files?.[0] ?? null)} />
          <button type="button" className="btn-ghost" style={{ flex: "0 0 auto" }} disabled={busy}
                  onClick={() => photoRef.current?.click()} aria-label="Gửi ảnh bữa ăn hoặc phiếu xét nghiệm"
                  title="Gửi ảnh bữa ăn hoặc phiếu xét nghiệm">📎</button>
          <textarea ref={inputRef} aria-label="Câu hỏi" placeholder="Nhập, bấm micro để nói, hoặc 📎 gửi ảnh bữa ăn hay phiếu xét nghiệm..." value={input} maxLength={2000}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }} />
          <button className="btn-primary" style={{ flex: "0 0 auto" }} disabled={busy || !input.trim()}>Gửi</button>
        </form>
      </div>
    </>
  );
}
