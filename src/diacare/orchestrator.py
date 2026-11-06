import json
import time
from datetime import datetime, timezone
from pathlib import Path

from diacare.advisor import advise
from diacare.context import HISTORY_TOKEN_BUDGET, build_context, estimate_tokens
from diacare.llm import DEFAULT_NUM_CTX
from diacare.labs import parse_lab_text
from diacare.memory import compress_history
from diacare.nutrition import is_nutrition_question
from diacare.rules import (DISCLAIMER, HIGH_RISK_NOTE, LAB_NOTES, SMALL_TALK_REPLY, apply_rules,
                           is_small_talk, risk_band, validate_profile)

# Hỏi thẳng về nguy cơ / khám thì nhắc lại lời khuyên đi khám dù đã nhắc trong phiên.
_RISK_WORDS = ("nguy cơ", "có bị", "xét nghiệm", "đi khám", "risk")


class _Tracer:
    """Ghi từng bước agent vào state.trace (thời gian tính từ bước trước) và báo ra ngoài qua on_step."""

    def __init__(self, state, on_step=None):
        self.state, self.on_step, self.t = state, on_step, time.perf_counter()
        state.trace = []

    def __call__(self, agent, detail):
        now = time.perf_counter()
        entry = {"agent": agent, "detail": detail, "ms": round((now - self.t) * 1000, 1)}
        self.t = now
        self.state.trace.append(entry)
        if self.on_step is not None:
            try:
                self.on_step(entry)
            except Exception:  # lỗi hiển thị không được làm hỏng pipeline
                pass


def _short(items, n=3):
    items = list(items)
    return ", ".join(items[:n]) + (f" (+{len(items) - n})" if len(items) > n else "")


class Orchestrator:
    def __init__(self, predictor, retriever, llm, log_path=None, store=None, session_id=None,
                 nutrition_agent=None, memory_agent=None, summarizer_llm=None, lab_agent=None,
                 graph_agent=None):
        self.predictor = predictor
        self.retriever = retriever
        self.llm = llm
        self.log_path = Path(log_path) if log_path else None
        self.store = store
        self.session_id = session_id
        self.nutrition_agent = nutrition_agent
        self.memory_agent = memory_agent
        self.lab_agent = lab_agent
        self.graph_agent = graph_agent
        self.summarizer_llm = summarizer_llm if summarizer_llm is not None else (
            llm if memory_agent is not None else None)

    def run(self, state, on_token=None, on_step=None):
        """on_token: nhận từng đoạn bản nháp khi LLM đang viết (giao diện dùng để hiện chữ dần).
        on_step: nhận mỗi bước agent {agent, detail, ms} ngay khi bước đó xong."""
        step = _Tracer(state, on_step)
        errors = validate_profile(state.profile)
        if errors:
            step("Orchestrator", f"hồ sơ không hợp lệ ({len(errors)} lỗi), dừng")
            state.flags = ["invalid_input"]
            state.final = "Dữ liệu nhập chưa hợp lệ: " + "; ".join(errors)
            self._log(state)
            return state

        full_history = state.history
        if is_small_talk(state.question):
            step("Orchestrator", "câu chào hỏi: trả lời ngay, không dự đoán nguy cơ, không gọi LLM")
            state.flags = ["small_talk"]
            state.final = SMALL_TALK_REPLY + "\n\n" + DISCLAIMER
            state.history = full_history + [
                {"role": "user", "content": state.question},
                {"role": "assistant", "content": state.final},
            ]
            self._log(state)
            return state
        summary_usage, summarised = None, False
        try:
            if self.memory_agent is not None and state.patient_id is not None:
                learned = self.memory_agent.observe(state.patient_id, state.question)
                state.memory = self.memory_agent.recall(state.patient_id)
                new = f"ghi nhận {len(learned)} thông tin mới, " if learned else ""
                step("Memory", f"{new}nhớ {len(state.memory)} thông tin về bệnh nhân"
                     + (f": {_short(m['content'] for m in state.memory)}" if state.memory else ""))
            if self.memory_agent is not None:
                try:
                    compressed, summarised = compress_history(
                        full_history, self.summarizer_llm, HISTORY_TOKEN_BUDGET, estimate_tokens)
                except Exception:  # tóm tắt hỏng thì dùng lịch sử gốc (sẽ bị cắt như V1)
                    compressed, summarised = full_history, False
                if summarised:
                    step("Memory", f"lịch sử dài: tóm tắt {len(full_history)} tin nhắn để vừa ngữ cảnh")
                    state.history = compressed
                    summary_usage = dict(getattr(self.summarizer_llm, "last_usage", None) or {})
            if self.lab_agent is not None:
                state.labs = self.lab_agent.collect(state.patient_id, state.question)
                step("Lab", _short(f"{r['label']} {r['value_std']:g} {r['unit_std']} → {r['level']}"
                                   for r in state.labs) if state.labs else "không có kết quả xét nghiệm")
            state.risk = self.predictor.predict(build_context("predictor", state)["profile"])
            step("Predictor", f"MLP trên 21 chỉ số hồ sơ BRFSS: {state.risk:.1%} → nguy cơ {risk_band(state.risk)}")
            state.docs = self.retriever.search(state.question)
            step("Retriever", f"{len(state.docs)} đoạn tài liệu: {_short(d['source'] for d in state.docs)}"
                 if state.docs else "không tìm thấy tài liệu phù hợp")
            if self.graph_agent is not None:
                state.kg = self.graph_agent.lookup(state.question)
                step("Graph", f"{state.kg['backend']}: " + (
                    "yếu tố " + _short(state.kg["factors"]) if state.kg["factors"]
                    else "câu hỏi không nhắc tới yếu tố nguy cơ nào trong đồ thị"))
            if self.nutrition_agent is not None:
                analysis = self.nutrition_agent.analyze(state.question)
                state.nutrition = analysis if is_nutrition_question(state.question, analysis) else None
                step("Nutrition", "tra USDA: " + _short(i["name"] for i in state.nutrition["items"])
                     if state.nutrition else "không phải câu hỏi dinh dưỡng, bỏ qua")
            num_ctx = getattr(self.llm, "num_ctx", DEFAULT_NUM_CTX)
            ctx = build_context("advisor", state, num_ctx=num_ctx)
            step("Context", f"ghép ngữ cảnh cho Advisor: ~{ctx['est_tokens']} token / num_ctx {num_ctx}")
            state.draft = advise(ctx, self.llm, on_token=on_token)
            state.usage = dict(getattr(self.llm, "last_usage", None) or {})
            u = state.usage
            step("Advisor", f"LLM viết bản nháp: {u.get('prompt_tokens', '?')} token vào, "
                            f"{u.get('completion_tokens', '?')} token ra" if u else "LLM viết bản nháp")
            if summary_usage:
                state.usage["summary_prompt_tokens"] = summary_usage.get("prompt_tokens")
                state.usage["summary_completion_tokens"] = summary_usage.get("completion_tokens")
            if state.usage:
                state.usage["est_prompt_tokens"] = ctx["est_tokens"]
            rule_ctx = build_context("rule", state)
            already = any(HIGH_RISK_NOTE in m.get("content", "") for m in full_history
                          if m.get("role") == "assistant")
            asks_risk = any(w in state.question.lower() for w in _RISK_WORDS)
            # nhận xét xét nghiệm: nhắc khi người dùng vừa đưa số liệu, hoặc chưa nhắc lần nào trong phiên
            lab_noted = any(n in m.get("content", "") for m in full_history if m.get("role") == "assistant"
                            for n in LAB_NOTES.values())
            labs_for_rules = rule_ctx["labs"] if (parse_lab_text(state.question) or not lab_noted) else []
            state.final, flags = apply_rules(
                rule_ctx["risk"], rule_ctx["draft"], rule_ctx["question"], diagnosed=rule_ctx["diagnosed"],
                remind_risk=asks_risk or not already, labs=labs_for_rules)
            step("Rules", "kiểm tra an toàn: " + (", ".join(flags) if flags else "không bật cờ nào"))
        except Exception as exc:
            step("Orchestrator", f"lỗi {type(exc).__name__}, trả lời thông báo sự cố")
            state.history = full_history
            state.flags = ["system_error"]
            state.final = "Hệ thống đang gặp sự cố, vui lòng thử lại sau."
            self._log(state, error=type(exc).__name__)
            return state
        state.flags = flags
        num_ctx = state.usage.get("num_ctx")
        if num_ctx and state.usage.get("prompt_tokens", 0) >= 0.9 * num_ctx:
            state.flags.append("context_near_limit")
        if summarised:
            state.flags.append("history_summarized")
        state.history = full_history + [
            {"role": "user", "content": state.question},
            {"role": "assistant", "content": state.final},
        ]
        self._log(state)
        return state

    def _log(self, state, error=None):
        self._log_file(state, error)
        if self.store is not None:
            try:
                self.store.log_run(self.session_id, state, error)
            except Exception:
                pass

    def _log_file(self, state, error=None):
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "question": state.question,
            "risk": state.risk,
            "sources": [d["source"] for d in state.docs],
            "flags": state.flags,
            "final_chars": len(state.final),
            "usage": state.usage,
            "memory_kinds": [m["kind"] for m in state.memory],
            "nutrition_items": [i["name"] for i in (state.nutrition or {}).get("items", [])],
            "lab_levels": {r["test"]: r["level"] for r in state.labs},
            "kg_factors": (state.kg or {}).get("factors", []),
            "trace": state.trace,
        }
        if error:
            record["error"] = error
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
