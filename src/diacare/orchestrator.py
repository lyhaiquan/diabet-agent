import json
from datetime import datetime, timezone
from pathlib import Path

from diacare.advisor import advise
from diacare.context import build_context
from diacare.llm import DEFAULT_NUM_CTX
from diacare.nutrition import is_nutrition_question
from diacare.rules import apply_rules, validate_profile


class Orchestrator:
    def __init__(self, predictor, retriever, llm, log_path=None, store=None, session_id=None,
                 nutrition_agent=None):
        self.predictor = predictor
        self.retriever = retriever
        self.llm = llm
        self.log_path = Path(log_path) if log_path else None
        self.store = store
        self.session_id = session_id
        self.nutrition_agent = nutrition_agent

    def run(self, state):
        errors = validate_profile(state.profile)
        if errors:
            state.flags = ["invalid_input"]
            state.final = "Dữ liệu nhập chưa hợp lệ: " + "; ".join(errors)
            self._log(state)
            return state

        try:
            state.risk = self.predictor.predict(build_context("predictor", state)["profile"])
            state.docs = self.retriever.search(state.question)
            if self.nutrition_agent is not None:
                analysis = self.nutrition_agent.analyze(state.question)
                state.nutrition = analysis if is_nutrition_question(state.question, analysis) else None
            num_ctx = getattr(self.llm, "num_ctx", DEFAULT_NUM_CTX)
            ctx = build_context("advisor", state, num_ctx=num_ctx)
            state.draft = advise(ctx, self.llm)
            state.usage = dict(getattr(self.llm, "last_usage", None) or {})
            if state.usage:
                state.usage["est_prompt_tokens"] = ctx["est_tokens"]
            rule_ctx = build_context("rule", state)
            state.final, flags = apply_rules(rule_ctx["risk"], rule_ctx["draft"], rule_ctx["question"])
        except Exception as exc:
            state.flags = ["system_error"]
            state.final = "Hệ thống đang gặp sự cố, vui lòng thử lại sau."
            self._log(state, error=type(exc).__name__)
            return state
        state.flags = flags
        num_ctx = state.usage.get("num_ctx")
        if num_ctx and state.usage.get("prompt_tokens", 0) >= 0.9 * num_ctx:
            state.flags.append("context_near_limit")
        state.history = state.history + [
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
            "nutrition_items": [i["name"] for i in (state.nutrition or {}).get("items", [])],
        }
        if error:
            record["error"] = error
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
