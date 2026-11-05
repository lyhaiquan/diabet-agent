import numpy as np


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
    def __init__(self, embed_fn, docs, min_score=0.0):
        self.embed = embed_fn
        self.min_score = min_score  # bỏ các đoạn có điểm cosine thấp hơn ngưỡng này
        self.chunks = [
            {"source": src, "text": c} for src, text in docs for c in chunk_text(text)
        ]
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
        q = self._normalize(self.embed([query]))[0]
        scores = self.matrix @ q
        top = np.argsort(-scores)[:k]
        return [
            dict(self.chunks[i], score=float(scores[i]))
            for i in top
            if scores[i] >= min_score
        ]
