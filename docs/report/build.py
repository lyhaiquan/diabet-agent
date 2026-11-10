# -*- coding: utf-8 -*-
"""Dung bao cao chi tiet va bao cao kien truc PTIT (.docx + .pdf qua pandoc & Word COM)."""
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORTS = [
    ("baocao_chitiet.md", "BaoCao_DiaCare-MAS.docx"),
    ("baocao_kien_truc_mas_ptit.md", "BaoCao_KienTruc_MAS_PTIT.docx"),
]

for src_name, out_name in REPORTS:
    src = HERE / src_name
    if not src.exists():
        continue
    out = HERE / out_name
    subprocess.run(
        [
            "pandoc",
            str(src),
            "-o",
            str(out),
            "--toc",
            "--toc-depth=2",
            "--syntax-highlighting=tango",
            "--resource-path",
            str(HERE),
            "--reference-doc",
            str(HERE / "reference.docx"),
        ],
        check=True,
        cwd=str(HERE),
    )
    print(f"{out_name}: {out.stat().st_size / 1024:.0f} KB")
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HERE / "export_pdf.ps1"),
            "-DocPath",
            str(out),
            "-PdfPath",
            str(out.with_suffix(".pdf")),
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    print(r.stdout.strip() or r.stderr.strip())
