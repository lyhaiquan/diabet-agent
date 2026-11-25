# Chạy DiaCare-MAS trên máy cá nhân với LLM thật qua Ollama (mặc định qwen2.5:3b).
#   Bấm đúp chay_local.bat, hoặc:  powershell -ExecutionPolicy Bypass -File chay_local.ps1 [-Model qwen2.5:7b]
#   Chat ngay trong terminal (không mở trình duyệt): chay_cli.bat, tức là thêm -Cli [-HoSo đường_dẫn.json]
#   Bật đồ thị tri thức đọc từ Neo4j (cần Docker Desktop): chay_kg.bat, tức là thêm -KG
#   Đồ thị tri thức (networkx trong bộ nhớ) và agent học tăng cường luôn bật; -KG chỉ đổi nơi đọc sang Neo4j.
#   -V3 (chay_v3.bat) giữ lại cho quen tay, giờ giống hệt bản thường.
#   Dùng model 7B chạy trên Kaggle: chay_kaggle.bat, tức là thêm -Kaggle auto (tự bật notebook qua Kaggle CLI bằng
#   tools/kaggle_llm.py, đọc link + token đã lưu). Hoặc -Kaggle https://....trycloudflare.com khi tự Run All trên web
#   (token hỏi ẩn, hoặc đặt sẵn $env:DIACARE_OLLAMA_TOKEN). Mặc định qwen2.5:7b.
param([string]$Model = "", [int]$Port = 8501, [switch]$Cli, [switch]$KG, [switch]$V3, [string]$Kaggle = "",
      [string]$HoSo = "docs\samples\hoso_nguy_co_cao.json", [string]$Ten = "Nguoi dung terminal")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
if (-not $Model) { $Model = $(if ($Kaggle) { "qwen2.5:7b" } else { "qwen2.5:3b" }) }

if ($Kaggle -eq "auto") {
    $env:PYTHONIOENCODING = "utf-8"
    python tools/kaggle_llm.py up
    if ($LASTEXITCODE -ne 0) { throw "Không bật được notebook Kaggle (xem thông báo ở trên)" }
    $Kaggle = (Get-Content -Raw -Encoding UTF8 (Join-Path $root "kaggle\ollama_session.local.json") | ConvertFrom-Json).url
    $env:DIACARE_OLLAMA_TOKEN = (Get-Content -Raw -Encoding UTF8 (Join-Path $root "kaggle\ollama_token.local")).Trim()
}
if ($Kaggle) {
    $base = $Kaggle.Trim().TrimEnd("/")
    # http:// chỉ cho phép với máy này (thử cổng chặn ở máy mình); link Kaggle luôn là https://
    if ($base -notmatch '^(https://|http://(127\.0\.0\.1|localhost)[:/])') { throw "Link Kaggle phải bắt đầu bằng https:// (link trycloudflare.com notebook in ra)" }
    if (-not $env:DIACARE_OLLAMA_TOKEN) {
        $secure = Read-Host "Dán token notebook Kaggle in ra (gõ ẩn)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $env:DIACARE_OLLAMA_TOKEN = ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)).Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
    try {
        $tags = Invoke-RestMethod -Uri "$base/api/tags" -TimeoutSec 30 `
            -Headers @{ Authorization = "Bearer $env:DIACARE_OLLAMA_TOKEN" }
    } catch {
        throw "Không gọi được Ollama trên Kaggle ($base): sai token, link cũ, hoặc notebook đã tắt. Lỗi: $($_.Exception.Message)"
    }
    if (-not ($tags.models.name -contains $Model)) { throw "Notebook Kaggle chưa có model $Model (đang có: $($tags.models.name -join ', '))" }
    $env:DIACARE_OLLAMA_URL = $base
    Write-Host "Dùng $Model trên Kaggle: $base"
} else {

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
}  # hết phần Ollama chạy ở máy này

$env:DIACARE_LLM = "ollama"
$env:DIACARE_MODEL = $Model
$env:DIACARE_EMBED = "sbert"
$env:DIACARE_NUM_CTX = "4096"
$env:DIACARE_KB = Join-Path $root "kb"
$env:DIACARE_DB = Join-Path $root "data\diacare.db"
$env:DIACARE_LOG = Join-Path $root "logs\runs.jsonl"
# Nhận dạng giọng nói (trợ lý chủ động hỏi bằng giọng): dùng PhoWhisper đã tải sẵn ở D:\hf_cache nếu có.
# Không đổi HF_HOME: mô hình embedding sbert nằm ở cache mặc định.
if (-not $env:DIACARE_ASR_MODEL) {
    $asr = Get-ChildItem "D:\hf_cache\hub\models--vinai--PhoWhisper-small\snapshots" -Directory -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($asr) { $env:DIACARE_ASR_MODEL = $asr.FullName }
}
# Giọng đọc tiếng Việt (Piper, chế độ trò chuyện bằng giọng nói): dùng bản đã tải ở D:\hf_cache nếu có.
if (-not $env:DIACARE_TTS_MODEL) {
    $tts = Get-ChildItem "D:\hf_cache\hub\models--rhasspy--piper-voices\snapshots\*\vi\vi_VN\vais1000\medium\vi_VN-vais1000-medium.onnx" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($tts) { $env:DIACARE_TTS_MODEL = $tts.FullName }
}

if ($KG) {
    # Bật Neo4j trong Docker, nạp đồ thị, rồi cho Graph agent đọc từ Neo4j.
    Write-Host "Đang bật Neo4j và nạp đồ thị tri thức..."
    $env:PYTHONIOENCODING = "utf-8"
    python tools/kg_neo4j.py | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { throw "Không bật được Neo4j: Docker Desktop đã chạy chưa?" }
    $env:DIACARE_KG = "neo4j"
    Write-Host "Neo4j Browser: http://localhost:7475  (bolt://localhost:7688, user neo4j, mật khẩu trong neo4j.local.json)"
}

# Không dùng "v3" vì "v3" bật cả hybrid, mà hybrid lọc câu ngoài chủ đề kém hơn dense (xem factory.py).
$features = @("v2", "kg", "rl", "journal")
$env:DIACARE_FEATURES = $features -join ","
Write-Host "Tính năng bật: $env:DIACARE_FEATURES"

if ($Cli) {
    $env:PYTHONIOENCODING = "utf-8"
    Write-Host "Chat trong terminal với hồ sơ $HoSo. Gõ /patients, /history, /stats; q để thoát."
    python src/cli.py --profile $HoSo --name $Ten
    exit
}

Write-Host "Mở giao diện tại http://localhost:$Port  (đóng cửa sổ này để tắt)"
# Streamlit không có đăng nhập: chỉ nghe trên máy này. Không đặt address thì Streamlit nghe mọi giao diện mạng,
# ai cùng mạng Wi-Fi cũng mở được và xem mọi hồ sơ.
python -m streamlit run src/app.py --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false
