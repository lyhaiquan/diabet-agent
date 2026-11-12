"""Tạo notebook Kaggle huấn luyện RGCN trên đồ thị con đái tháo đường (PrimeKG + DiaCare).

Chạy:  python kaggle/build_rgcn_notebook.py
Kết quả: kaggle/rgcn_kernel/kg_rgcn.ipynb + kernel-metadata.json
Đẩy lên (riêng tư, GPU, có Internet):  kaggle kernels push -p kaggle/rgcn_kernel

Notebook tự tải PrimeKG (nodes.tab + edges.csv, khoảng 400 MB) từ Harvard Dataverse ngay trên Kaggle,
nên máy cá nhân không phải tải gì. Hai script tools/primekg_subgraph.py và tools/kg_rgcn.py được nhúng
nguyên văn vào notebook.
"""
import json
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "rgcn_kernel"
OUT = OUT_DIR / "kg_rgcn.ipynb"

FILES = {
    6180617: ("nodes.tab", "7f9ab4109c54049e819ecd14e15a6038"),
    6180616: ("edges.csv", "5d4d211a22e88544b78fde2735e797bc"),
}

INTRO = """# DiaCare-MAS: RGCN dự đoán cạnh trên đồ thị con đái tháo đường

1. Tải PrimeKG (Chandak, Huang & Zitnik 2023; CC0 1.0) từ Harvard Dataverse: `nodes.tab`, `edges.csv`.
2. Cắt đồ thị con quanh các bệnh đái tháo đường và ghép yếu tố nguy cơ DiaCare (`primekg_subgraph.py`).
3. Huấn luyện RGCN (phân rã cơ sở) + DistMult, đánh giá MRR/Hits@k có lọc (`kg_rgcn.py`).
4. Chấm điểm các cặp (yếu tố DiaCare, đái tháo đường). Kết quả ở `/kaggle/working/out/`.

Cần bật **GPU** và **Internet** ở Session options.
"""


def code(src):
    return nbf.v4.new_code_cell(src)


def main():
    nb = nbf.v4.new_notebook()
    cells = [nbf.v4.new_markdown_cell(INTRO)]
    for rel in ("tools/primekg_subgraph.py", "tools/kg_rgcn.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        cells.append(code(f"%%writefile /kaggle/working/{Path(rel).name}\n{text}"))
    dl = ["import hashlib, subprocess, pathlib",
          "d = pathlib.Path('/kaggle/working/primekg'); d.mkdir(exist_ok=True)",
          f"FILES = {json.dumps({str(k): v for k, v in FILES.items()})}",
          "for fid, (name, md5) in FILES.items():",
          "    p = d / name",
          "    if not p.exists():",
          "        subprocess.run(['curl', '-sSL', '--retry', '3', '-o', str(p),",
          "                        f'https://dataverse.harvard.edu/api/access/datafile/{fid}?format=original'], check=True)",
          "    h = hashlib.md5(p.read_bytes()).hexdigest()",
          "    print(name, p.stat().st_size, 'md5 ok' if h == md5 else f'MD5 SAI {h}')",
          "    assert h == md5"]
    cells.append(code("\n".join(dl)))
    cells.append(code("!nvidia-smi --query-gpu=name,memory.total --format=csv\n"
                      "import torch; print(torch.__version__, torch.cuda.is_available())"))
    cells.append(code("HOPS = 1   # 1 bước: khoảng 2,8 nghìn nút, 29 nghìn cạnh, xoay quanh đái tháo đường\n"
                      "!python /kaggle/working/primekg_subgraph.py --primekg /kaggle/working/primekg "
                      "--out /kaggle/working/out/graph --hops {HOPS}"))
    cells.append(code(
        "# RGCN 2 tầng so với mốc DistMult (0 tầng: chỉ embedding nông), mỗi cấu hình 3 hạt giống.\n"
        "import subprocess\n"
        "CONFIGS = {'rgcn': '--layers 2', 'distmult': '--layers 0'}\n"
        "for name, extra in CONFIGS.items():\n"
        "    for seed in (1, 2, 3):\n"
        "        cmd = (f'python /kaggle/working/kg_rgcn.py --data /kaggle/working/out/graph '\n"
        "               f'--out /kaggle/working/out/{name}_s{seed} --epochs 600 --dim 128 --bases 10 '\n"
        "               f'--eval-every 50 --seed {seed} {extra}')\n"
        "        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)\n"
        "        print(name, seed, [l for l in r.stdout.splitlines() if 'TEST' in l], r.stderr[-500:] if r.returncode else '')"))
    cells.append(code(
        "import json, pandas as pd, numpy as np\n"
        "rows = []\n"
        "for name in CONFIGS:\n"
        "    for seed in (1, 2, 3):\n"
        "        m = json.load(open(f'/kaggle/working/out/{name}_s{seed}/metrics.json'))\n"
        "        rows.append({'model': name, 'seed': seed, **m['test'], 'seconds': m['seconds']})\n"
        "res = pd.DataFrame(rows)\n"
        "summary = res.groupby('model')[['mrr', 'hits@1', 'hits@3', 'hits@10', 'seconds']].agg(['mean', 'std']).round(3)\n"
        "summary.to_csv('/kaggle/working/out/summary_test.csv'); summary"))
    cells.append(code(
        "# Theo từng quan hệ (RGCN, hạt giống 1)\n"
        "m = json.load(open('/kaggle/working/out/rgcn_s1/metrics.json'))\n"
        "pd.DataFrame(m['test_by_relation']).T.sort_values('mrr')"))
    cells.append(code(
        "# Yếu tố DiaCare -> đái tháo đường: phân vị độ gần embedding, trung bình 3 hạt giống RGCN.\n"
        "ps = [pd.read_json(f'/kaggle/working/out/rgcn_s{s}/predictions.json') for s in (1, 2, 3)]\n"
        "key = ['factor', 'factor_node', 'target']\n"
        "base = ps[0].drop(columns=['embedding_cosine', 'embedding_percentile', 'head', 'tail'])\n"
        "pct = pd.concat([p.set_index(key)['embedding_percentile'] for p in ps], axis=1)\n"
        "base = base.set_index(key)\n"
        "base['percentile_mean'] = pct.mean(axis=1).round(3)\n"
        "base['percentile_std'] = pct.std(axis=1).round(3)\n"
        "out = base.reset_index().sort_values(['target', 'percentile_mean'], ascending=[True, False])\n"
        "out.to_json('/kaggle/working/out/factor_relatedness.json', orient='records', force_ascii=False, indent=2)\n"
        "out"))
    cells.append(code("# Xóa dữ liệu PrimeKG gốc khỏi output, chỉ giữ đồ thị con và kết quả.\n"
                      "import shutil; shutil.rmtree('/kaggle/working/primekg', ignore_errors=True)"))
    nb["cells"] = cells
    nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    OUT_DIR.mkdir(exist_ok=True)
    nbf.write(nb, OUT)
    meta = {"id": "b23dccn676lhiqun/diacare-kg-rgcn", "title": "DiaCare KG RGCN",
            "code_file": OUT.name, "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": True, "enable_tpu": False, "enable_internet": True,
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": []}
    (OUT_DIR / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
