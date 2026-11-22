#!/usr/bin/env bash
# 宝塔面板环境一键准备（NapCat-M Stack）
#
# 在宝塔面板的「终端」（或 SSH，root）里执行本脚本，完成：
#   1. 系统依赖安装（git / curl / xvfb / python3-venv）
#   2. 拉取 NapCat-M Stack 代码（默认 /www/wwwroot/napcat-m-stack）
#   3. 下载 NapCat-M Shell 产物 + WebUI 子路径重写（prepare-napcat.sh）
#   4. 创建 venv 并安装 AstrBot 依赖
#
# 不做的事（需要你手动/在面板里完成，见 docs/deploy-baota.md）：
#   - 安装 Linux 版 QQNT（官网 deb/rpm，脚本会给出提示）
#   - 把 NapCat 接进 QQ（sudo bash scripts/wire-qq.sh）
#   - 在宝塔面板里创建守护进程并启动
#
# 用法：
#   bash scripts/baota-setup.sh [--repo-dir /www/wwwroot/napcat-m-stack] [--mirror]
#
#   --repo-dir  代码安装位置（默认 /www/wwwroot/napcat-m-stack，宝塔惯例路径）
#   --mirror    pip 走清华镜像源（国内服务器建议）
set -euo pipefail

REPO_DIR="/www/wwwroot/napcat-m-stack"
REPO_URL="https://github.com/Ming-QWQ520/NapCat-M-Stack"
PIP_INDEX=""

while [ $# -gt 0 ]; do
    case "$1" in
        --repo-dir) REPO_DIR="$2"; shift 2 ;;
        --mirror)   PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"; shift ;;
        -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "[!] 未知参数: $1（--help 查看用法）"; exit 1 ;;
    esac
done

log()  { echo -e "\033[32m[..]\033[0m $1"; }
ok()   { echo -e "\033[32m[OK]\033[0m $1"; }
warn() { echo -e "\033[33m[!]\033[0m $1"; }

# ---------------------------------------------------------------- 1. 系统依赖
log "安装系统依赖（git / curl / xvfb / python3-venv）..."
if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq git curl xvfb python3 python3-venv python3-pip >/dev/null
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q git curl xorg-x11-server-Xvfb python3 python3-pip >/dev/null
elif command -v yum >/dev/null 2>&1; then
    yum install -y -q git curl xorg-x11-server-Xvfb python3 python3-pip >/dev/null
else
    warn "未识别的包管理器，请手动安装 git curl xvfb python3(>=3.10) 后重跑。"
    exit 1
fi
ok "系统依赖就绪"

# Python 版本检查（栈要求 >= 3.10）
PY_OK=0
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PY="$candidate"; PY_OK=1; break
        fi
    fi
done
if [ "$PY_OK" != "1" ]; then
    warn "未找到 Python >= 3.10。宝塔可在「软件商店 → 运行环境」安装 Python 3.10+，"
    warn "或使用系统包管理器（Debian 12 / Ubuntu 22.04+ 自带的 python3 即满足）。"
    exit 1
fi
ok "Python: $($PY --version)"

# ---------------------------------------------------------------- 2. 拉取代码
if [ -d "$REPO_DIR/.git" ] || [ -f "$REPO_DIR/main.py" ]; then
    ok "代码已存在: $REPO_DIR（如需更新: cd $REPO_DIR && git pull）"
else
    log "克隆 NapCat-M Stack 到 $REPO_DIR ..."
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone --depth 1 "$REPO_URL" "$REPO_DIR"
    ok "代码就绪"
fi
cd "$REPO_DIR"

# ---------------------------------------------------------------- 3. NapCat 产物
if [ -f napcat/napcat.mjs ]; then
    ok "NapCat-M 产物已存在，跳过下载（升级可重跑 bash scripts/prepare-napcat.sh）"
else
    log "下载 NapCat-M Shell 产物（约 36 MB）..."
    bash scripts/prepare-napcat.sh
    ok "NapCat-M 产物就绪"
fi

# ---------------------------------------------------------------- 4. venv + 依赖
if [ -x venv/bin/python ] && venv/bin/python -c 'import fastapi, hypercorn, httpx, websockets, aiocqhttp' 2>/dev/null; then
    ok "AstrBot 依赖已就绪，跳过安装"
else
    log "创建虚拟环境并安装依赖（首次 3-10 分钟）..."
    [ -d venv ] || "$PY" -m venv venv
    venv/bin/pip install -q -U pip
    if [ -n "$PIP_INDEX" ]; then
        venv/bin/pip install -q -r requirements.txt -i "$PIP_INDEX"
    else
        venv/bin/pip install -q -r requirements.txt \
            || { warn "官方源安装失败，改用清华镜像源重试 ..."; \
                 venv/bin/pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple; }
    fi
    ok "AstrBot 依赖就绪"
fi

# ---------------------------------------------------------------- 5. QQNT 检查
echo
if [ -x /opt/QQ/qq ]; then
    if grep -q '"main": *"\./napcat/napcat.mjs"' /opt/QQ/resources/app/package.json 2>/dev/null; then
        ok "QQNT 已接线（加载栈内 NapCat）"
    else
        warn "检测到 QQNT（/opt/QQ）但尚未接线，请执行："
        echo "    sudo bash $REPO_DIR/scripts/wire-qq.sh"
    fi
else
    warn "未检测到 Linux 版 QQNT（/opt/QQ）。请先安装："
    echo "    1) 到 https://linux.qq.com 下载 deb（Debian/Ubuntu）或 rpm（RHEL 系）"
    echo "    2) 宝塔终端执行安装，例：sudo apt install ./linuxqq_*.deb"
    echo "    3) 无桌面服务器先初始化一次：xvfb-run -a /opt/QQ/qq ，等 10 秒后 Ctrl+C"
    echo "    4) 接线：sudo bash $REPO_DIR/scripts/wire-qq.sh"
fi

# ---------------------------------------------------------------- 6. 下一步
cat <<EOF

============================================================
 宝塔面板里的最后两步（详见 docs/deploy-baota.md）
------------------------------------------------------------
 1. 守护进程（二选一）：
    A. 软件商店 →「进程守护管理器」→ 添加守护进程：
         名称: napcat-m-stack
         启动用户: root（或能启动 QQ 的用户）
         运行目录: $REPO_DIR
         启动命令: bash $REPO_DIR/start.sh
    B. 网站 → Python项目 → 添加：
         路径指向 $REPO_DIR，启动文件 main.py，
         端口 6185（用栈内 venv: $REPO_DIR/venv/bin/python）
 2. 访问：http://<服务器IP>:6185
      /        AstrBot 控制台
      /napcat  NapCat WebUI（账户 napcat，密码与 AstrBot 一致）
 域名/HTTPS：宝塔建站后反向代理到 127.0.0.1:6185
 （WebSocket/SSE 配置片段见 docs/deploy-baota.md 附录）
============================================================
EOF
