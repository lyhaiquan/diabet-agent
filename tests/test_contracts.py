import json

from diacare.contracts import (
    LIMITATIONS,
    MODEL_VERSION,
    SYSTEM_VERSION,
    PatientDataAgent,
    build_decision_report,
    evaluate_pre_rules,
    make_message,
    new_request_id,
)
from diacare.kg import DEFAULT_CYPHER, export_cypher_file
from diacare.orchestrator import Orchestrator
from diacare.samples import HIGH_RISK, LOW_RISK
from diacare.state import State


def test_patient_data_agent_validates_and_normalizes():
    agent = PatientDataAgent()
    res = agent.validate(dict(LOW_RISK, BMI=24, HighBP=True))
    assert res["valid"] is True and res["errors"] == []
    assert isinstance(res["profile"]["BMI"], float)
    assert isinstance(res["profile"]["HighBP"], int)

    bad = agent.validate(dict(LOW_RISK, BMI=999))
    assert bad["valid"] is False and bad["errors"]


def test_agent_message_structure_matches_ptit_section_6():
    req = new_request_id()
    assert req.startswith("req_") and len(req) == 12
    msg = make_message(
        req,
        "DiabetesPredictionAgent",
        "ok",
        {"prediction": 1, "score": 0.78},
        evidence=[],
        model_version=MODEL_VERSION,
    )
    assert set(msg) == {"request_id", "agent", "status", "payload", "evidence", "model_version"}
    assert msg["model_version"] == "diabetes_dl_v1"


def test_pre_rules_detects_uncertain_and_conflicting_results():
    # Vùng không chắc chắn quanh ngưỡng nguy cơ cao 0,30 (0,25 - 0,35)
    u = evaluate_pre_rules(0.28, LOW_RISK, "Tôi nên ăn gì?")
    assert "uncertain_prediction_review" in u["review_flags"]
    assert u["needs_human_review"] is True

    # Mâu thuẫn: risk < 0.10 (thấp) nhưng xét nghiệm HbA1c mức diabetes
    c1 = evaluate_pre_rules(
        0.08,
        LOW_RISK,
        "Kết quả này sao?",
        labs=[{"test": "hba1c", "level": "diabetes"}],
    )
    assert "conflicting_results_review" in c1["review_flags"]

    # Mâu thuẫn: risk < 0.10 nhưng có triệu chứng lâm sàng rõ rệt
    c2 = evaluate_pre_rules(0.05, LOW_RISK, "Tôi khát nước nhiều và tiểu nhiều")
    assert "conflicting_results_review" in c2["review_flags"]

    # Bình thường: risk thấp, không có xét nghiệm bất thường hay triệu chứng
    ok = evaluate_pre_rules(0.08, LOW_RISK, "Tôi nên ăn rau gì?")
    assert ok["review_flags"] == [] and ok["needs_human_review"] is False


def test_orchestrator_populates_messages_and_decision_report(tmp_path):
    class P:
        def predict(self, profile):
            return 0.29  # vùng không chắc chắn

    class R:
        def search(self, q, k=4):
            return [{"source": "ada.txt", "text": "Tầm soát đường huyết định kỳ.", "score": 0.75}]

    orch = Orchestrator(P(), R(), lambda m: "Hãy xét nghiệm định kỳ [ada.txt].", log_path=tmp_path / "r.jsonl")
    state = orch.run(State(question="Tôi có cần khám không?", profile=HIGH_RISK))

    assert state.request_id.startswith("req_")
    agents = [m["agent"] for m in state.messages]
    assert agents == [
        "PatientDataAgent",
        "DiabetesPredictionAgent",
        "RuleBasedAgent",
        "KnowledgeGraphRAGAgent",
        "ExplanationAgent",
        "MonitoringAgent",
    ]
    assert all(m["request_id"] == state.request_id for m in state.messages)

    rep = state.report
    assert rep["request_id"] == state.request_id
    assert rep["model_version"] == MODEL_VERSION
    assert rep["system_version"] == SYSTEM_VERSION
    assert rep["prediction"]["score"] == 0.29
    assert "uncertain_prediction_review" in rep["rules"]["flags"]
    assert rep["rules"]["needs_human_review"] is True
    assert rep["evidence"]["sources"] == ["ada.txt"]
    assert rep["explanation"]["draft"] and rep["explanation"]["final"]
    assert len(rep["limitations"]) == len(LIMITATIONS) == 7

    log_row = json.loads((tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert log_row["request_id"] == state.request_id
    assert log_row["model_version"] == MODEL_VERSION
    assert "uncertain_prediction_review" in log_row["review_flags"]


def test_db_diabet_cypher_exists_and_export_works(tmp_path):
    assert DEFAULT_CYPHER.exists()
    content = DEFAULT_CYPHER.read_text(encoding="utf-8")
    assert "CREATE CONSTRAINT entity_id" in content
    assert "MERGE (n:Entity:Condition {id: 'T2D'})" in content
    out = export_cypher_file(path=tmp_path / "DB_diabet.cypher")
    assert out.exists() and out.read_text(encoding="utf-8") == content
