import json
from datetime import datetime, timezone
from pathlib import Path

from diacare.advisor import advise
from diacare.context import HISTORY_TOKEN_BUDGET, build_context, estimate_tokens
from diacare.llm import DEFAULT_NUM_CTX
from diacare.memory import compress_history
from diacare.nutrition import is_nutrition_question
from diacare.rules import apply_rules, validate_profile


class Orchestrator:
    def __init__(self, predictor, retriever, llm, log_path=None, store=None, session_id=None,
                 nutrition_agent=None, memory_agent=None, summarizer_llm=None):
        self.predictor = predictor
        self.retriever = retriever
        self.llm = llm
        self.log_path = Path(log_path) if log_path else None
        self.store = store
        self.session_id = session_id
        self.nutrition_agent = nutrition_agent
        self.memory_agent = memory_agent
        self.summarizer_llm = summarizer_llm if summarizer_llm is not None else (
            llm if memory_agent is not None else None)

    def run(self, state):
        errors = validate_profile(state.profile)
        if errors:
            state.flags = ["invalid_input"]
            state.final = "Dữ liệu nhập chưa hợp lệ: " + "; ".join(errors)
            self._log(state)
            return state

        full_history = state.history
        summary_usage, summarised = None, False
        try:
            if self.memory_agent is not None and state.patient_id is not None:
                self.memory_agent.observe(state.patient_id, state.question)
                state.memory = self.memory_agent.recall(state.patient_id)
            if self.memory_agent is not None:
                try:
                    compressed, summarised = compress_history(
                        full_history, self.summarizer_llm, HISTORY_TOKEN_BUDGET, estimate_tokens)
                except Exception:  # tóm tắt hỏng thì dùng lịch sử gốc (sẽ bị cắt như V1)
                    compressed, summarised = full_history, False
                if summarised:
                    state.history = compressed
                    summary_usage = dict(getattr(self.summarizer_llm, "last_usage", None) or {})
            state.risk = self.predictor.predict(build_context("predictor", state)["profile"])
            state.docs = self.retriever.search(state.question)
            if self.nutrition_agent is not None:
                analysis = self.nutrition_agent.analyze(state.question)
                state.nutrition = analysis if is_nutrition_question(state.question, analysis) else None
            num_ctx = getattr(self.llm, "num_ctx", DEFAULT_NUM_CTX)
            ctx = build_context("advisor", state, num_ctx=num_ctx)
            state.draft = advise(ctx, self.llm)
            state.usage = dict(getattr(self.llm, "last_usage", None) or {})
            if summary_usage:
                state.usage["summary_prompt_tokens"] = summary_usage.get("prompt_tokens")
                state.usage["summary_completion_tokens"] = summary_usage.get("completion_tokens")
            if state.usage:
                state.usage["est_prompt_tokens"] = ctx["est_tokens"]
            rule_ctx = build_context("rule", state)
            state.final, flags = apply_rules(
                rule_ctx["risk"], rule_ctx["draft"], rule_ctx["question"], diagnosed=rule_ctx["diagnosed"])
        except Exception as exc:
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
        }
        if error:
            record["error"] = error
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
