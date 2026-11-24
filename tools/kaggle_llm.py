"""Bật / tắt Ollama qwen2.5:7b trên Kaggle hoàn toàn từ máy mình, không cần mở web Kaggle.

    python tools/kaggle_llm.py up       # đẩy notebook, đợi GPU, đọc link từ log, thử gọi, lưu phiên
    python tools/kaggle_llm.py status   # trạng thái notebook + thử gọi link đang lưu
    python tools/kaggle_llm.py down     # bảo notebook tự tắt (trả GPU)

Cần Kaggle CLI đã đăng nhập (kaggle/save_token.ps1). Token cổng chặn tạo một lần, lưu ở kaggle/ollama_token.local
(gitignore), nhúng vào notebook riêng tư lúc đẩy. Phiên đang chạy lưu ở kaggle/ollama_session.local.json để
chay_local.ps1 -Kaggle auto đọc. Notebook tự tắt khi rảnh quá --idle phút, nên quên `down` cũng không tốn mãi giờ GPU.
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kaggle"))
from build_ollama_notebook import KERNEL_DIR, KERNEL_ID, URL_MARK, build  # noqa: E402

TOKEN_FILE = ROOT / "kaggle" / "ollama_token.local"
SESSION_FILE = ROOT / "kaggle" / "ollama_session.local.json"
MODEL = "qwen2.5:7b"
TERMINAL = ("ERROR", "COMPLETE", "CANCEL_ACKNOWLEDGED", "CANCELLED")


def url_re(run_id):
    """Chỉ nhận dòng link của đúng lần đẩy này: log của lần chạy trước (link đã chết) vẫn còn trong `kernels logs`."""
    return re.compile(re.escape(URL_MARK) + re.escape(run_id) + r" (https://[a-z0-9-]+\.trycloudflare\.com)")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def say(*a):
    print(*a, flush=True)


def load_token(create=True):
    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(tok) >= 16:
            return tok
    if not create:
        return None
    tok = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(tok, encoding="utf-8")
    return tok


def load_session():
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def call(url, token, path="/api/tags", method="GET", timeout=15):
    req = urllib.request.Request(url + path, method=method, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def ping(url, token):
    try:
        status, body = call(url, token)
        return status == 200 and MODEL in body.decode(errors="ignore")
    except (OSError, ValueError):
        return False


def kernel_status():
    out = subprocess.run(["kaggle", "kernels", "status", KERNEL_ID], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=ENV)
    m = re.search(r"KernelWorkerStatus\.(\w+)", out.stdout + out.stderr)
    return m.group(1).upper() if m else (out.stdout + out.stderr).strip()


def find_url_in_logs(run_id, deadline):
    """Đọc `kaggle kernels logs -f` (log trực tiếp) tới khi thấy dòng URL_MARK. Nếu lệnh -f thoát sớm thì đọc lại
    log không -f mỗi 20 giây."""
    found = {}
    rx = url_re(run_id)

    def follow():
        try:
            p = subprocess.Popen(["kaggle", "kernels", "logs", "-f", KERNEL_ID], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=ENV)
        except OSError:
            return
        found["proc"] = p
        for line in p.stdout:
            m = rx.search(line)
            if m:
                found["url"] = m.group(1)
                break
            for key in ("Đã tải", "Model đã nạp", "Traceback", "Error", "KHÔNG THẤY GPU"):
                if key in line:
                    say("  [kaggle]", line.strip()[:200])
                    break

    t = threading.Thread(target=follow, daemon=True)
    t.start()
    while time.time() < deadline and "url" not in found:
        time.sleep(5)
        if not t.is_alive() and "url" not in found:
            out = subprocess.run(["kaggle", "kernels", "logs", KERNEL_ID], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", env=ENV)
            m = rx.search(out.stdout)
            if m:
                found["url"] = m.group(1)
                break
            st = kernel_status()
            if st in TERMINAL:
                raise SystemExit(f"Notebook đã dừng ({st}) trước khi in link. Xem log: kaggle kernels logs {KERNEL_ID}")
            time.sleep(15)
    if "proc" in found and found["proc"].poll() is None:
        found["proc"].terminate()
    return found.get("url")


def up(idle):
    tok = load_token()
    sess = load_session()
    if sess and ping(sess["url"], tok):
        say("Notebook đang chạy sẵn:", sess["url"])
        return sess
    say(f"Đóng gói notebook (tự tắt khi rảnh {idle} phút) và đẩy lên Kaggle...")
    run_id = secrets.token_hex(4)
    build(serve_token=tok, idle_minutes=idle, run_id=run_id)
    out = subprocess.run(["kaggle", "kernels", "push", "-p", str(KERNEL_DIR)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=ENV)
    if out.returncode != 0 or "successfully" not in out.stdout.lower():
        raise SystemExit("Đẩy notebook thất bại:\n" + out.stdout + out.stderr)
    say(out.stdout.strip())
    start = time.time()
    deadline = start + 40 * 60
    last, seen_new = None, False
    while time.time() < deadline:
        st = kernel_status()
        if st != last:
            say(f"  trạng thái: {st} ({time.time() - start:.0f}s)")
            last = st
        if st == "RUNNING":
            break
        seen_new = seen_new or st == "QUEUED"
        # Ngay sau push, status có thể vẫn là của lần chạy trước (COMPLETE): chỉ tin trạng thái kết thúc khi đã thấy
        # lần mới vào hàng đợi, hoặc sau 2 phút
        if st in TERMINAL and (seen_new or time.time() - start > 120):
            raise SystemExit(f"Notebook dừng ngay ({st}). Xem: kaggle kernels logs {KERNEL_ID}")
        time.sleep(15)
    else:
        raise SystemExit("Đợi GPU quá 40 phút vẫn chưa chạy (hàng đợi Kaggle). Thử lại sau.")
    say("Đang chạy trên GPU; đợi cài Ollama, tải model, mở tunnel (thường 3-5 phút)...")
    url = find_url_in_logs(run_id, time.time() + 20 * 60)
    if not url:
        raise SystemExit(f"Không thấy link trong log sau 20 phút. Xem: kaggle kernels logs {KERNEL_ID}")
    for _ in range(30):
        if ping(url, tok):
            break
        time.sleep(3)
    else:
        raise SystemExit(f"Có link {url} nhưng gọi thử không được")
    sess = {"url": url, "model": MODEL, "started": time.strftime("%Y-%m-%d %H:%M"), "idle_minutes": idle}
    SESSION_FILE.write_text(json.dumps(sess, indent=2), encoding="utf-8")
    say(f"Sẵn sàng sau {(time.time() - start) / 60:.1f} phút: {url}")
    return sess


def status():
    say("Notebook:", kernel_status())
    sess, tok = load_session(), load_token(create=False)
    if not sess:
        say("Chưa có phiên nào được lưu.")
        return
    say("Phiên đã lưu:", sess["url"], "| bắt đầu", sess.get("started"))
    say("Gọi thử:", "được" if tok and ping(sess["url"], tok) else "KHÔNG được (đã tắt hoặc link hết hạn)")


def down():
    sess, tok = load_session(), load_token(create=False)
    if not sess or not tok:
        say("Không có phiên nào đang lưu.")
        return
    try:
        call(sess["url"], tok, "/gate/stop", "POST")
        say("Đã bảo notebook tắt; nó dừng trong khoảng 10 giây và trả GPU.")
    except (OSError, urllib.error.HTTPError) as e:
        say("Không gọi được link (có thể notebook đã tự tắt):", type(e).__name__)
    SESSION_FILE.unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["up", "status", "down"])
    ap.add_argument("--idle", type=int, default=30, help="notebook tự tắt sau chừng này phút không có yêu cầu")
    args = ap.parse_args(argv)
    {"up": lambda: up(args.idle), "status": status, "down": down}[args.cmd]()


if __name__ == "__main__":
    main()
