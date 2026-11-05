@echo off
chcp 65001 >nul
rem Chat voi DiaCare-MAS ngay trong terminal (qwen2.5:3b). Ho so khac: chay_cli.bat docs\samples\hoso_nguy_co_thap.json
set HOSO=%1
if "%HOSO%"=="" set HOSO=docs\samples\hoso_nguy_co_cao.json
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0chay_local.ps1" -Cli -HoSo "%HOSO%"
pause
