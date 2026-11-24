@echo off
chcp 65001 >nul
rem Bat dich vu nhan dien mon Calo Khay (YOLO + DINOv2) o http://127.0.0.1:8010 cho trang "Bua an" cua DiaCare.
rem Calo Khay la project rieng; doi duong dan bang bien moi truong CALO_KHAY_DIR va CALO_KHAY_PY neu can.
rem Du lieu tam (SQLite, anh quet) nam trong data\calo_khay cua DiaCare, khong can MySQL.
if "%CALO_KHAY_DIR%"=="" set CALO_KHAY_DIR=D:\CVision\Final_Project_Digital_Image_Processing
if "%CALO_KHAY_PY%"=="" set CALO_KHAY_PY=D:\food-labeling\.venv\Scripts\python.exe
set CALO_DATA_DIR=%~dp0data\calo_khay
if not exist "%CALO_DATA_DIR%" mkdir "%CALO_DATA_DIR%"
set CALO_DATABASE_URL=sqlite:///%CALO_DATA_DIR:\=/%/calo.db
set CALO_ENGINE=real
set PYTHONIOENCODING=utf-8
rem DINOv2 da tai san: chay offline de demo khong can mang (lan dau tren may moi thi xoa 2 dong duoi)
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
cd /d "%CALO_KHAY_DIR%"
echo Dang nap mo hinh (khoang 15 giay), xong se thay "Uvicorn running"...
"%CALO_KHAY_PY%" -m uvicorn backend.app:app --host 127.0.0.1 --port 8010
pause
