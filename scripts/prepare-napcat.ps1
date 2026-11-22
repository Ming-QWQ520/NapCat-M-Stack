#!/usr/bin/env pwsh
# 准备 NapCat-M Shell 产物（Windows OneKey 注入版流程使用）
#
# 用法（仓库根目录执行，或由 windows\install.ps1 进程内调用）：
#   powershell -ExecutionPolicy Bypass -File scripts\prepare-napcat.ps1 [版本号]
#
# 产物：napcat\（打好 /napcat 子路径补丁的 NapCat Shell）。
# install.ps1 会把它重新打包成 napcat-onekey\NapCat.Shell.zip，
# 供 OneKey 安装器本地取用（避免其回源已停止维护的上游）。
#
# 兼容性说明：本文件为 UTF-8 with BOM + CRLF，Windows PowerShell 5.1 与
# PowerShell 7+ 均可直接运行。
param(
    [string]$Version = 'v4.18.44'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TargetDir = Join-Path $RepoRoot 'napcat'
$ZipPath = Join-Path $PSScriptRoot 'NapCat.Shell.zip'
$Url = "https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/$Version/NapCat.Shell.zip"

Add-Type -AssemblyName System.IO.Compression.FileSystem

function Test-ZipIntact {
    param([string]$Path)
    try {
        $z = [System.IO.Compression.ZipFile]::OpenRead($Path)
        $count = $z.Entries.Count
        $z.Dispose()
        return ($count -gt 0)
    } catch {
        return $false
    }
}

if (Test-Path (Join-Path $TargetDir 'napcat.mjs')) {
    Write-Host '[OK] napcat\napcat.mjs 已存在，跳过下载。'
} else {
    # 复用本地 zip 前先校验：curl 超时会留下半截文件，直接解压必然失败
    if (-not ((Test-Path $ZipPath) -and (Test-ZipIntact $ZipPath))) {
        if (Test-Path $ZipPath) {
            Write-Host '[!] 已有的 NapCat.Shell.zip 不完整，删除后重新下载 ...'
            Remove-Item $ZipPath -Force
        }
        Write-Host "[..] 下载 NapCat.Shell.zip ($Version) ..."
        # curl 的进度/错误信息走 stderr，临时放宽 EAP 避免 PS 5.1 包装成终止错误
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & curl.exe -fL --ssl-revoke-best-effort --connect-timeout 20 --retry 3 --retry-all-errors --retry-delay 3 --progress-bar -o $ZipPath $Url
            $code = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prev
        }
        if ($code -ne 0 -or -not (Test-Path $ZipPath)) {
            if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
            Write-Warning "自动下载失败，请手动下载后放到 scripts\ 目录重跑：$Url"
            exit 1
        }
        if (-not (Test-ZipIntact $ZipPath)) {
            Remove-Item $ZipPath -Force
            Write-Warning "下载的 zip 校验失败（非有效 zip）：$Url"
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

# ---- WebUI 子路径重写（/napcat 前缀，幂等）----
$py = $null
$venvPy = Join-Path $RepoRoot 'venv\Scripts\python.exe'
if (Test-Path $venvPy) {
    $py = $venvPy
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = 'python'
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $py = 'py'
}
if (-not $py) {
    Write-Warning '未找到可用的 Python，跳过 WebUI 子路径重写（启动时会用 venv 重试）。'
} else {
    Write-Host '[..] WebUI 子路径重写（/napcat 前缀）...'
    & $py (Join-Path $RepoRoot 'stack\webui_patch.py') (Join-Path $TargetDir 'static')
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'WebUI 子路径重写失败：统一网关的 /napcat 入口将不可用。'
    }
}

Write-Host '[OK] 准备完成。可执行 windows\start.bat'
