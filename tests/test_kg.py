import json

import pytest

from diacare.kb import load_kb
from diacare.kg import (DEFAULT_KB, DEFAULT_STATS, TARGET, build_graph, edges_of, extract_claims,
                        facts_for_question, link_factors, load_default_graph, structure, to_cypher,
                        verify_claim)

STATS = {"n": 1000, "features": {
    "BMI": {"or_marginal": 1.7, "or_adjusted": 1.5, "unit": "mỗi độ lệch chuẩn"},
    "PhysActivity": {"or_marginal": 0.5, "or_adjusted": 0.95, "unit": "có so với không"},
    "Smoker": {"or_marginal": 1.4, "or_adjusted": 0.99, "unit": "có so với không"},
    "HighBP": {"or_marginal": 0.6, "or_adjusted": 0.7, "unit": "có so với không"},
    "Age": {"or_marginal": 1.05, "or_adjusted": 1.0, "unit": "mỗi độ lệch chuẩn"},
}}

DOC = ("Who is at risk?\n\nYou are at higher risk of developing type 2 diabetes if you:\n\n"
       "Are overweight or have obesity\n\nAre not physically active\n\nHave a family history of diabetes\n\n"
       "Have high blood pressure\n\nHow can I prevent it?\n\n"
       "People with diabetes have a higher risk of stroke.\n\n"
       "You are at higher risk of developing gestational diabetes if you:\n\nHave polycystic ovary syndrome\n")


def claim(factor, direction=1):
    return {"factor": factor, "direction": direction, "source": "doc.txt", "context": "risk_list",
            "sentence": "..."}


def test_extract_claims_reads_type2_list_only():
    got = {c["factor"]: c["direction"] for c in extract_claims([("doc.txt", DOC)])}
    assert got == {"OBESITY": 1, "INACTIVITY": 1, "FAMILY_HISTORY": 1, "HIGH_BP": 1}


def test_complication_sentence_is_not_a_risk_factor():
    # "người tiểu đường dễ bị đột quỵ" là biến chứng, chiều ngược với yếu tố nguy cơ
    assert "STROKE" not in {c["factor"] for c in extract_claims([("doc.txt", DOC)])}


def test_prevention_sentence_counts():
    doc = "A healthy diet, regular physical activity and avoiding tobacco use are ways to prevent diabetes."
    got = {c["factor"]: c["direction"] for c in extract_claims([("who.txt", doc)])}
    assert got == {"HEALTHY_DIET": -1, "INACTIVITY": 1, "SMOKING": 1}


@pytest.mark.parametrize("factor,verdict", [
    ("OBESITY", "nhất quán"),
    ("INACTIVITY", "nhất quán"),            # PhysActivity đo chiều ngược: OR < 1 là nhất quán
    ("HIGH_BP", "mâu thuẫn"),
    ("AGE", "không đủ bằng chứng"),
    ("FAMILY_HISTORY", "không kiểm chứng được"),
])
def test_verify_claim(factor, verdict):
    assert verify_claim(claim(factor), STATS)["verdict"] == verdict


def test_graph_keeps_relations_separate():
    g = build_graph(STATS, foods=[{"name": "cơm trắng", "per_100g": {"carb_g": 28.2, "fiber_g": 0.4}}],
                    docs=[("doc.txt", DOC)])
    rels = structure(g)["by_relation"]
    assert rels["associated_with"] == 5           # 5 cột có trong STATS; Veggies (HEALTHY_DIET) thì không
    assert rels["claims_risk"] == 4
    assert rels["contains"] == 2
    assert len(edges_of(g, "indicates", "hba1c")) == 3
    assert {d["verdict"] for _, _, d in edges_of(g, "claims_risk", "HIGH_BP", TARGET)} == {"mâu thuẫn"}


def test_link_factors_vietnamese_without_accents():
    assert set(link_factors("toi bi huyet ap cao va beo phi")) == {"HIGH_BP", "OBESITY"}
    assert link_factors("Hôm nay trời đẹp") == []


def test_facts_mark_adjusted_association_and_unmeasurable():
    g = build_graph(STATS, docs=[("doc.txt", DOC)])
    smoke = facts_for_question(g, "hút thuốc có sao không")[0]
    assert "biến mất sau hiệu chỉnh" in smoke
    family = facts_for_question(g, "bố mẹ tôi bị tiểu đường")[0]
    assert "không đo" in family


GENES = {"factors": {
    "DEPRESSION": {"primekg_nodes": ["major depressive disorder"], "factor_genes": 278, "shared_genes": 12,
                   "genes": ["CAT", "HP", "SOD1", "SOD2"]},
    "ACANTHOSIS": {"primekg_nodes": ["acanthosis nigricans (disease)"], "factor_genes": 0, "shared_genes": 0,
                   "genes": []},
    "UNKNOWN": {"primekg_nodes": ["x"], "factor_genes": 3, "shared_genes": 2, "genes": ["A", "B"]},
}}


def test_shared_genes_edge_is_separate_and_described():
    g = build_graph(STATS, docs=[("doc.txt", DOC)], genes=GENES)
    edges = edges_of(g, "shares_genes")
    assert [(u, v) for u, v, _ in edges] == [("DEPRESSION", TARGET)]   # 0 gen hoặc yếu tố lạ thì không có cạnh
    assert edges[0][2]["n_genes"] == 12
    line = facts_for_question(g, "tôi bị trầm cảm")[0]
    assert "chung 12 gen" in line and "CAT, HP, SOD1" in line and "SOD2" not in line
    assert "không phải mức nguy cơ" in line
    # cạnh gen không thay đổi kết luận kiểm chứng tài liệu
    assert structure(g)["claim_verdicts"] == structure(build_graph(STATS, docs=[("doc.txt", DOC)]))["claim_verdicts"]


def test_to_cypher_is_idempotent_merge():
    g = build_graph(STATS, docs=[("doc.txt", DOC)])
    script = to_cypher(g)
    assert script.count("MERGE (n:Entity:") == g.number_of_nodes()
    assert script.count("MERGE (a)-[") == g.number_of_edges()
    assert "CREATE (" not in script


@pytest.mark.skipif(not DEFAULT_STATS.exists(), reason="chưa chạy tools/build_kg_stats.py")
def test_default_graph_on_real_kb():
    g = load_default_graph()
    s = structure(g)
    assert s["by_relation"]["associated_with"] >= 8
    assert s["claim_verdicts"].get("mâu thuẫn", 0) == 0
    assert s["claim_verdicts"]["không kiểm chứng được"] > 0
    assert len(extract_claims(load_kb(DEFAULT_KB))) == s["by_relation"]["claims_risk"]
    json.dumps(s)
