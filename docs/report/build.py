# -*- coding: utf-8 -*-
"""Dung bao cao chi tiet: baocao_chitiet.md -> BaoCao_DiaCare-MAS.docx (pandoc, kieu chu lay tu reference.docx)."""
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "baocao_chitiet.md"
OUT = HERE / "BaoCao_DiaCare-MAS.docx"

subprocess.run(["pandoc", str(SRC), "-o", str(OUT), "--toc", "--toc-depth=2", "--syntax-highlighting=tango",
                "--resource-path", str(HERE), "--reference-doc", str(HERE / "reference.docx")],
               check=True, cwd=str(HERE))
print("docx: %.0f KB" % (OUT.stat().st_size / 1024))
