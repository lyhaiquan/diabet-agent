import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from diacare.advisor import advise
from diacare.context import HISTORY_TOKEN_BUDGET, build_context, estimate_tokens
from diacare.critic import check_grounding, describe as describe_grounding
from diacare.contracts import (MODEL_VERSION, SYSTEM_VERSION, PatientDataAgent, build_decision_report,
                               evaluate_pre_rules, make_message, new_request_id)
from diacare.guard import filter_docs, injection_signals
from diacare.llm import DEFAULT_NUM_CTX
from diacare.labs import parse_lab_text
from diacare.memory import SummaryCache, compress_history, has_diagnosis
from diacare.nutrition import is_nutrition_question
from diacare.rules import (DISCLAIMER, HIGH_RISK_NOTE, HIGH_RISK_THRESHOLD, LAB_NOTES, SMALL_TALK_REPLY,
                           apply_rules, is_small_talk, risk_band)

# Hỏi thẳng về nguy cơ / khám thì nhắc lại lời khuyên đi khám dù đã nhắc trong phiên.
_RISK_WORDS = ("nguy cơ", "có bị", "xét nghiệm", "đi khám", "risk")


class _Tracer:
    """Ghi từng bước agent vào state.trace (thời gian tính từ bước trước) và báo ra ngoài qua on_step."""

    def __init__(self, state, on_step=None):
        self.state, self.on_step, self.t = state, on_step, time.perf_counter()
        state.trace = []

    def __call__(self, agent, detail, ms=None):
        """ms: thời gian riêng của bước (các agent chạy song song tự đo); bỏ trống thì tính từ bước trước."""
        now = time.perf_counter()
        entry = {"agent": agent, "detail": detail, "ms": round((now - self.t) * 1000, 1) if ms is None else ms}
        self.t = now
        self.state.trace.append(entry)
        if self.on_step is not None:
            try:
                self.on_step(entry)
            except Exception:  # lỗi hiển thị không được làm hỏng pipeline
                pass


def _timed(fn):
    t = time.perf_counter()
    try:
        return fn(), round((time.perf_counter() - t) * 1000, 1), None
    except Exception as exc:  # trả lỗi về cho Orchestrator quyết định: agent bắt buộc thì dừng, agent phụ thì bỏ qua
        return None, round((time.perf_counter() - t) * 1000, 1), exc


def _short(items, n=3):
    items = list(items)
    return ", ".join(items[:n]) + (f" (+{len(items) - n})" if len(items) > n else "")


class Orchestrator:
    def __init__(self, predictor, retriever, llm, log_path=None, store=None, session_id=None,
                 nutrition_agent=None, memory_agent=None, summarizer_llm=None, lab_agent=None,
                 graph_agent=None, rl_agent=None, data_agent=None, journal_agent=None, parallel=None):
        # Predictor, Retriever, Graph, Nutrition không phụ thuộc nhau nên chạy song song (tắt: DIACARE_PARALLEL=0)
        self.parallel = (os.environ.get("DIACARE_PARALLEL", "1") != "0") if parallel is None else bool(parallel)
        self.predictor = predictor
        self.retriever = retriever
        self.llm = llm
        self.log_path = Path(log_path) if log_path else None
        self.store = store
        self.session_id = session_id
        self.nutrition_agent = nutrition_agent
        self.memory_agent = memory_agent
        self.lab_agent = lab_agent
        self.journal_agent = journal_agent
        self.graph_agent = graph_agent
        self.rl_agent = rl_agent
        self.data_agent = data_agent or PatientDataAgent()
        self.summarizer_llm = summarizer_llm if summarizer_llm is not None else (
            llm if memory_agent is not None else None)

    def run(self, state, on_token=None, on_step=None):
        """on_token: nhận từng đoạn bản nháp khi LLM đang viết (giao diện dùng để hiện chữ dần).
        on_step: nhận mỗi bước agent {agent, detail, ms} ngay khi bước đó xong."""
        step = _Tracer(state, on_step)
        req_id = state.request_id or new_request_id()
        state.request_id = req_id
        state.messages = []

        data_res = self.data_agent.validate(state.profile)
        errors = data_res["errors"]
        state.messages.append(make_message(
            req_id, "PatientDataAgent", "error" if errors else "ok",
            {"valid": data_res["valid"], "errors": errors},
        ))
        if errors:
            step("Orchestrator", f"hồ sơ không hợp lệ ({len(errors)} lỗi), dừng")
            state.flags = ["invalid_input"]
            state.final = "Dữ liệu nhập chưa hợp lệ: " + "; ".join(errors)
            state.report = build_decision_report(state, request_id=req_id)
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
            state.report = build_decision_report(state, request_id=req_id)
            self._log(state)
            return state
        summary_usage, summarised = None, False
        try:
            if self.memory_agent is not None and state.patient_id is not None:
                upd = self.memory_agent.update(state.patient_id, state.question)
                learned, retracted = upd["learned"], upd["retracted"]
                state.memory = self.memory_agent.recall(state.patient_id)
                new = f"ghi nhận {len(learned)} thông tin mới, " if learned else ""
                new += f"thôi ghi nhớ {_short(c for _, c in retracted)}, " if retracted else ""
                step("Memory", f"{new}nhớ {len(state.memory)} thông tin về bệnh nhân"
                     + (f": {_short(m['content'] for m in state.memory)}" if state.memory else ""))
            if self.memory_agent is not None:
                try:
                    cache = (SummaryCache(self.store, self.session_id)
                             if self.store is not None and self.session_id is not None else None)
                    compressed, summarised = compress_history(
                        full_history, self.summarizer_llm, HISTORY_TOKEN_BUDGET, estimate_tokens, cache=cache)
                except Exception:  # tóm tắt hỏng thì dùng lịch sử gốc (sẽ bị cắt như V1)
                    compressed, summarised = full_history, False
                if summarised:
                    mode = compress_history.last_mode
                    step("Memory", {"reused": "lịch sử dài: dùng lại bản tóm tắt đã lưu, không gọi LLM",
                                    "incremental": "lịch sử dài: tóm tắt thêm các tin mới vào bản đã lưu"}.get(
                        mode, f"lịch sử dài: tóm tắt {len(full_history)} tin nhắn để vừa ngữ cảnh"))
                    state.history = compressed
                    if mode != "reused":
                        summary_usage = dict(getattr(self.summarizer_llm, "last_usage", None) or {})
            if self.lab_agent is not None:
                state.labs = self.lab_agent.collect(state.patient_id, state.question)
                step("Lab", _short(f"{r['label']} {r['value_std']:g} {r['unit_std']} → {r['level']}"
                                   for r in state.labs) if state.labs else "không có kết quả xét nghiệm")
            if self.journal_agent is not None:
                state.journal = self.journal_agent.collect(state.patient_id)
                j = state.journal
                step("Journal", (f"nhật ký 14 ngày: {j['n_glucose']} lần đo đường huyết"
                                 + (f", {j['hypo']} lần hạ" if j["hypo"] else "")
                                 + (f", {j['very_high']} lần rất cao" if j["very_high"] else ""))
                     if j else "chưa có nhật ký tự theo dõi")
            # Bốn agent chỉ đọc câu hỏi / hồ sơ và ghi mỗi agent một trường riêng của State: chạy song song.
            # Predictor và Retriever là bắt buộc (lỗi thì dừng lượt); Graph và Nutrition là phụ (lỗi thì bỏ qua).
            profile, question = build_context("predictor", state)["profile"], state.question
            jobs = {"predictor": lambda: self.predictor.predict(profile),
                    "retriever": lambda: self.retriever.search(question)}
            if self.graph_agent is not None:
                jobs["graph"] = lambda: self.graph_agent.lookup(question)
            if self.nutrition_agent is not None:
                jobs["nutrition"] = lambda: self.nutrition_agent.analyze(question)
            res = self._run_jobs(jobs)
            for name in ("predictor", "retriever"):
                if res[name][2] is not None:
                    raise res[name][2]

            state.risk = res["predictor"][0]
            kind = "mô hình đa nguồn" if getattr(self.predictor, "kind", "") == "multisource" else "MLP"
            step("Predictor", f"{kind} trên 21 chỉ số hồ sơ: {state.risk:.1%} → nguy cơ {risk_band(state.risk)}",
                 ms=res["predictor"][1])
            state.messages.append(make_message(
                req_id, "DiabetesPredictionAgent", "ok",
                {"prediction": int(state.risk >= HIGH_RISK_THRESHOLD), "score": round(float(state.risk), 4),
                 "risk_band": risk_band(state.risk)},
                model_version=MODEL_VERSION,
            ))

            # Suy diễn luật tiền xử lý (Mục 5.3 Bước 7: Rule Agent đánh giá trên features + prediction trước Explanation)
            state.pre_rules = evaluate_pre_rules(
                state.risk, state.profile, state.question,
                diagnosed=has_diagnosis(state.memory), labs=state.labs,
            )
            state.messages.append(make_message(
                req_id, "RuleBasedAgent", "ok", state.pre_rules,
            ))

            # Đoạn tài liệu có câu ra lệnh cho mô hình (kho bị chèn nội dung) không được tới Advisor
            state.docs, poisoned = filter_docs(res["retriever"][0])
            step("Retriever", (f"{len(state.docs)} đoạn tài liệu: {_short(d['source'] for d in state.docs)}"
                               if state.docs else "không tìm thấy tài liệu phù hợp")
                 + (f"; loại {len(poisoned)} đoạn có câu ra lệnh cho mô hình ({_short(d['source'] for d in poisoned)})"
                    if poisoned else ""), ms=res["retriever"][1])
            guard_flags = (["kb_injection_filtered"] if poisoned else []) + (
                ["prompt_injection_suspected"] if injection_signals(state.question) else [])
            if "graph" in res:
                kg, ms, err = res["graph"]
                if err is not None:
                    step("Graph", f"lỗi {type(err).__name__}, bỏ qua đồ thị tri thức", ms=ms)
                    state.messages.append(make_message(req_id, "KnowledgeGraphRAGAgent", "error",
                                                       {"error": type(err).__name__}))
                else:
                    state.kg = kg
                    step("Graph", f"{kg['backend']}: " + (
                        "yếu tố " + _short(kg["factors"]) if kg["factors"]
                        else "câu hỏi không nhắc tới yếu tố nguy cơ nào trong đồ thị"), ms=ms)
            state.messages.append(make_message(
                req_id, "KnowledgeGraphRAGAgent", "ok",
                {"docs_count": len(state.docs), "kg_factors": list((state.kg or {}).get("factors", []))},
                evidence=[d["source"] for d in state.docs],
            ))
            if "nutrition" in res:
                analysis, ms, err = res["nutrition"]
                if err is not None:
                    step("Nutrition", f"lỗi {type(err).__name__}, bỏ qua phân tích dinh dưỡng", ms=ms)
                else:
                    state.nutrition = analysis if is_nutrition_question(state.question, analysis) else None
                    step("Nutrition", "tra USDA: " + _short(i["name"] for i in state.nutrition["items"])
                         if state.nutrition else "không phải câu hỏi dinh dưỡng, bỏ qua", ms=ms)
            if self.rl_agent is not None:
                try:
                    state.rl = self.rl_agent.recommend(state)
                except Exception as exc:  # agent phụ: mất định hướng trọng tâm thì vẫn trả lời được
                    state.rl = None
                    step("RL", f"lỗi {type(exc).__name__}, bỏ qua định hướng trọng tâm")
                else:
                    step("RL", f"{state.rl['mode']}: {state.rl['label']} (điểm {state.rl['q_value']:+.2f}, "
                               f"chính sách {state.rl['policy_version']})")
                    state.messages.append(make_message(req_id, "RLAgent", "ok", state.rl))
            num_ctx = getattr(self.llm, "num_ctx", DEFAULT_NUM_CTX)
            ctx = build_context("advisor", state, num_ctx=num_ctx)
            step("Context", f"ghép ngữ cảnh cho Advisor: ~{ctx['est_tokens']} token / num_ctx {num_ctx}")
            state.draft = advise(ctx, self.llm, on_token=on_token)
            state.usage = dict(getattr(self.llm, "last_usage", None) or {})
            u = state.usage
            step("Advisor", f"LLM viết bản nháp: {u.get('prompt_tokens', '?')} token vào, "
                            f"{u.get('completion_tokens', '?')} token ra" if u else "LLM viết bản nháp")
            try:  # Critic chỉ đo và gắn cờ; lỗi ở đây không được chặn câu trả lời
                state.grounding = check_grounding(state.draft, ctx)
                step("Critic", "đối chiếu bản nháp với ngữ cảnh: " + describe_grounding(state.grounding))
            except Exception as exc:
                state.grounding = None
                step("Critic", f"lỗi {type(exc).__name__}, bỏ qua kiểm tra căn cứ")
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
            flags += [f for f in guard_flags + (state.grounding or {}).get("flags", []) if f not in flags]
            state.messages.append(make_message(
                req_id, "ExplanationAgent", "ok",
                {"draft": state.draft, "final": state.final},
                evidence=[d["source"] for d in state.docs],
            ))
        except Exception as exc:
            step("Orchestrator", f"lỗi {type(exc).__name__}, trả lời thông báo sự cố")
            state.history = full_history
            state.flags = ["system_error"]
            state.final = "Hệ thống đang gặp sự cố, vui lòng thử lại sau."
            state.messages.append(make_message(req_id, "MonitoringAgent", "error", {"error": type(exc).__name__}))
            state.report = build_decision_report(state, request_id=req_id)
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
        state.report = build_decision_report(state, request_id=req_id)
        state.messages.append(make_message(
            req_id, "MonitoringAgent", "ok",
            {"flags": state.report["rules"]["flags"], "steps": len(state.trace), "usage": state.usage},
        ))
        self._log(state)
        return state

    def _run_jobs(self, jobs):
        """Chạy các việc độc lập, trả {tên: (kết quả, ms, lỗi)}. Song song bằng luồng khi self.parallel."""
        if not self.parallel or len(jobs) < 2:
            return {name: _timed(fn) for name, fn in jobs.items()}
        with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="agent") as pool:
            futures = {name: pool.submit(_timed, fn) for name, fn in jobs.items()}
            return {name: f.result() for name, f in futures.items()}

    def _log(self, state, error=None):
        self._log_file(state, error)
        run_id = None
        if self.store is not None:
            try:
                run_id = self.store.log_run(self.session_id, state, error)
            except Exception:
                pass
        if self.rl_agent is not None and state.rl and not error:
            try:  # ghi quyết định RL để người dùng chấm và agent học (không có store thì bỏ qua)
                state.rl["event_id"] = self.rl_agent.record(state.rl, self.session_id, run_id)
            except Exception:
                pass

    def _log_file(self, state, error=None):
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": state.request_id,
            "model_version": MODEL_VERSION,
            "system_version": SYSTEM_VERSION,
            "question": state.question,
            "risk": state.risk,
            "sources": [d["source"] for d in state.docs],
            "flags": state.flags,
            "review_flags": (state.pre_rules or {}).get("review_flags", []),
            "final_chars": len(state.final),
            "usage": state.usage,
            "memory_kinds": [m["kind"] for m in state.memory],
            "nutrition_items": [i["name"] for i in (state.nutrition or {}).get("items", [])],
            "lab_levels": {r["test"]: r["level"] for r in state.labs},
            "kg_factors": (state.kg or {}).get("factors", []),
            "rl_action": (state.rl or {}).get("action"),
            "grounding": state.grounding,
            "trace": state.trace,
        }
        if error:
            record["error"] = error
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
