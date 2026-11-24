import json
import re
import threading
import urllib.error
import urllib.request
import zlib

import numpy as np


DEFAULT_NUM_CTX = 4096
# Giới hạn độ dài câu trả lời = phần ngân sách context chừa cho câu trả lời (context.ANSWER_RESERVE_TOKENS).
# Không giới hạn thì model có thể viết mãi và hết thời gian chờ (đã gặp trên Kaggle lần 2).
DEFAULT_NUM_PREDICT = 512


class _PerThreadUsage:
    """`last_usage` riêng cho từng luồng. Một đối tượng LLM được dùng chung cho mọi lượt hỏi của API; các lượt
    chạy song song trên các luồng khác nhau, mỗi lượt gọi LLM rồi đọc last_usage trên cùng luồng của nó, nên không
    lượt nào đọc nhầm số token của lượt khác."""

    @property
    def last_usage(self):
        return getattr(self.__dict__["_usage"], "value", {})

    @last_usage.setter
    def last_usage(self, value):
        if "_usage" not in self.__dict__:
            self.__dict__["_usage"] = threading.local()
        self.__dict__["_usage"].value = value


# Thời gian chờ mỗi lần đọc socket. Ollama trên máy: 300 giây (lần nạp model đầu tiên có thể lâu). Ollama từ xa qua
# đường hầm (có token, Kaggle): 90 giây; benchmark 7B ngày 2026-11-24 có một yêu cầu treo hết 300 giây vì đường hầm,
# trong khi lượt bình thường chỉ mất khoảng 7 giây. Đổi bằng DIACARE_OLLAMA_TIMEOUT.
LOCAL_TIMEOUT = 300
REMOTE_TIMEOUT = 90


class LLMUnavailable(RuntimeError):
    """Không gọi được mô hình (hết thời gian chờ, mất kết nối, bị từ chối). Thông điệp viết cho người dùng."""


class OllamaLLM(_PerThreadUsage):
    def __init__(self, model="qwen2.5:7b", url="http://localhost:11434/api/chat",
                 num_ctx=DEFAULT_NUM_CTX, temperature=0.2, timeout=None,
                 num_predict=DEFAULT_NUM_PREDICT, token=None):
        self.model, self.url, self.num_ctx = model, url, num_ctx
        # token: khi Ollama chạy ở máy khác qua tunnel công khai (kaggle/build_ollama_notebook.py), cổng chặn phía đó
        # chỉ cho qua yêu cầu có header "Authorization: Bearer <token>"
        self.token = token
        if timeout is None:
            timeout = REMOTE_TIMEOUT if token else LOCAL_TIMEOUT
        self.temperature, self.timeout, self.num_predict = temperature, timeout, num_predict
        self.last_usage = {}

    def __call__(self, messages, on_token=None):
        """on_token(piece): nhận từng đoạn chữ khi model sinh ra (Ollama stream NDJSON)."""
        body = json.dumps({
            "model": self.model, "messages": messages, "stream": on_token is not None,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx,
                        "num_predict": self.num_predict},
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, body, headers)
        where = "máy chủ mô hình từ xa (Kaggle)" if self.token else "Ollama trên máy"
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            with resp:
                if on_token is None:
                    data = json.load(resp)
                    text = data["message"]["content"]
                else:
                    text, data = _read_stream(resp, on_token)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMUnavailable("Máy chủ mô hình từ xa từ chối yêu cầu: sai hoặc thiếu DIACARE_OLLAMA_TOKEN.") from e
            if e.code in (502, 503, 504, 530) and self.token:  # 530: đường hầm Cloudflare không còn nối tới Kaggle
                raise LLMUnavailable(f"Không kết nối được {where} (mã {e.code}). Có thể notebook Kaggle đã tắt; "
                                     "chạy lại chay_kaggle.bat hoặc chuyển sang mô hình trên máy.") from e
            raise
        except TimeoutError as e:
            raise LLMUnavailable(f"{where.capitalize()} không trả lời trong {self.timeout:g} giây. "
                                 "Vui lòng thử lại; nếu lặp lại, kiểm tra notebook Kaggle hoặc chuyển sang mô hình "
                                 "trên máy." if self.token else
                                 f"{where.capitalize()} không trả lời trong {self.timeout:g} giây. Vui lòng thử lại.") from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise LLMUnavailable(f"{where.capitalize()} không trả lời trong {self.timeout:g} giây. "
                                     "Vui lòng thử lại.") from e
            raise LLMUnavailable(f"Không kết nối được {where}. "
                                 + ("Có thể notebook Kaggle đã tắt; chạy lại chay_kaggle.bat hoặc chuyển sang mô hình "
                                    "trên máy." if self.token else "Hãy kiểm tra Ollama đã chạy chưa.")) from e
        self.last_usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "seconds": round(data.get("total_duration", 0) / 1e9, 3),
            "num_ctx": self.num_ctx,
        }
        # Ollama báo done_reason="length" khi dừng vì chạm num_predict: câu cuối bị cắt giữa chừng
        if data.get("done_reason") == "length" or (
                self.num_predict is not None and data.get("eval_count", 0) >= self.num_predict):
            self.last_usage["truncated"] = True
        return text


def _read_stream(lines, on_token):
    """Đọc stream NDJSON của Ollama /api/chat: mỗi dòng một đoạn, dòng cuối done=true kèm số token."""
    parts, data = [], {}
    for line in lines:
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("error"):
            raise RuntimeError(data["error"])
        piece = (data.get("message") or {}).get("content", "")
        if piece:
            parts.append(piece)
            on_token(piece)
        if data.get("done"):
            break
    return "".join(parts), data


def ollama_llm(**kwargs):
    return OllamaLLM(**kwargs)


def sbert_embed_fn(name="paraphrase-multilingual-MiniLM-L12-v2"):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(name)
    return lambda texts: model.encode(texts)


_NO_DOC_REPLY = "Chưa có đủ thông tin trong tài liệu để trả lời."
_DOC_MARK = "Tài liệu tham khảo:"
_LABEL = re.compile(r"^\[([^\]\n]+)\][ \t]*\n?", re.M)


class DemoLLM(_PerThreadUsage):
    """Fake LLM for demos and tests ONLY: quotes the first retrieved document."""

    def __init__(self):
        self.num_ctx = DEFAULT_NUM_CTX
        self.last_usage = {}

    def __call__(self, messages, on_token=None):
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
        if on_token is not None:
            for word in re.findall(r"\S+\s*", reply):
                on_token(word)
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
