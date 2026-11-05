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
