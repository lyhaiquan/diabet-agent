"""Cổng chặn đứng trước Ollama khi Ollama phải mở ra Internet (Kaggle + Cloudflare quick tunnel).

Vì sao: link trycloudflare.com là công khai, ai có link đều gọi được Ollama (dùng GPU của mình, kéo / xoá model).
Cổng này chỉ cho qua yêu cầu có header "Authorization: Bearer <token>" đúng, và chỉ các đường cần cho DiaCare
(/api/chat, /api/tags, /api/version). Phần thân trả về được chuyển tiếp theo từng đoạn nên stream NDJSON vẫn chạy.

Điều khiển từ xa (cần token): POST /gate/stop ghi file `stop` vào --state-dir để notebook tự tắt và trả GPU; mỗi
yêu cầu hợp lệ chạm file `last_used` để notebook biết lần cuối có người dùng (tự tắt khi rảnh lâu).

Chạy:  python -m diacare.ollama_gate --token <token> --port 11435 --upstream http://127.0.0.1:11434 [--state-dir D]
(hoặc đặt token qua biến OLLAMA_GATE_TOKEN). Chỉ dùng thư viện chuẩn để chép thẳng vào notebook Kaggle được.
"""
import argparse
import hmac
import http.client
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED = {("POST", "/api/chat"), ("GET", "/api/tags"), ("GET", "/api/version")}
MAX_BODY = 4 * 1024 * 1024
TIMEOUT = 600


def make_handler(token, upstream, state_dir=None):
    up = urlsplit(upstream)
    state = Path(state_dir) if state_dir else None
    if state:
        state.mkdir(parents=True, exist_ok=True)
        (state / "last_used").touch()
    expected = f"Bearer {token}".encode()

    class Gate(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # không ghi token / nội dung câu hỏi ra log
            sys.stderr.write("gate %s %s -> %s\n" % (self.command, self.path.split("?")[0], args[1] if len(args) > 1 else ""))

        def _drain(self):
            # Đọc bỏ phần thân yêu cầu bị từ chối (tối đa MAX_BODY) trước khi trả lời. Đóng kết nối khi phía kia còn
            # đang gửi thân thì trên Windows client nhận lỗi "connection aborted" thay vì mã 401 rõ ràng.
            # (Không dùng docstring: tệp này được nhúng vào notebook trong một chuỗi ba nháy kép.)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return
            if 0 < length <= MAX_BODY:
                try:
                    self.rfile.read(length)
                except OSError:
                    pass

        def _reply(self, code, text, drain=True):
            if drain:
                self._drain()
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            # Vẫn đóng kết nối sau mọi câu trả lời lỗi: thân yêu cầu quá lớn (413) không được đọc, mà cloudflared dùng lại
            # kết nối, phần thân còn sót lại sẽ bị đọc nhầm thành yêu cầu kế tiếp
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            self.wfile.write(data)

        def _handle(self):
            got = (self.headers.get("Authorization") or "").encode()
            if not hmac.compare_digest(got, expected):
                return self._reply(401, "unauthorized")
            path = self.path.split("?")[0]
            if state and (self.command, path) == ("POST", "/gate/stop"):
                (state / "stop").touch()
                return self._reply(200, "stopping")
            if (self.command, path) not in ALLOWED:
                return self._reply(403, "forbidden")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._reply(413, "too large", drain=False)  # quá lớn: không đọc, chỉ đóng kết nối
            body = self.rfile.read(length) if length else None
            if state:
                (state / "last_used").touch()
            conn = http.client.HTTPConnection(up.hostname, up.port or 80, timeout=TIMEOUT)
            started = False
            try:
                conn.request(self.command, path, body=body,
                             headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
                resp = conn.getresponse()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.getheader("Content-Type", "application/json"))
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                started = True
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except OSError as e:
                self.close_connection = True
                if not started:  # lỗi giữa chừng stream thì chỉ đóng kết nối, không chèn thêm phản hồi
                    try:
                        self._reply(502, f"upstream error: {type(e).__name__}")
                    except OSError:
                        pass
            finally:
                conn.close()

        do_GET = _handle
        do_POST = _handle

        def do_DELETE(self):
            self._reply(403, "forbidden")

        do_PUT = do_DELETE

    return Gate


def serve(token, port=11435, upstream="http://127.0.0.1:11434", host="127.0.0.1", state_dir=None):
    if not token or len(token) < 16:
        raise ValueError("token phải dài ít nhất 16 ký tự")
    server = ThreadingHTTPServer((host, port), make_handler(token, upstream, state_dir))
    server.daemon_threads = True
    return server


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--token", default=os.environ.get("OLLAMA_GATE_TOKEN"))
    ap.add_argument("--port", type=int, default=11435)
    ap.add_argument("--upstream", default="http://127.0.0.1:11434")
    ap.add_argument("--state-dir", default=None)
    args = ap.parse_args(argv)
    server = serve(args.token, args.port, args.upstream, state_dir=args.state_dir)
    print(f"Cổng chặn đang nghe 127.0.0.1:{args.port} -> {args.upstream}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
