# Save a Kaggle API token to %USERPROFILE%\.kaggle\access_token (read automatically by Kaggle CLI >= 1.8).
# Run in your own PowerShell:  powershell -ExecutionPolicy Bypass -File C:\DATA\diacare-mas\kaggle\save_token.ps1
# The token is typed hidden and never printed. (ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI.)

$dir = Join-Path $env:USERPROFILE ".kaggle"
$file = Join-Path $dir "access_token"

$secure = Read-Host "Paste your Kaggle API token and press Enter (input is hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)).Trim()
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host "No token entered, nothing saved." -ForegroundColor Yellow
    exit 1
}

New-Item -ItemType Directory -Force -Path $dir | Out-Null
[IO.File]::WriteAllText($file, $token, (New-Object Text.UTF8Encoding $false))

# Only the current Windows user may read this file.
$grant = "${env:USERNAME}:(R,W)"
icacls $file /inheritance:r /grant:r $grant | Out-Null

Write-Host ("Saved token to {0} ({1} characters)." -f $file, $token.Length) -ForegroundColor Green
Remove-Variable token
