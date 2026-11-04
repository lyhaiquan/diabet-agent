import json
from datetime import datetime, timezone
from pathlib import Path

from diacare.advisor import advise
from diacare.context import build_context
from diacare.rules import apply_rules, validate_profile


class Orchestrator:
    def __init__(self, predictor, retriever, llm, log_path=None):
        self.predictor = predictor
        self.retriever = retriever
        self.llm = llm
        self.log_path = Path(log_path) if log_path else None

    def run(self, state):
        errors = validate_profile(state.profile)
        if errors:
            state.flags = ["invalid_input"]
            state.final = "Dữ liệu nhập chưa hợp lệ: " + "; ".join(errors)
            self._log(state)
            return state

        state.risk = self.predictor.predict(build_context("predictor", state)["profile"])
        state.docs = self.retriever.search(state.question)
        state.draft = advise(build_context("advisor", state), self.llm)
        rule_ctx = build_context("rule", state)
        state.final, flags = apply_rules(rule_ctx["risk"], rule_ctx["draft"])
        state.flags = flags
        state.history += [
            {"role": "user", "content": state.question},
            {"role": "assistant", "content": state.final},
        ]
        self._log(state)
        return state

    def _log(self, state):
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
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
