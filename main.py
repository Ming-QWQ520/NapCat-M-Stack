"""NapCat-M Stack 统一入口。

一条命令同时拉起整栈::

    python main.py            # Linux / macOS / Windows / Docker 容器入口

进程树（单根）::

    python main.py                       ← 唯一主进程
    ├── AstrBot 核心 + 仪表盘            ← 进程内直接运行（非子进程调用）
    │   └── 统一网关 :6185
    │       ├── /             AstrBot WebUI
    │       └── /napcat/...   NapCat WebUI（反向代理到 127.0.0.1:6099）
    └── QQ（内嵌 NapCat-M）             ← 受监督子进程
        └── 反向 WS → 127.0.0.1:6199 → AstrBot aiocqhttp 平台

首次启动自动完成全部接线：AstrBot 平台创建、NapCat 反向 WS 预配置、
WebUI 静态资源子路径重写，扫码后即可直接使用。
"""

from __future__ import annotations

import argparse
import asyncio
import mimetypes
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# runtime_bootstrap 必须先于 astrbot 的一切导入（SSL/CA 补丁）
sys.path.insert(0, str(ROOT))
import runtime_bootstrap  # noqa: E402

runtime_bootstrap.initialize_runtime_bootstrap()

DASHBOARD_RESET_PASSWORD_ENV = "ASTRBOT_RESET_DASHBOARD_PASSWORD"

STACK_BANNER = r"""
 _   _  _____  _  ___  __     __ _______ _   _  ____  _  _______ ____
| \ | || ____|| |/ _ \ \ \   / /| ____| \ | |/ ___|| |/ / ____|  _ \
|  \| ||  _|  | | | | | \ \ / / |  _|  |  \| |\___ \| ' /|  _| | |_) |
| |\  || |___ | | |_| |  \ V /  | |___ | |\  | ___) | . \| |___|  _ <
|_| \_||_____||_|\___/    \_/   |_____||_| \_||____/|_|\_\_____|_| \_\
        NapCat-M + AstrBot · 单进程树 · 单命令 · 单端口
"""


def _apply_startup_env_flags(argv: list[str]) -> None:
    """与上游 AstrBot main.py 保持一致的启动旗标处理。"""
    if "-h" in argv or "--help" in argv:
        return
    startup_parser = argparse.ArgumentParser(add_help=False)
    startup_parser.add_argument("--reset-password", action="store_true")
    startup_args, _ = startup_parser.parse_known_args(argv)
    if startup_args.reset_password:
        os.environ[DASHBOARD_RESET_PASSWORD_ENV] = "1"


def _prepare_environment() -> None:
    """导入 astrbot 前必须完成的路径与环境准备。"""
    os.environ.setdefault("ASTRBOT_ROOT", str(ROOT))
    os.makedirs(ROOT / "data", exist_ok=True)


def _check_env() -> None:
    if not (sys.version_info.major == 3 and sys.version_info.minor >= 10):
        print("请使用 Python 3.10+ 运行本项目。")
        sys.exit(1)
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("application/json", ".json")


async def check_dashboard_files(webui_dir: str | None = None) -> str | None:
    """解析/修复 AstrBot 仪表盘静态文件（逻辑对齐上游 main.py）。"""
    from astrbot.core import logger  # noqa: PLC0415
    from astrbot.core.dashboard_assets import resolve_dashboard_dist  # noqa: PLC0415
    from astrbot.core.updater import AstrBotUpdater  # noqa: PLC0415

    if webui_dir:
        if os.path.exists(webui_dir):
            resolved = resolve_dashboard_dist(webui_dir)
            if resolved is not None:
                logger.info("Using WebUI directory: %s", resolved)
                return str(resolved)
            logger.warning("WebUI 目录不兼容，尝试修复: %s", webui_dir)
        else:
            logger.warning("WebUI 目录不存在: %s，使用默认。", webui_dir)

    try:
        await AstrBotUpdater().ensure_dashboard()
    except Exception as e:  # noqa: BLE001
        logger.critical(f"下载仪表盘文件失败: {e}")
        return None

    resolved = resolve_dashboard_dist()
    if resolved is None:
        logger.critical("仪表盘文件与当前核心版本不兼容。")
        return None
    return str(resolved)


def _effective_gateway_port() -> int:
    """统一网关实际监听端口（与 AstrBotDashboard.run 的解析链一致）。"""
    for env_name in ("DASHBOARD_PORT", "ASTRBOT_DASHBOARD_PORT"):
        raw = os.environ.get(env_name)
        if raw:
            try:
                return int(raw)
            except ValueError:
                break
    try:
        from astrbot.core import astrbot_config  # noqa: PLC0415

        return int(astrbot_config.get("dashboard", {}).get("port", 6185))
    except Exception:  # noqa: BLE001
        return 6185


async def amain(args: argparse.Namespace) -> int:
    from stack.bootstrap import (  # noqa: PLC0415
        patch_deployed_webui,
        seed_napcat_configs,
        wire_astrbot_platform,
    )
    from stack.napcat_process import NapCatSupervisor  # noqa: PLC0415
    from stack.napcat_proxy import mount_napcat_proxy  # noqa: PLC0415
    from stack.settings import SETTINGS  # noqa: PLC0415

    print(STACK_BANNER)

    # 停机信号（提前创建：子进程退出回调可能在启动早期就触发）
    stop_event = asyncio.Event()

    # ---- 1. 栈引导：预置配置 + WebUI 产物子路径重写 -----------------------
    seed_napcat_configs(SETTINGS)
    patch_deployed_webui(SETTINGS)

    # ---- 2. 拉起 QQ(NapCat) 子进程（与 AstrBot 初始化并行） ---------------
    supervisor = NapCatSupervisor(SETTINGS)

    def _on_napcat_exit(code: int) -> None:
        if SETTINGS.exit_with_napcat and not stop_event.is_set():
            print(f"[!] NapCat 子进程退出 (code={code})，整栈即将停止。")
            stop_event.set()

    supervisor.on_exit(_on_napcat_exit)

    try:
        await supervisor.start()
    except Exception as e:  # noqa: BLE001
        print(f"[!] NapCat 子进程启动失败: {e}")
        return 1

    async def log_napcat_ready() -> None:
        try:
            port = await supervisor.wait_ready(timeout=300)
        except Exception:  # noqa: BLE001
            return
        gateway_port = _effective_gateway_port()
        if SETTINGS.shared_napcat_password:
            password_hint = "   ➜  登录账户 napcat，密码与 AstrBot 仪表盘一致（以 AstrBot 为准）"
        else:
            password_hint = "   ➜  登录账户 napcat，初始密码见上方 [NapCat] 启动日志（首次登录后需修改）"
        print(
            "\n ✨ NapCat WebUI 已接入统一网关\n"
            f"   ➜  http://127.0.0.1:{gateway_port}/napcat/webui/\n"
            f"{password_hint}\n"
            f"   ➜  内部端口 127.0.0.1:{port}（仅本机，经 /napcat 代理对外）\n"
        )

    ready_log_task = asyncio.create_task(log_napcat_ready())

    # ---- 3. 导入 AstrBot（此前的环境变量决定其数据目录） -------------------
    from astrbot.core import LogBroker, LogManager, db_helper, logger  # noqa: PLC0415
    from astrbot.core.core_lifecycle import AstrBotCoreLifecycle  # noqa: PLC0415
    from astrbot.dashboard.server import AstrBotDashboard  # noqa: PLC0415

    # 零接线：自动创建 OneBot v11 平台等待 NapCat 回连
    if SETTINGS.auto_wire_aiocqhttp:
        try:
            if wire_astrbot_platform(SETTINGS):
                logger.info(
                    "已自动创建 aiocqhttp(OneBot v11) 平台，监听 "
                    "0.0.0.0:%s 等待 NapCat 反向 WS 接入。",
                    SETTINGS.onebot_ws_port,
                )
        except Exception:  # noqa: BLE001
            logger.exception("自动创建 aiocqhttp 平台失败，请稍后在 WebUI 手动创建。")

    log_broker = LogBroker()
    LogManager.set_queue_handler(logger, log_broker)

    webui_dir = await check_dashboard_files(args.webui_dir)
    if webui_dir is None:
        logger.warning("仪表盘文件不可用，WebUI 功能将被禁用（其余功能不受影响）。")

    core_lifecycle = AstrBotCoreLifecycle(log_broker, db_helper)

    try:
        await core_lifecycle.initialize()
    except Exception as e:  # noqa: BLE001
        logger.critical(f"AstrBot 核心初始化失败: {e}")
        import traceback  # noqa: PLC0415

        logger.critical(traceback.format_exc())
        await supervisor.stop()
        return 1

    core_task = asyncio.create_task(core_lifecycle.start())

    dashboard = AstrBotDashboard(
        core_lifecycle,
        db_helper,
        core_lifecycle.dashboard_shutdown_event,
        webui_dir,
    )

    # 关键：把 /napcat 代理挂进同一个 FastAPI 应用 —— 两套 WebUI 同端口
    mount_napcat_proxy(dashboard.asgi_app, supervisor, SETTINGS)

    dashboard_coro = dashboard.run()
    tasks: list[asyncio.Task] = [core_task]
    server_task: asyncio.Task | None = None
    if dashboard_coro is not None:
        server_task = asyncio.create_task(dashboard_coro)
        tasks.append(server_task)

    logger.info(
        "统一网关: http://0.0.0.0:%s  （AstrBot 于 / ，NapCat 于 /napcat/）",
        _effective_gateway_port(),
    )

    # ---- 4. 停机信号 ------------------------------------------------------
    def _request_stop() -> None:
        if not stop_event.is_set():
            print("\n[..] 收到停机信号，正在优雅退出……")
            stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _request_stop)
    else:  # pragma: no cover - Windows
        signal.signal(signal.SIGTERM, lambda *_: _request_stop())
        signal.signal(signal.SIGINT, lambda *_: _request_stop())

    stop_watcher = asyncio.create_task(stop_event.wait())

    # ---- 5. 运行至任一终结条件（核心/服务器异常退出、停机信号、NapCat 退出）
    try:
        await asyncio.wait([*tasks, stop_watcher], return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        pass

    # ---- 6. 收尾 ----------------------------------------------------------
    stop_event.set()
    if server_task and not server_task.done():
        core_lifecycle.dashboard_shutdown_event.set()
    for task in (ready_log_task, *tasks, stop_watcher):
        if not task.done():
            task.cancel()
    await asyncio.gather(ready_log_task, *tasks, return_exceptions=True)

    try:
        await asyncio.wait_for(core_lifecycle.stop(), timeout=15)
    except Exception:  # noqa: BLE001
        pass
    await supervisor.stop()
    print("[OK] NapCat-M Stack 已退出。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="napcat-m-stack", description="NapCat-M + AstrBot 一体化栈"
    )
    parser.add_argument(
        "--webui-dir",
        type=str,
        default=None,
        help="AstrBot 仪表盘静态文件目录（默认自动解析/下载）",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="重置仪表盘初始密码并打印在启动日志中",
    )
    args = parser.parse_args()

    _apply_startup_env_flags(sys.argv[1:])
    _prepare_environment()
    _check_env()

    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
