import numpy as np

from diacare.advisor import build_messages
from diacare.factory import ROOT, build_orchestrator, make_llm, open_store
from diacare.llm import DEFAULT_NUM_CTX, DemoLLM, OllamaLLM, hash_embed_fn
from diacare.retriever import Retriever
from diacare.samples import LOW_RISK
from diacare.state import State


def test_make_llm_demo():
    assert isinstance(make_llm("demo"), DemoLLM)


def test_make_llm_env(monkeypatch):
    monkeypatch.delenv("DIACARE_LLM", raising=False)
    monkeypatch.setenv("DIACARE_MODEL", "foo:1b")
    monkeypatch.setenv("DIACARE_NUM_CTX", "2048")
    llm = make_llm()
    assert isinstance(llm, OllamaLLM)
    assert llm.model == "foo:1b" and llm.num_ctx == 2048


def test_make_llm_defaults(monkeypatch):
    for k in ("DIACARE_LLM", "DIACARE_MODEL", "DIACARE_NUM_CTX"):
        monkeypatch.delenv(k, raising=False)
    llm = make_llm()
    assert llm.model == "qwen2.5:3b" and llm.num_ctx == DEFAULT_NUM_CTX


def _ctx(docs):
    return {"docs": docs, "risk": 0.1, "question": "Ăn gì?", "history": []}


def test_demo_llm_cites_first_source():
    llm = DemoLLM()
    msgs = build_messages(_ctx([{"source": "a.txt", "text": "Ăn nhiều rau."},
                                {"source": "b.txt", "text": "Khác."}]))
    reply = llm(msgs)
    assert reply == "Theo tài liệu [a.txt]: Ăn nhiều rau.."
    assert llm.last_usage["num_ctx"] == DEFAULT_NUM_CTX
    assert llm.last_usage["prompt_tokens"] > 0 and llm.last_usage["seconds"] == 0.0


def test_demo_llm_truncates_to_160():
    reply = DemoLLM()(build_messages(_ctx([{"source": "a.txt", "text": "x" * 500}])))
    assert reply == "Theo tài liệu [a.txt]: " + "x" * 160 + "."


def test_demo_llm_no_docs():
    assert DemoLLM()(build_messages(_ctx([]))) == "Chưa có đủ thông tin trong tài liệu để trả lời."


def test_hash_embed_deterministic_and_retrieval():
    f = hash_embed_fn()
    a, b = f(["rau xanh tốt"]), f(["rau xanh tốt"])
    assert a.shape == (1, 256) and a.dtype == np.float32 and np.array_equal(a, b)
    r = Retriever(f, [("rau.txt", "rau xanh và trái cây tốt cho sức khỏe"),
                      ("xe.txt", "động cơ ô tô hoạt động bằng xăng")])
    assert r.search("ăn rau xanh", k=1)[0]["source"] == "rau.txt"


def test_build_orchestrator_end_to_end(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ada.txt").write_text("Ăn nhiều rau xanh và hạn chế đường.", encoding="utf-8")
    orch = build_orchestrator(kb_dir=kb, model_dir=ROOT / "models", log_path=tmp_path / "r.jsonl",
                              llm=DemoLLM(), embed_fn=hash_embed_fn())
    state = orch.run(State(question="Nên ăn rau không?", profile=LOW_RISK))
    assert "system_error" not in state.flags
    assert state.final and "[" in state.final


def test_open_store_env(tmp_path, monkeypatch):
    db = tmp_path / "sub" / "x.db"
    monkeypatch.setenv("DIACARE_DB", str(db))
    store = open_store()
    store.save_patient("A", LOW_RISK)
    assert db.exists() and len(store.list_patients()) == 1


def test_default_min_score_depends_on_embed_and_env(monkeypatch):
    from diacare.factory import DEFAULT_MIN_SCORE, default_min_score
    monkeypatch.delenv("DIACARE_MIN_SCORE", raising=False)
    assert default_min_score("sbert") == DEFAULT_MIN_SCORE
    assert default_min_score("hash") == 0.0
    monkeypatch.setenv("DIACARE_MIN_SCORE", "0.35")
    assert default_min_score("sbert") == 0.35
