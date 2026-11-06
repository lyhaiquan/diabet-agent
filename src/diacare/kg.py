"""Đồ thị tri thức tiểu đường: cạnh có kiểu, tách theo nguồn gốc, và dùng để kiểm chứng tài liệu.

Ba nguồn cạnh có độ tin cậy khác nhau nên không được trộn làm một loại "có liên quan":

- Tra cứu (reference), coi như đúng:
    LabTest  -[indicates {min, max, unit}]->  Condition      ngưỡng ADA 2024 trong labs.THRESHOLDS
    Symptom  -[requires]->                    Action         luật chuyển khám / cấp cứu trong rules.py
    Food     -[contains {g_per_100g}]->       Nutrient       bảng USDA trong data/nutrition/vn_foods.json
- Tính từ dữ liệu, đo được:
    RiskFactor -[associated_with {or_marginal, or_adjusted, n}]-> Condition   BRFSS 2015 (tools/build_kg_stats.py)
- Trích từ tài liệu, là lời khẳng định:
    RiskFactor -[claims_risk {direction, source, sentence}]-> Condition       câu trong kb/ (MedlinePlus, WHO)

Điểm chính: một cạnh claims_risk có thể đem đối chiếu với cạnh associated_with cùng cặp nút
(verify_claims). Yếu tố nào không có cột trong BRFSS (tiền sử gia đình, chủng tộc, thai kỳ...) thì không
kiểm chứng được bằng dữ liệu, và đồ thị nói rõ điều đó thay vì lặng lẽ bỏ qua.

Mặc định chạy trên networkx trong bộ nhớ, không cần máy chủ. Xuất sang Neo4j bằng to_cypher()
(xem tools/kg_neo4j.py).
"""
import json
import re
from pathlib import Path

import networkx as nx

from diacare.labs import LABELS as LAB_LABELS, LOW_GLUCOSE_MGDL, THRESHOLDS
from diacare.nutrition import strip_accents
from diacare.rules import EMERGENCY_TERMS, SYMPTOM_TERMS

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STATS = ROOT / "kb" / "graph" / "brfss_associations.json"
DEFAULT_FOODS = ROOT / "data" / "nutrition" / "vn_foods.json"
DEFAULT_KB = ROOT / "kb"

TARGET = "T2D"   # nút đích của mọi cạnh nguy cơ: đái tháo đường típ 2

# Yếu tố nguy cơ. `feature` là cột BRFSS tương ứng (None: dữ liệu không đo, nên không kiểm chứng được).
# `approx` đánh dấu chỗ cột BRFSS chỉ gần đúng với khái niệm trong tài liệu.
# `vi` là cách gọi tiếng Việt để nối câu hỏi của người dùng vào đồ thị (tài liệu là tiếng Anh).
RISK_FACTORS = {
    "OBESITY":         dict(name="Thừa cân, béo phì", feature="BMI",
                            vi=["béo phì", "thừa cân", "cân nặng", "bmi", "béo bụng", "giảm cân"]),
    "AGE":             dict(name="Tuổi cao", feature="Age",
                            vi=["tuổi", "lớn tuổi", "người già", "cao tuổi"]),
    "INACTIVITY":      dict(name="Ít vận động", feature="PhysActivity",
                            vi=["vận động", "tập thể dục", "thể dục", "đi bộ", "lười vận động", "ít vận động"]),
    "HIGH_BP":         dict(name="Tăng huyết áp", feature="HighBP",
                            vi=["huyết áp cao", "tăng huyết áp", "cao huyết áp", "huyết áp"]),
    "HIGH_CHOL":       dict(name="Rối loạn mỡ máu", feature="HighChol", approx=True,
                            vi=["mỡ máu", "cholesterol", "máu nhiễm mỡ", "triglycerid"]),
    "HEART_DISEASE":   dict(name="Bệnh tim", feature="HeartDiseaseorAttack",
                            vi=["bệnh tim", "nhồi máu cơ tim", "tim mạch"]),
    "STROKE":          dict(name="Đột quỵ", feature="Stroke", vi=["đột quỵ", "tai biến"]),
    "SMOKING":         dict(name="Hút thuốc lá", feature="Smoker", vi=["hút thuốc", "thuốc lá"]),
    "HEALTHY_DIET":    dict(name="Ăn nhiều rau, trái cây", feature="Veggies", approx=True,
                            vi=["rau", "trái cây", "hoa quả", "ăn uống lành mạnh", "chế độ ăn"]),
    "FAMILY_HISTORY":  dict(name="Tiền sử gia đình", feature=None,
                            vi=["di truyền", "gia đình", "bố mẹ", "cha mẹ", "anh chị em", "bố tôi",
                                "mẹ tôi", "ông bà", "người thân"]),
    "PREDIABETES":     dict(name="Tiền đái tháo đường", feature=None,
                            vi=["tiền tiểu đường", "tiền đái tháo đường"]),
    "GESTATIONAL":     dict(name="Đái tháo đường thai kỳ, con to khi sinh", feature=None,
                            vi=["thai kỳ", "mang thai", "có bầu", "sinh con"]),
    "ETHNICITY":       dict(name="Nhóm chủng tộc", feature=None, vi=["chủng tộc", "người châu á"]),
    "PCOS":            dict(name="Hội chứng buồng trứng đa nang", feature=None, vi=["buồng trứng đa nang", "pcos"]),
    "DEPRESSION":      dict(name="Trầm cảm", feature=None, vi=["trầm cảm"]),
    "ACANTHOSIS":      dict(name="Gai đen (acanthosis nigricans)", feature=None, vi=["gai đen", "da sẫm màu"]),
    "GENETICS":        dict(name="Yếu tố di truyền", feature=None, vi=["gen"]),
}

# Cụm tiếng Anh trong tài liệu -> (yếu tố, chiều tác động lên nguy cơ). Chiều +1: có yếu tố thì nguy cơ tăng.
# Chiều được gán theo cụm chứ không bằng một quy tắc phủ định chung, vì tài liệu nói cùng một ý theo hai
# kiểu: "are not physically active" (danh sách nguy cơ) và "regular physical activity" (cách phòng ngừa).
CLAIM_PHRASES = [
    (r"overweight|obesity|normal body weight|losing weight", "OBESITY", +1),
    (r"over age \d+|older (?:adults|people)", "AGE", +1),
    (r"not physically active|not getting enough exercise", "INACTIVITY", +1),
    (r"physical(?:ly)? activ|regular exercise", "INACTIVITY", +1),
    (r"high blood pressure", "HIGH_BP", +1),
    (r"heart disease", "HEART_DISEASE", +1),
    (r"\bstroke\b", "STROKE", +1),
    (r"low hdl|high triglycerides", "HIGH_CHOL", +1),
    (r"tobacco|\bsmok", "SMOKING", +1),
    (r"healthy diet", "HEALTHY_DIET", -1),
    (r"family history|parent or sibling", "FAMILY_HISTORY", +1),
    (r"prediabetes|impaired glucose tolerance", "PREDIABETES", +1),
    (r"gestational diabetes|diabetes in pregnancy|baby weighing 9 pounds", "GESTATIONAL", +1),
    (r"african american|hispanic|asian american|pacific islander|american indian", "ETHNICITY", +1),
    (r"polycystic ovary|pcos", "PCOS", +1),
    (r"depression", "DEPRESSION", +1),
    (r"acanthosis nigricans", "ACANTHOSIS", +1),
    (r"genetics", "GENETICS", +1),
]
_CLAIM_RX = [(re.compile(p, re.IGNORECASE), f, d) for p, f, d in CLAIM_PHRASES]

# Câu mở đầu danh sách yếu tố nguy cơ, và câu nói về phòng ngừa. Chỉ trích trong hai ngữ cảnh này:
# câu "người tiểu đường có nguy cơ cao bị đột quỵ" nói chiều ngược lại (biến chứng), không phải yếu tố nguy cơ.
_LIST_HEAD = re.compile(r"higher risk of developing (type 2|gestational) diabetes if you", re.IGNORECASE)
_PREVENT = re.compile(r"prevent or delay|ways to prevent|contribute to developing type 2", re.IGNORECASE)

# Ngưỡng coi một mối liên hệ là đáng kể: OR nằm ngoài [1/1.1; 1.1] thì mới xét dấu.
OR_WEAK = 1.1

NUTRIENTS = {"carb_g": "Tinh bột (carb)", "sugar_g": "Đường", "fiber_g": "Chất xơ"}


def _sentences(text):
    """Tách tài liệu thành câu, giữ dấu hiệu "đang ở trong danh sách nguy cơ".

    Tài liệu MedlinePlus viết danh sách thành nhiều dòng ngắn sau một câu mở đầu; danh sách kết thúc
    khi gặp một dòng tiêu đề kết thúc bằng dấu hỏi hoặc một câu mở đầu danh sách khác.
    """
    in_list, kind = False, None
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        head = _LIST_HEAD.search(line)
        if head:
            in_list, kind = True, head.group(1).lower()
            continue
        if line.endswith("?") or (in_list and len(line) > 220):
            in_list = False
        if in_list:
            yield line, "risk_list", kind
        else:
            for s in re.split(r"(?<=[.!?])\s+", line):
                if _PREVENT.search(s):
                    yield s, "prevention", "type 2"


def extract_claims(docs):
    """Trích khẳng định "yếu tố X làm tăng/giảm nguy cơ đái tháo đường típ 2" từ tài liệu kb/.

    docs: danh sách (tên tệp, nội dung) như diacare.kb.load_kb trả về.
    Chỉ giữ khẳng định về típ 2; danh sách nguy cơ của đái tháo đường thai kỳ là chuyện khác.
    """
    out, seen = [], set()
    for source, text in docs:
        for sentence, context, kind in _sentences(text):
            if kind != "type 2":
                continue
            for rx, factor, direction in _CLAIM_RX:
                if rx.search(sentence) and (source, factor) not in seen:
                    seen.add((source, factor))
                    out.append({"factor": factor, "direction": direction, "source": source,
                                "context": context, "sentence": sentence[:240]})
    return out


def verify_claim(claim, stats):
    """Đối chiếu một khẳng định với mối liên hệ đo được trong BRFSS.

    Trả về một trong bốn kết luận: nhất quán, mâu thuẫn, không đủ bằng chứng (OR quá gần 1),
    không kiểm chứng được (BRFSS không có cột tương ứng).
    """
    meta = RISK_FACTORS[claim["factor"]]
    feat = meta.get("feature")
    if feat is None or feat not in stats["features"]:
        return {**claim, "verdict": "không kiểm chứng được", "reason": "BRFSS không đo yếu tố này"}
    s = stats["features"][feat]
    # Cột PhysActivity đo "có vận động", ngược chiều với nút INACTIVITY; tương tự Veggies với chế độ ăn.
    sign_flip = -1 if feat == "PhysActivity" else 1
    odds = s["or_marginal"]
    observed = 0 if 1 / OR_WEAK <= odds <= OR_WEAK else (1 if odds > 1 else -1)
    observed *= sign_flip
    if observed == 0:
        verdict = "không đủ bằng chứng"
    else:
        verdict = "nhất quán" if observed == claim["direction"] else "mâu thuẫn"
    return {**claim, "verdict": verdict, "feature": feat, "or_marginal": odds,
            "or_adjusted": s["or_adjusted"], "approx": bool(meta.get("approx"))}


def verify_claims(claims, stats):
    return [verify_claim(c, stats) for c in claims]


def _lab_edges(g):
    """Ngưỡng ADA 2024 thành cạnh LabTest -[indicates]-> Condition."""
    # Ngưỡng xét nghiệm chỉ ra đái tháo đường nói chung, không phân típ, nên dùng nút riêng
    # thay vì nút TARGET (típ 2) của các cạnh nguy cơ.
    for c, name in (("NORMAL", "Bình thường"), ("PREDIABETES_LAB", "Tiền đái tháo đường"),
                    ("DIABETES_LAB", "Ngưỡng chẩn đoán đái tháo đường"), ("HYPOGLYCEMIA", "Hạ đường huyết"),
                    (TARGET, "Đái tháo đường típ 2")):
        g.add_node(c, label="Condition", name=name)
    for test, (pre, dia) in THRESHOLDS.items():
        unit = "%" if test == "hba1c" else "mg/dL"
        g.add_node(test, label="LabTest", name=LAB_LABELS[test])
        if pre is not None:
            g.add_edge(test, "NORMAL", key="normal", rel="indicates", max=pre, unit=unit, source="ada_2024")
            g.add_edge(test, "PREDIABETES_LAB", key="pre", rel="indicates", min=pre, max=dia,
                       unit=unit, source="ada_2024")
        g.add_edge(test, "DIABETES_LAB", key="dia", rel="indicates", min=dia, unit=unit, source="ada_2024")
        if test != "hba1c":
            g.add_edge(test, "HYPOGLYCEMIA", key="low", rel="indicates", max=LOW_GLUCOSE_MGDL,
                       unit=unit, source="ada_2024")


def _rule_edges(g):
    """Luật an toàn của rules.py thành cạnh Symptom -[requires]-> Action."""
    g.add_node("SEE_DOCTOR", label="Action", name="Đi khám bác sĩ")
    g.add_node("EMERGENCY", label="Action", name="Gọi cấp cứu 115")
    for term in SYMPTOM_TERMS:
        g.add_node("sym:" + term, label="Symptom", name=term)
        g.add_edge("sym:" + term, "SEE_DOCTOR", key="rule", rel="requires", source="rules.py")
    for term in EMERGENCY_TERMS:
        g.add_node("sym:" + term, label="Symptom", name=term)
        g.add_edge("sym:" + term, "EMERGENCY", key="rule", rel="requires", source="rules.py")


def _food_edges(g, foods):
    for key, name in NUTRIENTS.items():
        g.add_node(key, label="Nutrient", name=name)
    for f in foods:
        fid = "food:" + f["name"]
        g.add_node(fid, label="Food", name=f["name"], usda_fdc_id=f.get("usda_fdc_id"))
        for key in NUTRIENTS:
            v = f.get("per_100g", {}).get(key)
            if v is not None:
                g.add_edge(fid, key, key="usda", rel="contains", g_per_100g=float(v), source="usda_fdc")


def build_graph(stats=None, foods=None, docs=None):
    """Dựng đồ thị từ ba nguồn. Thiếu nguồn nào thì bỏ loại cạnh đó, không báo lỗi."""
    g = nx.MultiDiGraph()
    _lab_edges(g)
    _rule_edges(g)
    if foods:
        _food_edges(g, foods)
    for fid, meta in RISK_FACTORS.items():
        g.add_node(fid, label="RiskFactor", name=meta["name"], brfss=meta.get("feature"),
                   measurable=meta.get("feature") is not None)
    if stats:
        for fid, meta in RISK_FACTORS.items():
            s = stats["features"].get(meta.get("feature") or "")
            if s:
                g.add_edge(fid, TARGET, key="brfss", rel="associated_with", or_marginal=s["or_marginal"],
                           or_adjusted=s["or_adjusted"], unit=s["unit"], n=stats["n"], source="brfss_2015")
    if docs:
        claims = extract_claims(docs)
        checked = verify_claims(claims, stats) if stats else claims
        for c in checked:
            g.add_edge(c["factor"], TARGET, key="claim:" + c["source"], rel="claims_risk",
                       direction=c["direction"], source=c["source"], sentence=c["sentence"],
                       verdict=c.get("verdict", "chưa đối chiếu"))
    return g


def load_default_graph(stats_path=DEFAULT_STATS, foods_path=DEFAULT_FOODS, kb_dir=DEFAULT_KB):
    from diacare.kb import load_kb
    stats = json.loads(Path(stats_path).read_text(encoding="utf-8")) if Path(stats_path).exists() else None
    foods = (json.loads(Path(foods_path).read_text(encoding="utf-8"))["foods"]
             if Path(foods_path).exists() else None)
    docs = load_kb(kb_dir) if Path(kb_dir).is_dir() else None
    return build_graph(stats, foods, docs)


# ---------- truy vấn ----------

def _alias_rx():
    out = {}
    for fid, meta in RISK_FACTORS.items():
        al = sorted({strip_accents(a.lower()) for a in meta["vi"]}, key=len, reverse=True)
        out[fid] = re.compile(r"(?<![a-z])(" + "|".join(re.escape(a) for a in al) + r")(?![a-z])")
    return out


_ALIAS = _alias_rx()


def link_factors(question):
    """Nối câu hỏi tiếng Việt vào các nút yếu tố nguy cơ (so khớp không dấu)."""
    q = strip_accents(question.lower())
    return [fid for fid, rx in _ALIAS.items() if rx.search(q)]


def edges_of(g, rel, src=None, dst=None):
    return [(u, v, d) for u, v, d in g.edges(data=True)
            if d["rel"] == rel and (src is None or u == src) and (dst is None or v == dst)]


def factor_facts(g, fid):
    """Gom ba loại cạnh của một yếu tố nguy cơ thành một mục, giữ nguyên nguồn của từng thứ."""
    node = g.nodes[fid]
    assoc = edges_of(g, "associated_with", fid, TARGET)
    claims = edges_of(g, "claims_risk", fid, TARGET)
    return {"factor": fid, "name": node["name"], "measurable": node["measurable"],
            "association": assoc[0][2] if assoc else None,
            "claims": [{"source": d["source"], "direction": d["direction"], "verdict": d["verdict"]}
                       for _, _, d in claims]}


def describe_factor(facts):
    """Một dòng ngữ cảnh cho Advisor, tách rõ "tài liệu nói" và "dữ liệu đo"."""
    parts = [facts["name"] + ":"]
    if facts["claims"]:
        src = ", ".join(sorted({c["source"].split(".")[0] for c in facts["claims"]}))
        protective = all(c["direction"] < 0 for c in facts["claims"])
        parts.append(f"tài liệu ({src}) nêu là "
                     + ("yếu tố bảo vệ, giúp giảm nguy cơ." if protective else "yếu tố nguy cơ."))
    a = facts["association"]
    if a:
        n = f"{a['n']:,}".replace(",", ".")
        vn = lambda x: f"{x:g}".replace(".", ",")   # noqa: E731  số thập phân kiểu Việt
        parts.append(f"BRFSS 2015 (n = {n}): OR {vn(a['or_marginal'])} khi xét riêng, "
                     f"{vn(a['or_adjusted'])} khi hiệu chỉnh 21 chỉ số ({a['unit']}); là liên hệ, không phải nhân quả.")
        far = not 1 / OR_WEAK <= a["or_marginal"] <= OR_WEAK
        near = 1 / OR_WEAK <= a["or_adjusted"] <= OR_WEAK
        if far and near:
            parts.append("Liên hệ gần như biến mất sau hiệu chỉnh, nên phần lớn đến từ các yếu tố đi kèm.")
    elif not facts["measurable"]:
        parts.append("dữ liệu khảo sát không đo yếu tố này nên chưa đối chiếu được.")
    verdicts = {c["verdict"] for c in facts["claims"]}
    if "mâu thuẫn" in verdicts:
        parts.append("Lưu ý: dữ liệu cho chiều ngược với tài liệu.")
    return " ".join(parts)


def facts_for_question(g, question, limit=3):
    """Các dòng tri thức từ đồ thị liên quan tới câu hỏi, để ghép vào ngữ cảnh của Advisor."""
    return [describe_factor(factor_facts(g, f)) for f in link_factors(question)[:limit]]


def structure(g):
    """Số liệu cấu trúc: đếm nút, cạnh theo loại, và tỉ lệ khẳng định kiểm chứng được."""
    rels, labels = {}, {}
    for _, _, d in g.edges(data=True):
        rels[d["rel"]] = rels.get(d["rel"], 0) + 1
    for _, d in g.nodes(data=True):
        labels[d["label"]] = labels.get(d["label"], 0) + 1
    verdicts = {}
    for _, _, d in edges_of(g, "claims_risk"):
        verdicts[d["verdict"]] = verdicts.get(d["verdict"], 0) + 1
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "by_relation": rels, "by_label": labels, "claim_verdicts": verdicts}


# ---------- xuất Neo4j ----------

def _cy(v):
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return repr(v)
    if v is None:
        return "null"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def to_cypher(g):
    """Script Cypher dựng lại đồ thị trong Neo4j. Dùng MERGE nên chạy lại nhiều lần vẫn đúng."""
    lines = ["CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE;"]
    for n, d in g.nodes(data=True):
        props = ", ".join(f"n.{k} = {_cy(v)}" for k, v in sorted(d.items()) if k != "label")
        lines.append(f"MERGE (n:Entity:{d['label']} {{id: {_cy(n)}}}) SET {props};")
    for u, v, d in g.edges(data=True):
        props = ", ".join(f"{k}: {_cy(val)}" for k, val in sorted(d.items()) if k != "rel")
        lines.append(f"MATCH (a:Entity {{id: {_cy(u)}}}), (b:Entity {{id: {_cy(v)}}}) "
                     f"MERGE (a)-[:{d['rel']} {{{props}}}]->(b);")
    return "\n".join(lines) + "\n"


# ---------- đọc đồ thị từ Neo4j ----------

# Cùng một câu hỏi như factor_facts() nhưng chạy bằng Cypher trên Neo4j.
FACTOR_CYPHER = """
MATCH (f:RiskFactor {id: $fid})
OPTIONAL MATCH (f)-[a:associated_with]->(:Condition {id: 'T2D'})
OPTIONAL MATCH (f)-[c:claims_risk]->(:Condition {id: 'T2D'})
RETURN f.name AS name, f.measurable AS measurable,
       a {.or_marginal, .or_adjusted, .unit, .n} AS association,
       collect(c {.source, .direction, .verdict}) AS claims
"""


class Neo4jKG:
    """Đồ thị nằm trong Neo4j; ứng dụng truy vấn qua bolt thay vì dựng lại trong bộ nhớ."""

    name = "neo4j"

    def __init__(self, uri, user, password):
        from neo4j import GraphDatabase   # chỉ cần thư viện neo4j khi thật sự dùng Neo4j
        self.uri = uri
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.driver.verify_connectivity()

    def factor_facts(self, fid):
        with self.driver.session() as s:
            r = s.run(FACTOR_CYPHER, fid=fid).single()
        if r is None:
            return None
        return {"factor": fid, "name": r["name"], "measurable": r["measurable"],
                "association": r["association"], "claims": r["claims"]}

    def close(self):
        self.driver.close()


class MemoryKG:
    """Đồ thị networkx trong bộ nhớ, dựng từ tệp. Dùng khi không có Neo4j (test, demo, Kaggle)."""

    name = "networkx"

    def __init__(self, g=None):
        self.g = g if g is not None else load_default_graph()

    def factor_facts(self, fid):
        return factor_facts(self.g, fid) if fid in self.g else None


class GraphAgent:
    """Agent đồ thị: nối câu hỏi vào nút yếu tố nguy cơ rồi lấy cả ba loại cạnh của từng nút."""

    def __init__(self, backend, limit=3):
        self.backend, self.limit = backend, limit

    def lookup(self, question):
        facts = [f for f in (self.backend.factor_facts(fid) for fid in link_factors(question)[:self.limit]) if f]
        return {"backend": self.backend.name, "factors": [f["factor"] for f in facts],
                "lines": [describe_factor(f) for f in facts]}


def format_kg(kg):
    """Khối ngữ cảnh gửi cho Advisor."""
    if not kg or not kg["lines"]:
        return ""
    return ("Tri thức từ đồ thị [kg] (tài liệu nói gì và dữ liệu BRFSS đo được gì; "
            "số liệu là mối liên hệ thống kê, không phải quan hệ nhân quả):\n"
            + "\n".join("- " + line for line in kg["lines"]))
