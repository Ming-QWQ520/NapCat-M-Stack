#!/usr/bin/env bash
# NapCatQQ-M 一键启动（Linux / macOS）
#
#   ./start.sh              # 前台运行（Ctrl+C 优雅停止）
#   ./start.sh --daemon     # 后台运行，日志写入 data/stack.log
#
# 脚本保证：venv 就绪、依赖就绪、NapCat 产物就绪（必要时自动下载），
# 然后把控制权交给统一入口 python main.py。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

DAEMON=0
if [ "${1:-}" = "--daemon" ]; then DAEMON=1; fi

# ---------- Python ----------
if [ -z "${PYTHON:-}" ]; then
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
                PYTHON="$candidate"
                break
            fi
        fi
    done
fi
if [ -z "${PYTHON:-}" ]; then
    echo "[!] 未找到 Python >= 3.10。请先安装（Debian/Ubuntu: apt install python3 python3-venv）。"
    exit 1
fi

# ---------- venv ----------
VENV="$REPO_ROOT/venv"
if [ ! -f "$VENV/bin/python" ]; then
    echo "[..] 创建虚拟环境 venv/ ..."
    "$PYTHON" -m venv "$VENV"
fi
PIP="$VENV/bin/pip"
if ! "$VENV/bin/python" -c 'import fastapi, hypercorn, httpx, websockets, aiocqhttp' 2>/dev/null; then
    echo "[..] 安装依赖（首次较慢；国内网络可设 PIP_INDEX_URL 环境变量换源）..."
    "$PIP" install -q -U pip
    "$PIP" install -q -r "$REPO_ROOT/requirements.txt"
fi

# ---------- NapCat 产物 ----------
if [ ! -f "$REPO_ROOT/napcat/napcat.mjs" ]; then
    echo "[..] 首次运行：准备 NapCat 产物 ..."
    bash "$REPO_ROOT/scripts/prepare-napcat.sh"
fi

# ---------- 启动 ----------
export ASTRBOT_ROOT="$REPO_ROOT"
export NAPCAT_WORKDIR="${NAPCAT_WORKDIR:-$REPO_ROOT/data/napcat}"

if [ "$DAEMON" = "1" ]; then
    mkdir -p "$REPO_ROOT/data"
    LOG="$REPO_ROOT/data/stack.log"
    echo "[..] 后台启动，日志: $LOG"
    nohup "$VENV/bin/python" "$REPO_ROOT/main.py" >>"$LOG" 2>&1 &
    echo $! > "$REPO_ROOT/data/stack.pid"
    echo "[OK] PID: $(cat "$REPO_ROOT/data/stack.pid")"
    echo "     统一入口: http://127.0.0.1:6185  （/ = AstrBot，/napcat = NapCat）"
else
    exec "$VENV/bin/python" "$REPO_ROOT/main.py"
fi
