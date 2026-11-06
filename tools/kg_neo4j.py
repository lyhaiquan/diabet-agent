"""Nạp đồ thị tri thức DiaCare vào Neo4j chạy trong Docker và chạy các truy vấn Cypher minh hoạ.

Dùng container riêng `diacare-neo4j` trên cổng 7475 (Browser) và 7688 (bolt), để không đụng tới
Neo4j của dự án khác trên 7474/7687: script xoá sạch cơ sở dữ liệu trước khi nạp.
Mật khẩu sinh ngẫu nhiên, lưu trong neo4j.local.json ở gốc repo (đã gitignore).

Chạy:  python tools/kg_neo4j.py
Rồi mở http://localhost:7475, kết nối bolt://localhost:7688, user neo4j, mật khẩu trong neo4j.local.json.
Kết quả truy vấn ghi ra docs/results/kg_neo4j_queries.json.
"""
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.kg import load_default_graph, structure, to_cypher  # noqa: E402

NAME = "diacare-neo4j"
CFG = ROOT / "neo4j.local.json"
OUT = ROOT / "docs" / "results" / "kg_neo4j_queries.json"

QUERIES = [
    ("Yếu tố nào tài liệu nêu là nguy cơ nhưng dữ liệu BRFSS không đo được?",
     """MATCH (f:RiskFactor)-[c:claims_risk]->(:Condition {id: 'T2D'})
        WHERE NOT f.measurable
        RETURN f.name AS yeu_to, collect(DISTINCT c.source) AS nguon ORDER BY yeu_to"""),
    ("Với yếu tố đo được: tài liệu nói gì, dữ liệu đo được bao nhiêu?",
     """MATCH (f:RiskFactor)-[a:associated_with]->(t:Condition {id: 'T2D'})
        OPTIONAL MATCH (f)-[c:claims_risk]->(t)
        RETURN f.name AS yeu_to, a.or_marginal AS or_rieng, a.or_adjusted AS or_hieu_chinh,
               count(c) AS so_tai_lieu_neu, collect(DISTINCT c.verdict) AS ket_luan
        ORDER BY or_rieng DESC"""),
    ("HbA1c bao nhiêu thì ở mức nào (ngưỡng ADA 2024)?",
     """MATCH (:LabTest {id: 'hba1c'})-[r:indicates]->(c:Condition)
        RETURN c.name AS muc, r.min AS tu, r.max AS duoi, r.unit AS don_vi ORDER BY coalesce(r.min, 0)"""),
    ("Triệu chứng nào phải gọi cấp cứu?",
     """MATCH (s:Symptom)-[:requires]->(:Action {id: 'EMERGENCY'}) RETURN s.name AS trieu_chung ORDER BY trieu_chung"""),
    ("Năm món nhiều tinh bột nhất trên 100 g",
     """MATCH (f:Food)-[r:contains]->(:Nutrient {id: 'carb_g'})
        RETURN f.name AS mon, r.g_per_100g AS carb_g ORDER BY carb_g DESC LIMIT 5"""),
    ("Đếm cạnh theo loại",
     """MATCH ()-[r]->() RETURN type(r) AS loai_canh, count(*) AS so_canh ORDER BY so_canh DESC"""),
]


def _config():
    if not CFG.exists():
        CFG.write_text(json.dumps({"uri": "bolt://localhost:7688", "user": "neo4j",
                                   "password": "dc-" + secrets.token_urlsafe(12)}, indent=1), encoding="utf-8")
    return json.loads(CFG.read_text(encoding="utf-8"))


def _start(cfg):
    have = subprocess.run(["docker", "ps", "-a", "-q", "-f", f"name=^{NAME}$"],
                          capture_output=True, text=True).stdout.strip()
    if have:
        subprocess.run(["docker", "start", NAME], check=True, capture_output=True)
    else:
        subprocess.run(["docker", "run", "-d", "--name", NAME, "-p", "7475:7474", "-p", "7688:7687",
                        "-e", f"NEO4J_AUTH={cfg['user']}/{cfg['password']}", "neo4j:5"],
                       check=True, capture_output=True)


def _connect(cfg):
    from neo4j import GraphDatabase
    for _ in range(60):          # Neo4j cần 10-30 giây mới nhận kết nối
        try:
            drv = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
            drv.verify_connectivity()
            return drv
        except Exception:
            time.sleep(2)
    raise SystemExit(f"Neo4j không lên sau 2 phút; xem: docker logs {NAME}")


def main():
    cfg = _config()
    _start(cfg)
    drv = _connect(cfg)
    g = load_default_graph()
    stmts = [s for s in to_cypher(g).split(";\n") if s.strip()]
    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
        s.run(stmts[0])                      # ràng buộc id duy nhất, phải chạy ngoài giao dịch dữ liệu
        with s.begin_transaction() as tx:
            for st in stmts[1:]:
                tx.run(st)
            tx.commit()
        nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"Đã nạp {nodes} nút, {rels} cạnh vào {cfg['uri']}")
        res = {"nodes": nodes, "edges": rels, "graph": structure(g), "queries": []}
        for question, cypher in QUERIES:
            rows = [r.data() for r in s.run(cypher)]
            res["queries"].append({"question": question, "cypher": " ".join(cypher.split()), "rows": rows})
            print("\n# " + question)
            for r in rows[:10]:
                print("  ", r)
    drv.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
