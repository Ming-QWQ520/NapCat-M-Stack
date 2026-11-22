"""NapCat WebUI 模拟后端（仅用于集成测试）。

复刻真实 NapCat WebUI 后端的对外行为面（路径、响应形状、SSE、WS、重定向），
用于在无 QQ 的环境中端到端验证统一网关的 /napcat 代理。

用法：python tests/mock_napcat_webui.py [port]
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "napcat" / "static"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".json": "application/json",
}

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

#: 模拟后端的账户密码（对齐 NapCat-M v4.18.44 的账户密码登录）
MOCK_USERNAME = "napcat"
MOCK_PASSWORD = "mock1234"


def _password_hash(password: str) -> str:
    """对齐真实后端：SHA256(密码 + '.napcat')。"""
    return hashlib.sha256((password + ".napcat").encode()).hexdigest()


def _response(status: str, body: bytes, content_type: str, extra: str = "") -> bytes:
    head = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
    )
    if extra:
        head += extra + "\r\n"
    return head.encode() + b"\r\n" + body


def _json_response(payload, status: str = "200 OK") -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _response(status, body, "application/json")


def handle_http(method: str, path: str, query: str, headers: dict, body: bytes = b"") -> bytes | None:
    """返回完整响应字节；返回 None 表示挂起（SSE，由调用方处理）。"""
    if path == "/":
        return b"HTTP/1.1 301 Moved Permanently\r\nLocation: /webui\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"

    # 动态路由：SW 脚本（真实后端由 /webui/sw.js 动态生成）
    if path == "/webui/sw.js":
        sw = (STATIC_DIR / "sw_template.js")
        body = sw.read_bytes() if sw.is_file() else b"/* no-op */"
        return _response("200 OK", body, "application/javascript",
                         extra="Service-Worker-Allowed: /napcat/webui/\nCache-Control: no-cache")
    # 动态路由：主题 CSS
    if path == "/files/theme.css":
        return _response("200 OK", b":root{--font-family-base:system-ui}",
                         "text/css", extra="Cache-Control: no-cache")

    if path.startswith("/webui"):
        rel = path[len("/webui"):].lstrip("/") or "index.html"
        file = STATIC_DIR / rel
        if not file.is_file():
            file = STATIC_DIR / "index.html"  # SPA 兜底
        body = file.read_bytes()
        return _response(
            "200 OK", body, MIME.get(file.suffix, "application/octet-stream"),
            extra="Cache-Control: max-age=86400",
        )

    if path == "/api/auth/check":
        authed = bool(headers.get("authorization"))
        return _json_response({"code": 0, "message": "", "data": authed})
    if path == "/api/auth/login":
        # 对齐真实后端：{username, hash} → data.Credential 即后续 Bearer 令牌
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            payload = {}
        if (
            payload.get("username") == MOCK_USERNAME
            and payload.get("hash") == _password_hash(MOCK_PASSWORD)
        ):
            return _json_response(
                {
                    "code": 0,
                    "message": "",
                    "data": {"Credential": "mock-credential", "passwordChangeRequired": False},
                }
            )
        return _json_response(
            {"code": -1, "message": "username or password is invalid", "data": None}
        )
    if path == "/api/auth/update_password":
        # 对齐真实后端：{oldPassword, newPassword} → 新凭证
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            payload = {}
        if payload.get("oldPassword") == MOCK_PASSWORD and payload.get("newPassword"):
            return _json_response(
                {"code": 0, "message": "", "data": {"Credential": "mock-credential-2"}}
            )
        return _json_response({"code": -1, "message": "旧密码不匹配", "data": None})
    if path == "/api/Base/GetVersion":
        return _json_response(
            {"code": 0, "message": "", "data": {"version": "4.18.42-mock"}}
        )
    if path == "/api/Plugin":
        # 后端返回站内绝对路径 → 验证网关的 JSON 路径改写
        return _json_response(
            {
                "code": 0,
                "message": "",
                "data": [
                    {
                        "name": "demo",
                        "icon": "/api/Plugin/Icon/demo",
                        "page": "/plugin/demo/page/index",
                        "url": "https://example.com/untouched",
                    }
                ],
            }
        )
    if path == "/api/Log/GetLogRealTime":
        return None  # SSE，由调用方流式处理
    return _json_response({"code": 0, "message": "", "data": None})


async def serve_sse(writer: asyncio.StreamWriter) -> None:
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n"
    )
    await writer.drain()
    for i in range(5):
        await asyncio.sleep(0.15)
        payload = json.dumps({"level": "info", "message": f"log line {i}"})
        writer.write(f"data: {payload}\n\n".encode())
        await writer.drain()


async def serve_ws(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """极简 WebSocket echo（含 ping/pong）。"""
    try:
        while True:
            header = await reader.readexactly(2)
            opcode = header[0] & 0x0F
            length = header[1] & 0x7F
            masked = header[1] & 0x80
            if length == 126:
                length = int.from_bytes(await reader.readexactly(2), "big")
            elif length == 127:
                length = int.from_bytes(await reader.readexactly(8), "big")
            mask = await reader.readexactly(4) if masked else b""
            payload = await reader.readexactly(length)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:  # close
                return
            if opcode == 9:  # ping
                writer.write(bytes([0x8A, len(payload)]) + payload)
                await writer.drain()
                continue
            if opcode != 1:  # 只处理文本帧
                continue
            reply = f"echo: {payload.decode('utf-8', errors='replace')}".encode()
            frame = bytes([0x81])
            if len(reply) < 126:
                frame += bytes([len(reply)])
            else:
                frame += bytes([126]) + len(reply).to_bytes(2, "big")
            writer.write(frame + reply)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass


async def handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        # keep-alive 请求循环（贴近 Express 默认行为）
        while True:
            first = await reader.readline()
            if not first:
                return
            parts = first.decode().split(" ")
            if len(parts) < 3:
                return
            method, target = parts[0], parts[1]
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                key, _, value = line.decode(errors="replace").partition(":")
                headers[key.strip().lower()] = value.strip()

            path, _, query = target.partition("?")
            print(f"[mock] {method} {target}")

            # 读取请求体（登录/改密等 POST 需要）
            body = b""
            try:
                content_length = int(headers.get("content-length", "0") or "0")
            except ValueError:
                content_length = 0
            if content_length > 0:
                body = await reader.readexactly(content_length)

            if headers.get("upgrade", "").lower() == "websocket":
                accept = base64.b64encode(
                    hashlib.sha1(
                        (headers.get("sec-websocket-key", "") + _WS_GUID).encode()
                    ).digest()
                ).decode()
                writer.write(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                    ).encode()
                )
                await writer.drain()
                await serve_ws(reader, writer)
                return

            keep_alive = headers.get("connection", "").lower() != "close"

            def respond(payload: bytes) -> None:
                writer.write(payload)

            response = handle_http(method, path, query, headers, body)
            if response is None:
                await serve_sse(writer)
            else:
                respond(response)
                await writer.drain()
            if not keep_alive:
                return
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        return
    except Exception as e:  # noqa: BLE001
        print(f"[mock] connection error: {e!r}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6099
    server = await asyncio.start_server(handle_connection, "127.0.0.1", port)
    print(f"[mock] NapCat WebUI 模拟后端已启动: http://127.0.0.1:{port}")
    print("[NapCat] [WebUi] WebUI 已启用账户密码登录")
    print(f"[NapCat] [WebUi] 初始账户: {MOCK_USERNAME}")
    print(f"[NapCat] [WebUi] 初始密码: {MOCK_PASSWORD}")
    print(f"[NapCat] [WebUi] WebUi User Panel Url: http://127.0.0.1:{port}/webui")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
