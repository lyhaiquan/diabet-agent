"""So sánh dense / bm25 / hybrid trên kb/ với bộ eval/retrieval_cases.json.

    python eval/retrieval_eval.py --embed sbert [--k 4] [--kb kb] [--cases ...] [--out reports/...]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from diacare.factory import ROOT, default_min_score, make_embed_fn  # noqa: E402
from diacare.kb import load_kb  # noqa: E402
from diacare.retrieval_eval import format_table, load_cases, misses_everywhere, run_modes  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--embed", choices=["sbert", "hash"], default="sbert")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--kb", default=str(ROOT / "kb"))
    ap.add_argument("--cases", default=str(ROOT / "eval" / "retrieval_cases.json"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    out = Path(args.out) if args.out else ROOT / "reports" / f"retrieval_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    threshold = default_min_score(args.embed)
    docs, cases = load_kb(args.kb), load_cases(args.cases)
    results = run_modes(docs, cases, make_embed_fn(args.embed), k=args.k, threshold=threshold)

    first = next(iter(results.values()))
    table = format_table(results, args.k)
    missed = misses_everywhere(results)
    text = (f"{table}\n\nKB: {', '.join(n for n, _ in docs)}; embed={args.embed}; k={args.k}; "
            f"on-topic={first['n_on']}, off-topic={first['n_off']}\n"
            f"Missed by every mode: {', '.join(missed) or '(none)'}\n")
    (out / "table.md").write_text(text, encoding="utf-8")
    (out / "per_query.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text)
    print(f"Saved to {out}")
    return results


if __name__ == "__main__":
    main()
