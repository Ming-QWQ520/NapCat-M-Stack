"""NapCat WebUI 与 AstrBot 共用密码（以 AstrBot 为准）。

背景：NapCat WebUI 与 AstrBot 仪表盘各有一套账户密码，用户要记两份、
翻两次日志。本模块让 **AstrBot 的密码成为唯一权威**：

- AstrBot 登录 / 初始化 / 改密成功时，``SharedPasswordMiddleware`` 捕获
  请求中的明文密码（仅在进程内短暂存在），写入 NapCat 的 ``webui.json``
- NapCat 侧（v4.18.45+）检测到 ``NAPCAT_SHARED_PASSWORD=1`` 后会在每次
  登录前重读该文件，AstrBot 改密无需重启 NapCat 即可生效
- 首次启动 / ``--reset-password`` 后，AstrBot 生成的初始密码会立刻同步
  给 NapCat（读取其内存属性 ``_generated_dashboard_password``）

关闭方式：环境变量 ``STACK_SHARED_PASSWORD=0``（恢复 NapCat 自管密码，
需 NapCat 侧产物 v4.18.45+ 才能识别共享模式；旧产物只是忽略该环境变量）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .settings import NAPCAT_SHARED_PASSWORD_ENV, StackSettings

#: AstrBot 鉴权端点 -> 请求体中携带密码的字段名
#:（均为 legacy_router，前缀 /api/auth；成功响应体 status == "ok"）
_WATCHED_FIELDS: dict[tuple[str, str], str] = {
    ("POST", "/api/auth/login"): "password",
    ("POST", "/api/auth/setup"): "password",
    ("POST", "/api/auth/setup-authenticated"): "password",
    ("POST", "/api/auth/account/edit"): "new_password",
}


def _webui_json_path(settings: StackSettings) -> Path:
    return settings.napcat_config_dir / "webui.json"


def sync_password_to_napcat(password: str, settings: StackSettings) -> bool:
    """把明文密码写入 NapCat 的 webui.json（合并保留其余字段）。

    Returns:
        密码是否有变化（True 表示已写入新值）。
    """
    if not password:
        return False
    path = _webui_json_path(settings)
    data: dict[str, Any] = {}
    try:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
    except (OSError, ValueError):
        data = {}

    if data.get("password") == password and not data.get("passwordChangeRequired"):
        return False

    data["password"] = password
    data["passwordChangeRequired"] = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        print(f"[!] 写入 NapCat webui.json 失败（共用密码未同步）: {e}")
        return False
    try:
        # webui.json 内含明文密码，收紧权限（与 NapCat 自身存储姿态一致）
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def sync_initial_password(settings: StackSettings) -> bool:
    """首启 / 重置密码后：把 AstrBot 生成的初始密码同步给 NapCat。

    必须在 ``astrbot.core`` 导入之后、AstrBotDashboard 启动打印（该属性
    随打印被清空）之前调用。
    """
    try:
        from astrbot.core import astrbot_config  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return False
    generated = getattr(astrbot_config, "_generated_dashboard_password", None)
    if not isinstance(generated, str) or not generated:
        return False
    return sync_password_to_napcat(generated, settings)


class SharedPasswordMiddleware:
    """纯 ASGI 中间件：AstrBot 鉴权成功时把密码同步给 NapCat WebUI。

    实现要点：

    - 只观察 :data:`_WATCHED_FIELDS` 中的端点，其余请求零开销直通
    - 请求体缓冲后重放给下游路由（content-length 不变，透传无感）
    - 响应体只收集不修改；HTTP 200 且 JSON ``status == "ok"`` 才同步
      （AstrBot 的 ``AuthServiceResult`` 失败时也可能返回 HTTP 200）
    - 同步失败只打日志，绝不影响 AstrBot 自身登录
    """

    def __init__(self, app, settings: StackSettings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        field = (
            _WATCHED_FIELDS.get(
                (str(scope.get("method", "")).upper(), str(scope.get("path", "")))
            )
            if scope.get("type") == "http"
            else None
        )
        if field is None or not self.settings.shared_password:
            await self.app(scope, receive, send)
            return

        # ---- 缓存请求体（下游路由仍要读，需重放） ----------------------
        buffered: list[dict] = []
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] == "http.disconnect":
                await self.app(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        raw_body = b"".join(m.get("body", b"") for m in buffered)

        password = ""
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            if isinstance(payload, dict):
                value = payload.get(field)
                if isinstance(value, str):
                    password = value
        except (ValueError, UnicodeDecodeError):
            password = ""

        replay = self._replay(buffered, receive)

        async def replay_receive() -> dict:
            return await replay.__anext__()

        status_code: list[int] = []
        response_chunks: list[bytes] = []

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_code.append(int(message.get("status", 0)))
            elif message["type"] == "http.response.body" and message.get("body"):
                response_chunks.append(bytes(message["body"]))
            await send(message)

        try:
            await self.app(scope, replay_receive, send_wrapper)
        finally:
            self._maybe_sync(password, status_code, response_chunks)

    def _maybe_sync(
        self, password: str, status_code: list[int], chunks: list[bytes]
    ) -> None:
        if not password:
            return
        if not status_code or status_code[0] != 200:
            return
        try:
            payload = json.loads(b"".join(chunks).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not (isinstance(payload, dict) and payload.get("status") == "ok"):
            return
        try:
            if sync_password_to_napcat(password, self.settings):
                print(
                    "[OK] 已把 AstrBot 密码同步给 NapCat WebUI"
                    "（/ 与 /napcat 共用同一密码，账户 napcat）"
                )
        except Exception:  # noqa: BLE001
            print("[!] 同步 AstrBot 密码到 NapCat 失败（不影响 AstrBot 登录）")

    @staticmethod
    def _replay(buffered: list[dict], receive):  # noqa: ANN001, ANN202
        async def gen():
            for message in buffered:
                yield message
            while True:
                yield await receive()

        return gen()


def mount_shared_password_sync(app, settings: StackSettings) -> bool:
    """把密码同步中间件挂进 AstrBot 仪表盘应用（幂等）。

    Returns:
        是否实际挂载（关闭共用密码时返回 False）。
    """
    if not settings.shared_password:
        return False
    for middleware in getattr(app, "user_middleware", []) or []:
        if getattr(middleware, "cls", None) is SharedPasswordMiddleware:
            return False
    try:
        app.add_middleware(SharedPasswordMiddleware, settings=settings)
    except Exception as e:  # noqa: BLE001
        print(f"[!] 挂载共用密码中间件失败: {e}")
        return False
    return True
