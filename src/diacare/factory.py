from pathlib import Path

from diacare.kb import load_kb
from diacare.llm import ollama_llm, sbert_embed_fn
from diacare.orchestrator import Orchestrator
from diacare.predictor import Predictor
from diacare.retriever import Retriever

ROOT = Path(__file__).resolve().parent.parent.parent


def build_orchestrator(kb_dir=None, model_dir=None, log_path=None, llm=None, store=None, session_id=None):
    kb_dir = kb_dir or ROOT / "kb"
    model_dir = model_dir or ROOT / "models"
    log_path = log_path or ROOT / "logs" / "runs.jsonl"
    retriever = Retriever(sbert_embed_fn(), load_kb(kb_dir))
    return Orchestrator(
        Predictor(model_dir), retriever, llm or ollama_llm(), log_path=log_path, store=store, session_id=session_id
    )
