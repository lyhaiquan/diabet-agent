"""So sánh cặp hai cấu hình benchmark trên cùng bộ ca bằng kiểm định McNemar chính xác.

Mỗi vế là `đường_dẫn/results.json[::tên_mô_hình]` (bỏ tên mô hình nếu tệp chỉ có một mô hình). Không gọi LLM.
Một ca được tính là đạt khi đạt ở MỌI lượt (Pass^k); các lượt của cùng một ca không độc lập nên không ghép cặp
theo lượt. Thêm --rescore để chấm lại bản nháp đã lưu bằng tiêu chí hiện tại trước khi so (như eval/rescore.py).

    python eval/compare.py docs/results/2026-11-05_kaggle_run3_ablation/v1/results.json \
                           docs/results/2026-11-05_kaggle_run3_ablation/v2/results.json --rescore
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.bench import load_cases, rescore_record  # noqa: E402
from diacare.metrics import paired_outcomes  # noqa: E402


def load_side(spec, cases=None):
    """Trả (nhãn, {ca: [đạt?, ...]}). cases: bộ ca hiện tại để chấm lại, None = dùng kết quả đã lưu."""
    path, _, model = spec.partition("::")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    results = data["results"]
    if not model:
        if len(results) != 1:
            raise SystemExit(f"{path} có nhiều mô hình ({', '.join(results)}): ghi rõ bằng {path}::tên_mô_hình")
        model = next(iter(results))
    if model not in results:
        raise SystemExit(f"{path} không có mô hình {model!r} (có: {', '.join(results)})")
    features = data.get("meta", {}).get("features")
    nutrition = features is None or "nutrition" in features
    out = {}
    for cid, runs in results[model]["runs"].items():
        if cases is not None and cid in cases:
            out[cid] = [rescore_record(cases[cid], r, nutrition=nutrition)[0] for r in runs]
        else:
            out[cid] = [r["ok"] for r in runs]
    label = f"{Path(path).parent.name}/{model}"
    return label, out


def compare(spec_a, spec_b, rescore=False, category=None):
    cases = {c["name"]: c for c in load_cases(ROOT / "eval" / "cases.json")} if rescore or category else None
    la, a = load_side(spec_a, cases if rescore else None)
    lb, b = load_side(spec_b, cases if rescore else None)
    if category:
        keep = {cid for cid, c in cases.items() if c["category"] in category}
        a = {k: v for k, v in a.items() if k in keep}
        b = {k: v for k, v in b.items() if k in keep}
    return la, lb, paired_outcomes(a, b)


def main(argv=None):
    p = argparse.ArgumentParser(description="Kiểm định McNemar cho hai kết quả benchmark trên cùng bộ ca.")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--rescore", action="store_true", help="chấm lại bằng tiêu chí hiện tại trước khi so")
    p.add_argument("--category", nargs="+", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    la, lb, r = compare(args.a, args.b, args.rescore, args.category)
    if args.json:
        print(json.dumps({"a": la, "b": lb, **r}, ensure_ascii=False, indent=1))
        return 0
    print(f"A = {la}\nB = {lb}\nSố ca chung: {r['n_cases']} (đạt = đạt mọi lượt)")
    print(f"  cả hai đạt: {r['both']} | chỉ A đạt: {r['only_a']} | chỉ B đạt: {r['only_b']} | "
          f"cả hai trượt: {r['neither']}")
    print(f"  McNemar chính xác, hai phía: p = {r['p_value']:.4f}"
          + ("  (khác biệt có ý nghĩa ở mức 0,05)" if r["p_value"] < 0.05 else "  (chưa đủ bằng chứng là khác nhau)"))
    if r["only_a_cases"]:
        print("  chỉ A đạt:", ", ".join(r["only_a_cases"]))
    if r["only_b_cases"]:
        print("  chỉ B đạt:", ", ".join(r["only_b_cases"]))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
