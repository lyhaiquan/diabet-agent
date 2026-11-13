import json
import os
from pathlib import Path

from diacare.db import Store
from diacare.kb import load_kb
from diacare.kg import GraphAgent, MemoryKG, Neo4jKG
from diacare.labs import LabAgent
from diacare.llm import DEFAULT_NUM_CTX, DemoLLM, OllamaLLM, hash_embed_fn, sbert_embed_fn
from diacare.memory import MemoryAgent
from diacare.nutrition import NutritionAgent, load_foods
from diacare.orchestrator import Orchestrator
from diacare.predictor import Predictor
from diacare.retriever import Retriever
from diacare.rl import DEFAULT_EPSILON, RLAgent, load_policy

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "diacare.db"


def make_llm(kind=None, model=None, num_ctx=None):
    kind = (kind or os.environ.get("DIACARE_LLM") or "ollama").lower()
    if kind == "demo":
        return DemoLLM()
    model = model or os.environ.get("DIACARE_MODEL") or "qwen2.5:3b"
    num_ctx = int(num_ctx or os.environ.get("DIACARE_NUM_CTX") or DEFAULT_NUM_CTX)
    return OllamaLLM(model=model, num_ctx=num_ctx)


def make_embed_fn(kind=None):
    kind = (kind or os.environ.get("DIACARE_EMBED") or "sbert").lower()
    return hash_embed_fn() if kind == "hash" else sbert_embed_fn()


# Ngưỡng điểm truy xuất mặc định cho sbert: câu hỏi liên quan đo được 0.36-0.83,
# câu ngoài chủ đề 0.04-0.10 (thử trên kb/ mẫu). Embedding băm (demo) không lọc.
DEFAULT_MIN_SCORE = 0.2


def default_min_score(kind=None):
    env = os.environ.get("DIACARE_MIN_SCORE")
    if env is not None:
        return float(env)
    kind = (kind or os.environ.get("DIACARE_EMBED") or "sbert").lower()
    return 0.0 if kind == "hash" else DEFAULT_MIN_SCORE


FEATURES_ALL = ("nutrition", "memory", "labs", "hybrid", "kg", "rl")
# Mặc định V2 KHÔNG bật hybrid: đo trong docs/results/2026-11-05_retrieval_eval.md, hybrid chỉ tăng MRR
# rất ít nhưng lọc câu ngoài chủ đề kém hơn dense (0.25 so với 0.50). Bật bằng "all" hoặc "hybrid".
FEATURES_V2 = ("nutrition", "memory", "labs")
# Khi chạy ứng dụng không đặt DIACARE_FEATURES thì bật đồ thị tri thức (KG) và agent học tăng cường (RL).
# Nhãn 'v2' vẫn giữ nguyên nghĩa cũ (không KG, không RL) để các benchmark đã chạy tái lập được.
FEATURES_DEFAULT = FEATURES_V2 + ("kg", "rl")


def parse_features(value=None):
    """Mặc định / 'default' = FEATURES_DEFAULT (V2 + KG + RL); 'v2' = FEATURES_V2; 'all'/'v3' = mọi tính năng;
    'v1'/'none'/'' = tắt hết; hoặc danh sách."""
    if value is None:
        value = os.environ.get("DIACARE_FEATURES")
        if value is None:
            value = "default"
    value = value.strip().lower()
    if value in ("", "v1", "none"):
        return set()
    out = set()
    for part in (p.strip() for p in value.split(",")):
        if part in ("all", "v3"):
            out |= set(FEATURES_ALL)
        elif part == "v2":
            out |= set(FEATURES_V2)
        elif part == "default":
            out |= set(FEATURES_DEFAULT)
        elif part in FEATURES_ALL:
            out.add(part)
        elif part in ("", "v1", "none"):
            continue
        else:
            raise ValueError(f"tính năng không biết: {part!r} (cho phép: all, v1, {', '.join(FEATURES_ALL)})")
    return out


def open_store(path=None):
    path = Path(path or os.environ.get("DIACARE_DB") or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return Store(path)


def rl_epsilon(value=None):
    """Tỉ lệ thăm dò của agent RL: tham số, rồi DIACARE_RL_EPSILON, rồi mặc định 0,1. Benchmark đặt 0."""
    if value is not None:
        return float(value)
    env = os.environ.get("DIACARE_RL_EPSILON")
    return float(env) if env is not None else DEFAULT_EPSILON


class Parts:
    """Các phần nặng, không giữ dữ liệu người dùng: dựng một lần, dùng chung cho mọi lượt hỏi."""

    def __init__(self, predictor, retriever, llm, nutrition_agent, graph_agent, rl_prior, features, log_path):
        self.predictor, self.retriever, self.llm = predictor, retriever, llm
        self.nutrition_agent, self.graph_agent, self.rl_prior = nutrition_agent, graph_agent, rl_prior
        self.features, self.log_path = features, log_path


def build_parts(kb_dir=None, model_dir=None, log_path=None, llm=None, embed_fn=None, min_score=None,
                features=None):
    kb_dir = kb_dir or os.environ.get("DIACARE_KB") or ROOT / "kb"
    model_dir = model_dir or ROOT / "models"
    log_path = log_path or os.environ.get("DIACARE_LOG") or ROOT / "logs" / "runs.jsonl"
    if min_score is None:
        min_score = default_min_score()
    if features is None or isinstance(features, str):
        features = parse_features(features)
    nutrition_agent = None
    if "nutrition" in features:
        nutrition_agent = NutritionAgent(load_foods(ROOT / "data" / "nutrition" / "vn_foods.json"))
    retriever = Retriever(embed_fn or make_embed_fn(), load_kb(kb_dir), min_score=min_score,
                          mode="hybrid" if "hybrid" in features else "dense")
    graph_agent = make_graph_agent() if "kg" in features else None
    rl_prior = load_policy() if "rl" in features else None
    return Parts(Predictor(model_dir), retriever, llm or make_llm(), nutrition_agent, graph_agent, rl_prior,
                 set(features), log_path)


def orchestrator_from_parts(parts, store, session_id=None, rl_epsilon_value=None):
    """Orchestrator cho một lượt: các agent có trạng thái (Memory, Lab, RL) gắn vào `store` của lượt đó.
    RLAgent đọc lại mô hình mới nhất từ bảng rl_model nên không có trạng thái dùng chung giữa các lượt."""
    f = parts.features
    return Orchestrator(
        parts.predictor, parts.retriever, parts.llm, log_path=parts.log_path, store=store, session_id=session_id,
        nutrition_agent=parts.nutrition_agent,
        memory_agent=MemoryAgent(store) if "memory" in f else None,
        lab_agent=LabAgent(store) if "labs" in f else None,
        graph_agent=parts.graph_agent,
        rl_agent=RLAgent(prior=parts.rl_prior, store=store, epsilon=rl_epsilon(rl_epsilon_value)) if "rl" in f
        else None,
    )


def build_orchestrator(kb_dir=None, model_dir=None, log_path=None, llm=None, store=None,
                       session_id=None, embed_fn=None, min_score=None, features=None, rl_epsilon_value=None):
    parts = build_parts(kb_dir, model_dir, log_path, llm, embed_fn, min_score, features)
    # Không truyền store: Memory/Lab/RL vẫn cần nơi lưu trong lượt, dùng SQLite trong bộ nhớ
    shared = store or (Store(":memory:") if {"memory", "labs", "rl"} & parts.features else None)
    orch = orchestrator_from_parts(parts, shared, session_id, rl_epsilon_value)
    orch.store = store
    return orch


def neo4j_config():
    """Kết nối Neo4j: biến môi trường NEO4J_URI/USER/PASSWORD, nếu không có thì neo4j.local.json."""
    cfg = {}
    path = ROOT / "neo4j.local.json"
    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
    return (os.environ.get("NEO4J_URI", cfg.get("uri", "bolt://localhost:7688")),
            os.environ.get("NEO4J_USER", cfg.get("user", "neo4j")),
            os.environ.get("NEO4J_PASSWORD", cfg.get("password")))


def make_graph_agent(kind=None):
    """DIACARE_KG=neo4j: đọc đồ thị từ Neo4j (tools/kg_neo4j.py phải đã nạp).
    Mặc định, hoặc khi không kết nối được Neo4j: dựng đồ thị networkx trong bộ nhớ từ tệp."""
    kind = (kind or os.environ.get("DIACARE_KG") or "memory").lower()
    if kind == "neo4j":
        uri, user, password = neo4j_config()
        try:
            return GraphAgent(Neo4jKG(uri, user, password))
        except Exception as exc:  # không có Neo4j thì vẫn chạy được, ghi rõ đang dùng gì
            print(f"[kg] Không kết nối được Neo4j ở {uri} ({type(exc).__name__}); dùng networkx trong bộ nhớ.")
    return GraphAgent(MemoryKG())
