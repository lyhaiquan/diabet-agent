import json
import urllib.request


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
