# Chạy DiaCare-MAS trên máy cá nhân với LLM thật qua Ollama (mặc định qwen2.5:3b).
#   Bấm đúp chay_local.bat, hoặc:  powershell -ExecutionPolicy Bypass -File chay_local.ps1 [-Model qwen2.5:7b]
#   Chat ngay trong terminal (không mở trình duyệt): chay_cli.bat, tức là thêm -Cli [-HoSo đường_dẫn.json]
param([string]$Model = "qwen2.5:3b", [int]$Port = 8501, [switch]$Cli,
      [string]$HoSo = "docs\samples\hoso_nguy_co_cao.json", [string]$Ten = "Nguoi dung terminal")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Model Ollama đặt ở ổ D để ổ C không đầy (đã đặt sẵn trong biến môi trường của người dùng).
if (-not $env:OLLAMA_MODELS) {
    $env:OLLAMA_MODELS = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
}
if (-not $env:OLLAMA_MODELS) { $env:OLLAMA_MODELS = "D:\ollama\models" }
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollama)) { throw "Chưa cài Ollama: winget install Ollama.Ollama" }

function Test-Ollama {
    try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

if (-not (Test-Ollama)) {
    Write-Host "Đang bật Ollama..."
    Start-Process -WindowStyle Hidden $ollama -ArgumentList "serve"
    for ($i = 0; $i -lt 30 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
    if (-not (Test-Ollama)) { throw "Ollama không khởi động được" }
}
Write-Host "Ollama đang chạy. Model ở $env:OLLAMA_MODELS"

if (-not ((& $ollama list) -match [regex]::Escape($Model))) {
    Write-Host "Chưa có $Model, đang tải..."
    & $ollama pull $Model
}

# Nạp model vào GPU trước để câu hỏi đầu tiên không phải chờ (giữ trong bộ nhớ 1 giờ).
Write-Host "Đang nạp $Model..."
$body = @{ model = $Model; prompt = "xin chào"; stream = $false; keep_alive = "1h"; options = @{ num_predict = 1 } } | ConvertTo-Json
Invoke-WebRequest -UseBasicParsing -Method Post http://127.0.0.1:11434/api/generate -Body $body -ContentType "application/json" -TimeoutSec 300 | Out-Null

$env:DIACARE_LLM = "ollama"
$env:DIACARE_MODEL = $Model
$env:DIACARE_EMBED = "sbert"
$env:DIACARE_NUM_CTX = "4096"
$env:DIACARE_KB = Join-Path $root "kb"
$env:DIACARE_DB = Join-Path $root "data\diacare.db"
$env:DIACARE_LOG = Join-Path $root "logs\runs.jsonl"

if ($Cli) {
    $env:PYTHONIOENCODING = "utf-8"
    Write-Host "Chat trong terminal với hồ sơ $HoSo. Gõ /patients, /history, /stats; q để thoát."
    python src/cli.py --profile $HoSo --name $Ten
    exit
}

Write-Host "Mở giao diện tại http://localhost:$Port  (đóng cửa sổ này để tắt)"
python -m streamlit run src/app.py --server.port $Port --browser.gatherUsageStats false
