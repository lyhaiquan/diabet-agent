@echo off
chcp 65001 >nul
rem Bat dich vu nhan dien mon Calo Khay (YOLO + DINOv2) o http://127.0.0.1:8010 cho trang "Bua an" cua DiaCare.
rem Ma Calo Khay nam ngay trong project: services\calo_khay (chep tu do an Xu ly anh so cua nhom, ngay 25/11/2026).
rem Can moi truong Python rieng co torch, ultralytics, transformers (xem services\calo_khay\README_DIACARE.md).
rem Doi bang bien moi truong: CALO_KHAY_DIR (thu muc ma), CALO_KHAY_PY (python cua moi truong do).
rem Du lieu tam (SQLite, anh quet) nam trong data\calo_khay cua DiaCare, khong can MySQL.
if "%CALO_KHAY_DIR%"=="" set CALO_KHAY_DIR=%~dp0services\calo_khay
if "%CALO_KHAY_PORT%"=="" set CALO_KHAY_PORT=8010
if "%CALO_KHAY_PY%"=="" if exist "%~dp0services\calo_khay\.venv\Scripts\python.exe" set CALO_KHAY_PY=%~dp0services\calo_khay\.venv\Scripts\python.exe
if "%CALO_KHAY_PY%"=="" set CALO_KHAY_PY=D:\food-labeling\.venv\Scripts\python.exe
if not exist "%CALO_KHAY_PY%" (
  echo Khong tim thay Python co torch: %CALO_KHAY_PY%
  echo Tao moi truong theo huong dan trong services\calo_khay\README_DIACARE.md, hoac dat CALO_KHAY_PY.
  pause
  exit /b 1
)
set CALO_DATA_DIR=%~dp0data\calo_khay
if not exist "%CALO_DATA_DIR%" mkdir "%CALO_DATA_DIR%"
set CALO_DATABASE_URL=sqlite:///%CALO_DATA_DIR:\=/%/calo.db
set CALO_ENGINE=real
set PYTHONIOENCODING=utf-8
rem DINOv2 da tai san: chay offline de demo khong can mang (lan dau tren may moi thi xoa 2 dong duoi)
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
cd /d "%CALO_KHAY_DIR%"
echo Calo Khay: %CALO_KHAY_DIR%
echo Dang nap mo hinh (khoang 15 giay), xong se thay "Uvicorn running"...
"%CALO_KHAY_PY%" -m uvicorn backend.app:app --host 127.0.0.1 --port %CALO_KHAY_PORT%
pause
