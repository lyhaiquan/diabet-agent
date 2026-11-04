import json
import urllib.request


def ollama_llm(model="qwen2.5:7b", url="http://localhost:11434/v1/chat/completions"):
    def call(messages):
        body = json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode()
        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"]
    return call


def sbert_embed_fn(name="paraphrase-multilingual-MiniLM-L12-v2"):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(name)
    return lambda texts: model.encode(texts)
