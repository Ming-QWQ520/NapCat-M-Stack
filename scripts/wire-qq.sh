#!/usr/bin/env bash
# 裸机 Linux：把栈内 NapCat 产物接进系统 QQNT（Electron）
#
# 原理：QQ 是 Electron 应用。把它 resources/app/package.json 的 main 指向
# NapCat 入口后，QQ 启动时会先加载 NapCat，由 NapCat 接管协议。本脚本：
#   1. 定位 QQ 的 resources/app 目录（默认 /opt/QQ/resources/app，
#      可用 --qq-dir 或环境变量 QQ_RESOURCES_DIR 覆盖；也支持从 QQ_PATH 推导）
#   2. 首次执行时备份原 package.json（package.json.stack-backup）
#   3. 用符号链接把 <仓库>/napcat 挂进 QQ（默认；--copy 改为物理复制）
#   4. 把 main 字段改写为 ./napcat/napcat.mjs
#
# 幂等：重复执行安全（已接线则只做校验）。
# 回滚：--rollback 恢复原 package.json 并移除接线。
#
# 用法：
#   sudo bash scripts/wire-qq.sh                 # 接线（默认符号链接）
#   sudo bash scripts/wire-qq.sh --copy          # 接线（物理复制）
#   sudo bash scripts/wire-qq.sh --rollback      # 回滚
#   bash scripts/wire-qq.sh --qq-dir /tmp/fake   # 指定 QQ resources/app 目录
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAPCAT_DIR="$REPO_ROOT/napcat"
BACKUP_SUFFIX=".stack-backup"
NAPCAT_MAIN="./napcat/napcat.mjs"

MODE="wire"        # wire | rollback
LINK_MODE="symlink"  # symlink | copy
QQ_DIR="${QQ_RESOURCES_DIR:-}"

usage() { sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

log()  { printf '%s\n' "$*"; }
die()  { printf '[!] %s\n' "$*" >&2; exit 1; }

# ---------- 参数解析 ----------
while [ $# -gt 0 ]; do
    case "$1" in
        --rollback) MODE="rollback" ;;
        --copy)     LINK_MODE="copy" ;;
        --qq-dir)   [ $# -ge 2 ] || die "--qq-dir 需要一个路径参数"; QQ_DIR="$2"; shift ;;
        -h|--help)  usage; exit 0 ;;
        *)          die "未知参数: $1（--help 查看用法）" ;;
    esac
    shift
done

# ---------- 定位 QQ resources/app ----------
find_qq_dir() {
    # 1) 显式指定
    if [ -n "$QQ_DIR" ]; then
        [ -d "$QQ_DIR" ] || die "指定的 QQ 目录不存在: $QQ_DIR"
        printf '%s' "$QQ_DIR"
        return
    fi
    # 2) 从 QQ_PATH（栈用来启动 QQ 可执行文件的变量）推导
    local qq_exe="${QQ_PATH:-}"
    if [ -n "$qq_exe" ] && [ -x "$qq_exe" ]; then
        local derived
        derived="$(dirname "$qq_exe")/resources/app"
        [ -d "$derived" ] && { printf '%s' "$derived"; return; }
    fi
    # 3) 常见安装位置
    local candidate
    for candidate in \
        /opt/QQ/resources/app \
        /usr/lib/QQ/resources/app \
        /usr/local/lib/QQ/resources/app \
        /usr/share/QQ/resources/app
    do
        [ -d "$candidate" ] && { printf '%s' "$candidate"; return; }
    done
    # 4) 包管理器查询（deb / rpm）
    if command -v dpkg >/dev/null 2>&1; then
        local pkg_list
        pkg_list="$(dpkg -L linuxqq 2>/dev/null || dpkg -L qq 2>/dev/null || true)"
        local hit
        hit="$(printf '%s\n' "$pkg_list" | grep -m1 'resources/app/package.json$' || true)"
        if [ -n "$hit" ]; then
            printf '%s' "$(dirname "$hit")"
            return
        fi
    fi
    return 1
}

QQ_DIR="$(find_qq_dir || true)"
[ -n "${QQ_DIR:-}" ] || die "未找到 QQ 的 resources/app 目录。
请安装 Linux 版 QQNT 后重试，或用 --qq-dir / QQ_RESOURCES_DIR 显式指定。
（AppImage 用户请先解包，见 docs/deploy-linux-native.md 附录。）"

case "$QQ_DIR" in
    *".AppImage"*|*"squashfs-root"*)
        die "检测到 AppImage 内部路径: $QQ_DIR
AppImage 不能直接接线，请参考 docs/deploy-linux-native.md 附录先解包安装。"
        ;;
esac

PKG_JSON="$QQ_DIR/package.json"
[ -f "$PKG_JSON" ] || die "$PKG_JSON 不存在——这不是 QQ 的 resources/app 目录。"

# ---------- 权限：目标不可写且非 root 时自动提权 ----------
if [ ! -w "$QQ_DIR" ] && [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "需要 root 权限写入 $QQ_DIR（且系统无 sudo）。"
    log "[..] 目标目录需要 root 权限，使用 sudo 重新执行……"
    reexec_args=("$0" --qq-dir "$QQ_DIR")
    if [ "$MODE" = "rollback" ]; then reexec_args+=("--rollback"); fi
    if [ "$LINK_MODE" = "copy" ]; then reexec_args+=("--copy"); fi
    exec sudo "${reexec_args[@]}"
fi

# ---------- 回滚 ----------
if [ "$MODE" = "rollback" ]; then
    BACKUP="$PKG_JSON$BACKUP_SUFFIX"
    if [ -f "$BACKUP" ]; then
        mv -f "$BACKUP" "$PKG_JSON"
        log "[OK] 已恢复原 package.json。"
    else
        log "[..] 未找到备份（从未接线或已回滚），仅清理 napcat 接线。"
    fi
    if [ -L "$QQ_DIR/napcat" ]; then
        rm -f "$QQ_DIR/napcat"
        log "[OK] 已移除符号链接 $QQ_DIR/napcat。"
    elif [ -d "$QQ_DIR/napcat" ] && [ -f "$QQ_DIR/napcat/.stack-copied" ]; then
        rm -rf "$QQ_DIR/napcat"
        log "[OK] 已移除复制进去的 $QQ_DIR/napcat。"
    else
        log "[..] $QQ_DIR/napcat 不是本脚本接线产物，保持不动。"
    fi
    log "[OK] 回滚完成。QQ 已恢复为未加载 NapCat 的原始状态。"
    exit 0
fi

# ---------- 接线 ----------
[ -f "$NAPCAT_DIR/napcat.mjs" ] || die "缺少 $NAPCAT_DIR/napcat.mjs。
请先在仓库根目录执行: bash scripts/prepare-napcat.sh"

# 备份（只备份最初的原始文件）
if [ ! -f "$PKG_JSON$BACKUP_SUFFIX" ]; then
    cp -p "$PKG_JSON" "$PKG_JSON$BACKUP_SUFFIX"
    log "[OK] 已备份原配置 -> package.json$BACKUP_SUFFIX"
fi

# 挂载 napcat 产物
if [ -L "$QQ_DIR/napcat" ]; then
    current="$(readlink -f "$QQ_DIR/napcat")"
    want="$(readlink -f "$NAPCAT_DIR")"
    if [ "$current" = "$want" ]; then
        log "[OK] 符号链接已存在且指向正确: $QQ_DIR/napcat -> $NAPCAT_DIR"
    else
        rm -f "$QQ_DIR/napcat"
        ln -s "$NAPCAT_DIR" "$QQ_DIR/napcat"
        log "[OK] 已更新符号链接: $QQ_DIR/napcat -> $NAPCAT_DIR（旧: $current）"
    fi
elif [ -d "$QQ_DIR/napcat" ] && [ ! -f "$QQ_DIR/napcat/.stack-copied" ]; then
    die "$QQ_DIR/napcat 已存在且不是本脚本产物（可能是手动安装的旧版 NapCat）。
请先手动移除或重命名后重试；--rollback 不会动它。"
elif [ "$LINK_MODE" = "copy" ]; then
    rm -rf "$QQ_DIR/napcat"
    cp -r "$NAPCAT_DIR" "$QQ_DIR/napcat"
    touch "$QQ_DIR/napcat/.stack-copied"
    log "[OK] 已复制产物 -> $QQ_DIR/napcat（--copy 模式：仓库更新后需重跑本脚本）"
else
    ln -s "$NAPCAT_DIR" "$QQ_DIR/napcat"
    log "[OK] 已建立符号链接: $QQ_DIR/napcat -> $NAPCAT_DIR"
    log "     （仓库 napcat/ 更新后无需重跑；如需物理复制改用 --copy）"
fi

# 改写 main 字段（幂等：已是目标值则跳过）
current_main="$(python3 - "$PKG_JSON" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f).get("main", ""))
PY
)"
if [ "$current_main" = "$NAPCAT_MAIN" ]; then
    log "[OK] package.json 的 main 已是 $NAPCAT_MAIN"
else
    python3 - "$PKG_JSON" "$NAPCAT_MAIN" <<'PY'
import json, sys
path, new_main = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
data["main"] = new_main
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
    log "[OK] package.json 的 main: ${current_main:-<无>} -> $NAPCAT_MAIN"
fi

log "[OK] 接线完成。现在可以回到仓库根目录执行 ./start.sh 启动整栈。"
log "    回滚: sudo bash $0 --rollback"
