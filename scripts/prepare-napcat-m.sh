#!/usr/bin/env bash
# 准备 NapCat-M Docker 构建产物：下载 NapCat.Shell.zip 并解压 napcat/ 到 napcat-m/napcat/
# 用法：在仓库根目录执行  bash scripts/prepare-napcat-m.sh [版本号，默认 v4.18.42]
set -euo pipefail

VERSION="${1:-v4.18.42}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$REPO_ROOT/napcat-m/napcat"
ZIP_PATH="$REPO_ROOT/scripts/NapCat.Shell.zip"
URL="https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/$VERSION/NapCat.Shell.zip"

if [ -f "$TARGET_DIR/napcat.mjs" ]; then
    echo "[OK] napcat-m/napcat/napcat.mjs 已存在，跳过准备。"
    exit 0
fi

if [ ! -f "$ZIP_PATH" ]; then
    echo "[..] 下载 NapCat.Shell.zip ($VERSION) ..."
    curl -sSL --connect-timeout 20 --max-time 600 -o "$ZIP_PATH" "$URL" \
        || { echo "[!] 自动下载失败（网络受限时可手动下载后放到 scripts/ 目录）：$URL"; exit 1; }
fi

echo "[..] 解压 napcat/ ..."
EXTRACT_DIR="$REPO_ROOT/scripts/shell-extract"
rm -rf "$EXTRACT_DIR"
mkdir -p "$EXTRACT_DIR"
tar -xzf "$ZIP_PATH" -C "$EXTRACT_DIR"

# Shell zip 结构：napcat/（可能包一层目录，兼容两种布局）
NAPCAT_DIR="$EXTRACT_DIR/napcat"
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

echo "[OK] NapCat-M 产物已就位：napcat-m/napcat/（napcat.mjs 已确认）"
echo "     现在可以在仓库根目录执行: docker compose up -d --build"
