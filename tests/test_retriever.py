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


def test_empty_docs_search_returns_empty():
    def boom(texts):
        raise AssertionError("embed_fn must not be called on empty input")

    assert Retriever(boom, []).search("glucose") == []
    r2 = Retriever(fake_embed, [("blank.txt", "   ")])
    assert r2.search("glucose") == []


def test_k_larger_than_chunks_returns_all():
    r = Retriever(fake_embed, [("g.txt", "glucose insulin"), ("e.txt", "exercise")])
    assert len(r.search("glucose", k=10)) == 2


def test_min_score_filters_low_hits():
    r = Retriever(fake_embed, [("g.txt", "glucose glucose insulin"), ("e.txt", "exercise exercise")])
    hits = r.search("glucose", k=4, min_score=0.5)
    assert [h["source"] for h in hits] == ["g.txt"]


def test_constructor_min_score_is_default_for_search():
    r = Retriever(fake_embed, [("g.txt", "glucose glucose insulin"), ("e.txt", "exercise exercise")], min_score=0.5)
    assert [h["source"] for h in r.search("glucose", k=4)] == ["g.txt"]
    assert len(r.search("glucose", k=4, min_score=0.0)) == 2  # tham số gọi vẫn ghi đè được
