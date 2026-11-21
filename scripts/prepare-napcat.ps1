#!/usr/bin/env pwsh
# 准备 NapCat-M Shell 产物（Windows 原生部署）
#
# 用法（仓库根目录执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\prepare-napcat.ps1 [版本号]
#
# 产物：napcat\（供 python main.py 在裸机 QQ 注入模式下使用 NAPCAT_MAIN_PATH 指向）
param(
    [string]$Version = 'v4.18.42'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$TargetDir = Join-Path $RepoRoot 'napcat'
$ZipPath = Join-Path $PSScriptRoot 'NapCat.Shell.zip'
$Url = "https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/$Version/NapCat.Shell.zip"

if (Test-Path (Join-Path $TargetDir 'napcat.mjs')) {
    Write-Host '[OK] napcat\napcat.mjs 已存在，跳过下载。'
} else {
    if (-not (Test-Path $ZipPath)) {
        Write-Host "[..] 下载 NapCat.Shell.zip ($Version) ..."
        & curl.exe -sSL --ssl-revoke-best-effort --connect-timeout 20 --max-time 600 -o $ZipPath $Url
        if (-not (Test-Path $ZipPath)) {
            Write-Warning "自动下载失败，请手动下载后放到 scripts\ 目录：$Url"
            exit 1
        }
    }
    Write-Host '[..] 解压 napcat\ ...'
    $ExtractDir = Join-Path $PSScriptRoot 'shell-extract'
    if (Test-Path $ExtractDir) { Remove-Item $ExtractDir -Recurse -Force }
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force
    $NapCatDir = $ExtractDir
    if (-not (Test-Path (Join-Path $NapCatDir 'napcat.mjs'))) {
        $found = Get-ChildItem -Path $ExtractDir -Filter 'napcat.mjs' -Recurse | Select-Object -First 1
        if ($null -eq $found) {
            Write-Warning '解压结果中未找到 napcat.mjs，请检查 zip 内容。'
            exit 1
        }
        $NapCatDir = $found.DirectoryName
    }
    if (Test-Path $TargetDir) { Remove-Item $TargetDir -Recurse -Force }
    New-Item -ItemType Directory -Path $TargetDir | Out-Null
    Copy-Item -Path (Join-Path $NapCatDir '*') -Destination $TargetDir -Recurse -Force
    Remove-Item $ExtractDir -Recurse -Force
    Write-Host '[OK] NapCat-M 产物已就位：napcat\'
}

Write-Host '[..] WebUI 子路径重写（/napcat 前缀）...'
$py = 'python'
if (Get-Command py -ErrorAction SilentlyContinue) { $py = 'py' }
& $py (Join-Path $RepoRoot 'stack\webui_patch.py') (Join-Path $TargetDir 'static') --force
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'WebUI 子路径重写失败：统一网关的 /napcat 入口将不可用。'
}

Write-Host '[OK] 准备完成。可执行 windows\start.bat'
