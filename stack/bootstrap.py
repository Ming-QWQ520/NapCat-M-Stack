"""栈引导：目录准备、NapCat 预置配置、AstrBot 平台自动接线。

目标：「扫码 → 填 Key → 开聊」路径上的手工接线步骤全部归零。

- 预置 ``webui.json``：NapCat WebUI 只绑 127.0.0.1，端口确定化；登录凭证
  （账户 napcat + 初始密码）由 NapCat 启动时自动生成并输出到控制台
- 预置 ``onebot11.json``：新登录的 QQ 号自动继承「反向 WS → 本机 6199」
- AstrBot 侧自动创建 aiocqhttp(OneBot v11) 平台，监听 6199 等待 NapCat 回连
"""

from __future__ import annotations

import json
from pathlib import Path

from .settings import StackSettings


def seed_napcat_configs(settings: StackSettings) -> None:
    """写入 NapCat 预置配置。

    幂等：已存在的文件不覆盖（用户在 NapCat WebUI 里改过的配置优先）。
    登录密码不在此处预置——由 NapCat 首次启动时自动生成初始密码并
    打印到控制台（见 NapCat-M v4.18.43 的账户密码登录）。
    """
    config_dir = settings.napcat_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    # ---- webui.json：只绑本机，端口确定化 --------------------------------
    webui_json = config_dir / "webui.json"
    if not webui_json.is_file():
        data = {
            "host": "127.0.0.1",
            "port": settings.napcat_webui_port,
            "prefix": "",
            "username": "napcat",
            "loginRate": 3,
            "accessControlMode": "none",
            "ipWhitelist": [],
            "ipBlacklist": [],
            "enableXForwardedFor": False,
        }
        webui_json.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- onebot11.json：反向 WS 指向本机 AstrBot ------------------------
    onebot_json = config_dir / "onebot11.json"
    if not onebot_json.is_file():
        onebot_json.write_text(
            json.dumps(
                {
                    "network": {
                        "websocketClients": [
                            {
                                "name": "astrbot",
                                "enable": True,
                                "url": f"ws://127.0.0.1:{settings.onebot_ws_port}/ws",
                                "messagePostFormat": "array",
                                "reportSelfMessage": False,
                                "reconnectInterval": 5000,
                                "token": "",
                                "debug": False,
                                "heartInterval": 30000,
                            }
                        ]
                    },
                    "musicSignUrl": "",
                    "enableLocalFile2Url": True,
                    "parseMultMsg": False,
                    "imageDownloadProxy": "",
                    "timeout": {
                        "baseTimeout": 10000,
                        "uploadSpeedKBps": 256,
                        "downloadSpeedKBps": 256,
                        "maxTimeout": 1800000,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def wire_astrbot_platform(settings: StackSettings) -> bool:
    """在 AstrBot 配置中确保存在 aiocqhttp 平台（OneBot v11 反向 WS）。

    必须在 ``astrbot.core`` 导入之后、核心生命周期启动之前调用。

    Returns:
        是否新创建了平台配置。
    """
    from astrbot.core import astrbot_config  # noqa: PLC0415 延迟导入保证单例已就绪

    platforms = astrbot_config.get("platform", [])
    if any(p.get("type") == "aiocqhttp" for p in platforms):
        return False

    platforms.append(
        {
            "id": "napcat",
            "type": "aiocqhttp",
            "enable": True,
            "ws_reverse_host": "0.0.0.0",
            "ws_reverse_port": settings.onebot_ws_port,
            "ws_reverse_token": "",
        }
    )
    astrbot_config["platform"] = platforms
    astrbot_config.save_config()
    return True


def patch_deployed_webui(settings: StackSettings, *, quiet: bool = False) -> int:
    """定位并重写 NapCat WebUI 静态产物（Docker 预备产物 / Windows 安装器部署）。

    Returns:
        成功重写的 static 目录数量。
    """
    from . import webui_patch  # noqa: PLC0415

    candidates: list[Path] = []

    # 1) 栈内 napcat 产物（Linux/macOS 原生与 Docker 共用布局）
    if (settings.napcat_dir / "static" / "index.html").is_file():
        candidates.append(settings.napcat_dir / "static")

    # 2) 显式指定的 static 目录
    import os  # noqa: PLC0415

    explicit = os.environ.get("NAPCAT_STATIC_DIR", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if (p / "index.html").is_file():
            candidates.append(p)

    # 3) Windows：OneKey 安装器部署的可移植 QQ 树
    windows_dir = settings.root / "windows"
    if windows_dir.is_dir():
        for found in webui_patch.find_static_dirs(windows_dir):
            if found not in candidates:
                candidates.append(found)

    patched = 0
    for static_dir in candidates:
        report = webui_patch.patch_static_dir(static_dir)
        if report is None:
            continue
        if not quiet:
            if report.skipped_files:
                print(f"[OK] NapCat WebUI 已打过补丁: {static_dir}")
            else:
                print(
                    f"[OK] NapCat WebUI 子路径重写完成: {static_dir} "
                    f"({report.summary()})"
                )
                if report.leftovers:
                    for line in report.leftovers[:10]:
                        print(f"    残留: {line}")
        patched += 1
    return patched
