"""CLI benchmark: python eval/benchmark.py --help"""
import argparse
import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from diacare import bench  # noqa: E402
from diacare.factory import ROOT, build_orchestrator, make_embed_fn, make_llm, parse_features  # noqa: E402
from diacare.kb import load_kb  # noqa: E402
from diacare.llm import DEFAULT_NUM_CTX  # noqa: E402

DEFAULT_CASES = ROOT / "eval" / "cases.json"
DEFAULT_METRICS = ROOT / "models" / "metrics.json"
OLLAMA_WARNING = "Ollama không phản hồi: kiểm tra `ollama serve` và tên model"


def _parse(argv):
    p = argparse.ArgumentParser(description="Đo benchmark DiaCare-MAS (Pass@k, Pass^k, token, độ trễ).")
    p.add_argument("--cases", default=str(DEFAULT_CASES))
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--models", nargs="+", default=None)
    p.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
    p.add_argument("--llm", choices=["ollama", "demo"], default=None)
    p.add_argument("--embed", choices=["sbert", "hash"], default=None)
    p.add_argument("--kb", default=None)
    p.add_argument("--features", default=None,
                   help="all | v1 | danh sách cách nhau dấu phẩy (mặc định: env DIACARE_FEATURES, rồi all)")
    p.add_argument("--out", default=None)
    p.add_argument("--predictor-metrics", default=str(DEFAULT_METRICS))
    return p.parse_args(argv)


def _all_runs_system_failure(result):
    runs = [r for rs in result["runs"].values() for r in rs]
    return bool(runs) and all(
        r["reasons"][:1] == ["lỗi hệ thống / dữ liệu không hợp lệ"]
        or (r["reasons"] and r["reasons"][0].startswith("exception:")) for r in runs if not r["ok"]
    ) and not any(r["ok"] for r in runs)


def main(argv=None):
    args = _parse(argv)
    kind = (args.llm or os.environ.get("DIACARE_LLM") or "ollama").lower()
    embed_kind = (args.embed or os.environ.get("DIACARE_EMBED") or "sbert").lower()
    models = ["demo"] if kind == "demo" else (
        args.models or [os.environ.get("DIACARE_MODEL") or "qwen2.5:3b"])
    now = datetime.now()
    out = Path(args.out) if args.out else ROOT / "reports" / f"benchmark_{now:%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    kb_dir = Path(args.kb or os.environ.get("DIACARE_KB") or ROOT / "kb")

    features = parse_features(args.features)
    cases = bench.load_cases(args.cases)
    embed_fn = make_embed_fn(embed_kind)  # tạo một lần cho cả tiến trình
    results, warnings = {}, []
    for model in models:
        llm = make_llm(kind, model=None if kind == "demo" else model, num_ctx=args.num_ctx)
        orch = build_orchestrator(kb_dir=kb_dir, log_path=out / f"runs_{model.replace(':', '_')}.jsonl",
                                  llm=llm, embed_fn=embed_fn, features=features, rl_epsilon_value=0)
        print(f"Đang đo mô hình {model} ({len(cases)} ca x {args.k} lượt)...", flush=True)
        results[model] = bench.run_benchmark(orch, cases, args.k)
        if kind == "ollama" and _all_runs_system_failure(results[model]):
            warnings.append(f"{OLLAMA_WARNING} (mô hình: {model})")

    meta = {
        "title": "Báo cáo benchmark DiaCare-MAS", "date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "demo" if kind == "demo" else "real", "llm_kind": kind, "llm_model": ", ".join(models),
        "num_ctx": args.num_ctx, "embed_kind": embed_kind,
        "kb_files": [name for name, _ in load_kb(kb_dir)], "k": args.k, "n_cases": len(cases),
        "python": platform.python_version(), "warnings": warnings, "features": sorted(features),
    }
    pm_path = Path(args.predictor_metrics)
    if pm_path.is_file():
        meta["predictor_metrics"] = json.loads(pm_path.read_text(encoding="utf-8"))

    report = bench.build_report(results, meta)
    (out / "report.md").write_text(report, encoding="utf-8")
    (out / "results.json").write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    bench.make_charts(results, out)

    print(f"\nBáo cáo: {out / 'report.md'}")
    for w in warnings:
        print("CẢNH BÁO:", w)
    for model, res in results.items():
        a = bench.aggregate(res)
        lo, hi = a["run_pass_ci"]
        print(f"{model}: Pass@{args.k}={a['pass_at_k']:.2f}  Pass^{args.k}={a['pass_hat_k']:.2f}  "
              f"tỉ lệ đạt từng lượt={a['run_pass_rate']:.2f} [{lo:.2f}; {hi:.2f}]  "
              f"giây TB={a['latency']['mean']:.2f}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
