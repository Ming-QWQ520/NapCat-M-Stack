#!/usr/bin/env bash
# 准备 NapCat-M Shell 产物（Linux / macOS / Docker 构建上下文）
#
# 用法（仓库根目录执行）：
#   bash scripts/prepare-napcat.sh [版本号，默认 v4.18.42]
#
# 产物：napcat/（napcat.mjs + static/ + native/ + config/），其中 static/
# 已完成 /napcat 子路径重写（统一网关同端口方案的关键步骤）。
set -euo pipefail

VERSION="${1:-v4.18.42}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$REPO_ROOT/napcat"
ZIP_PATH="$REPO_ROOT/scripts/NapCat.Shell.zip"
URL="https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/$VERSION/NapCat.Shell.zip"

if [ -f "$TARGET_DIR/napcat.mjs" ]; then
    echo "[OK] napcat/napcat.mjs 已存在，跳过下载。"
else
    if [ ! -f "$ZIP_PATH" ]; then
        echo "[..] 下载 NapCat.Shell.zip ($VERSION) ..."
        curl -sSL --connect-timeout 20 --max-time 600 -o "$ZIP_PATH" "$URL" \
            || { echo "[!] 自动下载失败（网络受限时可手动下载后放到 scripts/ 目录）：$URL"; exit 1; }
    fi
    echo "[..] 解压 napcat/ ..."
    EXTRACT_DIR="$REPO_ROOT/scripts/shell-extract"
    rm -rf "$EXTRACT_DIR"
    mkdir -p "$EXTRACT_DIR"
    tar -xzf "$ZIP_PATH" -C "$EXTRACT_DIR" 2>/dev/null || unzip -qo "$ZIP_PATH" -d "$EXTRACT_DIR"

    NAPCAT_DIR="$EXTRACT_DIR"
    if [ ! -f "$NAPCAT_DIR/napcat.mjs" ]; then
        NAPCAT_DIR="$(find "$EXTRACT_DIR" -name napcat.mjs -printf '%h\n' -quit 2>/dev/null || true)"
        if [ -z "$NAPCAT_DIR" ]; then
            echo "[!] 解压结果中未找到 napcat.mjs，请检查 zip 内容。"
            exit 1
        fi
    fi

    rm -rf "$TARGET_DIR"
    mkdir -p "$TARGET_DIR"
    cp -r "$NAPCAT_DIR/." "$TARGET_DIR/"
    rm -rf "$EXTRACT_DIR"
    echo "[OK] NapCat-M 产物已就位：napcat/"
fi

echo "[..] WebUI 子路径重写（/napcat 前缀）..."
python3 "$REPO_ROOT/stack/webui_patch.py" "$TARGET_DIR/static" --force

echo "[OK] 准备完成。可执行: python main.py 或 docker compose up -d --build"
