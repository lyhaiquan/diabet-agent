"""Tạo notebook Kaggle CHỈ chạy Ollama qwen2.5:7b trên GPU, mở ra ngoài bằng Cloudflare quick tunnel, có token.

Khác diacare_app.ipynb (chạy cả giao diện trên Kaggle): ở đây giao diện, dữ liệu, nhật ký vẫn ở máy mình, chỉ phần
sinh câu trả lời gọi sang Kaggle. Dữ liệu người dùng không nằm trên Kaggle, chỉ lời nhắn từng lượt đi qua.

Hai cách dùng:
- Tự động (không mở web Kaggle): `python tools/kaggle_llm.py up` (hoặc bấm đúp chay_kaggle.bat). Script gọi
  build(serve_token=...) để notebook phục vụ luôn trong lần chạy Batch do `kaggle kernels push` khởi động, token nhúng
  sẵn, đọc link từ `kaggle kernels logs -f`, rồi mở DiaCare. Tắt: `python tools/kaggle_llm.py down`.
- Tay: `python kaggle/build_ollama_notebook.py` rồi `kaggle kernels push -p kaggle/ollama_kernel`, mở Edit -> Run All
  trên web, dán link + token notebook in ra vào chay_local.ps1 -Kaggle <link>.
"""
import json
import shutil
import subprocess
from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).resolve().parent
GATE_SRC = HERE.parent / "src" / "diacare" / "ollama_gate.py"
OUT = HERE / "diacare_ollama.ipynb"
KERNEL_DIR = HERE / "ollama_kernel"
KERNEL_ID = "b23dccn676lhiqun/diacare-ollama-7b"
URL_MARK = "DIACARE_TUNNEL_URL="

INTRO = """# DiaCare-MAS: Ollama qwen2.5:7b trên Kaggle (chỉ model, giao diện chạy ở máy mình)

**Phiên bản code: `{version}`**

**Cách dùng tay (bản tự động thì không cần mở trang này):**
1. Bấm **Edit**. Thanh bên phải: **Accelerator = GPU T4**, **Internet = On**.
2. **Run All**, đợi khoảng 3-4 phút (cài Ollama, tải model 4,7 GB, nạp vào GPU).
3. Ô "Kết nối" in ra link `https://....trycloudflare.com` (và token nếu token không nhúng sẵn).
4. Dùng xong bấm **Stop session**. Notebook cũng tự tắt khi rảnh quá `IDLE_MINUTES` phút hoặc sau `SERVE_HOURS` giờ.

**An toàn:** link công khai, nhưng mọi yêu cầu phải có token, và chỉ `/api/chat`, `/api/tags`, `/api/version`,
`/gate/stop` được qua (không ai kéo, xoá hay đổi model được). Đừng dán token vào chỗ công khai.
"""

CELL_CONFIG = '''import os, re, secrets, subprocess, sys, time, json, urllib.request, urllib.error
from pathlib import Path

MODEL = "qwen2.5:7b"
SERVE_HOURS = 4            # tự dừng sau chừng này giờ để không quên tắt (giới hạn phiên Kaggle ~12 giờ)
IDLE_MINUTES = {idle}        # tự dừng khi chừng này phút không có yêu cầu nào (đỡ tốn giờ GPU nếu quên tắt)
GATE_PORT = 11435          # cổng chặn token; tunnel trỏ vào đây, không trỏ thẳng vào Ollama (11434)
# /tmp chứ không phải /kaggle/working: lần chạy Batch lưu mọi thứ trong working thành output (cloudflared 40 MB, log)
WORK = Path("/tmp/diacare") if Path("/kaggle").exists() else Path.cwd()
WORK.mkdir(parents=True, exist_ok=True)
STATE = WORK / "state"     # cổng chặn ghi last_used / stop ở đây
RUN_TYPE = os.environ.get("KAGGLE_KERNEL_RUN_TYPE", "")
BATCH = RUN_TYPE.lower() == "batch"
SERVE_IN_BATCH = {serve}   # True: bản do tools/kaggle_llm.py đẩy lên, phục vụ luôn trong lần chạy Batch
CHECK_ONLY = BATCH and not SERVE_IN_BATCH
EMBED_TOKEN = {token}
RUN_ID = {run_id}        # mã lần đẩy, để máy mình không đọc nhầm link của lần chạy trước trong log
print("Phiên bản code: {version} | chế độ:", RUN_TYPE or "(không rõ, coi là Interactive)",
      "| phục vụ trong Batch" if SERVE_IN_BATCH else "")


def sh(cmd):
    print("$", cmd, flush=True)
    return subprocess.run(cmd, shell=True).returncode


def wait_http(url, seconds, proc=None, headers=None):
    for _ in range(seconds):
        if proc is not None and proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5)
            return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code
        except Exception:
            pass
        time.sleep(1)
    return False


TOKEN = EMBED_TOKEN
if TOKEN:
    print("Dùng token nhúng sẵn (máy mình đã có, không in ra).")
else:
    try:
        from kaggle_secrets import UserSecretsClient
        TOKEN = UserSecretsClient().get_secret("DIACARE_OLLAMA_TOKEN")
        print("Dùng token từ Kaggle Secrets (giữ nguyên giữa các lần bật).")
    except Exception:
        pass
if not TOKEN or len(TOKEN) < 16:
    TOKEN = secrets.token_urlsafe(24)
    print("Không có token nhúng sẵn hay secret DIACARE_OLLAMA_TOKEN hợp lệ: tạo token mới cho phiên này.")
AUTH = {"Authorization": f"Bearer {TOKEN}"}
'''

CELL_GATE = '''# Cổng chặn token (chép nguyên từ src/diacare/ollama_gate.py, chỉ dùng thư viện chuẩn).
GATE_CODE = r"""{gate}"""
(WORK / "ollama_gate.py").write_text(GATE_CODE, encoding="utf-8")
gate = subprocess.Popen([sys.executable, str(WORK / "ollama_gate.py"), "--port", str(GATE_PORT),
                         "--state-dir", str(STATE)],
                        env=dict(os.environ, OLLAMA_GATE_TOKEN=TOKEN),
                        stdout=open(WORK / "gate.log", "w"), stderr=subprocess.STDOUT)
code = wait_http(f"http://127.0.0.1:{GATE_PORT}/api/tags", 20, gate)
assert code == 401, f"Cổng chặn phải từ chối yêu cầu không có token (nhận {code}); xem gate.log"
print("Cổng chặn chạy ở cổng", GATE_PORT, "và từ chối yêu cầu không có token.")
if CHECK_ONLY:
    gate.terminate()
    print("Batch (push / Save Version): mã chạy được. Mở Edit -> Run All để dùng thật.")
'''

CELL_OLLAMA = '''# Cài Ollama, giữ model trong VRAM, tải model và chạy thử một câu.
if not CHECK_ONLY:
    if sh("nvidia-smi --query-gpu=name,memory.total --format=csv") != 0:
        print("!!! KHÔNG THẤY GPU: bật Accelerator = GPU T4 rồi Run All lại. 7B trên CPU rất chậm.")
    sh("apt-get -qq update > /dev/null 2>&1; apt-get -qq install -y zstd pciutils lshw > /dev/null 2>&1")
    sh("curl -fsSL https://ollama.com/install.sh | sh > /dev/null")
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_KEEP_ALIVE="-1", OLLAMA_NUM_PARALLEL="2")
    ollama = subprocess.Popen(["ollama", "serve"], env=env,
                              stdout=open(WORK / "ollama.log", "w"), stderr=subprocess.STDOUT)
    if not wait_http("http://127.0.0.1:11434/api/tags", 60, ollama):
        print(open(WORK / "ollama.log").read()[-2000:])
        raise RuntimeError("Ollama không khởi động được, xem log ở trên")
    t = time.time()
    sh(f"ollama pull {MODEL} > /dev/null 2>&1")
    print(f"Đã tải {MODEL} ({time.time() - t:.0f}s)", flush=True)
    t = time.time()
    sh(f"ollama run {MODEL} 'Trả lời một từ: xin chào'")
    print(f"Model đã nạp vào GPU ({time.time() - t:.0f}s)", flush=True)
'''

CELL_TUNNEL = '''# Kết nối: mở Cloudflare quick tunnel tới cổng chặn, thử gọi qua link công khai, rồi in lệnh cho máy mình.
PUBLIC_URL = None
if not CHECK_ONLY:
    cf = WORK / "cloudflared"
    if not cf.exists():
        sh(f"wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O {cf}")
        cf.chmod(0o755)
    cf_log = WORK / "cloudflared.log"
    tunnel = subprocess.Popen([str(cf), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{GATE_PORT}"],
                              stdout=open(cf_log, "w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        m = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", cf_log.read_text(errors="ignore"))
        if m:
            PUBLIC_URL = m.group(0)
            break
        time.sleep(1)
    if not PUBLIC_URL:
        print(cf_log.read_text(errors="ignore")[-2000:])
        raise RuntimeError("Không lấy được link tunnel, xem log ở trên")
    # Link mới cần 10-60 giây để DNS chạy được
    ok = wait_http(PUBLIC_URL + "/api/tags", 120, tunnel, AUTH)
    assert ok is True, f"Gọi qua link công khai chưa được ({ok}); đợi thêm rồi chạy lại ô này"
    assert wait_http(PUBLIC_URL + "/api/tags", 10) == 401, "Link công khai phải từ chối yêu cầu không có token"
    body = json.dumps({"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "Chào bạn"}],
                       "options": {"num_predict": 30}}).encode()
    t = time.time()
    req = urllib.request.Request(PUBLIC_URL + "/api/chat", body, {**AUTH, "Content-Type": "application/json"})
    reply = json.load(urllib.request.urlopen(req, timeout=120))["message"]["content"]
    print(f"Thử qua link công khai ({time.time() - t:.1f}s): {reply[:80]!r}")
    print("{mark}" + f"{RUN_ID} {PUBLIC_URL}", flush=True)   # tools/kaggle_llm.py tìm dòng này trong log
    print()
    print("=" * 70)
    print("Link :", PUBLIC_URL)
    if EMBED_TOKEN:
        print("Token: nhúng sẵn (ở máy mình: kaggle/ollama_token.local)")
    else:
        print("Token:", TOKEN)
        print("Ở máy mình: chay_local.ps1 -Kaggle <link>, dán token khi được hỏi.")
    print("=" * 70, flush=True)
'''

CELL_KEEP = '''# Giữ phiên tới khi: hết SERVE_HOURS, rảnh quá IDLE_MINUTES, nhận lệnh dừng (kaggle_llm.py down), hoặc bấm Stop.
if not CHECK_ONLY:
    deadline = time.time() + SERVE_HOURS * 3600
    (STATE / "last_used").touch()
    last_print = 0
    try:
        while time.time() < deadline:
            alive = {"ollama": ollama.poll() is None, "gate": gate.poll() is None, "tunnel": tunnel.poll() is None}
            idle = (time.time() - (STATE / "last_used").stat().st_mtime) / 60
            if (STATE / "stop").exists():
                print("Nhận lệnh dừng từ máy mình.", flush=True)
                break
            if idle > IDLE_MINUTES:
                print(f"Không có yêu cầu nào trong {IDLE_MINUTES} phút: tự tắt để trả GPU.", flush=True)
                break
            if not all(alive.values()):
                print("Một tiến trình đã dừng:", alive, "; log ở", WORK, flush=True)
                break
            if time.time() - last_print > 600:
                last_print = time.time()
                print(time.strftime("%H:%M"), alive,
                      f"| rảnh {idle:.0f} phút | còn {(deadline - time.time()) / 60:.0f} phút", flush=True)
            time.sleep(10)
    except KeyboardInterrupt:
        print("Đã dừng theo yêu cầu.")
    for p in (tunnel, gate, ollama):
        p.terminate()
    print("Đã tắt, GPU được trả lại.", flush=True)
'''


def build(serve_token=None, idle_minutes=30, run_id=""):
    """serve_token: None = bản thường (Batch chỉ kiểm tra mã, dùng thật bằng Run All trên web). Có token = bản tự
    động: phục vụ ngay trong lần chạy Batch, token nhúng sẵn vào notebook (notebook để riêng tư; file chỉ nằm trong
    kaggle/ollama_kernel/ và kaggle/*.ipynb, đều đã gitignore)."""
    version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE.parent,
                             capture_output=True, text=True).stdout.strip() or "không rõ"
    gate_code = GATE_SRC.read_text(encoding="utf-8")
    assert '"""' not in gate_code.split('"""', 2)[2], "ollama_gate.py chỉ được có một docstring dùng ba nháy kép"
    gate_code = gate_code.replace('"""', "'''")
    config = (CELL_CONFIG.replace("{version}", version).replace("{idle}", str(int(idle_minutes)))
              .replace("{serve}", str(bool(serve_token))).replace("{token}", repr(serve_token))
              .replace("{run_id}", repr(run_id)))
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.cells = [
        nbf.v4.new_markdown_cell(INTRO.replace("{version}", version)),
        nbf.v4.new_code_cell(config),
        nbf.v4.new_code_cell(CELL_GATE.replace("{gate}", gate_code)),
        nbf.v4.new_code_cell(CELL_OLLAMA),
        nbf.v4.new_code_cell(CELL_TUNNEL.replace("{mark}", URL_MARK)),
        nbf.v4.new_code_cell(CELL_KEEP),
    ]
    nbf.validate(nb)
    nbf.write(nb, OUT)
    KERNEL_DIR.mkdir(exist_ok=True)
    shutil.copy(OUT, KERNEL_DIR / OUT.name)
    meta = {
        "id": KERNEL_ID, "title": "DiaCare Ollama 7B", "code_file": OUT.name, "language": "python",
        "kernel_type": "notebook", "is_private": True, "enable_gpu": True, "enable_tpu": False,
        "enable_internet": True, "dataset_sources": [], "competition_sources": [],
        "kernel_sources": [], "model_sources": [],
    }
    (KERNEL_DIR / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Đã tạo {OUT} ({OUT.stat().st_size} bytes) và {KERNEL_DIR}")
    return KERNEL_DIR


if __name__ == "__main__":
    build()
