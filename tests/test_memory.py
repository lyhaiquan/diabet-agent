import json
import sqlite3

import pytest

from diacare import context
from diacare.context import MEMORY_TOKEN_BUDGET, build_context, estimate_tokens
from diacare.db import Store
from diacare.factory import build_orchestrator, parse_features
from diacare.llm import DemoLLM, hash_embed_fn
from diacare.memory import MemoryAgent, compress_history, extract_facts, format_memory, summarise_history
from diacare.orchestrator import Orchestrator
from diacare.rules import apply_rules
from diacare.samples import HIGH_RISK, LOW_RISK
from diacare.state import State


# ---------- extract_facts ----------

@pytest.mark.parametrize("text,expected", [
    ("Tôi bị tiểu đường típ 2", [("diagnosis", "đái tháo đường típ 2")]),
    ("tôi mắc đái tháo đường type 2.", [("diagnosis", "đái tháo đường típ 2")]),
    ("Tôi đã được chẩn đoán tiểu đường tuýp 2 năm ngoái", [("diagnosis", "đái tháo đường típ 2")]),
    ("Em bị tiểu đường típ 1 từ nhỏ", [("diagnosis", "đái tháo đường típ 1")]),
    ("Mình bị tiền tiểu đường", [("diagnosis", "tiền đái tháo đường")]),
    ("Bác sĩ nói tôi bị tiền đái tháo đường", [("diagnosis", "tiền đái tháo đường")]),
    ("Bác sĩ chẩn đoán tôi tiểu đường típ 2", [("diagnosis", "đái tháo đường típ 2")]),
    ("toi bi tieu duong tip 2", [("diagnosis", "đái tháo đường típ 2")]),
    ("Tôi đang dùng metformin mỗi ngày.", [("medication", "metformin")]),
    ("toi dang dung metformin", [("medication", "metformin")]),
    ("Tôi uống Gliclazide", [("medication", "gliclazide")]),
    ("Mình bị tiểu đường típ 2 và đang tiêm insulin.",
     [("diagnosis", "đái tháo đường típ 2"), ("medication", "insulin")]),
    ("Tôi bị dị ứng tôm.", [("allergy", "tôm")]),
    ("Tôi dị ứng với sữa bò, nên gợi ý giúp tôi", [("allergy", "sữa bò")]),
    ("Tôi dị ứng tôm nên gợi ý bữa tối", [("allergy", "tôm")]),
    ("Tôi ăn chay", [("diet", "ăn chay")]),
    ("Tôi không ăn được cay", [("diet", "không ăn cay")]),
    ("Tôi bị huyết áp cao", [("condition", "tăng huyết áp")]),
    ("Mình có mỡ máu cao", [("condition", "rối loạn mỡ máu")]),
])
def test_extract_positive(text, expected):
    assert sorted(extract_facts(text)) == sorted(expected)


@pytest.mark.parametrize("text", [
    "Tiểu đường típ 2 là gì?",
    "Người bị tiểu đường típ 2 nên ăn gì?",
    "Metformin dùng như thế nào?",
    "Tôi có nên dùng metformin không?",
    "Huyết áp cao có nguy hiểm không?",
    "Gợi ý bữa tối giàu đạm",
    "",
])
def test_extract_negative(text):
    assert extract_facts(text) == []


@pytest.mark.parametrize("text,expected", [
    ("Tôi bị tiểu đường 5 năm rồi", [("diagnosis", "đái tháo đường (chưa rõ típ)")]),
    ("Mình bị đái tháo đường", [("diagnosis", "đái tháo đường (chưa rõ típ)")]),
    ("toi bi tieu duong", [("diagnosis", "đái tháo đường (chưa rõ típ)")]),
    ("Tôi bị tiểu đường típ 2, tôi nên làm gì?", [("diagnosis", "đái tháo đường típ 2")]),
    ("Tôi bị huyết áp cao và mỡ máu cao",
     [("condition", "tăng huyết áp"), ("condition", "rối loạn mỡ máu")]),
    ("Tôi bị tăng huyết áp, mỡ máu cao", [("condition", "tăng huyết áp"), ("condition", "rối loạn mỡ máu")]),
    ("Em bị tiểu đường típ 1", [("diagnosis", "đái tháo đường típ 1")]),
    ("Em bị tiểu đường típ 1, mẹ em cũng vậy", [("diagnosis", "đái tháo đường típ 1")]),
])
def test_extract_more_positive(text, expected):
    assert sorted(extract_facts(text)) == sorted(expected)


@pytest.mark.parametrize("text", [
    "Mẹ tôi bị tiểu đường típ 2",
    "me toi bi tieu duong tip 2",
    "Bố mình bị tiểu đường",
    "Vợ em mắc đái tháo đường típ 2",
    "Ông nội tôi bị huyết áp cao",
    "Con tôi đang tiêm insulin",
    "Chồng tôi dị ứng tôm",
    "Bạn tôi bị tiền tiểu đường",
    "Em trai tôi bị tiểu đường típ 1",
    "Hàng xóm tôi ăn chay",
    "Tôi không bị tiểu đường",
    "Tôi chưa bị tiểu đường",
    "Tôi chưa từng bị tiểu đường",
    "Tôi sợ bị tiểu đường",
    "Tôi có bị tiểu đường không?",
    "Tôi bị tiểu đường không?",
    "Tôi không bị tiểu đường típ 2",
])
def test_extract_other_people_and_negation(text):
    assert extract_facts(text) == []


def test_untyped_diagnosis_counts_but_prediabetes_not():
    a = MemoryAgent(Store())
    a.observe(1, "Tôi bị tiểu đường 5 năm rồi")
    assert a.is_diagnosed(1)
    a.observe(2, "Mình bị tiền tiểu đường")
    assert not a.is_diagnosed(2)


# ---------- Store ----------

def test_store_memory_dedupe_list_deactivate():
    s = Store()
    a = s.add_memory(1, "allergy", "Tôm")
    assert s.add_memory(1, "allergy", "tôm") == a
    b = s.add_memory(1, "diet", "ăn chay", source="llm")
    other = s.add_memory(2, "allergy", "tôm")
    assert other != a
    rows = s.list_memories(1)
    assert [r["id"] for r in rows] == [a, b]
    assert set(rows[0]) >= {"id", "patient_id", "kind", "content", "source", "created_at", "updated_at", "active"}
    assert rows[1]["source"] == "llm"
    s.deactivate_memory(a)
    assert [r["id"] for r in s.list_memories(1)] == [b]
    assert [r["id"] for r in s.list_memories(1, active_only=False)] == [a, b]
    assert [r["id"] for r in s.list_memories(2)] == [other]


def test_store_summary_roundtrip():
    s = Store()
    assert s.get_summary(5) is None
    s.save_summary(5, 4, "tóm tắt 1")
    s.save_summary(5, 8, "tóm tắt 2")
    got = s.get_summary(5)
    assert got["content"] == "tóm tắt 2" and got["upto_message_index"] == 8 and got["session_id"] == 5
    assert s.get_summary(6) is None


def test_old_db_gains_tables(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE patients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,"
                " profile_json TEXT NOT NULL, created_at TEXT NOT NULL)")
    con.commit()
    con.close()
    s = Store(path)
    s.add_memory(1, "diet", "ăn chay")
    s.save_summary(1, 2, "x")
    s.close()
    s2 = Store(path)
    assert len(s2.list_memories(1)) == 1 and s2.get_summary(1)["content"] == "x"


# ---------- MemoryAgent ----------

def test_memory_agent_observe_recall_diagnosed():
    agent = MemoryAgent(Store())
    got = agent.observe(7, "Tôi bị tiểu đường típ 2 và đang dùng metformin, tôi dị ứng tôm")
    assert sorted(k for k, _ in got) == ["allergy", "diagnosis", "medication"]
    assert agent.is_diagnosed(7) and not agent.is_diagnosed(8)
    agent.observe(7, "Tôi dị ứng tôm")
    assert len(agent.recall(7)) == 3
    a2 = MemoryAgent(Store())
    a2.observe(1, "Mình bị tiền tiểu đường")
    assert not a2.is_diagnosed(1)


def test_format_memory():
    agent = MemoryAgent(Store())
    agent.observe(1, "Tôi bị tiểu đường típ 2 và đang dùng metformin, tôi dị ứng tôm")
    text = format_memory(agent.recall(1))
    assert text.splitlines()[0] == "Thông tin đã biết về người dùng (từ các phiên trước):"
    assert "- chẩn đoán: đái tháo đường típ 2" in text
    assert "- thuốc đang dùng: metformin" in text
    assert "- dị ứng: tôm" in text
    assert format_memory([{"kind": "diet", "content": "ăn chay"}]).endswith("- chế độ ăn: ăn chay")
    assert format_memory([{"kind": "condition", "content": "tăng huyết áp"}]).endswith("- bệnh kèm theo: tăng huyết áp")


# ---------- orchestrator across sessions ----------

class FakePredictor:
    def __init__(self, risk=0.9):
        self.risk = risk

    def predict(self, profile):
        return self.risk


class FakeRetriever:
    def search(self, query, k=4):
        return [{"source": "ada.txt", "text": "Hạn chế đường."}]


def make_orch(risk=0.9, with_memory=True, store=None):
    calls = []

    def llm(messages):
        calls.append(messages)
        return "Hãy giảm đường [ada.txt]."

    agent = MemoryAgent(store or Store()) if with_memory else None
    return Orchestrator(FakePredictor(risk), FakeRetriever(), llm, memory_agent=agent), calls


def prompt_text(messages):
    return "\n".join(m["content"] for m in messages)


def test_memory_across_runs_and_isolated_by_patient():
    orch, calls = make_orch()
    orch.run(State(question="Tôi dị ứng tôm.", profile=LOW_RISK, patient_id=1))
    orch.run(State(question="Gợi ý bữa tối", profile=LOW_RISK, patient_id=1))
    second = prompt_text(calls[1])
    assert "Thông tin đã biết về người dùng" in second and "- dị ứng: tôm" in second
    assert calls[1][-1]["content"].startswith("Thông tin đã biết")
    orch.run(State(question="Gợi ý bữa tối", profile=LOW_RISK, patient_id=2))
    assert "dị ứng" not in prompt_text(calls[2])
    orch.run(State(question="Gợi ý bữa tối", profile=LOW_RISK))  # no patient id
    assert "dị ứng" not in prompt_text(calls[3])


def test_no_memory_agent_behaves_as_before():
    orch, calls = make_orch(with_memory=False)
    st = orch.run(State(question="Tôi dị ứng tôm.", profile=LOW_RISK, patient_id=1))
    assert "Thông tin đã biết" not in prompt_text(calls[0]) and st.memory == []
    assert "history_summarized" not in st.flags


def test_diagnosed_followup_replaces_referral():
    orch, _ = make_orch(0.9)
    st = orch.run(State(question="Tôi bị tiểu đường típ 2, tôi nên làm gì?", profile=HIGH_RISK, patient_id=3))
    assert "diagnosed_followup" in st.flags and "high_risk_referral" not in st.flags
    assert "Bạn đã được chẩn đoán đái tháo đường" in st.final
    st2 = orch.run(State(question="Ăn gì?", profile=HIGH_RISK, patient_id=4))
    assert "high_risk_referral" in st2.flags and "diagnosed_followup" not in st2.flags


def test_apply_rules_diagnosed():
    text, flags = apply_rules(0.9, "ok", "x", diagnosed=True)
    assert "diagnosed_followup" in flags and "high_risk_referral" not in flags
    assert "theo dõi đường huyết và tái khám" in text
    _, flags = apply_rules(0.9, "ok", "tôi bị đau ngực", diagnosed=True)
    assert "emergency_referral" in flags
    _, flags = apply_rules(0.9, "ok", "x")
    assert "high_risk_referral" in flags and "diagnosed_followup" not in flags


def test_memory_kinds_logged(tmp_path):
    orch, _ = make_orch()
    orch.log_path = tmp_path / "r.jsonl"
    orch.run(State(question="Tôi dị ứng tôm.", profile=LOW_RISK, patient_id=1))
    rec = json.loads((tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["memory_kinds"] == ["allergy"]


# ---------- summarisation ----------

class SummLLM:
    num_ctx = 4096

    def __init__(self):
        self.calls = []
        self.last_usage = {}

    def __call__(self, messages):
        self.calls.append(messages)
        if "Tóm tắt ngắn gọn" in messages[0]["content"]:
            self.last_usage = {"prompt_tokens": 50, "completion_tokens": 9, "seconds": 0.1, "num_ctx": 4096}
            return "  Người dùng bị tiểu đường.  "
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 20, "seconds": 0.2, "num_ctx": 4096}
        return "Trả lời [ada.txt]."


def long_history(n=12, size=400):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i} " + "x" * size}
            for i in range(n)]


def test_summarise_history_prompt():
    llm = SummLLM()
    out = summarise_history([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], llm)
    assert out == "Người dùng bị tiểu đường."
    msgs = llm.calls[0]
    assert msgs[0]["role"] == "system" and "tối đa 80 từ" in msgs[0]["content"]
    assert msgs[1]["content"] == "Người dùng: a\nTrợ lý: b"


def test_compress_history_unchanged_when_small():
    h = [{"role": "user", "content": "hi"}]
    llm = SummLLM()
    new, did = compress_history(h, llm, 800, estimate_tokens)
    assert new is h and did is False and llm.calls == []


def test_compress_history_summarises_old():
    h = long_history()
    snapshot = [dict(m) for m in h]
    llm = SummLLM()
    new, did = compress_history(h, llm, 800, estimate_tokens)
    assert did and h == snapshot
    assert new[0] == {"role": "system", "content": "Tóm tắt hội thoại trước: Người dùng bị tiểu đường."}
    kept = new[1:]
    assert kept and kept == h[-len(kept):]
    assert sum(estimate_tokens(m["content"]) for m in kept) <= 400
    assert len(kept) < len(h)


def test_orchestrator_summarises_and_keeps_full_history():
    llm = SummLLM()
    orch = Orchestrator(FakePredictor(0.1), FakeRetriever(), llm, memory_agent=MemoryAgent(Store()))
    h = long_history()
    st = orch.run(State(question="Ăn gì?", profile=LOW_RISK, history=h, patient_id=1))
    assert st.flags[-1] == "history_summarized"
    assert st.history[:len(h)] == h and len(st.history) == len(h) + 2
    assert st.usage["summary_prompt_tokens"] == 50 and st.usage["summary_completion_tokens"] == 9
    assert st.usage["prompt_tokens"] == 100
    assert any("Tóm tắt hội thoại trước" in m["content"] for m in llm.calls[-1])
    assert len(h) == 12


def test_orchestrator_short_history_not_summarised():
    llm = SummLLM()
    orch = Orchestrator(FakePredictor(0.1), FakeRetriever(), llm, memory_agent=MemoryAgent(Store()))
    st = orch.run(State(question="Ăn gì?", profile=LOW_RISK, history=[{"role": "user", "content": "a"}]))
    assert "history_summarized" not in st.flags and len(llm.calls) == 1


# ---------- context ----------

def test_context_memory_first_and_capped():
    facts = [{"kind": "allergy", "content": f"chất {i} " + "y" * 60} for i in range(20)]
    ctx = build_context("advisor", State(question="q", profile={}, memory=facts))
    assert ctx["memory_text"].startswith("Thông tin đã biết")
    assert estimate_tokens(ctx["memory_text"]) <= MEMORY_TOKEN_BUDGET == 150
    assert "chất 19" in ctx["memory_text"] and "chất 0 " not in ctx["memory_text"]  # oldest dropped first
    assert ctx["est_tokens"] >= estimate_tokens(ctx["memory_text"])
    assert build_context("advisor", State(question="q", profile={}))["memory_text"] == ""


def test_context_memory_charged_before_docs():
    docs = [{"source": "a", "text": "d" * 400}]
    base = State(question="q", profile={}, docs=docs)
    mem = State(question="q", profile={}, docs=docs, memory=[{"kind": "diet", "content": "ăn chay"}])
    room = 1 + estimate_tokens(docs[0]["text"]) + context.DOC_LABEL_TOKENS
    num_ctx = context.ANSWER_RESERVE_TOKENS + context.SYSTEM_RESERVE_TOKENS + room
    assert len(build_context("advisor", base, num_ctx=num_ctx)["docs"]) == 1
    assert len(build_context("advisor", mem, num_ctx=num_ctx)["docs"]) == 0


def test_rule_context_has_diagnosed():
    st = State(question="q", profile={}, risk=0.1, draft="d",
               memory=[{"kind": "diagnosis", "content": "đái tháo đường típ 2"}])
    assert build_context("rule", st)["diagnosed"] is True
    assert build_context("rule", State(question="q", profile={}, risk=0.1, draft="d"))["diagnosed"] is False


# ---------- factory ----------

def test_features_memory(tmp_path):
    assert parse_features("memory") == {"memory"}
    assert "memory" in parse_features("all")
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.txt").write_text("Ăn rau.", encoding="utf-8")
    off = build_orchestrator(kb_dir=kb, llm=DemoLLM(), embed_fn=hash_embed_fn(), features="v1",
                             log_path=tmp_path / "l.jsonl")
    assert off.memory_agent is None
    on = build_orchestrator(kb_dir=kb, llm=DemoLLM(), embed_fn=hash_embed_fn(), features="memory",
                            log_path=tmp_path / "l.jsonl", store=Store())
    assert isinstance(on.memory_agent, MemoryAgent)
    assert on.summarizer_llm is on.llm
