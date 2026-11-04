import numpy as np
from diacare.retriever import Retriever, chunk_text

VOCAB = ["glucose", "insulin", "exercise", "diet"]


def fake_embed(texts):
    return np.array([[t.lower().count(w) for w in VOCAB] for t in texts], dtype="float32")


def test_chunk_text_overlap_and_no_empty():
    chunks = chunk_text("a" * 250, size=100, overlap=20)
    assert [len(c) for c in chunks] == [100, 100, 90]
    assert chunk_text("   ") == []


def test_search_returns_best_chunk_with_source():
    r = Retriever(fake_embed, [("g.txt", "glucose glucose insulin"), ("e.txt", "exercise exercise")])
    hits = r.search("glucose", k=1)
    assert hits[0]["source"] == "g.txt"
    assert "glucose" in hits[0]["text"]
