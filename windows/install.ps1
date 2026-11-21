# NapCat-M Stack Windows 一键安装
#
# 用法：powershell -ExecutionPolicy Bypass -File windows\install.ps1
#
# 完成四件事：
#   1. NapCat-M OneKey 包（NapCatInstaller.exe + bootmain）就位
#   2. 准备打好子路径补丁的 NapCat.Shell.zip（安装器直接使用，避免其回源已停维的上游）
#   3. AstrBot 依赖部署（独立 venv，不污染系统环境）
#   4. 生成 start.bat
#
# 安装后手动步骤（仅一次）：双击运行 napcat-onekey\NapCatInstaller.exe 完成注入。
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$onekeyDir = Join-Path $PSScriptRoot 'napcat-onekey'
$shellDir = Join-Path $root 'napcat'
$venvDir = Join-Path $root 'venv'
$version = 'v4.18.42'

Write-Host '==== NapCat-M Stack Windows 安装 ===='

# ---------- Python ----------
$py = $null
$pyVer = ''
foreach ($cmd in 'python', 'py') {
    try {
        $v = & $cmd -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) {
            $ver = ("$v").Trim()
            $parts = $ver.Split('.')
            if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)) {
                $py = $cmd; $pyVer = $ver; break
            }
        }
    } catch { }
}
if (-not $py) {
    Write-Warning '未检测到 Python >= 3.10。请先安装：winget install Python.Python.3.12'
    exit 1
}
Write-Host "[OK] 检测到 Python $pyVer（$py）"

# ---------- 1. OneKey 包 ----------
$installer = Join-Path $onekeyDir 'NapCatInstaller.exe'
if (Test-Path $installer) {
    Write-Host '[OK] NapCat OneKey 已就位，跳过。'
} else {
    $zipPath = Join-Path $PSScriptRoot 'NapCat.Shell.Windows.OneKey.zip'
    if (-not (Test-Path $zipPath)) {
        $url = "https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/$version/NapCat.Shell.Windows.OneKey.zip"
        Write-Host '[..] 下载 NapCat OneKey 包 ...'
        & curl.exe -sSL --ssl-revoke-best-effort --connect-timeout 20 --max-time 600 -o $zipPath $url
        if (-not (Test-Path $zipPath)) {
            Write-Warning "自动下载失败，请手动下载后放到 windows\ 目录重跑：$url"
            exit 1
        }
    }
    if (Test-Path $onekeyDir) { Remove-Item $onekeyDir -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $onekeyDir -Force
    if (-not (Test-Path $installer)) {
        Write-Warning '解压结果中未找到 NapCatInstaller.exe，请检查 zip 内容。'
        exit 1
    }
    Write-Host "[OK] OneKey 就位：windows\napcat-onekey\"
}

# ---------- 2. 打补丁的 Shell zip（供安装器本地取用） ----------
$shellZip = Join-Path $onekeyDir 'NapCat.Shell.zip'
$needZip = -not (Test-Path $shellZip)
if ($needZip -and (Test-Path (Join-Path $shellDir 'napcat.mjs'))) {
    # 由已准备产物重新打包（PowerShell 5 无 zip 命令，用 .NET）
    Write-Host '[..] 由 napcat\ 产物重新打包 NapCat.Shell.zip（含子路径补丁）...'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($shellDir, $shellZip,
        [System.IO.Compression.CompressionLevel]::Optimal, $false)
    $needZip = $false
}
if ($needZip) {
    Write-Host '[..] 运行 prepare-napcat.ps1 生成产物与补丁 zip ...'
    & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\prepare-napcat.ps1') $version 2>$null
    if ($LASTEXITCODE -ne 0) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\prepare-napcat.ps1') $version
    }
    if (Test-Path (Join-Path $shellDir 'napcat.mjs')) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::CreateFromDirectory($shellDir, $shellZip,
            [System.IO.Compression.CompressionLevel]::Optimal, $false)
    } else {
        Write-Warning 'NapCat Shell 产物未就位，start.bat 会再次尝试准备。'
    }
}

# ---------- 3. AstrBot venv ----------
if (Test-Path (Join-Path $venvDir 'Scripts\python.exe')) {
    Write-Host '[OK] AstrBot 虚拟环境已就位，跳过。'
} else {
    Write-Host '[..] 创建虚拟环境并安装依赖（国内网络自动使用清华源）...'
    & $py -m venv $venvDir
    $venvPy = Join-Path $venvDir 'Scripts\python.exe'
    & $venvPy -m pip install -U pip -q
    & $venvPy -m pip install -r (Join-Path $root 'requirements.txt') -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    Write-Host '[OK] AstrBot 依赖就位'
}

# ---------- 4. start.bat ----------
$startBat = @'
@echo off
chcp 65001 >nul
title NapCat-M Stack
setlocal
cd /d "%~dp0.."

set "VENV_PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [!] 未找到 venv，请先运行 windows\install.ps1
    pause
    exit /b 1
)

if not exist "napcat\napcat.mjs" (
    echo [..] 首次运行：准备 NapCat-M 产物 ...
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\prepare-napcat.ps1"
)

REM 对 OneKey 安装器部署的产物执行子路径重写（幂等）
"%VENV_PY%" -m stack.webui_patch "%~dp0napcat-onekey" 2>nul

set "ASTRBOT_ROOT=%~dp0.."
set "NAPCAT_WORKDIR=%~dp0..\data\napcat"
set "NAPCAT_DIR=%~dp0..\napcat"
set "NAPCAT_STATIC_DIR=%~dp0..\napcat\static"

echo.
echo   统一入口: http://127.0.0.1:6185
echo     /          AstrBot WebUI（填 API Key / 人格 / 插件）
echo     /napcat    NapCat WebUI（QQ 扫码登录 / 协议配置）
echo.
"%VENV_PY%" main.py
pause
'@
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'start.bat'), $startBat, (New-Object System.Text.UTF8Encoding($false)))
Write-Host '[OK] 已生成 windows\start.bat'

Write-Host ''
Write-Host '==== 安装完成 ===='
Write-Host '1. （仅一次）运行 windows\napcat-onekey\NapCatInstaller.exe 完成注入/部署'
Write-Host '2. 双击 windows\start.bat 启动整栈'
Write-Host '3. 浏览器打开 http://127.0.0.1:6185'
Write-Host '   - /       AstrBot（填大模型 API Key、人格、插件）'
Write-Host '   - /napcat NapCat（扫码登录 QQ 专用小号，Token 见启动日志）'
