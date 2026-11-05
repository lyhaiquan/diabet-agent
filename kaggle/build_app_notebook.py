"""Tạo notebook Kaggle chạy GIAO DIỆN DiaCare-MAS với agent thật (Ollama qwen2.5:7b trên GPU),
mở ra ngoài bằng Cloudflare quick tunnel (không cần tài khoản).

Chạy:  python kaggle/build_app_notebook.py
Kết quả: kaggle/diacare_app.ipynb và bản sao trong kaggle/app_kernel/ (để `kaggle kernels push`).

Notebook tự nhận chế độ chạy qua biến KAGGLE_KERNEL_RUN_TYPE:
  - Batch (khi push / Save Version): chỉ kiểm tra mã + Streamlit ở chế độ demo rồi dừng, không tốn GPU lâu.
  - Interactive (mở Edit rồi Run All): cài Ollama, tải model, chạy giao diện, in link công khai.
"""
import json
import shutil
import sys
from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_notebook import build_zip_b64, wrap  # noqa: E402

OUT = HERE / "diacare_app.ipynb"
KERNEL_DIR = HERE / "app_kernel"
KERNEL_ID = "b23dccn676lhiqun/diacare-mas-app"

INTRO = """# DiaCare-MAS: giao diện với agent thật trên Kaggle

**Cách dùng (mỗi lần muốn demo):**
1. Bấm **Edit** để mở notebook. Ở thanh bên phải (Session options) kiểm tra **Accelerator = GPU T4** và **Internet = On**.
2. Bấm **Run All**. Đợi khoảng 3-5 phút (cài Ollama, tải model 7B, nạp embedding).
3. Ô "Link giao diện" in ra một đường link `https://....trycloudflare.com`. Mở link đó (máy tính hoặc điện thoại).
4. Ô cuối giữ giao diện chạy tối đa `SERVE_HOURS` giờ. Dùng xong: bấm **Stop session** (góc trên) để không tốn giờ GPU.

**Lưu ý:**
- Link đổi mỗi lần bật. Ai có link đều vào được: không đăng công khai.
- Dữ liệu (bệnh nhân, lịch sử, bộ nhớ) lưu trong `/kaggle/working/diacare.db` và mất khi tắt phiên.
- Đây là công cụ học tập, không thay thế bác sĩ.
"""

CELL_CONFIG = '''import os, re, subprocess, sys, time, urllib.request
from pathlib import Path

MODEL = "qwen2.5:7b"      # đổi "qwen2.5:3b" nếu muốn nhanh hơn (chất lượng thấp hơn)
SERVE_HOURS = 6           # giao diện tự dừng sau chừng này giờ (giới hạn phiên Kaggle ~12 giờ)
PORT = 8501
WORK = Path(os.environ.get("DIACARE_WORK", "/kaggle/working"))
PROJECT = WORK / "diacare-mas"

RUN_TYPE = os.environ.get("KAGGLE_KERNEL_RUN_TYPE", "")
BATCH = RUN_TYPE.lower() == "batch"
print("Chế độ chạy:", RUN_TYPE or "(không rõ, coi là Interactive)")
if BATCH:
    print("Batch (push / Save Version): chỉ kiểm tra mã và Streamlit chế độ demo, không chạy model.")


def sh(cmd):
    print("$", cmd, flush=True)
    return subprocess.run(cmd, shell=True).returncode


def wait_http(url, seconds, proc=None):
    for _ in range(seconds):
        if proc is not None and proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False
'''

CELL_UNPACK = '''import base64, io, zipfile
PAYLOAD = """
{payload}
"""
PROJECT.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(base64.b64decode("".join(PAYLOAD.split())))) as zf:
    zf.extractall(PROJECT)
sys.path.insert(0, str(PROJECT / "src"))
print("Đã nạp dự án vào", PROJECT, "-", sum(1 for p in PROJECT.rglob("*") if p.is_file()), "file")
'''

CELL_PIP = '''# Thư viện (đa số Kaggle có sẵn; streamlit thường chưa có)
sh(f"{sys.executable} -m pip install -q streamlit pypdf sentence-transformers scikit-learn joblib")
if not BATCH:
    if sh("nvidia-smi --query-gpu=name,memory.total --format=csv") != 0:
        print("!!! KHÔNG THẤY GPU: bật Accelerator = GPU T4 ở thanh bên phải rồi Run All lại. "
              "Model 7B chạy trên CPU sẽ rất chậm.")
'''

CELL_OLLAMA = '''# Cài Ollama, khởi động server (giữ model trong VRAM), tải model và chạy thử một câu cho "nóng máy".
if BATCH:
    print("Batch: bỏ qua Ollama.")
else:
    sh("apt-get -qq update > /dev/null 2>&1; apt-get -qq install -y zstd pciutils lshw > /dev/null 2>&1")
    sh("curl -fsSL https://ollama.com/install.sh | sh")
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_KEEP_ALIVE="-1")
    ollama = subprocess.Popen(["ollama", "serve"], env=env,
                              stdout=open(WORK / "ollama.log", "w"), stderr=subprocess.STDOUT)
    if not wait_http("http://127.0.0.1:11434/api/tags", 60, ollama):
        print(open(WORK / "ollama.log").read()[-2000:])
        raise RuntimeError("Ollama không khởi động được, xem log ở trên")
    sh(f"ollama pull {MODEL}")
    t = time.time()
    sh(f"ollama run {MODEL} 'Trả lời một từ: xin chào'")
    print(f"Model đã nạp vào GPU ({time.time() - t:.0f}s)")
'''

CELL_WARM = '''# Kiểm tra pipeline và tải sẵn model embedding (để câu hỏi đầu tiên trên giao diện không phải chờ).
os.chdir(PROJECT)
os.environ.update(
    DIACARE_LLM="demo" if BATCH else "ollama",
    DIACARE_EMBED="hash" if BATCH else "sbert",
    DIACARE_MODEL=MODEL,
    DIACARE_NUM_CTX="4096",
    DIACARE_KB=str(PROJECT / "kb"),
    DIACARE_DB=str(WORK / "diacare.db"),
    DIACARE_LOG=str(WORK / "logs" / "runs.jsonl"),
)
from diacare.factory import build_orchestrator
from diacare.samples import HIGH_RISK
from diacare.state import State

orch = build_orchestrator(log_path=str(WORK / "logs" / "warmup.jsonl"))
t = time.time()
s = orch.run(State(question="Triệu chứng của tôi là đi đái thì có kiến bâu", profile=dict(HIGH_RISK)))
print(f"Chạy thử xong sau {time.time() - t:.1f}s | cờ: {s.flags} | nguồn: {[d['source'] for d in s.docs]}")
print(s.final[:800])
'''

CELL_STREAMLIT = '''# Chạy giao diện Streamlit ở cổng nội bộ.
log = open(WORK / "streamlit.log", "w")
app = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", str(PROJECT / "src" / "app.py"),
     "--server.headless", "true", "--server.port", str(PORT), "--server.address", "127.0.0.1",
     "--browser.gatherUsageStats", "false",
     "--server.enableCORS", "false", "--server.enableXsrfProtection", "false"],
    cwd=PROJECT, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT)
if not wait_http(f"http://127.0.0.1:{PORT}/_stcore/health", 90, app):
    print(open(WORK / "streamlit.log").read()[-3000:])
    raise RuntimeError("Streamlit không khởi động được, xem log ở trên")
print("Streamlit đang chạy ở cổng", PORT)
if BATCH:
    app.terminate()
    print("Batch: Streamlit khởi động được (demo). Notebook sẵn sàng; mở Edit -> Run All để dùng thật.")
'''

CELL_TUNNEL = '''# Link giao diện: mở Cloudflare quick tunnel (không cần tài khoản) tới Streamlit.
from IPython.display import HTML, display
PUBLIC_URL = None
if BATCH:
    print("Batch: không mở tunnel.")
else:
    cf = WORK / "cloudflared"
    if not cf.exists():
        sh(f"wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O {cf}")
        cf.chmod(0o755)
    cf_log = WORK / "cloudflared.log"
    tunnel = subprocess.Popen([str(cf), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
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
    display(HTML(f'<h2>Giao diện: <a href="{PUBLIC_URL}" target="_blank">{PUBLIC_URL}</a></h2>'
                 "<p>Link có thể mất 10-30 giây mới vào được lần đầu.</p>"))
'''

CELL_KEEP = '''# Giữ giao diện chạy. Bấm Stop (hoặc Stop session) để dừng.
if not BATCH:
    deadline = time.time() + SERVE_HOURS * 3600
    try:
        while time.time() < deadline:
            alive = {"ollama": ollama.poll() is None, "streamlit": app.poll() is None, "tunnel": tunnel.poll() is None}
            left = (deadline - time.time()) / 60
            print(time.strftime("%H:%M"), alive, f"| còn {left:.0f} phút | {PUBLIC_URL}", flush=True)
            if not all(alive.values()):
                print("Một tiến trình đã dừng; xem /kaggle/working/*.log")
                break
            time.sleep(600)
    except KeyboardInterrupt:
        print("Đã dừng theo yêu cầu.")
    for p in (tunnel, app):
        p.terminate()
    print("Đã tắt giao diện. Nhớ bấm Stop session để trả GPU.")
'''


def build():
    payload, raw_size = build_zip_b64()
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.cells = [
        nbf.v4.new_markdown_cell(INTRO),
        nbf.v4.new_code_cell(CELL_CONFIG),
        nbf.v4.new_code_cell(CELL_UNPACK.format(payload=wrap(payload))),
        nbf.v4.new_code_cell(CELL_PIP),
        nbf.v4.new_code_cell(CELL_OLLAMA),
        nbf.v4.new_code_cell(CELL_WARM),
        nbf.v4.new_code_cell(CELL_STREAMLIT),
        nbf.v4.new_code_cell(CELL_TUNNEL),
        nbf.v4.new_code_cell(CELL_KEEP),
    ]
    nbf.validate(nb)
    nbf.write(nb, OUT)
    KERNEL_DIR.mkdir(exist_ok=True)
    shutil.copy(OUT, KERNEL_DIR / OUT.name)
    meta = {
        "id": KERNEL_ID, "title": "DiaCare-MAS App", "code_file": OUT.name, "language": "python",
        "kernel_type": "notebook", "is_private": True, "enable_gpu": True, "enable_tpu": False,
        "enable_internet": True, "dataset_sources": [], "competition_sources": [],
        "kernel_sources": [], "model_sources": [],
    }
    (KERNEL_DIR / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Đã tạo {OUT} ({OUT.stat().st_size} bytes; zip nhúng {raw_size} bytes) và {KERNEL_DIR}")


if __name__ == "__main__":
    build()
