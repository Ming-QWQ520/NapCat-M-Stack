# NapCat-M Stack Windows 一键安装
# 功能：
#   1. 准备 NapCat-M Shell（Windows OneKey 包，注入本机 QQNT 客户端）
#   2. 部署 AstrBot（Python 源码方式，独立 venv，不污染系统环境）
#   3. 生成 start.bat（一键拉起 NapCat-M + AstrBot）
# 用法：powershell -ExecutionPolicy Bypass -File windows\install.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$winDir = Join-Path $root 'windows'
$shellDir = Join-Path $winDir 'napcat-shell'
$astrbotDir = Join-Path $winDir 'AstrBot'
$version = 'v4.18.42'

Write-Host '==== NapCat-M Stack Windows 安装 ===='

# ---------- 1. NapCat-M Shell ----------
$napcatBat = $null
if (Test-Path $shellDir) {
    $napcatBat = Get-ChildItem -Path $shellDir -Filter 'napcat.bat' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
}
if ($null -ne $napcatBat) {
    Write-Host '[OK] NapCat-M Shell 已就位，跳过。'
} else {
    $zipPath = Join-Path $winDir 'NapCat.Shell.Windows.OneKey.zip'
    if (-not (Test-Path $zipPath)) {
        $url = "https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/$version/NapCat.Shell.Windows.OneKey.zip"
        Write-Host "[..] 下载 NapCat-M Shell OneKey 包 ..."
        & curl.exe -sSL --ssl-revoke-best-effort --connect-timeout 20 --max-time 600 -o $zipPath $url
        if (-not (Test-Path $zipPath)) {
            Write-Warning "自动下载失败，请手动下载并放到 windows\ 目录后重跑本脚本："
            Write-Warning "  $url"
            exit 1
        }
    }
    Write-Host '[..] 解压 OneKey 包 ...'
    if (Test-Path $shellDir) { Remove-Item $shellDir -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $shellDir -Force
    if (-not (Get-ChildItem -Path $shellDir -Filter 'NapCatInstaller.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        Write-Warning '解压结果中未找到 NapCatInstaller.exe，请检查 zip 内容（可能不是 OneKey 包）。'
        exit 1
    }
    Write-Host "[OK] NapCat-M Shell 就位：windows\napcat-shell\"
    Write-Host '     注意：稍后需先运行其中的 NapCatInstaller.exe 完成注入（需要已安装 QQNT 客户端 9.9.x）。'
}

# ---------- 2. AstrBot ----------
if (Test-Path (Join-Path $astrbotDir 'main.py')) {
    Write-Host '[OK] AstrBot 已就位，跳过。'
} else {
    # Python 3.12+ 检测
    $py = $null
    $pyVer = ''
    foreach ($cmd in 'python', 'py') {
        try {
            $v = (& $cmd -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $v) {
                $ver = ("$v").Trim()
                $parts = $ver.Split('.')
                $major = [int]$parts[0]
                $minor = [int]$parts[1]
                if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 12)) { $py = $cmd; $pyVer = $ver; break }
            }
        } catch { }
    }
    if (-not $py) {
        Write-Warning '未检测到 Python >= 3.12。请先安装：'
        Write-Warning '  winget install Python.Python.3.12'
        Write-Warning '  或 https://www.python.org/downloads/（勾选 Add to PATH）'
        Write-Warning '安装后重跑本脚本。'
        exit 1
    }
    Write-Host "[OK] 检测到 Python $pyVer"

    if (-not (Test-Path $astrbotDir)) {
        Write-Host '[..] 获取 AstrBot 源码 ...'
        & git clone --depth 1 https://github.com/AstrBotDevs/AstrBot $astrbotDir 2>$null
        if (-not (Test-Path (Join-Path $astrbotDir 'main.py'))) {
            Write-Warning 'git clone 失败（网络受限）。请手动下载 AstrBot 源码 zip：'
            Write-Warning '  https://github.com/AstrBotDevs/AstrBot/archive/refs/heads/master.zip'
            Write-Warning "  解压到 windows\AstrBot\（保证 windows\AstrBot\main.py 存在）后重跑本脚本。"
            exit 1
        }
    }

    Write-Host '[..] 创建虚拟环境并安装依赖（国内网络自动使用清华源）...'
    & $py -m venv (Join-Path $astrbotDir 'venv')
    $pip = Join-Path $astrbotDir 'venv\Scripts\python.exe'
    & $pip -m pip install -U pip -q
    & $pip -m pip install -r (Join-Path $astrbotDir 'requirements.txt') -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    Write-Host '[OK] AstrBot 就位：windows\AstrBot\'
}

# ---------- 3. 生成 start.bat ----------
$startBat = @'
@echo off
chcp 65001 >nul
title NapCat-M Stack
setlocal
cd /d "%~dp0"

echo [1/2] 启动 NapCat-M Shell（QQ 注入端）...
set "NAPCAT_BAT="
for /r "%~dp0napcat-shell" %%f in (napcat.bat) do set "NAPCAT_BAT=%%f"
if "%NAPCAT_BAT%"=="" (
    echo 未找到 napcat.bat，请先运行 install.ps1 并执行 NapCatInstaller.exe 完成注入。
    pause & exit /b 1
)
start "NapCat-M Shell" cmd /k "%NAPCAT_BAT%"

echo [2/2] 启动 AstrBot（LLM Bot 框架）...
start "AstrBot" cmd /k "cd /d "%~dp0AstrBot" && venv\Scripts\python.exe main.py"

echo.
echo 两端已启动：
echo   NapCat-M WebUI : http://127.0.0.1:6099   （QQ 扫码登录 / 网络配置）
echo   AstrBot WebUI  : http://127.0.0.1:6185   （填 API Key / 人格 / 插件）
echo.
echo 首次使用请看 README.md 的「五步上手」。
pause
'@
[System.IO.File]::WriteAllText((Join-Path $winDir 'start.bat'), $startBat, (New-Object System.Text.UTF8Encoding($false)))
Write-Host '[OK] 已生成 windows\start.bat'

Write-Host ''
Write-Host '==== 安装完成，后续步骤 ===='
Write-Host '1. 运行 windows\napcat-shell\ 内的 NapCatInstaller.exe（把 NapCat-M 注入本机 QQ）'
Write-Host '2. 运行 windows\start.bat 启动两端'
Write-Host '3. NapCat WebUI（http://127.0.0.1:6099）扫码登录 QQ 小号'
Write-Host '4. AstrBot WebUI（http://127.0.0.1:6185）创建机器人（OneBot v11，反向 WS 主机 0.0.0.0 端口 6199）'
Write-Host '   Windows 非容器部署时 NapCat 侧连接地址填 ws://127.0.0.1:6199/ws'
Write-Host '5. 在 AstrBot WebUI 填大模型 API Key、设人格、装插件，开聊。详见仓库 README.md'
