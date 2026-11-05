import importlib.util

import pytest

from diacare.factory import ROOT
from diacare.retrieval_eval import evaluate_retrieval, load_cases, misses_everywhere


class FakeRetriever:
    def __init__(self, table):
        self.table = table

    def search(self, query, k=4, min_score=None):
        return [{"source": s, "text": "", "score": 1.0} for s in self.table[query]][:k]


CASES = [
    {"id": "a", "q": "qa", "relevant": ["x.txt"]},           # hạng 1 -> rr 1
    {"id": "b", "q": "qb", "relevant": ["x.txt", "y.txt"]},  # hạng 2 -> rr 0.5
    {"id": "c", "q": "qc", "relevant": ["x.txt"]},           # trượt -> 0
    {"id": "d", "q": "qd", "relevant": ["x.txt"]},           # hạng 3 (ngoài k=2) -> trượt
    {"id": "o1", "q": "o1", "relevant": []},                 # rỗng
    {"id": "o2", "q": "o2", "relevant": []},                 # 2 đoạn (cắt theo k)
]
TABLE = {"qa": ["x.txt", "z.txt"], "qb": ["z.txt", "y.txt"], "qc": ["z.txt"],
         "qd": ["z.txt", "z.txt", "x.txt"], "o1": [], "o2": ["z.txt", "z.txt", "z.txt"]}


def test_evaluate_retrieval_exact_numbers():
    m = evaluate_retrieval(FakeRetriever(TABLE), CASES, k=2)
    assert m["n_on"] == 4 and m["n_off"] == 2
    assert m["recall_at_1"] == pytest.approx(1 / 4)
    assert m["recall_at_k"] == pytest.approx(2 / 4)
    assert m["mrr"] == pytest.approx((1 + 0.5 + 0 + 0) / 4)
    assert m["offtopic_empty_rate"] == pytest.approx(0.5)
    assert m["offtopic_mean_chunks"] == pytest.approx((0 + 2) / 2)
    assert misses_everywhere({"m": m}) == ["c", "d"]


def test_repo_cases_are_valid():
    cases = load_cases(ROOT / "eval" / "retrieval_cases.json")
    kb = {p.name for p in (ROOT / "kb").glob("*.txt")}
    assert sum(1 for c in cases if c["relevant"]) == 24 and sum(1 for c in cases if not c["relevant"]) == 4
    assert all(set(c["relevant"]) <= kb and c["note"] for c in cases)


def test_cli_hash_mode_writes_table(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.txt").write_text("insulin glucose type 2 diabetes metformin", encoding="utf-8")
    (kb / "b.txt").write_text("hypoglycemia low glucose symptoms shaking", encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text('[{"id":"1","q":"insulin la gi","relevant":["a.txt"],"note":"n"},'
                     '{"id":"2","q":"thoi tiet","relevant":[],"note":"n"}]', encoding="utf-8")
    spec = importlib.util.spec_from_file_location("retrieval_eval_cli", ROOT / "eval" / "retrieval_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "out"
    mod.main(["--embed", "hash", "--kb", str(kb), "--cases", str(cases), "--out", str(out), "--k", "2"])
    table = (out / "table.md").read_text(encoding="utf-8")
    assert "| bm25 |" in table and "hybrid RRF" in table and "recall@2" in table
    assert (out / "per_query.json").exists()
