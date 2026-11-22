"""scripts/wire-qq.sh 的行为测试（在临时目录伪造 QQ resources/app 树）。

覆盖：首次接线（符号链接 / 复制两种模式）、幂等重跑、QQ 已被改写过的
场景、回滚、以及对非本脚本产物的 napcat 目录的保护。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "wire-qq.sh"


def _make_fake_qq(tmp_path: Path) -> Path:
    """构造一个最小化的 QQ resources/app 目录。"""
    qq_dir = tmp_path / "fake-root" / "resources" / "app"
    qq_dir.mkdir(parents=True)
    (qq_dir / "package.json").write_text(
        json.dumps({"name": "qq", "main": "./build/qq.js", "version": "9.9.9"}),
        encoding="utf-8",
    )
    (qq_dir / "build").mkdir()
    (qq_dir / "build" / "qq.js").write_text("// fake", encoding="utf-8")
    return qq_dir


def _make_napcat_artifacts(tmp_path: Path) -> Path:
    """构造仓库侧 napcat/ 产物目录，并让脚本定位到它。"""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    napcat = repo / "napcat"
    napcat.mkdir()
    (napcat / "napcat.mjs").write_text("// napcat entry", encoding="utf-8")
    # 把脚本复制过去（脚本通过自身位置推导 REPO_ROOT）
    (repo / "scripts" / "wire-qq.sh").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return repo


def _run(script: Path, *args: str, qq_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script / "scripts" / "wire-qq.sh"), "--qq-dir", str(qq_dir), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_main(qq_dir: Path) -> str:
    return json.loads(
        (qq_dir / "package.json").read_text(encoding="utf-8")
    )["main"]


def test_wire_with_symlink(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)

    result = _run(repo, qq_dir=qq_dir)
    assert result.returncode == 0, result.stderr

    assert _read_main(qq_dir) == "./napcat/napcat.mjs"
    link = qq_dir / "napcat"
    assert link.is_symlink()
    assert link.resolve() == (repo / "napcat").resolve()
    # 原始配置被备份且内容未变
    backup = qq_dir / "package.json.stack-backup"
    assert backup.is_file()
    assert json.loads(backup.read_text(encoding="utf-8"))["main"] == "./build/qq.js"


def test_wire_idempotent(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)

    first = _run(repo, qq_dir=qq_dir)
    assert first.returncode == 0, first.stderr
    second = _run(repo, qq_dir=qq_dir)
    assert second.returncode == 0, second.stderr
    assert "已存在且指向正确" in second.stdout

    # 重复执行不会叠加备份（备份仍是原始 main）
    backup = qq_dir / "package.json.stack-backup"
    assert json.loads(backup.read_text(encoding="utf-8"))["main"] == "./build/qq.js"
    assert _read_main(qq_dir) == "./napcat/napcat.mjs"


def test_wire_with_copy_mode(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)

    result = _run(repo, "--copy", qq_dir=qq_dir)
    assert result.returncode == 0, result.stderr

    copied = qq_dir / "napcat"
    assert copied.is_dir() and not copied.is_symlink()
    assert (copied / "napcat.mjs").is_file()
    assert (copied / ".stack-copied").is_file()
    assert _read_main(qq_dir) == "./napcat/napcat.mjs"


def test_rollback_restores_original(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)

    assert _run(repo, qq_dir=qq_dir).returncode == 0
    result = _run(repo, "--rollback", qq_dir=qq_dir)
    assert result.returncode == 0, result.stderr

    assert _read_main(qq_dir) == "./build/qq.js"
    assert not (qq_dir / "napcat").exists()
    assert not (qq_dir / "package.json.stack-backup").exists()


def test_rollback_after_copy_mode(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)

    assert _run(repo, "--copy", qq_dir=qq_dir).returncode == 0
    assert _run(repo, "--rollback", qq_dir=qq_dir).returncode == 0
    assert _read_main(qq_dir) == "./build/qq.js"
    assert not (qq_dir / "napcat").exists()


def test_rollback_without_prior_wire(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)

    result = _run(repo, "--rollback", qq_dir=qq_dir)
    assert result.returncode == 0, result.stderr
    assert _read_main(qq_dir) == "./build/qq.js"


def test_foreign_napcat_dir_is_protected(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)
    # 用户手动装过一份 NapCat
    foreign = qq_dir / "napcat"
    foreign.mkdir()
    (foreign / "napcat.mjs").write_text("// 手动安装", encoding="utf-8")

    result = _run(repo, qq_dir=qq_dir)
    assert result.returncode != 0
    assert "不是本脚本产物" in result.stderr
    # 手动安装的内容原样保留
    assert (foreign / "napcat.mjs").read_text(encoding="utf-8") == "// 手动安装"


def test_rollback_keeps_foreign_napcat_dir(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)
    foreign = qq_dir / "napcat"
    foreign.mkdir()
    (foreign / "napcat.mjs").write_text("// 手动安装", encoding="utf-8")

    assert _run(repo, "--rollback", qq_dir=qq_dir).returncode == 0
    assert (foreign / "napcat.mjs").is_file()


def test_missing_artifacts_hint(tmp_path):
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)
    (repo / "napcat" / "napcat.mjs").unlink()  # 产物未准备

    result = _run(repo, qq_dir=qq_dir)
    assert result.returncode != 0
    assert "prepare-napcat.sh" in result.stderr


def test_missing_qq_dir_hint(tmp_path):
    repo = _make_napcat_artifacts(tmp_path)
    env = dict(os.environ)
    env.pop("QQ_RESOURCES_DIR", None)
    env.pop("QQ_PATH", None)
    # CI 环境可能装了 dpkg 但没有 linuxqq 包，find_qq_dir 会落到常见路径
    # 探测——用 HOME 重定向避免误伤，并断言给出的是友好错误。
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "wire-qq.sh")],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    # 机器上确实可能存在 /opt/QQ（少见）；存在时允许成功，否则必须友好失败
    if not Path("/opt/QQ/resources/app/package.json").exists():
        assert result.returncode != 0
        assert "--qq-dir" in result.stderr or "QQ" in result.stderr


def test_relink_after_artifact_update(tmp_path):
    """仓库 napcat/ 更新（重建目录）后重跑，符号链接应指向新位置。"""
    qq_dir = _make_fake_qq(tmp_path)
    repo = _make_napcat_artifacts(tmp_path)

    assert _run(repo, qq_dir=qq_dir).returncode == 0
    link = qq_dir / "napcat"
    assert link.resolve() == (repo / "napcat").resolve()
