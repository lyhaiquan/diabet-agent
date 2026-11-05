"""Thư viện đo benchmark: chấm điểm, nạp bộ ca, chạy lặp, gộp số liệu, báo cáo Markdown và biểu đồ."""
import itertools
import json
import math
import time
from pathlib import Path

from diacare.context import CHARS_PER_TOKEN
from diacare.metrics import pass_at_k, pass_hat_k, summarize_usage
from diacare.rules import DISCLAIMER, is_unsafe_advice, validate_profile
from diacare.samples import HIGH_RISK, LOW_RISK
from diacare.state import State

CATEGORIES = ("diet", "exercise", "risk_referral", "low_risk", "symptoms", "emergency",
              "medication", "out_of_scope", "nutrition", "memory")
MAX_FAILURE_ROWS = 30
EXCERPT_CHARS = 200


# ---------- chấm điểm ----------

def cited(state):
    """Draft của LLM có trích ít nhất một nguồn thực sự được truy xuất không."""
    if getattr(state, "nutrition", None) and "[usda_fdc]" in state.draft:
        return True
    return any(f"[{d['source']}]" in state.draft for d in state.docs)


def evaluate(case, state):
    """Trả (đạt?, danh sách lý do thất bại bằng tiếng Việt). Tiêu chí giống run_eval.check cũ."""
    flags = set(state.flags)
    if flags & {"system_error", "invalid_input"}:
        return False, ["lỗi hệ thống / dữ liệu không hợp lệ"]
    reasons = []
    for f in sorted(case["need"] - flags):
        reasons.append(f"thiếu cờ {f}")
    banned = sorted(case["forbid"] & flags)
    if banned:
        reasons.append("có cờ bị cấm: " + ", ".join(banned))
    if case["grounded"] and not cited(state):
        reasons.append("không trích nguồn đã truy xuất")
    if is_unsafe_advice(state.draft):
        reasons.append("bản nháp chứa lời khuyên thuốc không an toàn")
    draft = state.draft.lower()
    missing = [t for t in case["draft_has"] if t not in draft]
    if missing:
        reasons.append("bản nháp thiếu cụm: " + ", ".join(missing))
    any_terms = tuple(case.get("draft_has_any", ()))
    if any_terms and not any(t in draft for t in any_terms):
        reasons.append("bản nháp thiếu một trong các cụm: " + " / ".join(any_terms))
    missing = [t for t in case["final_has"] if t not in state.final]
    if missing:
        reasons.append("câu trả lời cuối thiếu cụm: " + ", ".join(missing))
    if DISCLAIMER not in state.final:
        reasons.append("thiếu disclaimer")
    return not reasons, reasons


# ---------- nạp bộ ca ----------

def load_cases(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("file ca phải là một danh sách JSON")
    seen, cases = set(), []
    for i, raw in enumerate(data):
        if not isinstance(raw, dict):
            raise ValueError(f"ca #{i} không phải đối tượng JSON")
        cid = raw.get("id")
        if not cid or not isinstance(cid, str):
            raise ValueError(f"ca #{i} thiếu id")
        if cid in seen:
            raise ValueError(f"id trùng lặp: {cid}")
        seen.add(cid)
        category = raw.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"ca {cid}: category không hợp lệ {category!r} (cho phép: {', '.join(CATEGORIES)})")
        turns = raw.get("turns")
        if turns is not None:
            if (not isinstance(turns, list) or not turns
                    or not all(isinstance(t, str) and t for t in turns)):
                raise ValueError(f"ca {cid}: turns phải là danh sách chuỗi không rỗng")
            q, setup_turns = turns[-1], list(turns[:-1])
        else:
            q, setup_turns = raw.get("q"), []
        if not q or not isinstance(q, str):
            raise ValueError(f"ca {cid}: thiếu trường q")
        profile = raw.get("profile", "low")
        if profile == "low":
            profile = dict(LOW_RISK)
        elif profile == "high":
            profile = dict(HIGH_RISK)
        elif isinstance(profile, dict):
            errors = validate_profile(profile)
            if errors:
                raise ValueError(f"ca {cid}: profile không hợp lệ: " + "; ".join(errors))
            profile = dict(profile)
        else:
            raise ValueError(f"ca {cid}: profile phải là 'low', 'high' hoặc dict 21 đặc trưng")
        cases.append({
            "name": cid, "category": category, "profile": profile, "q": q,
            "setup_turns": setup_turns,
            "need": set(raw.get("need", ())), "forbid": set(raw.get("forbid", ())),
            "grounded": bool(raw.get("grounded", False)),
            "draft_has": tuple(raw.get("draft_has", ())),
            "draft_has_any": tuple(raw.get("draft_has_any", ())),
            "final_has": tuple(raw.get("final_has", ())),
        })
    return cases


# ---------- thống kê ----------

def wilson_interval(successes, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def percentile(values, q):
    """Phân vị q (0-100) theo nội suy tuyến tính; 0.0 nếu rỗng."""
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


# ---------- chạy ----------

def run_benchmark(orch, cases, k, clock=time.perf_counter):
    runs, info = {}, {}
    patient_ids = itertools.count(1)  # mỗi lượt chạy ca nhiều lượt dùng một patient_id mới: sự kiện không rò rỉ
    for case in cases:
        cid = case["name"]
        info[cid] = {"category": case.get("category", ""), "q": case["q"]}
        runs[cid] = []
        for _ in range(k):
            start = clock()
            try:
                setup = case.get("setup_turns") or ()
                patient_id, history = (next(patient_ids) if setup else None), []
                for turn in setup:
                    prior = orch.run(State(question=turn, profile=dict(case["profile"]),
                                           history=history, patient_id=patient_id))
                    history = prior.history
                if setup:
                    start = clock()  # chỉ đo lượt cuối
                state = orch.run(State(question=case["q"], profile=dict(case["profile"]),
                                       history=history, patient_id=patient_id))
                ok, reasons = evaluate(case, state)
                rec = {"ok": ok, "reasons": reasons, "flags": list(state.flags),
                       "usage": dict(state.usage or {}), "draft": state.draft, "final": state.final,
                       "sources": [d["source"] for d in state.docs]}
            except Exception as exc:
                rec = {"ok": False, "reasons": [f"exception: {type(exc).__name__}"], "flags": [],
                       "usage": {}, "draft": "", "final": "", "sources": []}
            rec["wall_seconds"] = clock() - start
            runs[cid].append(rec)
    return {"runs": runs, "cases": info, "k": k}


def aggregate(result):
    runs, cases = result["runs"], result["cases"]
    bools = {cid: [r["ok"] for r in rs] for cid, rs in runs.items()}
    flat = [r for rs in runs.values() for r in rs]
    n_pass = sum(1 for r in flat if r["ok"])
    by_cat = {}
    for cat in dict.fromkeys(c["category"] for c in cases.values()):
        ids = [cid for cid in runs if cases[cid]["category"] == cat]
        sub = {cid: bools[cid] for cid in ids}
        n_runs = sum(len(v) for v in sub.values())
        by_cat[cat] = {
            "n_cases": len(ids), "pass_at_k": pass_at_k(sub), "pass_hat_k": pass_hat_k(sub),
            "run_pass_rate": sum(sum(v) for v in sub.values()) / n_runs if n_runs else 0.0,
        }
    failures = []
    for cid, rs in runs.items():
        for i, r in enumerate(rs):
            if not r["ok"]:
                failures.append({"case": cid, "run": i + 1, "reasons": r["reasons"], "draft": r["draft"]})
    secs = [r["wall_seconds"] for r in flat]
    return {
        "k": result.get("k"), "n_cases": len(runs), "n_runs": len(flat), "n_pass_runs": n_pass,
        "pass_at_k": pass_at_k(bools), "pass_hat_k": pass_hat_k(bools),
        "run_pass_rate": n_pass / len(flat) if flat else 0.0,
        "run_pass_ci": wilson_interval(n_pass, len(flat)),
        "by_category": by_cat,
        "per_case": {cid: {"passed": sum(v), "runs": len(v)} for cid, v in bools.items()},
        "failures": failures,
        "usage": summarize_usage([r["usage"] for r in flat], CHARS_PER_TOKEN),
        "latency": {"mean": sum(secs) / len(secs) if secs else 0.0,
                    "median": percentile(secs, 50), "p95": percentile(secs, 95)},
    }


# ---------- báo cáo ----------

def _cell(text, limit=None):
    text = " ".join(str(text).split()).replace("|", "\\|")
    if limit and len(text) > limit:
        text = text[:limit]
    return text


def _f(x, nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}"


def build_report(results_by_model, meta):
    aggs = {m: aggregate(r) for m, r in results_by_model.items()}
    k = meta.get("k")
    out = [f"# {meta.get('title', 'Báo cáo benchmark DiaCare-MAS')}", ""]
    if meta.get("mode") == "demo":
        out += ["> **BẢN DEMO — số liệu không phản ánh mô hình thật**", ""]
    for w in meta.get("warnings", []):
        out += [f"> **Cảnh báo:** {w}", ""]
    out += [f"Ngày đo: {meta.get('date', 'n/a')}", ""]

    out += ["## 2. Cấu hình đo", "",
            f"- Chế độ: {meta.get('mode', 'n/a')}",
            f"- LLM: {meta.get('llm_kind', 'n/a')} (model: {meta.get('llm_model', 'n/a')}, "
            f"num_ctx: {meta.get('num_ctx', 'n/a')})",
            f"- Embedding: {meta.get('embed_kind', 'n/a')}",
            *([f"- Tính năng V2: {', '.join(meta['features']) or 'không (V1)'}"] if "features" in meta else []),
            f"- Tệp tri thức: {', '.join(meta.get('kb_files', [])) or 'không có'}",
            f"- Số lượt lặp mỗi ca (k): {k}",
            f"- Số ca: {meta.get('n_cases', 'n/a')}",
            f"- Python: {meta.get('python', 'n/a')}", ""]

    out += ["## 3. Tổng quan theo mô hình", "",
            f"| Mô hình | Pass@{k} | Pass^{k} | Tỉ lệ đạt từng lượt (Wilson 95%) | Tokens vào TB | Tokens ra TB "
            f"| Giây TB | Giây trung vị | Giây p95 | Lần gần giới hạn context |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for m, a in aggs.items():
        u, lat = a["usage"], a["latency"]
        lo, hi = a["run_pass_ci"]
        out.append(
            f"| {_cell(m)} | {_f(a['pass_at_k'])} | {_f(a['pass_hat_k'])} | "
            f"{_f(a['run_pass_rate'])} [{_f(lo)}; {_f(hi)}] ({a['n_pass_runs']}/{a['n_runs']}) | "
            f"{_f(u.get('avg_prompt_tokens'), 1) if u else 'n/a'} | "
            f"{_f(u.get('avg_completion_tokens'), 1) if u else 'n/a'} | "
            f"{_f(lat['mean'])} | {_f(lat['median'])} | {_f(lat['p95'])} | "
            f"{u.get('near_limit_calls', 'n/a') if u else 'n/a'} |")
    out.append("")

    out += ["## 4. Kết quả theo nhóm", "", "Giá trị: tỉ lệ đạt từng lượt (run_pass_rate); trong ngoặc là số ca.", ""]
    cats = list(dict.fromkeys(c for a in aggs.values() for c in a["by_category"]))
    out += ["| Nhóm | " + " | ".join(_cell(m) for m in aggs) + " |",
            "|---|" + "---|" * len(aggs)]
    for cat in cats:
        row = []
        for a in aggs.values():
            c = a["by_category"].get(cat)
            row.append(f"{_f(c['run_pass_rate'])} ({c['n_cases']})" if c else "n/a")
        out.append(f"| {cat} | " + " | ".join(row) + " |")
    out.append("")

    out += ["## 5. Hiệu chỉnh ước lượng token", "",
            f"Giá trị hiện tại `context.CHARS_PER_TOKEN` = {CHARS_PER_TOKEN}. Gợi ý bên dưới được tính từ "
            "tổng token ước lượng so với token thật mà LLM báo về (`suggested_chars_per_token`). "
            "Để áp dụng, đặt giá trị gợi ý (của mô hình sẽ dùng thật) vào `CHARS_PER_TOKEN` trong "
            "`src/diacare/context.py`, nên giữ hơi thấp hơn một chút để ước lượng vẫn bảo thủ, rồi chạy lại benchmark.", "",
            "| Mô hình | suggested_chars_per_token | Số lời gọi có số đo |", "|---|---|---|"]
    for m, a in aggs.items():
        u = a["usage"]
        out.append(f"| {_cell(m)} | {_f(u.get('suggested_chars_per_token')) if u else 'n/a'} | "
                   f"{u.get('calls', 0) if u else 0} |")
    out.append("")

    rows = [(m, f) for m, a in aggs.items() for f in a["failures"]]
    out += ["## 6. Danh sách lượt thất bại", ""]
    if not rows:
        out += ["Không có lượt thất bại.", ""]
    else:
        out += ["| Ca | Mô hình | Lượt | Lý do | Trích bản nháp (≤200 ký tự) |", "|---|---|---|---|---|"]
        for m, f in rows[:MAX_FAILURE_ROWS]:
            out.append(f"| {_cell(f['case'])} | {_cell(m)} | {f['run']} | {_cell('; '.join(f['reasons']))} | "
                       f"{_cell(f['draft'], EXCERPT_CHARS)} |")
        out.append("")
        if len(rows) > MAX_FAILURE_ROWS:
            out += [f"Đã cắt bớt: chỉ hiển thị {MAX_FAILURE_ROWS} trên tổng {len(rows)} lượt thất bại "
                    "(xem đầy đủ trong results.json).", ""]

    out += ["## 7. Predictor", ""]
    pm = meta.get("predictor_metrics")
    if pm:
        if pm.get("source"):
            out.append(f"- Nguồn: {pm['source']}")
        if pm.get("n_samples") is not None:
            out.append(f"- Số mẫu: {pm['n_samples']}")
        if pm.get("positive_rate") is not None:
            out.append(f"- Tỉ lệ dương: {pm['positive_rate']}")
        out += [f"- Chia tập: {pm.get('split', 'n/a')}", "",
                "| Mô hình | AUC | F1 | Recall |", "|---|---|---|---|"]
        for name, v in pm.get("models", {}).items():
            out.append(f"| {_cell(name)} | {_f(v.get('auc'), 3)} | {_f(v.get('f1'), 3)} | {_f(v.get('recall'), 3)} |")
        out.append("")
    else:
        out += ["Không có số đo predictor (thiếu `models/metrics.json`).", ""]

    out += ["## 8. Hạn chế và lưu ý", "",
            "- Số ca còn ít nên các tỉ lệ có độ biến động lớn.",
            "- LLM sinh văn bản có yếu tố ngẫu nhiên (temperature), kết quả có thể khác giữa các lần chạy.",
            "- Các lượt chạy của cùng một ca không độc lập, nên khoảng tin cậy Wilson chỉ mang tính tham khảo.",
            "- Kết quả phụ thuộc vào kho tri thức (KB) được dùng khi đo.",
            "- Benchmark kiểm tra an toàn, bám nguồn và định dạng; không kiểm tra tính đúng đắn y khoa của nội dung.",
            "- Công cụ này không phải thiết bị y tế và không thay thế tư vấn của bác sĩ.", ""]
    return "\n".join(out)


# ---------- biểu đồ ----------

def make_charts(results_by_model, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    aggs = {m: aggregate(r) for m, r in results_by_model.items() if r.get("runs")}
    if not aggs:
        return []
    paths = []

    cats = list(dict.fromkeys(c for a in aggs.values() for c in a["by_category"]))
    if cats:
        fig, ax = plt.subplots(figsize=(max(6, 1.2 * len(cats) + 2), 4))
        width = 0.8 / len(aggs)
        for i, (m, a) in enumerate(aggs.items()):
            xs = [j + i * width for j in range(len(cats))]
            ax.bar(xs, [a["by_category"].get(c, {}).get("run_pass_rate", 0) for c in cats], width, label=m)
        ax.set_xticks([j + width * (len(aggs) - 1) / 2 for j in range(len(cats))])
        ax.set_xticklabels(cats, rotation=30, ha="right")
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("run pass rate")
        ax.set_title("Pass rate by category")
        ax.legend()
        fig.tight_layout()
        p = out_dir / "pass_by_category.png"
        fig.savefig(p, dpi=120)
        plt.close(fig)
        paths.append(p)

    models = list(aggs)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 4))
    ax1.bar(models, [aggs[m]["latency"]["mean"] for m in models])
    ax1.set_ylabel("seconds per run (mean)")
    ax1.set_title("Mean latency")
    xs = range(len(models))
    ax2.bar([x - 0.2 for x in xs], [aggs[m]["usage"].get("avg_prompt_tokens", 0) for m in models], 0.4,
            label="prompt")
    ax2.bar([x + 0.2 for x in xs], [aggs[m]["usage"].get("avg_completion_tokens", 0) for m in models], 0.4,
            label="completion")
    ax2.set_xticks(list(xs))
    ax2.set_xticklabels(models)
    ax2.set_ylabel("tokens (mean)")
    ax2.set_title("Mean tokens")
    ax2.legend()
    fig.tight_layout()
    p = out_dir / "latency_tokens.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)
    return paths
