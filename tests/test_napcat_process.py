"""stack.napcat_process / stack.settings 的 Windows 启动命令构造测试。

在不依赖真实 Windows 的情况下，通过 monkeypatch ``sys.platform`` 验证：
- Node 便携版（windows/napcat-node）的发现与启动命令
- OneKey（NapCatWinBootMain.exe）的回退
- ``NAPCAT_FLAVOR`` 偏好的强制与互斥
- ``NAPCAT_QQ_CMD`` 在 win32 下对反斜杠路径的安全切分
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stack.napcat_process import NapCatProcessError, NapCatSupervisor
from stack.settings import StackSettings


def _make_layout(root: Path, *, node: bool = False, bootmain: bool = False) -> None:
    if node:
        d = root / "windows" / "napcat-node"
        d.mkdir(parents=True)
        (d / "node.exe").write_bytes(b"")
        (d / "index.js").write_bytes(b"")
        (d / "napcat").mkdir()
        (d / "napcat" / "napcat.mjs").write_bytes(b"")
    if bootmain:
        d = root / "windows" / "napcat-onekey" / "bootmain"
        d.mkdir(parents=True)
        (d / "NapCatWinBootMain.exe").write_bytes(b"")


def _clean_env(monkeypatch):
    for var in (
        "NAPCAT_QQ_CMD", "NAPCAT_FLAVOR", "ACCOUNT", "NAPCAT_WORKDIR", "NAPCAT_DIR",
        "NAPCAT_ASTRBOT_CONFIG", "STACK_SHARED_NAPCAT_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)


def test_windows_node_flavor_command(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    _make_layout(tmp_path, node=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    cmd, env, cwd = sup.build_command()

    assert cmd == [
        str(tmp_path / "windows" / "napcat-node" / "node.exe"),
        str(tmp_path / "windows" / "napcat-node" / "index.js"),
    ]
    assert cwd == tmp_path / "windows" / "napcat-node"
    # 便携版 QQ 数据目录收进栈内 data/qq
    assert env["NAPCAT_QQ_DATA_DIR"] == str(tmp_path / "data" / "qq")
    assert (tmp_path / "data" / "qq").is_dir()
    # 其余环境（工作目录约定）保持不变
    assert env["NAPCAT_WORKDIR"] == str(tmp_path / "data" / "napcat")


def test_windows_node_flavor_with_account(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    monkeypatch.setenv("ACCOUNT", "10001")
    _make_layout(tmp_path, node=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    cmd, _, _ = sup.build_command()
    assert cmd[-2:] == ["-q", "10001"]


def test_windows_onekey_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    _make_layout(tmp_path, bootmain=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    cmd, _, cwd = sup.build_command()
    assert cmd == [str(tmp_path / "windows" / "napcat-onekey" / "bootmain" / "NapCatWinBootMain.exe")]
    assert cwd == tmp_path / "windows" / "napcat-onekey" / "bootmain"


def test_windows_node_preferred_over_onekey(tmp_path, monkeypatch):
    """auto 模式下同时安装两种形态：Node 便携版优先。"""
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    _make_layout(tmp_path, node=True, bootmain=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    cmd, _, _ = sup.build_command()
    assert cmd[0].endswith("node.exe")


def test_windows_flavor_force_onekey(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    monkeypatch.setenv("NAPCAT_FLAVOR", "onekey")
    _make_layout(tmp_path, node=True, bootmain=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    cmd, _, _ = sup.build_command()
    assert cmd[0].endswith("NapCatWinBootMain.exe")


def test_windows_flavor_force_node_ignores_onekey(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    monkeypatch.setenv("NAPCAT_FLAVOR", "node")
    _make_layout(tmp_path, bootmain=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    with pytest.raises(NapCatProcessError, match="Node"):
        sup.build_command()


def test_windows_missing_artifacts_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    with pytest.raises(NapCatProcessError, match="install"):
        sup.build_command()


def test_qq_cmd_windows_backslash_paths(tmp_path, monkeypatch):
    """win32 下 NAPCAT_QQ_CMD 的反斜杠路径不能被 shlex 吃掉。"""
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    monkeypatch.setenv(
        "NAPCAT_QQ_CMD",
        r'"E:\Program Files\node\node.exe" E:\stack\index.js -q 10086',
    )

    settings = StackSettings(root=tmp_path)
    assert settings.napcat_qq_command == [
        r"E:\Program Files\node\node.exe",
        r"E:\stack\index.js",
        "-q",
        "10086",
    ]


def test_qq_cmd_posix_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    _clean_env(monkeypatch)
    monkeypatch.setenv("NAPCAT_QQ_CMD", "/opt/QQ/qq -q 10086")

    settings = StackSettings(root=tmp_path)
    assert settings.napcat_qq_command == ["/opt/QQ/qq", "-q", "10086"]


def test_napcat_flavor_parsing(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    settings = StackSettings(root=tmp_path)
    assert settings.napcat_flavor == "auto"

    monkeypatch.setenv("NAPCAT_FLAVOR", "OneKey")
    assert settings.napcat_flavor == "onekey"

    monkeypatch.setenv("NAPCAT_FLAVOR", "bogus")
    assert settings.napcat_flavor == "auto"


def test_shared_password_env_injected(tmp_path, monkeypatch):
    """共用密码模式：supervisor 默认向 NapCat 子进程注入 NAPCAT_ASTRBOT_CONFIG。"""
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    _make_layout(tmp_path, node=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    _, env, _ = sup.build_command()
    assert env["NAPCAT_ASTRBOT_CONFIG"] == str(tmp_path / "data" / "cmd_config.json")


def test_shared_password_env_disabled(tmp_path, monkeypatch):
    """STACK_SHARED_NAPCAT_PASSWORD=0 时不注入（回退独立密码模式）。"""
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    monkeypatch.setenv("STACK_SHARED_NAPCAT_PASSWORD", "0")
    _make_layout(tmp_path, node=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    _, env, _ = sup.build_command()
    assert "NAPCAT_ASTRBOT_CONFIG" not in env


def test_shared_password_env_respects_user_override(tmp_path, monkeypatch):
    """用户显式设置过 NAPCAT_ASTRBOT_CONFIG 时不覆盖。"""
    monkeypatch.setattr(sys, "platform", "win32")
    _clean_env(monkeypatch)
    monkeypatch.setenv("NAPCAT_ASTRBOT_CONFIG", "/custom/astrbot/cmd_config.json")
    _make_layout(tmp_path, node=True)

    sup = NapCatSupervisor(StackSettings(root=tmp_path))
    _, env, _ = sup.build_command()
    # 未被栈值覆盖（用户值由 os.environ 继承，而非 extra_env 注入）
    assert env.get("NAPCAT_ASTRBOT_CONFIG") != str(tmp_path / "data" / "cmd_config.json")
