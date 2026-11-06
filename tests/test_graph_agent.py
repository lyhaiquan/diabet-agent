import json

import pytest

from diacare.advisor import build_messages
from diacare.context import KG_TOKEN_BUDGET, build_context, estimate_tokens
from diacare.factory import make_graph_agent, neo4j_config, parse_features
from diacare.kg import GraphAgent, MemoryKG, build_graph, format_kg
from diacare.orchestrator import Orchestrator
from diacare.samples import LOW_RISK
from diacare.state import State

STATS = {"n": 1000, "features": {
    "BMI": {"or_marginal": 1.7, "or_adjusted": 1.5, "unit": "mỗi độ lệch chuẩn"},
    "HighBP": {"or_marginal": 5.0, "or_adjusted": 2.1, "unit": "có so với không"},
}}
DOC = ("You are at higher risk of developing type 2 diabetes if you:\n\n"
       "Are overweight or have obesity\n\nHave high blood pressure\n\nHave a family history of diabetes\n")


def agent():
    return GraphAgent(MemoryKG(build_graph(STATS, docs=[("doc.txt", DOC)])))


def test_lookup_returns_lines_with_both_sources():
    kg = agent().lookup("Tôi bị huyết áp cao, có sao không?")
    assert kg["backend"] == "networkx" and kg["factors"] == ["HIGH_BP"]
    assert "doc" in kg["lines"][0] and "OR 5 " in kg["lines"][0]


def test_lookup_without_factor_is_empty():
    assert agent().lookup("Hôm nay tôi nên ăn gì?")["lines"] == []
    assert format_kg({"backend": "networkx", "factors": [], "lines": []}) == ""


def test_orchestrator_runs_graph_step_and_feeds_advisor(tmp_path):
    seen = []

    class P:
        def predict(self, profile):
            return 0.1

    class R:
        def search(self, q, k=4):
            return []

    def llm(messages):
        seen.append(messages)
        return "Huyết áp cao là yếu tố nguy cơ [kg]."

    orch = Orchestrator(P(), R(), llm, log_path=tmp_path / "run.jsonl", graph_agent=agent())
    state = orch.run(State(question="Tôi bị huyết áp cao và béo phì", profile=LOW_RISK))
    steps = [t["agent"] for t in state.trace]
    assert steps.index("Retriever") < steps.index("Graph") < steps.index("Advisor")
    assert set(state.kg["factors"]) == {"HIGH_BP", "OBESITY"}
    prompt = seen[0][-1]["content"]
    assert "Tri thức từ đồ thị [kg]" in prompt and "không phải quan hệ nhân quả" in prompt
    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert set(record["kg_factors"]) == {"HIGH_BP", "OBESITY"}


def test_no_graph_agent_leaves_prompt_unchanged():
    state = State(question="Tôi bị huyết áp cao", profile={})
    ctx = build_context("advisor", state)
    assert ctx["kg_text"] == ""
    assert "[kg]" not in build_messages(ctx)[-1]["content"]


def test_context_trims_kg_lines_to_budget():
    long_line = "x" * int(KG_TOKEN_BUDGET * 4 * 0.6)
    state = State(question="?", profile={}, kg={"backend": "networkx", "factors": ["A", "B", "C"],
                                                  "lines": [long_line, long_line, long_line]})
    ctx = build_context("advisor", state)
    assert ctx["kg_text"].count("- ") == 1
    assert estimate_tokens(ctx["kg_text"]) <= KG_TOKEN_BUDGET


def test_kg_feature_is_opt_in():
    assert "kg" not in parse_features("v2")
    assert "kg" in parse_features("v2,kg")


def test_make_graph_agent_falls_back_without_neo4j(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:1")      # cổng không có gì
    monkeypatch.setenv("NEO4J_PASSWORD", "x")
    assert make_graph_agent("neo4j").backend.name == "networkx"


def _neo4j_up():
    uri, user, password = neo4j_config()
    if not password:
        return False
    try:
        from neo4j import GraphDatabase
        with GraphDatabase.driver(uri, auth=(user, password)) as d:
            d.verify_connectivity()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _neo4j_up(), reason="Neo4j chưa chạy (python tools/kg_neo4j.py)")
def test_neo4j_backend_matches_memory_backend():
    neo = make_graph_agent("neo4j")
    assert neo.backend.name == "neo4j"
    mem = GraphAgent(MemoryKG())
    q = "Tôi bị huyết áp cao, béo phì, bố mẹ bị tiểu đường"
    assert neo.lookup(q)["lines"] == mem.lookup(q)["lines"]
    neo.backend.close()
