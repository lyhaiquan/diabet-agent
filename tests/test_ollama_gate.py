import http.client
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from diacare.llm import OllamaLLM
from diacare.ollama_gate import serve

TOKEN = "t" * 24


class FakeOllama(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.seen.append(("GET", self.path, self.headers.get("Authorization")))
        data = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(("POST", self.path, self.headers.get("Authorization")))
        if body.get("stream"):
            lines = [{"message": {"content": "xin "}}, {"message": {"content": "chào"}},
                     {"done": True, "eval_count": 2, "prompt_eval_count": 5, "total_duration": 10}]
        else:
            lines = [{"message": {"content": "xin chào"}, "done": True, "eval_count": 2}]
        data = b"".join(json.dumps(x).encode() + b"\n" for x in lines)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def gate():
    FakeOllama.seen = []
    up = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    g = serve(TOKEN, port=0, upstream=f"http://127.0.0.1:{up.server_address[1]}")
    threading.Thread(target=g.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{g.server_address[1]}"
    g.shutdown()
    up.shutdown()


def _get(url, token=None, method="GET"):
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=5)


@pytest.mark.parametrize("token", [None, "sai-token-nhung-du-dai-16"])
def test_rejects_missing_or_wrong_token(gate, token):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(gate + "/api/tags", token)
    assert e.value.code == 401
    assert FakeOllama.seen == []


@pytest.mark.parametrize("path,method", [("/api/pull", "POST"), ("/api/delete", "DELETE"), ("/", "GET")])
def test_blocks_paths_diacare_does_not_need(gate, path, method):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(gate + path, TOKEN, method)
    assert e.value.code == 403
    assert FakeOllama.seen == []


def test_forwards_without_leaking_token_upstream(gate):
    assert json.load(_get(gate + "/api/tags", TOKEN))["models"][0]["name"] == "qwen2.5:7b"
    assert FakeOllama.seen == [("GET", "/api/tags", None)]


def test_ollama_llm_through_gate(gate):
    llm = OllamaLLM(url=gate + "/api/chat", token=TOKEN)
    assert llm([{"role": "user", "content": "hi"}]) == "xin chào"
    pieces = []
    assert llm([{"role": "user", "content": "hi"}], on_token=pieces.append) == "xin chào"
    assert pieces == ["xin ", "chào"]


def test_ollama_llm_wrong_token_gives_clear_error(gate):
    with pytest.raises(RuntimeError, match="DIACARE_OLLAMA_TOKEN"):
        OllamaLLM(url=gate + "/api/chat", token="khong-dung-token-nay-dau")([])


def test_short_token_refused():
    with pytest.raises(ValueError):
        serve("ngan", port=0)


def test_factory_reads_token(monkeypatch):
    from diacare.factory import make_llm
    monkeypatch.delenv("DIACARE_OLLAMA_TOKEN", raising=False)
    assert make_llm("ollama").token is None
    monkeypatch.setenv("DIACARE_OLLAMA_TOKEN", TOKEN)
    assert make_llm("ollama").token == TOKEN


def test_rejected_post_does_not_poison_reused_connection(gate):
    """cloudflared dùng lại kết nối tới gốc: một POST sai token (có thân) không được làm hỏng yêu cầu kế tiếp."""
    host, port = gate.split("//")[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.request("POST", "/api/chat", body=b'{"model": "x"}' * 50,
                 headers={"Authorization": "Bearer sai-token-nhung-du-dai-16", "Content-Type": "application/json"})
    r = conn.getresponse()
    assert r.status == 401
    r.read()
    conn.request("GET", "/api/tags", headers={"Authorization": f"Bearer {TOKEN}"})  # http.client tự nối lại nếu bị đóng
    r = conn.getresponse()
    assert r.status == 200 and b"qwen2.5:7b" in r.read()
    conn.close()


def test_keep_alive_after_success(gate):
    host, port = gate.split("//")[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    for _ in range(2):
        conn.request("GET", "/api/tags", headers={"Authorization": f"Bearer {TOKEN}"})
        r = conn.getresponse()
        assert r.status == 200 and json.loads(r.read())["models"]
    conn.close()


def test_stop_and_last_used_files(tmp_path):
    FakeOllama.seen = []
    up = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    g = serve(TOKEN, port=0, upstream=f"http://127.0.0.1:{up.server_address[1]}", state_dir=tmp_path)
    threading.Thread(target=g.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{g.server_address[1]}"
    try:
        last = tmp_path / "last_used"
        assert last.exists()
        import os
        os.utime(last, (0, 0))
        _get(base + "/api/tags", TOKEN)
        assert last.stat().st_mtime > 0
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(base + "/gate/stop", "sai-token-nhung-du-dai-16", "POST")
        assert e.value.code == 401 and not (tmp_path / "stop").exists()
        assert _get(base + "/gate/stop", TOKEN, "POST").status == 200
        assert (tmp_path / "stop").exists()
    finally:
        g.shutdown()
        up.shutdown()


def test_stop_not_available_without_state_dir(gate):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(gate + "/gate/stop", TOKEN, "POST")
    assert e.value.code == 403
