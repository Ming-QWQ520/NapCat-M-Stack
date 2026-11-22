"""NapCat WebUI 子路径重写器。

NapCat 的 WebUI 前端（vite 构建）把所有网络路径硬编码为根绝对路径：
``/webui/*``（静态资源与 SPA basename）、``/api/*``（REST/SSE/WS）、
``/files/*``（动态主题）、``/plugin/*``（插件页面/资源）。

统一网关把 NapCat WebUI 挂载在 ``/napcat`` 前缀之下，与 AstrBot 共用 6185
端口。由于 AstrBot 的仪表盘同样占用 ``/`` 与 ``/api/*``，必须把 NapCat 前端
产物在「准备阶段」静态重写为 ``/napcat`` 前缀，网关再剥前缀转发给只监听
127.0.0.1 的 NapCat 后端。

重写规则（针对真实构建产物逐条验证过，见 tests/test_webui_patch.py）：

Tier-A  完整已知端点字面量，任意位置替换（绝对安全，用于模板字符串拼接）：
        ``/api/Debug/ws``、``/api/ws/terminal``、``/api/Log/GetLogRealTime``、
        ``/api/base/GetSysStatusRealTime``、``/api/Mirror/Test/SSE``、
        ``/api/Plugin/Store/Install/SSE``、``/api/Plugin/Config/SSE``、
        ``/api/Debug/create``、``/api/Debug/schemas``、``/api/Debug/call/``、
        ``/files/theme.css``

Tier-B  引号锚定前缀（匹配 ``"`/api``、``'/api``、```/api`` 三种引号）：
        ``/api``、``/webui``、``/files``、``/plugin/``（带尾斜杠，
        避免误伤路由链接 ``/plugins``、``/plugin_store``）

Tier-C  CSS ``url(...)``：``url(/webui`` → ``url(/napcat/webui``

不重写 ``sw_template.js``：其路径判定在子路径下全部不命中，自动退化为
「全部直连网络」，功能不受影响（仅失去 SW 缓存）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PATCH_MARKER = ".stack-webui-patched"
PATCHER_VERSION = "2"

#: NapCat WebUI 在统一网关下的挂载前缀
MOUNT_PREFIX = "/napcat"

_TIER_A_LITERALS: tuple[str, ...] = (
    "/api/Debug/ws",
    "/api/ws/terminal",
    "/api/Log/GetLogRealTime",
    "/api/base/GetSysStatusRealTime",
    "/api/Mirror/Test/SSE",
    "/api/Plugin/Store/Install/SSE",
    "/api/Plugin/Config/SSE",
    "/api/Debug/create",
    "/api/Debug/schemas",
    "/api/Debug/call/",
    "/files/theme.css",
)

#: 引号锚定前缀。``/plugin`` 必须带尾斜杠（避开 /plugins 与 /plugin_store 路由链接）
_QUOTE_ANCHORED: tuple[tuple[str, bool], ...] = (
    ("/api", False),
    ("/webui", False),
    ("/files", False),
    ("/plugin/", True),
)


@dataclass
class PatchReport:
    changed_files: list[str] = field(default_factory=list)
    total_replacements: int = 0
    skipped_files: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"重写文件数: {len(self.changed_files)}，替换总数: {self.total_replacements}"
        ]
        if self.leftovers:
            lines.append(f"警告: {len(self.leftovers)} 处疑似残留（见 --verbose）")
        return "\n".join(lines)


def _quote_anchored_regex(prefix: str) -> re.Pattern[str]:
    """形如 ``["'`]​/api`` 的匹配（引号紧邻路径前缀）。"""
    return re.compile(rf'(["\'`]){re.escape(prefix)}')


def rewrite_text(
    text: str, mount: str = MOUNT_PREFIX, verbose_hits: list[str] | None = None
) -> tuple[str, int]:
    """对单份文本（HTML/JS/CSS）执行子路径重写，返回 (新文本, 替换次数)。

    全部规则幂等：已带 ``/napcat`` 前缀的文本再次重写不会再命中。
    """

    count = 0

    # Tier-A：完整端点字面量。负向后行断言避免重复运行时二次加前缀。
    for literal in _TIER_A_LITERALS:
        pattern = re.compile(rf"(?<!napcat){re.escape(literal)}")

        def _replace(m: re.Match[str], _lit: str = literal) -> str:
            return mount + _lit

        text, n = pattern.subn(_replace, text)
        count += n
        if n and verbose_hits is not None:
            verbose_hits.append(f"[A] {literal} x{n}")

    # Tier-B：引号锚定前缀。引号后紧跟 /napcat 不会再命中，天然幂等。
    for prefix, _needs_slash in _QUOTE_ANCHORED:
        pattern = _quote_anchored_regex(prefix)

        def _replace(m: re.Match[str], _p: str = prefix) -> str:
            return f"{m.group(1)}{mount}{_p}"

        text, n = pattern.subn(_replace, text)
        count += n
        if n and verbose_hits is not None:
            verbose_hits.append(f"[B] quote-anchored {prefix} x{n}")

    # Tier-C：CSS url(...) 以及 JS 内联 CSS 字符串中的 url('...')
    css_pattern = re.compile(r"(url\(\s*)([\"']?)(/webui)")

    def _css_replace(m: re.Match[str]) -> str:
        return f"{m.group(1)}{m.group(2)}{mount}/webui"

    text, n = css_pattern.subn(_css_replace, text)
    count += n
    if n and verbose_hits is not None:
        verbose_hits.append(f"[C] css url(/webui x{n}")

    return text, count


def scan_leftovers(static_dir: Path) -> list[str]:
    """扫描重写后仍残留的「引号锚定」可疑路径，用于自检。"""
    leftovers: list[str] = []
    for path in _iter_targets(static_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        for prefix, _slash in _QUOTE_ANCHORED:
            pattern = _quote_anchored_regex(prefix)
            for m in pattern.finditer(text):
                start = max(0, m.start() - 16)
                end = min(len(text), m.end() + 32)
                leftovers.append(f"{path.name}: ...{text[start:end]}...")
    return leftovers


def _iter_targets(static_dir: Path):
    """需要重写的文件集合：index.html + JS + CSS（不含 sw_template.js）。"""
    if (static_dir / "index.html").is_file():
        yield static_dir / "index.html"
    for pattern in ("*.js", "*.css"):
        for path in sorted(static_dir.rglob(pattern)):
            if path.name == "sw_template.js":
                continue
            yield path


def patch_static_dir(static_dir: Path, mount: str = MOUNT_PREFIX, force: bool = False) -> PatchReport | None:
    """重写一个 NapCat WebUI ``static`` 目录。

    Args:
        static_dir: WebUI 静态资源目录（包含 index.html）。
        mount: 挂载前缀，默认 ``/napcat``。
        force: 忽略已打补丁标记，强制重写（重写是幂等的：已加前缀的
            文本不会再命中旧模式）。

    Returns:
        补丁报告；目录不存在或不含 index.html 时返回 None。
    """
    if not (static_dir / "index.html").is_file():
        return None

    marker = static_dir / PATCH_MARKER
    if marker.is_file() and not force:
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
            if meta.get("patcher") == PATCHER_VERSION and meta.get("mount") == mount:
                return PatchReport(skipped_files=[str(static_dir)])
        except (ValueError, OSError):
            pass

    report = PatchReport()
    for path in _iter_targets(static_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        hits: list[str] = []
        new_text, n = rewrite_text(text, mount=mount, verbose_hits=hits)
        if n:
            path.write_text(new_text, encoding="utf-8")
            report.changed_files.append(path.name)
            report.total_replacements += n
            for line in hits:
                print(f"    {path.name}: {line}")

    report.leftovers = scan_leftovers(static_dir)
    marker.write_text(
        json.dumps({"patcher": PATCHER_VERSION, "mount": mount}, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def find_static_dirs(base: Path) -> list[Path]:
    """在 base 下递归查找所有 NapCat WebUI static 目录。

    匹配规则：目录内同时存在 ``index.html`` 与 ``vercel.json``（NapCat WebUI
    构建产物的固定组合），且 HTML 引用了 ``/webui/`` 资源（或已打过补丁）。
    """
    results: list[Path] = []
    for candidate in base.rglob("index.html"):
        parent = candidate.parent
        if not (parent / "vercel.json").exists():
            continue
        if (parent / PATCH_MARKER).exists():
            results.append(parent)
            continue
        try:
            html = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "/webui/" in html:
            results.append(parent)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NapCat WebUI 子路径重写器")
    parser.add_argument("target", help="NapCat WebUI static 目录或其上层目录")
    parser.add_argument("--mount", default=MOUNT_PREFIX, help="挂载前缀（默认 /napcat）")
    parser.add_argument("--force", action="store_true", help="忽略标记强制重写")
    parser.add_argument(
        "--dry-run", action="store_true", help="只报告将要重写的内容，不落盘"
    )
    args = parser.parse_args(argv)

    base = Path(args.target).expanduser().resolve()
    if (base / "index.html").is_file():
        static_dirs = [base]
    else:
        static_dirs = find_static_dirs(base)

    if not static_dirs:
        print(f"[!] 在 {base} 下未找到 NapCat WebUI static 目录（需含 index.html + vercel.json）")
        return 1

    for static_dir in static_dirs:
        print(f"[..] 重写 {static_dir}")
        if args.dry_run:
            leftovers_before = scan_leftovers(static_dir)
            total = 0
            for path in _iter_targets(static_dir):
                text = path.read_text(encoding="utf-8", errors="replace")
                _, n = rewrite_text(text, mount=args.mount)
                total += n
            print(f"     将替换 {total} 处；当前残留 {len(leftovers_before)} 处")
            continue
        report = patch_static_dir(static_dir, mount=args.mount, force=args.force)
        if report is None:
            print(f"[!] 跳过（非 WebUI 目录）: {static_dir}")
            continue
        if report.skipped_files:
            print(f"[OK] 已打过补丁，跳过: {static_dir}")
            continue
        print(f"[OK] {static_dir}: {report.summary()}")
        if report.leftovers:
            print("    残留明细:")
            for line in report.leftovers[:20]:
                print(f"      {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
