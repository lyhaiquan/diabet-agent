"""Tạo notebook Kaggle tự đủ: nhúng mã nguồn, model Predictor và KB vào chính file .ipynb.

Chạy:  python kaggle/build_notebook.py
Kết quả: kaggle/diacare_kaggle.ipynb  (import vào Kaggle: File -> Import Notebook)
"""
import base64
import io
import zipfile
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "diacare_kaggle.ipynb"

INCLUDE = [
    ("src", ["*.py", "diacare/*.py"]),
    ("eval", ["*.py", "*.json"]),
    ("models", ["predictor.pt", "scaler.joblib", "metrics.json", "predictor_ms.joblib", "rl_policy.json"]),
    ("kb", ["*.txt", "*.md", "*.pdf"]),
    ("kb/graph", ["*.json"]),
    ("kb/rl", ["*.json"]),
    ("data/nutrition", ["*.json"]),
]


def build_zip_b64():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, patterns in INCLUDE:
            for pattern in patterns:
                for path in sorted((ROOT / folder).glob(pattern)):
                    if "__pycache__" in path.parts or not path.is_file():
                        continue
                    zf.write(path, path.relative_to(ROOT).as_posix())
        zf.writestr("pytest.ini", "[pytest]\npythonpath = src\n")
    return base64.b64encode(buf.getvalue()).decode("ascii"), buf.tell()


def wrap(b64, width=100):
    return "\n".join(b64[i:i + width] for i in range(0, len(b64), width))


INTRO = """# DiaCare-MAS: chạy benchmark trên Kaggle

Notebook tự đủ: mã nguồn, model Predictor (MLP) và tài liệu KB mẫu được nhúng sẵn ở ô 2.

**Trước khi bấm Run All, ở thanh bên phải (Session options):**
1. **Accelerator**: chọn GPU T4 (hoặc P100).
2. **Internet**: bật On (Kaggle thường yêu cầu xác minh số điện thoại một lần). Cần mạng để cài Ollama và tải model.

Các ô chạy theo thứ tự: nạp dự án, cài Ollama, tải model, chạy thử một câu, chạy benchmark, hiển thị báo cáo.
Kết quả nằm trong `/kaggle/working/reports/` (bấm *Save Version* rồi tải mục Output nếu muốn giữ lại).

Lưu ý: `MODELS` ở ô 3 là danh sách model Ollama; bản 7B nặng hơn (khoảng 4-5 GB) nhưng chạy nhanh trên GPU Kaggle.
"""

CELL_UNPACK = '''import base64, io, os, zipfile
from pathlib import Path

PROJECT = Path("/kaggle/working/diacare-mas")
PAYLOAD = """
{payload}
"""
PROJECT.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(base64.b64decode("".join(PAYLOAD.split())))) as zf:
    zf.extractall(PROJECT)
os.chdir(PROJECT)
print("Đã nạp dự án vào", PROJECT)
for p in sorted(PROJECT.rglob("*")):
    if p.is_file():
        print(f"{{p.relative_to(PROJECT)!s:<45}} {{p.stat().st_size:>8}} bytes")
'''

CELL_PIP = '''# Thư viện cần cho dự án (đa số đã có sẵn trên Kaggle)
!pip install -q pypdf sentence-transformers matplotlib scikit-learn joblib
!nvidia-smi --query-gpu=name,memory.total --format=csv || echo "Không thấy GPU: hãy bật Accelerator ở thanh bên phải"
'''

CELL_OLLAMA = '''# Cài Ollama bằng script chính thức của ollama.com rồi khởi động server nền.
# (Script này chạy trong sandbox tạm của notebook; cần Internet = On.)
import subprocess, time, urllib.request, json, os

# Script cài có thể cần zstd (giải nén) và lshw/pciutils (nhận GPU); lỗi ở đây thì bỏ qua.
!apt-get -qq update > /dev/null 2>&1; apt-get -qq install -y zstd pciutils lshw > /dev/null 2>&1 || echo "apt-get không chạy được, tiếp tục"
!curl -fsSL https://ollama.com/install.sh | sh

os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"
server = subprocess.Popen(["ollama", "serve"], stdout=open("/kaggle/working/ollama.log", "w"), stderr=subprocess.STDOUT)
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        print("Ollama server sẵn sàng")
        break
    except Exception:
        time.sleep(1)
else:
    print(open("/kaggle/working/ollama.log").read()[-2000:])
    raise RuntimeError("Ollama server không khởi động được, xem log ở trên")
'''

CELL_PULL = '''MODELS = ["qwen2.5:7b", "qwen2.5:14b"]   # so sánh kích thước model (14B ~9 GB, vừa 1 GPU T4)
for m in MODELS:
    !ollama pull {m}
!ollama list
'''

CELL_SMOKE = '''# Chạy thử một câu hỏi qua toàn bộ pipeline (Predictor -> Advisor -> Rule)
import os, sys
sys.path.insert(0, "/kaggle/working/diacare-mas/src")
os.environ.setdefault("DIACARE_NUM_CTX", "4096")

from diacare.factory import make_embed_fn, make_llm, build_orchestrator
from diacare.samples import HIGH_RISK
from diacare.rules import risk_band
from diacare.state import State

embed_fn = make_embed_fn("sbert")
orch = build_orchestrator(kb_dir="kb", model_dir="models", log_path="logs/smoke.jsonl",
                          llm=make_llm("ollama", model=MODELS[0], num_ctx=4096), embed_fn=embed_fn)
state = orch.run(State(question="Tôi nên ăn uống thế nào để giảm nguy cơ tiểu đường?", profile=dict(HIGH_RISK)))
print("Mức nguy cơ:", risk_band(state.risk), "| cờ:", state.flags, "| nguồn:", [d["source"] for d in state.docs])
print("Token/giây:", state.usage)
print("\\n" + state.final)
'''

CELL_BENCH = '''# So sánh model: cùng bộ ca trong eval/cases.json x k=3 lần, cấu hình tính năng mặc định.
#   v1 = tắt mọi tính năng V2 | v2 = nutrition + memory + labs (mặc định) | all = v2 + hybrid retrieval
models_args = " ".join(MODELS)
FEATURE_SETS = ["v2"]
for f in FEATURE_SETS:
    print("=" * 20, "features =", f, "=" * 20)
    !python eval/benchmark.py --llm ollama --embed sbert --models {models_args} --k 3 --num-ctx 4096 --kb kb --features {f} --out /kaggle/working/reports/{f}
'''

CELL_SHOW = '''from IPython.display import Markdown, Image, display
from pathlib import Path

for f in FEATURE_SETS:
    out = Path("/kaggle/working/reports") / f
    display(Markdown(f"# Cấu hình: {f}"))
    display(Markdown((out / "report.md").read_text(encoding="utf-8")))
    for png in sorted(out.glob("*.png")):
        display(Image(filename=str(png)))
'''

CELL_ZIP = '''# Gói kết quả để tải về (hoặc lấy ở mục Output sau khi Save Version)
!cd /kaggle/working && zip -qr reports.zip reports && ls -la reports.zip
'''


def build():
    payload, raw_size = build_zip_b64()
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.cells = [
        nbf.v4.new_markdown_cell(INTRO),
        nbf.v4.new_code_cell(CELL_UNPACK.format(payload=wrap(payload))),
        nbf.v4.new_code_cell(CELL_PIP),
        nbf.v4.new_code_cell(CELL_OLLAMA),
        nbf.v4.new_code_cell(CELL_PULL),
        nbf.v4.new_code_cell(CELL_SMOKE),
        nbf.v4.new_code_cell(CELL_BENCH),
        nbf.v4.new_code_cell(CELL_SHOW),
        nbf.v4.new_code_cell(CELL_ZIP),
    ]
    nbf.validate(nb)
    nbf.write(nb, OUT)
    print(f"Đã tạo {OUT} ({OUT.stat().st_size} bytes; zip nhúng {raw_size} bytes)")


if __name__ == "__main__":
    build()
