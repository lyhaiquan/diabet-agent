import json
import urllib.request

from diacare.llm import OllamaLLM


class FakeResp:
    def __init__(self, payload):
        self._bytes = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *args):
        return self._bytes


def patch(monkeypatch, payload):
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["body"] = req.data.decode()
        sent["url"] = req.full_url
        return FakeResp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return sent


FULL = {
    "message": {"content": "xin chào"},
    "prompt_eval_count": 120,
    "eval_count": 30,
    "total_duration": 1_500_000_000,
}


def test_request_body_has_num_ctx_stream_false_and_model(monkeypatch):
    sent = patch(monkeypatch, FULL)
    OllamaLLM(model="m1", num_ctx=2048)([{"role": "user", "content": "hi"}])
    body = json.loads(sent["body"])
    assert body["options"]["num_ctx"] == 2048
    assert body["stream"] is False
    assert body["model"] == "m1"
    assert '"num_ctx": 2048' in sent["body"] and '"stream": false' in sent["body"]


def test_returns_message_content(monkeypatch):
    patch(monkeypatch, FULL)
    assert OllamaLLM()([{"role": "user", "content": "hi"}]) == "xin chào"


def test_last_usage(monkeypatch):
    patch(monkeypatch, FULL)
    llm = OllamaLLM(num_ctx=2048)
    llm([])
    assert llm.last_usage == {"prompt_tokens": 120, "completion_tokens": 30, "seconds": 1.5, "num_ctx": 2048}


def test_missing_usage_fields_give_zeros(monkeypatch):
    patch(monkeypatch, {"message": {"content": "ok"}})
    llm = OllamaLLM(num_ctx=2048)
    assert llm([]) == "ok"
    assert llm.last_usage == {"prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "num_ctx": 2048}


def test_num_predict_is_sent_and_matches_answer_reserve(monkeypatch):
    import json as _json
    from diacare import context
    from diacare.llm import DEFAULT_NUM_PREDICT, OllamaLLM
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps({"message": {"content": "ok"}}).encode()

    def fake_urlopen(req, timeout=None):
        seen["body"] = _json.loads(req.data)
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    OllamaLLM()([{"role": "user", "content": "hi"}])
    assert seen["body"]["options"]["num_predict"] == DEFAULT_NUM_PREDICT
    assert context.ANSWER_RESERVE_TOKENS == DEFAULT_NUM_PREDICT


def test_read_stream_collects_pieces_and_usage():
    import json
    from diacare.llm import _read_stream
    lines = [json.dumps({"message": {"content": "Xin "}, "done": False}).encode(),
             b"\n",
             json.dumps({"message": {"content": "chào"}, "done": False}).encode(),
             json.dumps({"message": {"content": ""}, "done": True, "eval_count": 2,
                         "prompt_eval_count": 9}).encode()]
    got = []
    text, data = _read_stream(lines, got.append)
    assert text == "Xin chào" and got == ["Xin ", "chào"] and data["eval_count"] == 2


def test_demo_llm_streams_same_text():
    from diacare.llm import DemoLLM
    msgs = [{"role": "user", "content": "Tài liệu tham khảo:\n[a.txt]\nĂn rau.\n\nCâu hỏi: gì?"}]
    got = []
    assert "".join(got) == "" and DemoLLM()(msgs, on_token=got.append) == "".join(got)


def test_truncated_when_ollama_stops_at_length(monkeypatch):
    patch(monkeypatch, {**FULL, "eval_count": 512, "done_reason": "length"})
    llm = OllamaLLM(num_predict=512)
    llm([])
    assert llm.last_usage["truncated"] is True


def test_not_truncated_when_answer_finishes(monkeypatch):
    patch(monkeypatch, {**FULL, "done_reason": "stop"})
    llm = OllamaLLM(num_predict=512)
    llm([])
    assert "truncated" not in llm.last_usage


def test_last_usage_is_per_thread():
    """API dùng chung một đối tượng LLM cho mọi lượt: mỗi luồng phải đọc đúng số token của lượt mình."""
    import threading
    from diacare.llm import DemoLLM
    llm, seen, ready = DemoLLM(), {}, threading.Barrier(2)

    def run(name, size):
        llm([{"role": "user", "content": "x" * size}])
        ready.wait(5)  # cả hai đã gọi xong trước khi đọc: biến dùng chung sẽ bị lượt kia ghi đè
        seen[name] = llm.last_usage["prompt_tokens"]

    ts = [threading.Thread(target=run, args=("a", 300)), threading.Thread(target=run, args=("b", 3000))]
    [t.start() for t in ts]
    [t.join(5) for t in ts]
    assert seen == {"a": 100, "b": 1000}


# ---- thời gian chờ và lỗi kết nối (V4.9) ----
import socket
import threading
import urllib.error

import pytest

from diacare.llm import LOCAL_TIMEOUT, REMOTE_TIMEOUT, LLMUnavailable


def test_default_timeout_shorter_for_remote():
    assert OllamaLLM().timeout == LOCAL_TIMEOUT
    assert OllamaLLM(token="x" * 20).timeout == REMOTE_TIMEOUT < LOCAL_TIMEOUT
    assert OllamaLLM(token="x" * 20, timeout=5).timeout == 5


def test_factory_timeout_env(monkeypatch):
    from diacare.factory import make_llm
    monkeypatch.delenv("DIACARE_OLLAMA_TOKEN", raising=False)
    monkeypatch.delenv("DIACARE_OLLAMA_TIMEOUT", raising=False)
    assert make_llm("ollama").timeout == LOCAL_TIMEOUT
    monkeypatch.setenv("DIACARE_OLLAMA_TIMEOUT", "12")
    assert make_llm("ollama").timeout == 12


def test_silent_server_gives_clear_timeout_error():
    """Máy chủ nhận kết nối nhưng không trả lời (đường hầm treo): báo lỗi rõ sau đúng thời gian chờ."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    conns = []
    t = threading.Thread(target=lambda: conns.append(srv.accept()), daemon=True)
    t.start()
    llm = OllamaLLM(url=f"http://127.0.0.1:{srv.getsockname()[1]}/api/chat", token="x" * 20, timeout=0.5)
    try:
        with pytest.raises(LLMUnavailable, match="không trả lời trong 0.5 giây.*Kaggle"):
            llm([{"role": "user", "content": "hi"}])
    finally:
        srv.close()
        for c, _ in conns:
            c.close()


def test_refused_connection_message_local_vs_remote(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailable, match="Ollama đã chạy chưa"):
        OllamaLLM()([{"role": "user", "content": "hi"}])
    with pytest.raises(LLMUnavailable, match="chay_kaggle.bat"):
        OllamaLLM(token="x" * 20)([{"role": "user", "content": "hi"}])


def test_tunnel_gone_status(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 530, "origin unreachable", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailable, match="mã 530"):
        OllamaLLM(token="x" * 20)([{"role": "user", "content": "hi"}])



def test_keep_alive_sent_so_model_stays_on_gpu(monkeypatch):
    sent = patch(monkeypatch, FULL)
    monkeypatch.delenv("DIACARE_OLLAMA_KEEP_ALIVE", raising=False)
    OllamaLLM()([{"role": "user", "content": "hi"}])
    assert json.loads(sent["body"])["keep_alive"] == "30m"
    monkeypatch.setenv("DIACARE_OLLAMA_KEEP_ALIVE", "-1")
    OllamaLLM()([{"role": "user", "content": "hi"}])
    assert json.loads(sent["body"])["keep_alive"] == "-1"
