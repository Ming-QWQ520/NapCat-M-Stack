# NapCat-M Stack Windows 一键安装
#
# 用法（在仓库根目录或任意位置执行均可）：
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Flavor Node
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Flavor OneKey
#
# 部署形态（-Flavor，缺省时交互询问）：
#   Node    便携版（推荐）：NapCat.Shell.Windows.Node.zip，自带无头 QQ 与
#           Node.js 运行时，免安装 QQ、免注入，解压即用（约 118 MB）
#   OneKey  注入版：NapCat.Shell.Windows.OneKey.zip，需要本机已安装 QQNT，
#           安装后需手动运行一次 napcat-onekey\NapCatInstaller.exe（约 1 MB）
#
# 本脚本完成：
#   1. AstrBot 依赖部署（独立 venv，不污染系统环境）
#   2. 按 -Flavor 下载并解压 NapCat-M 产物
#   3. NapCat WebUI 静态资源子路径重写（/napcat 前缀，供统一网关挂载）
#   4. 生成 windows\start.bat
#
# 兼容性说明：本文件为 UTF-8 with BOM + CRLF，Windows PowerShell 5.1 与
# PowerShell 7+ 均可直接运行；脚本内部不再派生 pwsh/powershell 子进程。
param(
    [ValidateSet('Node', 'OneKey', '')]
    [string]$Flavor = '',
    [string]$Version = 'v4.18.44',
    [string]$PypiMirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'
)

$ErrorActionPreference = 'Stop'
# PS 5.1 的进度条会把 Expand-Archive 拖慢一个数量级
$ProgressPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $root 'venv'
$venvPy = Join-Path $venvDir 'Scripts\python.exe'
$ReleaseBase = 'https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download'

Write-Host '==== NapCat-M Stack Windows 安装 ===='

# ---------------------------------------------------------------- 工具函数
function Invoke-StackDownload {
    # curl 进度条与错误信息走 stderr；PS 5.1 里重定向过的 stderr 会被包装成
    # ErrorRecord，叠加 ErrorActionPreference=Stop 即成终止错误。这里临时放宽，
    # 之后用 $LASTEXITCODE 显式判定成败。
    param([string]$Url, [string]$Out, [string]$Desc)
    if (Test-Path $Out) { Remove-Item $Out -Force }
    Write-Host "[..] $Desc"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & curl.exe -fL --ssl-revoke-best-effort --connect-timeout 20 --retry 3 --retry-all-errors --retry-delay 3 --progress-bar -o $Out $Url
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($code -ne 0 -or -not (Test-Path $Out)) {
        if (Test-Path $Out) { Remove-Item $Out -Force }
        throw "下载失败（curl 退出码 $code）：$Url  请检查网络后重跑，或手动下载该文件放到 $Out。"
    }
}

function Get-StackZip {
    # 已存在则复用，不做 zip 校验（按用户要求取消验证步骤）
    param([string]$Name, [string]$Out, [string]$Desc)
    if (Test-Path $Out) {
        Write-Host "[OK] $Name 已存在，复用。"
        return
    }
    Invoke-StackDownload -Url "$ReleaseBase/$Version/$Name" -Out $Out -Desc $Desc
}

function Expand-StackZip {
    param([string]$Zip, [string]$Dest)
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    New-Item -ItemType Directory -Path $Dest | Out-Null
    Expand-Archive -Path $Zip -DestinationPath $Dest -Force
}

# ---------------------------------------------------------------- 0. 形态选择
if (-not $Flavor) {
    Write-Host ''
    Write-Host '请选择 NapCat-M 部署形态：'
    Write-Host '  [1] Node 便携版（推荐）自带无头 QQ + Node.js，免装 QQ 免注入，开箱即用（约 118 MB）'
    Write-Host '  [2] OneKey 注入版      由安装器部署便携 QQ 并注入（注意：其内置 NapCat'
    Write-Host '        下载源已随上游停维失效，失败时请改用 [1]）'
    $answer = ''
    try { $answer = (Read-Host '输入 1 或 2（直接回车 = 1）').Trim() } catch { }
    if ($answer -eq '2') { $Flavor = 'OneKey' } else { $Flavor = 'Node' }
    Write-Host ''
}
Write-Host "[OK] 部署形态：$Flavor（$Version）"

# ---------------------------------------------------------------- 1. Python
$py = $null
$pyVer = ''
foreach ($name in 'python', 'py', 'python3') {
    try {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $v = & $name -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null
        } finally {
            $ErrorActionPreference = $prev
        }
        if ($LASTEXITCODE -eq 0 -and $v) {
            $ver = ("$v").Trim()
            $parts = $ver.Split('.')
            if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)) {
                $py = $name; $pyVer = $ver; break
            }
        }
    } catch { }
}
if (-not $py) {
    Write-Warning '未检测到 Python >= 3.10。请先安装：winget install Python.Python.3.12'
    exit 1
}
Write-Host "[OK] 检测到 Python $pyVer（$py）"

# 下载依赖 curl.exe（Windows 10 1803+ 系统自带；提前给出清晰报错而不是中途崩溃）
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Write-Warning '未找到 curl.exe（Windows 10 1803+ 自带）。请更新系统，或手动下载产物后重跑。'
    exit 1
}

# ---------------------------------------------------------------- 2. AstrBot venv
if (Test-Path $venvPy) {
    Write-Host '[OK] AstrBot 虚拟环境已就位，跳过。'
} else {
    Write-Host '[..] 创建虚拟环境并安装依赖（国内网络默认使用清华源）...'
    & $py -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw '创建 venv 失败，请检查 Python 安装。' }
    & $venvPy -m pip install -U pip -q --disable-pip-version-check -i $PypiMirror
    & $venvPy -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt') -i $PypiMirror
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[..] 镜像源安装失败，回退官方 PyPI ...'
        & $venvPy -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络后重跑本脚本。' }
    }
    Write-Host '[OK] AstrBot 依赖就位'
}

# ---------------------------------------------------------------- 3. NapCat-M 产物
if ($Flavor -eq 'Node') {
    $nodeDir = Join-Path $PSScriptRoot 'napcat-node'
    $nodeExe = Join-Path $nodeDir 'node.exe'
    $indexJs = Join-Path $nodeDir 'index.js'
    $napcatMjs = Join-Path $nodeDir 'napcat\napcat.mjs'
    if ((Test-Path $nodeExe) -and (Test-Path $indexJs) -and (Test-Path $napcatMjs)) {
        Write-Host '[OK] NapCat-M Node 便携版已就位，跳过下载。'
    } else {
        $zipPath = Join-Path $PSScriptRoot 'NapCat.Shell.Windows.Node.zip'
        Get-StackZip -Name 'NapCat.Shell.Windows.Node.zip' -Out $zipPath -Desc '下载 NapCat-M Node 便携版（约 118 MB，请耐心等待）...'
        Write-Host '[..] 解压 windows\napcat-node\ ...'
        Expand-StackZip -Zip $zipPath -Dest $nodeDir
        if (-not ((Test-Path $nodeExe) -and (Test-Path $indexJs) -and (Test-Path $napcatMjs))) {
            throw '解压结果不完整（缺 node.exe / index.js / napcat\napcat.mjs）。请删除 windows\napcat-node 后重跑本脚本。'
        }
        # 安装包不再保留，释放约 118 MB 磁盘空间（如需重新解压可重跑本脚本）
        Remove-Item $zipPath -Force
        Write-Host '[OK] Node 便携版就位：windows\napcat-node\'
    }
    # WebUI 子路径重写（幂等，打过标记会自动跳过）
    $nodeStatic = Join-Path $nodeDir 'napcat\static'
    if (Test-Path (Join-Path $nodeStatic 'index.html')) {
        Write-Host '[..] NapCat WebUI 子路径重写（/napcat 前缀）...'
        & $venvPy (Join-Path $root 'stack\webui_patch.py') $nodeStatic
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'WebUI 子路径重写失败：统一网关的 /napcat 入口将不可用（启动时会自动重试）。'
        }
    } else {
        Write-Warning 'napcat-node\napcat\static 缺失，跳过 WebUI 子路径重写。'
    }
} else {
    # ---- OneKey 注入版 ----
    $onekeyDir = Join-Path $PSScriptRoot 'napcat-onekey'
    $installer = Join-Path $onekeyDir 'NapCatInstaller.exe'
    if (Test-Path $installer) {
        Write-Host '[OK] NapCat OneKey 已就位，跳过。'
    } else {
        $zipPath = Join-Path $PSScriptRoot 'NapCat.Shell.Windows.OneKey.zip'
        Get-StackZip -Name 'NapCat.Shell.Windows.OneKey.zip' -Out $zipPath -Desc '下载 NapCat OneKey 包 ...'
        Expand-StackZip -Zip $zipPath -Dest $onekeyDir
        if (-not (Test-Path $installer)) {
            throw '解压结果中未找到 NapCatInstaller.exe，请检查 zip 内容。'
        }
        Write-Host '[OK] OneKey 就位：windows\napcat-onekey\'
    }

    # 打好子路径补丁的 NapCat.Shell.zip：放在安装器旁边，供其本地取用，
    # 避免安装器回源已停止维护的上游。
    $shellDir = Join-Path $root 'napcat'
    $shellZip = Join-Path $onekeyDir 'NapCat.Shell.zip'
    if (-not (Test-Path $shellZip)) {
        Write-Host '[..] 运行 prepare-napcat.ps1 生成产物与补丁 zip ...'
        # 进程内直接调用（不派生 pwsh/powershell 子进程，规避
        # CommandNotFoundException 与 NativeCommandError 两类问题）
        try {
            & (Join-Path $root 'scripts\prepare-napcat.ps1') $Version
        } catch {
            Write-Warning "prepare-napcat.ps1 执行出错：$($_.Exception.Message)"
        }
        if (Test-Path (Join-Path $shellDir 'napcat.mjs')) {
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            if (Test-Path $shellZip) { Remove-Item $shellZip -Force }
            [System.IO.Compression.ZipFile]::CreateFromDirectory(
                $shellDir, $shellZip,
                [System.IO.Compression.CompressionLevel]::Optimal, $false)
            Write-Host '[OK] 已生成补丁版 NapCat.Shell.zip（供 OneKey 安装器本地取用）'
        } else {
            Write-Warning 'NapCat Shell 产物未就位（网络问题？）。后续启动时会再次尝试准备。'
        }
    } else {
        Write-Host '[OK] 补丁版 NapCat.Shell.zip 已存在，跳过。'
    }
}

# ---------------------------------------------------------------- 4. start.bat
$startBat = @'
@echo off
chcp 65001 >nul
title NapCat-M Stack
setlocal
cd /d "%~dp0.."

set "VENV_PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [!] venv not found. Run windows\install.ps1 first.
    pause
    exit /b 1
)

set "ASTRBOT_ROOT=%~dp0.."
set "NAPCAT_WORKDIR=%~dp0..\data\napcat"

if not exist "%~dp0napcat-node\node.exe" if not exist "%~dp0napcat-onekey\NapCatInstaller.exe" (
    echo [!] NapCat-M artifacts not found. Run windows\install.ps1 first.
    pause
    exit /b 1
)

echo.
echo   Unified gateway: http://127.0.0.1:6185
echo     /          AstrBot WebUI
echo     /napcat    NapCat WebUI
echo.
"%VENV_PY%" main.py
pause
'@
$batText = $startBat -replace "`r?`n", "`r`n"
[System.IO.File]::WriteAllText(
    (Join-Path $PSScriptRoot 'start.bat'), $batText,
    (New-Object System.Text.UTF8Encoding($false)))
Write-Host '[OK] 已生成 windows\start.bat'

# ---------------------------------------------------------------- 5. 完成
Write-Host ''
Write-Host '==== 安装完成 ===='
if ($Flavor -eq 'Node') {
    Write-Host '1. 双击 windows\start.bat 启动整栈（无需任何额外步骤）'
} else {
    Write-Host '1. （仅一次）运行 windows\napcat-onekey\NapCatInstaller.exe 完成部署'
    Write-Host '   注意：安装器内置的 NapCat 下载源已随上游停维而失效；本脚本已在安装器'
    Write-Host '   旁放置补丁版 NapCat.Shell.zip，若安装器仍提示下载失败，请改用：'
    Write-Host '   powershell -ExecutionPolicy Bypass -File install.ps1 -Flavor Node'
}
Write-Host '2. 浏览器打开 http://127.0.0.1:6185'
Write-Host '   - /       AstrBot（填大模型 API Key、人格、插件）'
Write-Host '   - /napcat NapCat（账户 napcat，密码与 AstrBot 仪表盘一致）'
