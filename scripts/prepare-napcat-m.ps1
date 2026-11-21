# 准备 NapCat-M Docker 构建产物：下载 NapCat.Shell.zip 并解压 napcat/ 到 napcat-m/napcat/
# 用法：在仓库根目录执行  powershell -ExecutionPolicy Bypass -File scripts/prepare-napcat-m.ps1
# 若网络受限，可手动从 Release 下载 NapCat.Shell.zip 放到本目录，脚本会自动识别。
param(
    [string]$Version = 'v4.18.42'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $repoRoot 'napcat-m\napcat'
$zipPath = Join-Path $PSScriptRoot 'NapCat.Shell.zip'
$url = "https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/$Version/NapCat.Shell.zip"

if (Test-Path (Join-Path $targetDir 'napcat.mjs')) {
    Write-Host "[OK] napcat-m\napcat\napcat.mjs 已存在，跳过准备。"
    exit 0
}

if (-not (Test-Path $zipPath)) {
    Write-Host "[..] 下载 NapCat.Shell.zip ($Version) ..."
    try {
        & curl.exe -sSL --connect-timeout 20 --max-time 600 -o $zipPath $url
        if (-not (Test-Path $zipPath)) { throw '下载失败' }
    } catch {
        Write-Warning "自动下载失败（网络受限时可手动下载）："
        Write-Warning "  $url"
        Write-Warning "  下载后放到 scripts\ 目录并重跑本脚本。"
        exit 1
    }
}

Write-Host "[..] 解压 napcat/ ..."
$extractDir = Join-Path $PSScriptRoot 'shell-extract'
if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

# Shell zip 结构：napcat/（可能包一层目录，兼容两种布局）
$napcatDir = Join-Path $extractDir 'napcat'
if (-not (Test-Path (Join-Path $napcatDir 'napcat.mjs'))) {
    $inner = Get-ChildItem $extractDir -Directory | Select-Object -First 1
    $napcatDir = Join-Path $inner.FullName 'napcat'
}
if (-not (Test-Path (Join-Path $napcatDir 'napcat.mjs'))) {
    Write-Warning '解压结果中未找到 napcat.mjs，请检查 zip 内容。'
    exit 1
}

if (Test-Path $targetDir) { Remove-Item $targetDir -Recurse -Force }
Move-Item $napcatDir $targetDir
Remove-Item $extractDir -Recurse -Force

Write-Host "[OK] NapCat-M 产物已就位：napcat-m\napcat\（napcat.mjs 已确认）"
Write-Host "     现在可以在仓库根目录执行: docker compose up -d --build"
