@echo off
chcp 65001 >nul
rem Bam dup: chay DiaCare ban V3 = V2 + do thi tri thuc (networkx, khong can Docker) + agent hoc tang cuong.
rem Model khac: chay_v3.bat qwen2.5:7b
set MODEL=%1
if "%MODEL%"=="" set MODEL=qwen2.5:3b
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0chay_local.ps1" -Model %MODEL% -V3
pause
