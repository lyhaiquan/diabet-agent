@echo off
chcp 65001 >nul
rem Bam dup: bat Neo4j (Docker), nap do thi tri thuc, roi mo DiaCare voi Graph agent doc tu Neo4j.
rem Can Docker Desktop dang chay. Model khac: chay_kg.bat qwen2.5:7b
set MODEL=%1
if "%MODEL%"=="" set MODEL=qwen2.5:3b
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0chay_local.ps1" -Model %MODEL% -KG
pause
