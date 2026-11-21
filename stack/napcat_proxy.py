"""``/napcat`` 反向代理：让 NapCat WebUI 与 AstrBot 共用同一端口。

网关把 ``/napcat/<path>`` 剥前缀后转发给只监听 127.0.0.1 的 NapCat WebUI 后端：

- HTTP：全方法转发，请求/响应体流式透传（SSE 长连接友好）
- WebSocket：终端 (``/api/ws/terminal``) 与调试 (``/api/Debug/ws``) 双向泵
- JSON 响应体路径改写：后端返回的 ``/api/...``、``/plugin/...`` 等绝对路径
  字符串统一加上 ``/napcat`` 前缀（如插件图标 URL）
- ``Location`` 重定向头改写（``/`` → ``/webui`` → ``/napcat/webui``）
- NapCat 未就绪时返回 503（API 走 NapCat 风格 JSON，页面走可自动刷新的 HTML）
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .napcat_process import NapCatSupervisor
from .settings import StackSettings
from .webui_patch import MOUNT_PREFIX

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "accept-encoding",
}

_RESPONSE_STRIP = _HOP_BY_HOP | {"content-encoding", "date", "server"}

_REWRITABLE_PREFIXES = ("/api/", "/webui/", "/files/", "/plugin/")

_NOT_READY_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NapCat 启动中 · NapCat-M Stack</title>
<meta http-equiv="refresh" content="5">
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
background:#101319;color:#e6e9ef}
main{width:min(100%,560px);padding:36px;background:#171b23;border:1px solid #262c38;border-radius:16px;text-align:center}
.dot{width:14px;height:14px;margin:0 auto 18px;border-radius:50%;background:#f5b942;
box-shadow:0 0 0 0 rgba(245,185,66,.6);animation:p 1.4s infinite}
@keyframes p{70%{box-shadow:0 0 0 14px rgba(245,185,66,0)}100%{box-shadow:0 0 0 0 rgba(245,185,66,0)}}
h1{margin:0 0 10px;font-size:20px}
p{margin:0 0 8px;color:#9aa4b6;font-size:14px;line-height:1.8}
code{padding:2px 6px;background:#1f2530;border-radius:6px;color:#7ec7ff;font-size:13px}
a{color:#7ec7ff;text-decoration:none}
</style>
</head>
<body><main>
<div class="dot"></div>
<h1>NapCat 正在启动</h1>
<p>QQ 与 NapCat WebUI 还在初始化，本页将每 5 秒自动重试。</p>
<p>若长时间停留在此页，请回看启动日志中 <code>[NapCat]</code> 前缀的输出，或重启整个栈。</p>
<p><a href="/">← 返回 AstrBot 控制台</a></p>
</main></body></html>"""


def _rewrite_location(location: str) -> str:
    for prefix in ("/webui", "/api", "/files", "/plugin"):
        if location == prefix or location.startswith(prefix + "/") or location.startswith(prefix + "?"):
            return MOUNT_PREFIX + location
    return location


def _scoped_path(scope: dict) -> str:
    """计算子应用内的相对路径（剥去 Mount 前缀）。

    Starlette 的 Mount 会把前缀写入 ``root_path``，但部分版本下
    ``scope["path"]`` 仍是完整路径，必须显式剥高，否则代理会转发到
    错误的子路径。
    """
    raw_path = scope.get("path", "/") or "/"
    root_path = scope.get("root_path", "") or ""
    if root_path and raw_path.startswith(root_path):
        path = raw_path[len(root_path):]
    else:
        path = raw_path
    if not path.startswith("/"):
        path = "/" + path
    return path


def _rewrite_json_paths(obj: Any) -> Any:
    """递归改写 JSON 中的站内绝对路径字符串。"""
    if isinstance(obj, str):
        if obj.startswith(MOUNT_PREFIX):
            return obj
        for prefix in _REWRITABLE_PREFIXES:
            if obj.startswith(prefix):
                return MOUNT_PREFIX + obj
        return obj
    if isinstance(obj, list):
        return [_rewrite_json_paths(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _rewrite_json_paths(value) for key, value in obj.items()}
    return obj


class NapCatProxy:
    """绑定到一个 NapCatSupervisor 的反向代理应用。"""

    def __init__(self, supervisor: NapCatSupervisor, settings: StackSettings) -> None:
        self.supervisor = supervisor
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url="http://127.0.0.1",
            timeout=httpx.Timeout(connect=5.0, read=None, write=60.0, pool=10.0),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )

    # ------------------------------------------------------------------ app
    def build_app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/", self.entry, methods=["GET"]),
                Route("/healthz", self.healthz, methods=["GET"]),
                WebSocketRoute("/{path:path}", self.ws_proxy),
                Route("/{path:path}", self.http_proxy, methods=[
                    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS",
                ]),
            ]
        )

    # --------------------------------------------------------------- handlers
    async def entry(self, request: Request) -> Response:
        return RedirectResponse(f"{MOUNT_PREFIX}/webui/", status_code=307)

    async def healthz(self, request: Request) -> Response:
        return JSONResponse(
            {
                "running": self.supervisor.is_running,
                "ready": self.supervisor._ready_event.is_set(),
                "port": self.supervisor.port,
            }
        )

    async def _not_ready_response(self, path: str) -> Response:
        message = "NapCat WebUI 尚未就绪（QQ 启动中或已退出），请稍后重试。"
        if path.startswith("/api"):
            return JSONResponse(
                {"code": -1, "message": message, "data": None}, status_code=503
            )
        return HTMLResponse(_NOT_READY_HTML, status_code=503)

    async def http_proxy(self, request: Request) -> Response:
        path = _scoped_path(request.scope)
        if not self.supervisor.is_running or self.supervisor.port is None:
            # 快速等待一次，覆盖「请求先于发现到达」的窗口期
            try:
                await self.supervisor.ensure_ready(timeout=float(
                    request.headers.get("x-stack-wait-ready", "8")
                ))
            except Exception:
                return await self._not_ready_response(path)

        port = self.supervisor.port
        url = f"http://127.0.0.1:{port}{path}"
        if request.url.query:
            url += "?" + request.url.query

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _HOP_BY_HOP
        }
        headers["accept-encoding"] = "identity"
        headers.setdefault("x-forwarded-host", request.headers.get("host", ""))

        req = self.client.build_request(
            request.method,
            url,
            headers=headers,
            content=request.stream(),
        )
        try:
            backend_resp = await self.client.send(req, stream=True)
        except httpx.HTTPError as e:
            message = f"连接 NapCat WebUI 失败: {e.__class__.__name__}"
            if path.startswith("/api"):
                return JSONResponse(
                    {"code": -1, "message": message, "data": None}, status_code=502
                )
            return HTMLResponse(
                _NOT_READY_HTML.replace("NapCat 正在启动", "无法连接 NapCat"),
                status_code=502,
            )

        content_type = backend_resp.headers.get("content-type", "")
        resp_headers = [
            (key, _rewrite_location(value) if key.lower() == "location" else value)
            for key, value in backend_resp.headers.items()
            if key.lower() not in _RESPONSE_STRIP
        ]

        # JSON：缓冲 + 站内路径改写（插件图标、插件页面等由后端拼接的路径）
        if "application/json" in content_type:
            body = await backend_resp.aread()
            await backend_resp.aclose()
            try:
                data = json.loads(body)
                rewritten = json.dumps(
                    _rewrite_json_paths(data), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            except (ValueError, UnicodeDecodeError):
                rewritten = body
            return Response(
                content=rewritten,
                status_code=backend_resp.status_code,
                headers=dict(resp_headers),
                media_type=content_type or None,
            )

        # 其余（含 SSE / 静态资源 / 下载）：流式透传
        async def stream_body():
            try:
                async for chunk in backend_resp.aiter_raw():
                    yield chunk
            finally:
                await backend_resp.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=backend_resp.status_code,
            headers=dict(resp_headers),
            background=None,
        )

    async def ws_proxy(self, websocket: WebSocket) -> None:
        path = _scoped_path(websocket.scope)
        query = websocket.query_params

        await websocket.accept()
        if not self.supervisor.is_running or self.supervisor.port is None:
            await websocket.close(code=1011, reason="NapCat WebUI not ready")
            return

        from websockets.asyncio.client import connect as ws_connect  # noqa: PLC0415

        port = self.supervisor.port
        backend_url = f"ws://127.0.0.1:{port}{path}"
        if query:
            from urllib.parse import urlencode  # noqa: PLC0415

            backend_url += "?" + urlencode(list(query.multi_items()))

        extra_headers = {}
        auth = websocket.headers.get("authorization")
        if auth:
            extra_headers["Authorization"] = auth

        try:
            backend = await ws_connect(
                backend_url,
                additional_headers=extra_headers,
                open_timeout=10,
                max_size=None,
            )
        except Exception:
            await websocket.close(code=1011, reason="Cannot reach NapCat backend")
            return

        async def pump_up():
            try:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if "text" in message and message["text"] is not None:
                        await backend.send(message["text"])
                    elif "bytes" in message and message["bytes"] is not None:
                        await backend.send(message["bytes"])
            except WebSocketDisconnect:
                return

        async def pump_down():
            try:
                async for message in backend:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)
            except Exception:
                return

        try:
            _, pending = await asyncio.wait(
                [asyncio.create_task(pump_up()), asyncio.create_task(pump_down())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        finally:
            try:
                await backend.close()
            except Exception:
                pass


def mount_napcat_proxy(
    app, supervisor: NapCatSupervisor, settings: StackSettings
) -> Starlette:
    """把 /napcat 代理挂到 AstrBot 的 FastAPI 应用上（插到路由表最前）。

    必须插到最前：AstrBot 的静态资源路由含 ``/{path:path}`` 兜底，
    常规 ``include_router`` 会被它抢先吞掉。另补一条无斜杠入口路由
    （Starlette 的 Mount 不匹配 ``/napcat`` 精确路径）。
    """
    proxy = NapCatProxy(supervisor, settings)
    sub_app = proxy.build_app()
    from starlette.routing import Mount, Route  # noqa: PLC0415

    async def _entry(request: Request) -> Response:
        return RedirectResponse(f"{MOUNT_PREFIX}/webui/", status_code=307)

    app.router.routes.insert(0, Mount(MOUNT_PREFIX, app=sub_app))
    app.router.routes.insert(0, Route(MOUNT_PREFIX, _entry, methods=["GET"]))
    app.state.napcat_proxy = proxy
    return sub_app
