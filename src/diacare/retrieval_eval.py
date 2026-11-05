"""Đánh giá truy xuất: recall@1, recall@k, MRR (câu hỏi trong chủ đề) và tỉ lệ rỗng (ngoài chủ đề)."""
import json
from pathlib import Path

import numpy as np

from diacare.retriever import Retriever


def load_cases(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_retrieval(retriever, cases, k=4):
    """Mức nguồn: trúng nếu có đoạn trả về thuộc `relevant`. MRR theo hạng đoạn đầu tiên đúng (0 nếu không có)."""
    on = off = 0
    r1 = rk = mrr = 0.0
    empty = chunks_off = 0
    per_query = []
    for case in cases:
        hits = retriever.search(case["q"], k=k)
        sources = [h["source"] for h in hits]
        relevant = set(case.get("relevant") or [])
        row = {"id": case.get("id"), "q": case["q"], "relevant": sorted(relevant), "sources": sources}
        if relevant:
            on += 1
            rank = next((i for i, s in enumerate(sources, 1) if s in relevant), None)
            r1 += bool(sources and sources[0] in relevant)
            rk += rank is not None
            mrr += 1.0 / rank if rank else 0.0
            row["rank"] = rank
        else:
            off += 1
            empty += not hits
            chunks_off += len(hits)
        per_query.append(row)
    return {
        "k": k, "n_on": on, "n_off": off,
        "recall_at_1": r1 / on if on else 0.0,
        "recall_at_k": rk / on if on else 0.0,
        "mrr": mrr / on if on else 0.0,
        "offtopic_empty_rate": empty / off if off else 0.0,
        "offtopic_mean_chunks": chunks_off / off if off else 0.0,
        "per_query": per_query,
    }


def format_table(results, k):
    lines = [f"| mode | recall@1 | recall@{k} | MRR | off-topic empty rate | off-topic mean chunks |",
             "|---|---|---|---|---|---|"]
    for name, m in results.items():
        lines.append(f"| {name} | {m['recall_at_1']:.3f} | {m['recall_at_k']:.3f} | {m['mrr']:.3f} "
                     f"| {m['offtopic_empty_rate']:.2f} | {m['offtopic_mean_chunks']:.2f} |")
    return "\n".join(lines)


def cached_embed(embed_fn):
    """Bọc embed_fn để mỗi văn bản chỉ được nhúng một lần giữa các chế độ."""
    cache = {}

    def embed(texts):
        missing = [t for t in dict.fromkeys(texts) if t not in cache]
        if missing:
            for t, v in zip(missing, embed_fn(missing)):
                cache[t] = v
        return np.array([cache[t] for t in texts], dtype="float32")

    return embed


def run_modes(docs, cases, embed_fn, k=4, threshold=0.0):
    """Bốn cấu hình trên cùng KB: dense (không ngưỡng), dense+ngưỡng, bm25, hybrid+ngưỡng."""
    embed = cached_embed(embed_fn)
    configs = {
        "dense (no threshold)": dict(mode="dense", min_score=0.0),
        f"dense (min_score={threshold})": dict(mode="dense", min_score=threshold),
        "bm25": dict(mode="bm25"),
        f"hybrid RRF (min_score={threshold})": dict(mode="hybrid", min_score=threshold),
    }
    return {name: evaluate_retrieval(Retriever(embed, docs, **kw), cases, k=k)
            for name, kw in configs.items()}


def misses_everywhere(results):
    """Câu trong chủ đề mà mọi cấu hình đều không trả đoạn đúng nào."""
    ids = None
    for m in results.values():
        miss = {r["id"] for r in m["per_query"] if r["relevant"] and not r.get("rank")}
        ids = miss if ids is None else ids & miss
    return sorted(ids or [])
