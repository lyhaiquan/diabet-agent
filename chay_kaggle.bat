@echo off
chcp 65001 >nul
rem Bam dup: tu bat notebook Kaggle chay qwen2.5:7b (qua Kaggle CLI), roi mo DiaCare dung model do.
rem Tat giao dien bang Ctrl+C trong cua so nay: notebook duoc bao tat de tra GPU.
rem Dong han cua so thi notebook tu tat sau 30 phut khong ai dung.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0chay_local.ps1" -Kaggle auto %*
set PYTHONIOENCODING=utf-8
python "%~dp0tools\kaggle_llm.py" down
pause
