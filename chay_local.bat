@echo off
chcp 65001 >nul
rem Bam dup de chay DiaCare-MAS tren may (qwen2.5:3b). Muon dung 7B: chay_local.bat qwen2.5:7b
set MODEL=%1
if "%MODEL%"=="" set MODEL=qwen2.5:3b
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0chay_local.ps1" -Model %MODEL%
pause
