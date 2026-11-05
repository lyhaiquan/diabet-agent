import json
import re
import urllib.request
import zlib

import numpy as np


DEFAULT_NUM_CTX = 4096


class OllamaLLM:
    def __init__(self, model="qwen2.5:7b", url="http://localhost:11434/api/chat",
                 num_ctx=DEFAULT_NUM_CTX, temperature=0.2, timeout=300):
        self.model, self.url, self.num_ctx = model, url, num_ctx
        self.temperature, self.timeout = temperature, timeout
        self.last_usage = {}

    def __call__(self, messages):
        body = json.dumps({
            "model": self.model, "messages": messages, "stream": False,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.load(resp)
        self.last_usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "seconds": round(data.get("total_duration", 0) / 1e9, 3),
            "num_ctx": self.num_ctx,
        }
        return data["message"]["content"]


def ollama_llm(**kwargs):
    return OllamaLLM(**kwargs)


def sbert_embed_fn(name="paraphrase-multilingual-MiniLM-L12-v2"):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(name)
    return lambda texts: model.encode(texts)


_NO_DOC_REPLY = "Chưa có đủ thông tin trong tài liệu để trả lời."
_DOC_MARK = "Tài liệu tham khảo:"
_LABEL = re.compile(r"^\[([^\]\n]+)\][ \t]*\n?", re.M)


class DemoLLM:
    """Fake LLM for demos and tests ONLY: quotes the first retrieved document."""

    def __init__(self):
        self.num_ctx = DEFAULT_NUM_CTX
        self.last_usage = {}

    def __call__(self, messages):
        user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        block = user.split(_DOC_MARK, 1)[1] if _DOC_MARK in user else ""
        block = block.split("\n\nCâu hỏi:", 1)[0]
        m = _LABEL.search(block)
        if m:
            rest = block[m.end():]
            nxt = _LABEL.search(rest)
            text = (rest[:nxt.start()] if nxt else rest).strip()
            reply = f"Theo tài liệu [{m.group(1)}]: {text[:160]}."
        else:
            reply = _NO_DOC_REPLY
        total = sum(len(str(x.get("content", ""))) for x in messages)
        self.last_usage = {
            "prompt_tokens": total // 3, "completion_tokens": len(reply) // 3,
            "seconds": 0.0, "num_ctx": DEFAULT_NUM_CTX,
        }
        return reply


def hash_embed_fn(dim=256):
    """Deterministic hashed bag-of-words embedding for demos and tests ONLY."""
    def embed(texts):
        out = np.zeros((len(texts), dim), dtype="float32")
        for i, t in enumerate(texts):
            for tok in re.findall(r"\w+", t.lower()):
                out[i, zlib.crc32(tok.encode()) % dim] += 1
        return out
    return embed
