#!/usr/bin/env python3
"""NapCatQQ-M 宝塔面板（BT Panel）适配入口。

为「宝塔 · 网站 · Python 项目」与服务器命令行准备的启动文件，一条命令
直接拉起整栈::

    python bt-main.py

与 ``main.py`` 的关系：``main.py`` 是唯一真正的统一入口（单进程树 + 单端口
网关），本文件只做宝塔 / 裸服务器环境的**自举（bootstrap）**，随后把控制权
原样交给它：

1. cwd 无关 —— 无论从哪个目录启动都先切到仓库根（宝塔面板可能从任意
   工作目录拉起本文件）
2. 依赖自检 —— 缺 Python 依赖时自动 ``pip install -r requirements.txt``
   （优先清华镜像源，失败回退官方 PyPI，适配国内服务器）
3. NapCat 产物自检 —— 缺 ``napcat/napcat.mjs`` 时自动执行
   ``scripts/prepare-napcat.sh``（下载 Shell 产物 + /napcat 子路径重写）
4. QQ 接线自检 —— Linux 上检测到已安装 QQNT 但未接线时，自动执行
   ``scripts/wire-qq.sh``（幂等、可 ``--rollback``；需要 root/写权限）
5. 前台常驻 —— 宝塔项目管理器守望着本进程；Ctrl+C / SIGTERM 优雅退出

用法（宝塔面板）：网站 → Python 项目 → 添加 Python 项目，
项目目录选本仓库目录、启动方式选「python 启动文件」、启动文件填
``bt-main.py``、端口填 ``6185``，其余默认。

用法（命令行）::

    python bt-main.py                 # 等价于自举增强版的 python main.py
    python bt-main.py --port 6200     # 指定统一网关端口（默认 6185）

环境变量（可选，均可不设）::

    NAPCAT_AUTO_WIRE_QQ=0    关闭「root 下自动接线 QQ」（默认开启）
    PIP_INDEX_URL=...        自定义 pip 源（设置后不再走内置镜像回退）
    其余环境变量见仓库 README「常用配置（环境变量）」
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: 国内服务器优先使用的 pip 镜像（可用 PIP_INDEX_URL 覆盖）
PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

#: 与 start.sh 一致的核心依赖探测集（覆盖 astrbot 导入链主干；
#: hypercorn 由 quart 间接安装）
_CORE_DEPS = ("fastapi", "hypercorn", "httpx", "websockets", "aiocqhttp")

BT_BANNER = """
==================== NapCatQQ-M · 宝塔适配入口 ====================
  NapCat + AstrBot 一体化栈 · python bt-main.py 直接启动
  统一网关: / -> AstrBot WebUI, /napcat -> NapCat WebUI
===================================================================
"""


def _log(tag: str, message: str) -> None:
    print(f"{tag} {message}", flush=True)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


# ---------------------------------------------------------------- 0. 参数
def _extract_port_flag(argv: list[str]) -> int | None:
    """吃掉 ``--port N`` 旗标（宝塔面板的项目端口习惯），返回端口号。

    main.py 自身不认识 ``--port``，这里翻译成它认识的 DASHBOARD_PORT
    环境变量后从 argv 移除。
    """
    port: int | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--port":
            if i + 1 >= len(argv):
                raise SystemExit("--port 需要一个端口号参数，例如 --port 6185")
            port = int(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
            i += 1
            continue
        rest.append(arg)
        i += 1
    if port is not None:
        if not (1 <= port <= 65535):
            raise SystemExit(f"非法端口号: {port}")
        argv[:] = rest
    return port


# ---------------------------------------------------------------- 1. 依赖
def _deps_ready() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in _CORE_DEPS)


def ensure_python_deps() -> None:
    """缺依赖时自动安装（镜像优先，失败回退官方源）。"""
    if _deps_ready():
        return
    requirements = ROOT / "requirements.txt"
    if not requirements.is_file():
        _log("[!]", f"未找到 {requirements}，跳过依赖自检。")
        return
    _log("[..]", "首次运行：安装 Python 依赖（耗时数分钟，请耐心等待）……")
    base_cmd = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    attempts: list[list[str]] = []
    if not os.environ.get("PIP_INDEX_URL"):
        attempts.append([*base_cmd, "-i", PYPI_MIRROR])
    attempts.append(base_cmd)
    for cmd in attempts:
        if subprocess.call(cmd) == 0 and _deps_ready():
            _log("[OK]", "Python 依赖就位。")
            return
    _log("[!]", "依赖自动安装失败。请检查网络后重跑，或手动执行：")
    _log("    ", f"{sys.executable} -m pip install -r {requirements}")
    raise SystemExit(1)


# ---------------------------------------------------------------- 2. NapCat 产物
def ensure_napcat_artifacts() -> None:
    """缺 napcat/ 产物时自动执行 prepare-napcat.sh（下载 + 子路径重写）。"""
    if (ROOT / "napcat" / "napcat.mjs").is_file():
        return
    script = ROOT / "scripts" / "prepare-napcat.sh"
    if sys.platform == "win32":
        # Windows 由 windows\install.ps1 负责产物准备
        return
    if not script.is_file():
        _log("[!]", f"未找到 {script}，跳过 NapCat 产物自检。")
        return
    _log("[..]", "首次运行：准备 NapCat 产物（下载 + WebUI 子路径重写）……")
    if subprocess.call(["bash", str(script)]) != 0:
        _log("[!]", "NapCat 产物准备失败。可手动执行后重试：")
        _log("    ", "bash scripts/prepare-napcat.sh")
        raise SystemExit(1)


# ---------------------------------------------------------------- 3. QQ 接线
def _find_qq_resources_dir() -> Path | None:
    """定位 QQ 的 resources/app 目录（逻辑对齐 wire-qq.sh，不含包管理器查询）。"""
    explicit = os.environ.get("QQ_RESOURCES_DIR", "").strip()
    if explicit:
        candidate = Path(explicit)
        return candidate if (candidate / "package.json").is_file() else None

    qq_path = os.environ.get("QQ_PATH", "").strip()
    if qq_path:
        derived = Path(qq_path).parent / "resources" / "app"
        if (derived / "package.json").is_file():
            return derived

    for candidate in (
        "/opt/QQ/resources/app",
        "/usr/lib/QQ/resources/app",
        "/usr/local/lib/QQ/resources/app",
        "/usr/share/QQ/resources/app",
    ):
        p = Path(candidate)
        if (p / "package.json").is_file():
            return p
    return None


def _is_qq_wired(qq_dir: Path, napcat_dir: Path) -> bool:
    """判断 QQ 是否已接入本仓库的 NapCat 产物。"""
    link = qq_dir / "napcat"
    if not link.exists():
        return False
    if link.is_symlink():
        try:
            if link.resolve() != napcat_dir.resolve():
                return False  # 指向别处（旧安装），交给 wire-qq.sh 纠正
        except OSError:
            return False
    import json  # noqa: PLC0415

    try:
        pkg = json.loads((qq_dir / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return pkg.get("main") == "./napcat/napcat.mjs"


def ensure_qq_wired() -> None:
    """Linux：检测到已安装 QQNT 但未接线时自动执行 wire-qq.sh。"""
    if sys.platform == "win32":
        return
    if not _env_flag("NAPCAT_AUTO_WIRE_QQ", True):
        return
    qq_dir = _find_qq_resources_dir()
    if qq_dir is None:
        qq_hint = os.environ.get("QQ_PATH") or "/opt/QQ/qq"
        _log("[!]", f"未检测到 Linux QQNT（默认路径 {qq_hint}）。")
        _log("    ", "请先安装 Linux 版 QQ（教程：docs/deploy-linux-native.md 第 2 步），")
        _log("    ", "或用 QQ_PATH / QQ_RESOURCES_DIR 环境变量指定路径后重启本项目。")
        return
    if _is_qq_wired(qq_dir, ROOT / "napcat"):
        return
    if not (_is_root() or os.access(qq_dir, os.W_OK)):
        _log("[!]", f"QQ 位于 {qq_dir}，当前用户无写入权限且非 root，跳过自动接线。")
        _log("    ", "请手动执行: sudo bash scripts/wire-qq.sh")
        return
    _log("[..]", f"检测到 QQ（{qq_dir}）尚未接入 NapCat，自动执行 scripts/wire-qq.sh ……")
    if subprocess.call(["bash", str(ROOT / "scripts" / "wire-qq.sh")]) != 0:
        _log("[!]", "QQ 接线失败。请手动执行后重试：")
        _log("    ", "sudo bash scripts/wire-qq.sh")
        raise SystemExit(1)


# ---------------------------------------------------------------- 4. 显示服务器
def hint_virtual_display() -> None:
    """无桌面服务器提醒安装 xvfb（QQ/Electron 需要）。"""
    if sys.platform == "win32" or os.environ.get("DISPLAY"):
        return
    from shutil import which  # noqa: PLC0415

    if which("xvfb-run"):
        return
    _log("[!]", "未检测到 DISPLAY 且未找到 xvfb-run——QQ 可能无法启动。")
    _log("    ", "服务器部署请安装: apt install xvfb（Debian/Ubuntu）")
    _log("    ", "                或 dnf install xorg-x11-server-Xvfb（RHEL 系）")


# ---------------------------------------------------------------- 入口
def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    print(BT_BANNER, flush=True)
    _log("[OK]", f"项目根目录: {ROOT}")
    _log("[OK]", f"Python {sys.version.split()[0]} ({sys.executable})")
    if Path("/www/server").is_dir():
        _log("[OK]", "检测到宝塔面板环境（/www/server）。")

    port = _extract_port_flag(sys.argv[1:])
    if port is not None:
        # main.py 的端口解析链：DASHBOARD_PORT 环境变量优先于其自身配置
        os.environ["DASHBOARD_PORT"] = str(port)
        _log("[OK]", f"统一网关端口: {port}")

    # --help/-h 直接透传给 main.py（不触发依赖安装等自举动作）
    if not any(a in ("-h", "--help") for a in sys.argv[1:]):
        ensure_python_deps()
        ensure_napcat_artifacts()
        ensure_qq_wired()
        hint_virtual_display()
        _log("[OK]", "自举完成，交棒统一入口 main.py ……\n")

    from main import main as stack_main  # noqa: PLC0415

    return stack_main()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[..] 收到 Ctrl+C，已退出。")
        sys.exit(0)
