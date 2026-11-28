"""共用密码（stack/shared_password.py）单元测试。

覆盖：
- sync_password_to_napcat 的写入/幂等/字段保留
- SharedPasswordMiddleware：登录/改密成功同步、失败不同步、
  请求体对下游路由完全透传、非关注端点零干扰
- mount_shared_password_sync 幂等与开关
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from stack.settings import StackSettings, shared_password_enabled  # noqa: E402
from stack.shared_password import (  # noqa: E402
    NAPCAT_SHARED_PASSWORD_ENV,
    SharedPasswordMiddleware,
    mount_shared_password_sync,
    sync_password_to_napcat,
)


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("NAPCAT_WORKDIR", str(tmp_path / "napcat"))
    monkeypatch.delenv("STACK_SHARED_PASSWORD", raising=False)
    return StackSettings()


def _read_webui(settings) -> dict:
    path = settings.napcat_config_dir / "webui.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 同步函数
def test_sync_writes_password_and_clears_flag(settings):
    assert sync_password_to_napcat("abc123XYZ", settings) is True
    data = _read_webui(settings)
    assert data["password"] == "abc123XYZ"
    assert data["passwordChangeRequired"] is False


def test_sync_preserves_other_fields(settings):
    path = settings.napcat_config_dir / "webui.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"host": "127.0.0.1", "port": 6099, "username": "napcat", "token": "x"}
        ),
        encoding="utf-8",
    )
    assert sync_password_to_napcat("pw1", settings) is True
    data = _read_webui(settings)
    assert data["host"] == "127.0.0.1"
    assert data["username"] == "napcat"
    assert data["password"] == "pw1"


def test_sync_idempotent(settings):
    assert sync_password_to_napcat("same1", settings) is True
    assert sync_password_to_napcat("same1", settings) is False


def test_sync_rejects_empty(settings):
    assert sync_password_to_napcat("", settings) is False
    assert not (settings.napcat_config_dir / "webui.json").exists()


def test_sync_updates_existing_password(settings):
    sync_password_to_napcat("oldpw", settings)
    assert sync_password_to_napcat("newpw", settings) is True
    assert _read_webui(settings)["password"] == "newpw"


# ------------------------------------------------------------------ 开关
def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv("STACK_SHARED_PASSWORD", raising=False)
    assert shared_password_enabled() is True
    assert StackSettings().shared_password is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_disable_switch(monkeypatch, value):
    monkeypatch.setenv("STACK_SHARED_PASSWORD", value)
    assert shared_password_enabled() is False
    assert StackSettings().shared_password is False


# ------------------------------------------------------------------ 中间件
def _build_app(settings) -> FastAPI:
    app = FastAPI()

    @app.post("/api/auth/login")
    async def login(request: Request):
        body = await request.json()
        if body.get("password") == "right-pass":
            return JSONResponse({"status": "ok", "data": {"token": "t"}})
        return JSONResponse(
            {"status": "error", "message": "用户名或密码错误"}, status_code=401
        )

    @app.post("/api/auth/account/edit")
    async def edit_account(request: Request):
        body = await request.json()
        return JSONResponse({"status": "ok", "data": {}})

    @app.post("/api/echo")
    async def echo(request: Request):
        body = await request.body()
        return JSONResponse({"status": "ok", "data": {"len": len(body)}})

    mount_shared_password_sync(app, settings)
    return app


def test_middleware_syncs_successful_login(settings):
    app = _build_app(settings)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "astrbot", "password": "right-pass"}
    )
    assert resp.status_code == 200
    assert _read_webui(settings)["password"] == "right-pass"


def test_middleware_ignores_failed_login(settings):
    app = _build_app(settings)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "astrbot", "password": "wrong-pass"}
    )
    assert resp.status_code == 401
    assert not (settings.napcat_config_dir / "webui.json").exists()


def test_middleware_ignores_error_payload_with_http200(settings):
    """AstrBot 的 AuthServiceResult 失败时也可能返回 HTTP 200，不能误同步。"""
    app = _build_app(settings)

    @app.post("/api/auth/setup")
    async def setup(request: Request):
        await request.json()
        return JSONResponse({"status": "error", "message": "Invalid request payload"})

    mount_shared_password_sync(app, settings)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/setup", json={"username": "u", "password": "some-pass"}
    )
    assert resp.status_code == 200
    assert not (settings.napcat_config_dir / "webui.json").exists()


def test_middleware_syncs_account_edit_new_password(settings):
    app = _build_app(settings)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/account/edit",
        json={"password": "old", "new_password": "changed99", "confirm_password": "changed99"},
    )
    assert resp.status_code == 200
    assert _read_webui(settings)["password"] == "changed99"


def test_middleware_passes_body_through(settings):
    """下游路由必须能原样读到请求体（缓冲重放不能吃掉 body）。"""
    app = _build_app(settings)
    client = TestClient(app)
    payload = {"username": "astrbot", "password": "right-pass", "pad": "x" * 5000}
    resp = client.post("/api/auth/login", json=payload)
    assert resp.status_code == 200
    # body 透传且同步生效
    assert _read_webui(settings)["password"] == "right-pass"

    resp = client.post("/api/echo", content=b"plain-bytes-not-watched")
    assert resp.status_code == 200
    assert resp.json()["data"]["len"] == len(b"plain-bytes-not-watched")
    # 非关注端点不触发同步
    assert _read_webui(settings)["password"] == "right-pass"


def test_middleware_disabled_by_env(settings, monkeypatch):
    monkeypatch.setenv("STACK_SHARED_PASSWORD", "0")
    app = _build_app(settings)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "astrbot", "password": "right-pass"}
    )
    assert resp.status_code == 200
    assert not (settings.napcat_config_dir / "webui.json").exists()


# ------------------------------------------------------------------ 挂载
def test_mount_is_idempotent(settings):
    app = FastAPI()
    assert mount_shared_password_sync(app, settings) is True
    assert mount_shared_password_sync(app, settings) is False
    mounted = [m.cls for m in app.user_middleware]
    assert mounted.count(SharedPasswordMiddleware) == 1


def test_mount_disabled(settings, monkeypatch):
    monkeypatch.setenv("STACK_SHARED_PASSWORD", "0")
    app = FastAPI()
    assert mount_shared_password_sync(app, settings) is False
    assert not app.user_middleware


# ------------------------------------------------------------------ 子进程注入
def test_supervisor_injects_shared_password_env(tmp_path, monkeypatch):
    """共用密码开启时，NapCat 子进程环境应注入 NAPCAT_SHARED_PASSWORD=1。"""
    import sys

    from stack.napcat_process import NapCatSupervisor

    monkeypatch.delenv("STACK_SHARED_PASSWORD", raising=False)
    monkeypatch.delenv("NAPCAT_QQ_CMD", raising=False)
    monkeypatch.setenv("NAPCAT_WORKDIR", str(tmp_path / "napcat"))
    monkeypatch.setattr(sys, "platform", "win32")

    layout = tmp_path / "windows" / "napcat-node"
    layout.mkdir(parents=True)
    (layout / "node.exe").write_bytes(b"")
    (layout / "index.js").write_bytes(b"")
    (layout / "napcat").mkdir()
    (layout / "napcat" / "napcat.mjs").write_bytes(b"")

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    _cmd, env, _cwd = sup.build_command()
    assert env.get(NAPCAT_SHARED_PASSWORD_ENV) == "1"

    monkeypatch.setenv("STACK_SHARED_PASSWORD", "0")
    _cmd, env, _cwd = sup.build_command()
    assert NAPCAT_SHARED_PASSWORD_ENV not in env
