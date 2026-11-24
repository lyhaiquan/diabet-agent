import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from diacare.mcp_server import DiaCareTools, Server

ROOT = Path(__file__).resolve().parent.parent
PROFILE = {"HighBP": 1, "HighChol": 1, "CholCheck": 1, "BMI": 31, "Smoker": 0, "Stroke": 0,
           "HeartDiseaseorAttack": 0, "PhysActivity": 0, "Fruits": 1, "Veggies": 1, "HvyAlcoholConsump": 0,
           "AnyHealthcare": 1, "NoDocbcCost": 0, "GenHlth": 3, "MentHlth": 0, "PhysHlth": 0, "DiffWalk": 0,
           "Sex": 0, "Age": 9, "Education": 4, "Income": 5}


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("DIACARE_EMBED", "hash")
    return Server()


def call(server, name, args, mid=1):
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                          "params": {"name": name, "arguments": args}})["result"]


def test_initialize_and_list(server):
    r = server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "t", "version": "0"}}})["result"]
    assert r["protocolVersion"] == "2025-06-18" and r["serverInfo"]["name"] == "diacare"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [t["name"] for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
    assert names == ["check_lab", "search_guidelines", "risk_factor_evidence", "food_nutrition", "tray_carbs",
                     "predict_risk"]
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert len(tools[-1]["inputSchema"]["properties"]["profile"]["required"]) == 21


def test_unknown_version_gets_latest(server):
    r = server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_check_lab(server):
    r = call(server, "check_lab", {"text": "HbA1c 6,8%, đường huyết đói 5,4 mmol/L"})
    assert not r["isError"]
    levels = {x["label"]: x["level"] for x in r["structuredContent"]["results"]}
    assert "diabetes" in levels.values() and "normal" in levels.values()
    assert json.loads(r["content"][0]["text"]) == r["structuredContent"]


def test_tool_error_is_result_not_protocol_error(server):
    r = call(server, "check_lab", {"text": "hôm nay trời đẹp"})
    assert r["isError"] and "Không đọc được" in r["content"][0]["text"]
    r = call(server, "check_lab", {})  # thiếu tham số
    assert r["isError"]


def test_unknown_tool_and_method(server):
    r = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "chat", "arguments": {}}})
    assert r["error"]["code"] == -32602
    r = server.handle({"jsonrpc": "2.0", "id": 9, "method": "sampling/createMessage"})
    assert r["error"]["code"] == -32601


def test_search_guidelines_has_sources(server):
    r = call(server, "search_guidelines", {"question": "chế độ ăn cho người tiểu đường", "k": 2})
    hits = r["structuredContent"]["passages"]
    assert 1 <= len(hits) <= 2 and all(h["source"].endswith((".txt", ".md")) for h in hits)


def test_risk_factor_evidence(server):
    r = call(server, "risk_factor_evidence", {"question": "béo phì có làm tăng nguy cơ không"})
    assert not r["isError"] and "BRFSS" in r["structuredContent"]["factors"][0]["summary"]


def test_food_nutrition(server):
    r = call(server, "food_nutrition", {"text": "1 bát phở bò"})
    assert not r["isError"] and r["structuredContent"]["totals"]["carb_g"] > 0


def test_tray_carbs(server):
    r = call(server, "tray_carbs", {"dishes": [{"name": "cơm trắng", "grams": 200}, {"name": "potato", "grams": 100},
                                               {"name": "trà sữa", "grams": 300}]})
    s = r["structuredContent"]
    assert s["carb_g"] == 73 and s["carb_low"] < 73 < s["carb_high"]   # 56 + 17
    assert s["not_counted"] == ["trà sữa"]


def test_predict_risk(server):
    r = call(server, "predict_risk", {"profile": PROFILE})
    assert r["structuredContent"]["band"] in ("thấp", "trung bình", "cao")
    r = call(server, "predict_risk", {"profile": {**PROFILE, "BMI": 500}})
    assert r["isError"] and "BMI" in r["content"][0]["text"]


def test_resources_only_kb_files(server):
    res = server.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})["result"]["resources"]
    assert res and all(x["uri"].startswith("kb://") for x in res)
    doc = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": res[0]["uri"]}})
    assert doc["result"]["contents"][0]["text"]
    bad = server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                         "params": {"uri": "kb://../data/diacare.db.key"}})
    assert bad["error"]["code"] == -32602


def test_no_patient_data_or_chat_tool():
    names = {t["name"] for t in Server(DiaCareTools())._tool_list()}
    assert not names & {"chat", "ask", "advise", "journal", "memories", "readings"}


def test_stdio_subprocess():
    """Chạy đúng như host MCP chạy: tiến trình riêng, bản tin JSON từng dòng qua stdin/stdout."""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), DIACARE_EMBED="hash", PYTHONIOENCODING="utf-8")
    msgs = [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "check_lab", "arguments": {"text": "HbA1c 7%"}}},
        "không phải json",
    ]
    lines = "\n".join(m if isinstance(m, str) else json.dumps(m, ensure_ascii=False) for m in msgs) + "\n"
    p = subprocess.run([sys.executable, "-m", "diacare.mcp_server"], input=lines.encode("utf-8"),
                       capture_output=True, env=env, timeout=120)
    out = [json.loads(x) for x in p.stdout.decode("utf-8").splitlines()]
    assert [o.get("id") for o in out] == [0, 1, None]           # notification không có trả lời
    assert out[1]["result"]["structuredContent"]["results"][0]["level"] == "diabetes"
    assert out[2]["error"]["code"] == -32700
