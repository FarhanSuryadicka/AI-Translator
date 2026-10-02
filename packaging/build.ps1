# Build installer offline lengkap.
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-OutDir D:\Installer]
# Butuh: .venv (lihat README), Inno Setup 6, dan folder models\ + vendor\llama\ sudah terisi.
param(
    [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Build = Join-Path $Root "build"
if (-not $OutDir) { $OutDir = Join-Path $Build "installer" }

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 tidak ditemukan. Instal: winget install JRSoftware.InnoSetup" }

foreach ($p in @("models\translategemma", "models\whisper", "models\tts", "vendor\llama\llama-server.exe", "vendor\llama\vcruntime140.dll")) {
    if (-not (Test-Path (Join-Path $Root $p))) { throw "Belum ada: $p (jalankan: .venv\Scripts\python.exe packaging\download_models.py --xtts)" }
}

Write-Host "=== 1/2 PyInstaller ===" -ForegroundColor Cyan
& $Py -m PyInstaller (Join-Path $PSScriptRoot "ai_translator.spec") --noconfirm --clean `
    --distpath (Join-Path $Build "dist") --workpath (Join-Path $Build "work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller gagal" }

Write-Host "=== 2/2 Inno Setup ===" -ForegroundColor Cyan
& $iscc "/DDistDir=$Build\dist\AI Translator" "/DOutDir=$OutDir" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup gagal" }

Write-Host "Selesai. Installer ada di: $OutDir" -ForegroundColor Green
