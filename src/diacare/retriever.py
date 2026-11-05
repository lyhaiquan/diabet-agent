import math
import re
import unicodedata
from collections import Counter

import numpy as np

from diacare.nutrition import strip_accents

MODES = ("dense", "bm25", "hybrid")
STOPWORDS = frozenset(
    "the and of to a in is for with your you or can be are that it on as "
    "la cua va cac nhung co khong toi ban thi de cho nao gi nhu mot duoc bi".split()
)


def tokenize(text):
    """NFC, chữ thường, bỏ dấu; token [a-z0-9]+, bỏ token ngắn (<2) và stopword Anh/Việt không dấu."""
    text = strip_accents(unicodedata.normalize("NFC", text).lower())
    return [t for t in re.findall(r"[a-z0-9]+", text) if len(t) >= 2 and t not in STOPWORDS]


class BM25Index:
    """Okapi BM25, idf = ln(1 + (N - df + 0.5)/(df + 0.5))."""

    def __init__(self, texts, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(t)) for t in texts]
        self.lens = np.array([sum(tf.values()) for tf in self.tfs], dtype="float64")
        self.n = len(self.tfs)
        self.avgdl = float(self.lens.mean()) if self.n else 0.0
        df = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        self.idf = {t: math.log(1 + (self.n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def scores(self, query):
        out = np.zeros(self.n, dtype="float64")
        if not self.n:
            return out
        for term in set(tokenize(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tfs):
                f = tf.get(term, 0)
                if f:
                    norm = 1 - self.b + self.b * (self.lens[i] / self.avgdl if self.avgdl else 1.0)
                    out[i] += idf * f * (self.k1 + 1) / (f + self.k1 * norm)
        return out


def chunk_text(text, size=600, overlap=100):
    chunks, start = [], 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= len(text):
            break
        start += size - overlap
    return chunks


class Retriever:
    def __init__(self, embed_fn, docs, min_score=0.0, mode="dense", rrf_k=60):
        if mode not in MODES:
            raise ValueError(f"mode không hợp lệ: {mode!r} (cho phép: {', '.join(MODES)})")
        self.mode = mode
        self.rrf_k = rrf_k
        self.embed = embed_fn
        self.min_score = min_score  # bỏ các đoạn có điểm cosine thấp hơn ngưỡng này
        self.chunks = [
            {"source": src, "text": c} for src, text in docs for c in chunk_text(text)
        ]
        self.bm25 = BM25Index([c["text"] for c in self.chunks]) if mode != "dense" else None
        if self.chunks:
            self.matrix = self._normalize(self.embed([c["text"] for c in self.chunks]))
        else:
            self.matrix = np.empty((0, 0), dtype="float32")

    @staticmethod
    def _normalize(m):
        m = np.asarray(m, dtype="float32")
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(norms == 0, 1, norms)

    def search(self, query, k=4, min_score=None):
        if min_score is None:
            min_score = self.min_score
        if not self.chunks:
            return []
        if self.mode == "bm25":
            return self._search_bm25(query, k)
        q = self._normalize(self.embed([query]))[0]
        scores = self.matrix @ q
        if self.mode == "hybrid":
            return self._search_hybrid(query, k, min_score, scores)
        top = np.argsort(-scores)[:k]
        return [
            dict(self.chunks[i], score=float(scores[i]))
            for i in top
            if scores[i] >= min_score
        ]

    def _search_bm25(self, query, k):
        b = self.bm25.scores(query)
        top = np.argsort(-b, kind="stable")[:k]
        return [dict(self.chunks[i], score=float(b[i])) for i in top if b[i] > 0]

    def _search_hybrid(self, query, k, min_score, dense):
        b = self.bm25.scores(query)
        rrf = np.zeros(len(self.chunks))
        for r, i in enumerate(np.argsort(-dense, kind="stable"), start=1):
            rrf[i] += 1.0 / (self.rrf_k + r)
        pos = [i for i in np.argsort(-b, kind="stable") if b[i] > 0]
        for r, i in enumerate(pos, start=1):
            rrf[i] += 1.0 / (self.rrf_k + r)
        eligible = [i for i in range(len(self.chunks)) if dense[i] >= min_score or b[i] > 0]
        eligible.sort(key=lambda i: -rrf[i])  # sort ổn định: hòa thì giữ thứ tự chỉ số
        return [
            dict(self.chunks[i], score=float(dense[i]), rrf=float(rrf[i]), bm25=float(b[i]))
            for i in eligible[:k]
        ]
