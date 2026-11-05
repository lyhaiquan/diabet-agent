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


# ---------- V2-W4: BM25 + hybrid (RRF) ----------
import pytest

from diacare.retriever import BM25Index, tokenize


def test_tokenize_strips_accents_and_stopwords():
    assert tokenize("Đường huyết của TÔI và the Insulin, a1c!") == ["duong", "huyet", "insulin", "a1c"]
    assert tokenize("x of 2 a1") == ["a1"]  # token dài < 2 và stopword bị bỏ


def test_bm25_ranks_rare_term_first():
    idx = BM25Index(["glucose glucose insulin", "metformin glucose", "exercise diet"])
    s = idx.scores("metformin")
    assert int(np.argmax(s)) == 1 and s[0] == 0 and s[2] == 0


def test_bm25_absent_term_all_zeros():
    s = BM25Index(["glucose insulin", "exercise"]).scores("zzzz")
    assert list(s) == [0.0, 0.0]


def test_bm25_idf_formula_single_term():
    # N=2, df=1, doc dài bằng avgdl -> tf*(k1+1)/(tf+k1) * ln(1+(2-1+.5)/(1+.5))
    import math
    idx = BM25Index(["alpha beta", "gamma delta"], k1=1.5, b=0.75)
    expected = math.log(1 + 1.5 / 1.5) * (1 * 2.5) / (1 + 1.5)
    assert idx.scores("alpha")[0] == pytest.approx(expected)


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        Retriever(fake_embed, [("g.txt", "glucose")], mode="nope")


def test_bm25_mode_ignores_min_score_and_returns_bm25_score():
    r = Retriever(fake_embed, [("g.txt", "glucose glucose insulin"), ("e.txt", "exercise")],
                  mode="bm25", min_score=0.99)
    hits = r.search("glucose", k=4)
    assert [h["source"] for h in hits] == ["g.txt"]
    assert hits[0]["score"] > 0


def test_hybrid_returns_bm25_only_hit_below_dense_threshold():
    # embed bỏ qua từ "metformin" -> cosine 0 nhưng BM25 > 0
    r = Retriever(fake_embed, [("m.txt", "metformin"), ("e.txt", "exercise exercise")],
                  mode="hybrid", min_score=0.5)
    hits = r.search("metformin", k=4)
    assert [h["source"] for h in hits] == ["m.txt"]
    assert hits[0]["score"] == 0.0 and hits[0]["bm25"] > 0 and hits[0]["rrf"] > 0


def test_hybrid_keeps_offtopic_filter():
    r = Retriever(fake_embed, [("g.txt", "glucose insulin"), ("e.txt", "exercise diet")],
                  mode="hybrid", min_score=0.5)
    assert r.search("thoi tiet hom nay", k=4) == []


def test_hybrid_rrf_arithmetic():
    # dense: 3 đoạn; BM25 chỉ có 2 đoạn dương.
    docs = [("a.txt", "glucose"), ("b.txt", "glucose insulin insulin"), ("c.txt", "exercise")]
    r = Retriever(fake_embed, docs, mode="hybrid", min_score=0.0, rrf_k=10)
    q = "insulin"
    hits = r.search(q, k=4)
    # dense (cosine với [0,1,0,0]): b=1.0 hạng 1; a, c = 0 -> hạng 2,3 (argsort ổn định theo chỉ số)
    # bm25 > 0 chỉ có b -> hạng 1.  rrf(b) = 1/11 + 1/11
    assert hits[0]["source"] == "b.txt"
    assert hits[0]["rrf"] == pytest.approx(2 / 11)
    by = {h["source"]: h for h in hits}
    assert by["a.txt"]["rrf"] == pytest.approx(1 / 12)
    assert by["c.txt"]["rrf"] == pytest.approx(1 / 13)


def test_chunk_text_does_not_split_words():
    text = " ".join(f"word{i:03d}" for i in range(300))  # ~2400 ký tự, toàn từ 7 ký tự
    chunks = chunk_text(text, size=100, overlap=20)
    words = set(text.split())
    for c in chunks:
        assert all(w in words for w in c.split()), c   # không có mảnh từ bị cắt
        assert len(c) <= 100
    assert chunks[0].startswith("word000") and chunks[-1].endswith("word299")


def test_chunk_text_prefers_sentence_end():
    text = "A" * 70 + ". " + "b" * 60
    assert chunk_text(text, size=100, overlap=10)[0] == "A" * 70 + "."
