"""Chấm lại offline bản nháp đã lưu của một lần benchmark ablation (thư mục chứa v1/ v2/ all/)
bằng bộ lọc thuốc + bộ đề HIỆN TẠI. Không gọi LLM, nên KHÔNG phản ánh thay đổi ở các agent
(Nutrition, Retriever...): muốn đo những thay đổi đó phải chạy lại benchmark.

Chạy:  python eval/rescore.py docs/results/2026-11-05_kaggle_run3_ablation
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.bench import aggregate, evaluate, load_cases  # noqa: E402
from diacare.rules import SAFE_REPLACEMENT, is_unsafe_advice  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
D = sys.argv[1]
cases = {c["name"]: c for c in load_cases(ROOT / "eval" / "cases.json")}
out = {}
for f in ("v1", "v2", "all"):
    res = json.load(open(f"{D}/{f}/results.json", encoding="utf-8"))["results"]["qwen2.5:7b"]
    runs = {}
    for cid, rs in res["runs"].items():
        new = []
        for r in rs:
            flags = [x for x in r["flags"] if x != "unsafe_advice_blocked"]
            final = r["final"]
            if is_unsafe_advice(r["draft"]):
                flags.append("unsafe_advice_blocked")
            elif final.startswith(SAFE_REPLACEMENT):
                final = r["draft"] + final[len(SAFE_REPLACEMENT):]
            st = SimpleNamespace(flags=flags, draft=r["draft"], final=final,
                                 docs=[{"source": s} for s in r["sources"]],
                                 nutrition=(f != "v1") or None)
            ok, reasons = evaluate(cases[cid], st)
            new.append(dict(r, ok=ok, reasons=reasons, flags=flags, final=final))
        runs[cid] = new
    agg = aggregate({"runs": runs, "cases": cases, "k": res["k"]})
    old = aggregate({"runs": res["runs"], "cases": cases, "k": res["k"]})
    out[f] = {"old": old, "new": agg}
    print(f"== {f}: Pass@3 {old['pass_at_k']:.2f}->{agg['pass_at_k']:.2f} | Pass^3 {old['pass_hat_k']:.2f}->"
          f"{agg['pass_hat_k']:.2f} | run {old['run_pass_rate']:.3f}->{agg['run_pass_rate']:.3f} "
          f"({agg['n_pass_runs']}/{agg['n_runs']}) CI {agg['run_pass_ci'][0]:.2f}-{agg['run_pass_ci'][1]:.2f}")
    print("   ", {k: round(v["run_pass_rate"], 2) for k, v in agg["by_category"].items()})
    for fl in agg["failures"]:
        print("    x", fl["case"], fl["run"], "; ".join(fl["reasons"])[:90])
json.dump({f: {k: {kk: vv for kk, vv in v.items() if kk != "failures"} for k, v in d.items()} for f, d in out.items()},
          open(f"{D}/rescore_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
