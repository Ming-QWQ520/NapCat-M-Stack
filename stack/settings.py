"""NapCat-M Stack 运行配置。

所有可调项均可用环境变量覆盖，默认值面向「一条命令直接跑起来」的场景。

端口布局（默认）::

    6185  统一网关（AstrBot WebUI 于 / ，NapCat WebUI 于 /napcat/）
    6199  AstrBot aiocqhttp 反向 WS 监听（仅本机 / 容器内访问）
    6099  NapCat WebUI 内部端口（只绑定 127.0.0.1，经网关代理暴露）

对 Docker 部署，只需对外暴露 6185。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class StackSettings:
    """栈级配置。"""

    # ---- 路径 -------------------------------------------------------------
    # 栈根目录（本文件所在目录的上一级）
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def astrbot_root(self) -> Path:
        """AstrBot 运行根目录（其 data/ 所在地）。"""
        return self.root

    @property
    def napcat_dir(self) -> Path:
        """NapCat-M Shell 产物目录（含 napcat.mjs / static/）。"""
        return Path(
            os.environ.get("NAPCAT_DIR", "")
            or self.root / "napcat"
        )

    @property
    def napcat_workdir(self) -> Path:
        """NapCat 写入目录（config/logs/plugins/cache）。

        通过 NAPCAT_WORKDIR 环境变量与子进程约定，保证预置配置的路径确定性。
        """
        return Path(
            os.environ.get("NAPCAT_WORKDIR", "")
            or self.root / "data" / "napcat"
        )

    @property
    def napcat_config_dir(self) -> Path:
        return self.napcat_workdir / "config"

    @property
    def data_dir(self) -> Path:
        """栈数据目录（同时也是 AstrBot 的 data/）。"""
        return self.astrbot_root / "data"

    # ---- 端口 -------------------------------------------------------------
    #: AstrBot 仪表盘 / 统一网关监听端口（AstrBot 侧仍可通过其自身配置覆盖）
    gateway_port: int = field(default_factory=lambda: _env_int("STACK_PORT", 6185))

    #: NapCat WebUI 内部端口（写入 webui.json，只绑 127.0.0.1）
    napcat_webui_port: int = field(default_factory=lambda: _env_int("NAPCAT_WEBUI_PORT", 6099))

    #: 端口被占用时 NapCat 会自动向后探测（最多 +100），网关会跟着发现
    napcat_webui_port_scan_range: int = 100

    #: AstrBot aiocqhttp 平台反向 WS 端口（预接线用）
    onebot_ws_port: int = field(default_factory=lambda: _env_int("STACK_ONEBOT_WS_PORT", 6199))

    # ---- NapCat 子进程 -----------------------------------------------------
    @property
    def napcat_account(self) -> str:
        return os.environ.get("ACCOUNT", "").strip()

    @property
    def napcat_qq_command(self) -> list[str] | None:
        """显式覆盖 QQ/NapCat 启动命令（空格分隔，支持引号包裹含空格路径）。"""
        raw = os.environ.get("NAPCAT_QQ_CMD", "").strip()
        if not raw:
            return None
        if sys.platform == "win32":
            # POSIX 模式的 shlex 会把反斜杠当转义符，吃掉 E:\... 风格路径；
            # Windows 下改用保反斜杠的切分，再剥掉成对引号
            import re

            tokens = re.findall(r'"[^"]*"|\S+', raw)
            return [
                t[1:-1] if len(t) > 1 and t.startswith('"') and t.endswith('"') else t
                for t in tokens
            ]
        import shlex

        return shlex.split(raw)

    @property
    def napcat_flavor(self) -> str:
        """Windows 部署形态偏好。

        - ``auto``（默认）：Node 便携版优先，回退 OneKey
        - ``node``：仅使用 Node 便携版（windows\\napcat-node\\node.exe）
        - ``onekey``：仅使用 OneKey 注入版（NapCatWinBootMain.exe）
        """
        value = os.environ.get("NAPCAT_FLAVOR", "auto").strip().lower()
        return value if value in ("auto", "node", "onekey") else "auto"

    # ---- 行为开关 -----------------------------------------------------------
    #: 首次启动自动在 AstrBot 中创建 aiocqhttp 平台（零接线）
    auto_wire_aiocqhttp: bool = field(
        default_factory=lambda: _env_bool("STACK_AUTO_WIRE", True)
    )

    #: NapCat 子进程退出后整个栈退出（由 docker restart / 用户重启兜底）
    exit_with_napcat: bool = field(
        default_factory=lambda: _env_bool("STACK_EXIT_WITH_NAPCAT", True)
    )


SETTINGS = StackSettings()
