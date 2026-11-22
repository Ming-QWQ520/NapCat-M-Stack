#!/usr/bin/env python3
"""Docker 构建期 NapCat 产物准备。

按优先级取用 NapCat-M Shell 产物并完成 WebUI 子路径重写：

1. 构建上下文中已就位的 ``napcat/`` 目录（本地跑过 scripts/prepare-napcat.sh）
2. 构建上下文中的 ``scripts/NapCat.Shell.zip``（手动下载放置）
3. 在线下载（ARG NAPCAT_ZIP_URL，可用 build-arg 指向镜像源）

仅用标准库，可在任意含 python3 的构建阶段运行。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# 允许作为脚本直接执行（python3 scripts/docker-prepare.py）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stack.webui_patch import patch_static_dir  # noqa: E402


def copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def extract_zip(zip_path: Path, dest: Path) -> None:
    """解压 Shell zip 并定位 napcat.mjs 所在层（兼容带/不带外层目录）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_path)
        candidates = list(tmp_path.rglob("napcat.mjs"))
        if not candidates:
            raise SystemExit(f"[!] {zip_path} 中未找到 napcat.mjs")
        root = candidates[0].parent
        copy_tree(root, dest)


def download(url: str, dest_zip: Path) -> None:
    print(f"[..] 下载 {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310
        dest_zip.write_bytes(resp.read())
    print(f"[OK] 已下载 {dest_zip} ({dest_zip.stat().st_size // 1024} KiB)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="/src", help="构建上下文挂载位置")
    parser.add_argument("--dest", default="/app/napcat", help="产物输出目录")
    parser.add_argument("--version", default="v4.18.44")
    parser.add_argument("--url", default="", help="下载地址（默认按版本号拼接 GitHub Releases）")
    args = parser.parse_args()

    src = Path(args.src)
    dest = Path(args.dest)

    if (src / "napcat" / "napcat.mjs").is_file():
        print("[OK] 使用构建上下文中已准备的 napcat/")
        copy_tree(src / "napcat", dest)
    elif (src / "scripts" / "NapCat.Shell.zip").is_file():
        print("[OK] 使用构建上下文中的 scripts/NapCat.Shell.zip")
        extract_zip(src / "scripts" / "NapCat.Shell.zip", dest)
    else:
        url = args.url or (
            "https://github.com/Ming-QWQ520/NapCatQQ-M/releases/download/"
            f"{args.version}/NapCat.Shell.zip"
        )
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "NapCat.Shell.zip"
            download(url, zip_path)
            extract_zip(zip_path, dest)

    if not (dest / "napcat.mjs").is_file():
        print(f"[!] 产物异常：{dest}/napcat.mjs 不存在")
        return 1

    static_dir = dest / "static"
    report = patch_static_dir(static_dir, force=True)
    if report is None:
        print("[!] 未找到 WebUI static 目录，跳过子路径重写（/napcat 代理将不可用）")
        return 0
    if report.skipped_files:
        print("[OK] WebUI 已重写（标记命中）")
    else:
        print(f"[OK] WebUI 子路径重写: {report.summary()}")
        if report.leftovers:
            for line in report.leftovers[:10]:
                print(f"    残留: {line}")
    (dest / ".stack-napcat-version").write_text(args.version, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
