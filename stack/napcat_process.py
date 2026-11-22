"""NapCat(QQ) 子进程监督器。

统一入口 ``main.py`` 是唯一主进程，QQ（内嵌 NapCat-M）作为其子进程运行：

- 按平台构造启动命令：
  - Windows Node 便携版（推荐）：直接拉起 windows\\napcat-node\\node.exe
  - Windows OneKey：拉起 NapCatWinBootMain.exe（需先运行安装器注入）
  - Linux / macOS / Docker：直接拉起 QQ（QQ 加载栈内 NapCat-M 产物）
- 管道接住子进程 stdout/stderr，转发到统一日志并解析 WebUI 端口/令牌
- WebUI 端口发现：优先解析日志行，失败则回退为 127.0.0.1 端口探测
  （NapCat 在端口被占用时会自动 +1 顺延，网关必须跟着发现实际端口）
- 父进程退出联动：Linux 用 PR_SET_PDEATHSIG，Windows 尽力而为
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from .settings import StackSettings

# 兼容新旧两代 NapCat-M：旧版（token 登录）携带 ?token=，新版（账户密码登录）无查询参数
_WEBUI_URL_LINE = re.compile(
    r"\[NapCat\]\s*\[WebUi\]\s*WebUi User Panel Url:\s*"
    r"http://127\.0\.0\.1:(\d+)/webui(?:\?token=[0-9A-Za-z!@#$%^&*()_+\-=]+)?"
)

_WINDOWS_BOOTMAIN_CANDIDATES = ("NapCatWinBootMain.exe",)

#: Node 便携版（NapCat.Shell.Windows.Node.zip 解压产物）的入口标志：
#: node.exe 与 index.js 同目录，napcat/ 在其下
_WINDOWS_NODE_ENTRY_SCRIPT = "index.js"


class NapCatNotReadyError(RuntimeError):
    """NapCat WebUI 尚未就绪。"""


class NapCatProcessError(RuntimeError):
    """NapCat 子进程无法启动或已退出。"""


def _linux_set_pdeathsig() -> None:  # pragma: no cover - 平台相关
    """让内核在父进程死亡时向本子进程发送 SIGTERM（防孤儿 QQ）。"""
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass


class NapCatSupervisor:
    """QQ(NapCat) 子进程生命周期 + WebUI 端点发现。"""

    def __init__(self, settings: StackSettings) -> None:
        self.settings = settings
        self.process: subprocess.Popen | None = None
        self._port: int | None = None
        self._ready_event = asyncio.Event()
        self._stopped_by_us = False
        self._reader_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._exit_callback = None

    # ------------------------------------------------------------------ 状态
    @property
    def port(self) -> int | None:
        return self._port

    @property
    def base_url(self) -> str | None:
        if self._port is None:
            return None
        return f"http://127.0.0.1:{self._port}"

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def on_exit(self, callback) -> None:
        """注册子进程退出回调（用于整栈退出决策）。"""
        self._exit_callback = callback

    # ------------------------------------------------------------------ 启动
    def build_command(self) -> tuple[list[str], dict[str, str], Path]:
        """构造 (命令, 附加环境变量, 工作目录)。"""
        env = {
            "NAPCAT_WORKDIR": str(self.settings.napcat_workdir),
        }
        # 共用密码模式：把 AstrBot 的配置文件路径交给 NapCat，登录密码以
        # AstrBot 为准（用户显式设置过 NAPCAT_ASTRBOT_CONFIG 时不覆盖）。
        # 首次启动时 cmd_config.json 可能尚未生成——NapCat 侧在登录时才
        # 惰性读取，届时 AstrBot 已完成初始化。
        if (
            self.settings.shared_napcat_password
            and "NAPCAT_ASTRBOT_CONFIG" not in os.environ
        ):
            env["NAPCAT_ASTRBOT_CONFIG"] = str(self.settings.data_dir / "cmd_config.json")

        # 显式覆盖优先（保持当前工作目录，避免用户命令中的相对路径失效）
        override = self.settings.napcat_qq_command
        if override:
            if self._resolve_executable(override[0]) is None:
                raise NapCatProcessError(f"启动命令不存在: {override[0]}")
            return list(override), env, Path.cwd()

        if sys.platform == "win32":
            flavor = self.settings.napcat_flavor

            # ---- Node 便携版（自带无头 QQ + Node.js，免注入） ----
            if flavor in ("auto", "node"):
                node_entry = self._find_windows_node_entry()
                if node_entry is not None:
                    node_exe, index_js = node_entry
                    cmd = [str(node_exe), str(index_js)]
                    if self.settings.napcat_account:
                        cmd += ["-q", self.settings.napcat_account]
                    # 便携版的 QQ 数据目录收进栈内（登录态随 data/ 持久化，
                    # 不散落在用户目录）
                    qq_data = self.settings.data_dir / "qq"
                    try:
                        qq_data.mkdir(parents=True, exist_ok=True)
                    except OSError:
                        pass
                    env["NAPCAT_QQ_DATA_DIR"] = str(qq_data)
                    return cmd, env, node_exe.parent

            # ---- OneKey 注入版（需先运行 NapCatInstaller.exe） ----
            if flavor in ("auto", "onekey"):
                bootmain = self._find_windows_bootmain()
                if bootmain is not None:
                    if self.settings.napcat_account:
                        return (
                            [str(bootmain), self.settings.napcat_account],
                            env,
                            bootmain.parent,
                        )
                    return [str(bootmain)], env, bootmain.parent

            hint = (
                "Node（免注入便携版）" if flavor == "node"
                else "OneKey（需先运行过 NapCatInstaller.exe）" if flavor == "onekey"
                else "Node 便携版（-Flavor Node，推荐）或 OneKey 注入版（-Flavor OneKey）"
            )
            raise NapCatProcessError(
                f"未找到 NapCat-M Windows 产物（当前偏好：{hint}）。"
                "请先运行 windows\\install.ps1 完成安装，"
                "或用环境变量 NAPCAT_QQ_CMD 显式指定启动命令。"
            )

        # Linux / macOS / Docker
        qq_path = os.environ.get("QQ_PATH", "/opt/QQ/qq")
        if not Path(qq_path).exists():
            raise NapCatProcessError(
                f"未找到 QQ 可执行文件：{qq_path}。Docker 部署请使用仓库 "
                "Dockerfile（内含 QQ）；裸机部署请安装 QQNT 后通过环境变量 "
                "QQ_PATH 指定路径，或用 NAPCAT_QQ_CMD 覆盖整个启动命令。"
            )

        cmd = [qq_path, "--no-sandbox"]
        if self.settings.napcat_account:
            cmd += ["-q", self.settings.napcat_account]

        # 裸机无显示服务器时借助 xvfb-run（Docker 内由 entrypoint 提供 Xvfb）
        has_display = bool(os.environ.get("DISPLAY"))
        if not has_display:
            from shutil import which

            if which("xvfb-run"):
                cmd = ["xvfb-run", "-a", *cmd]

        cwd = self.settings.napcat_dir if self.settings.napcat_dir.is_dir() else Path.cwd()
        if not (cwd / "napcat.mjs").exists():
            # Docker 镜像布局：cwd 无所谓，QQ 按自身 package.json 加载 napcat
            cwd = Path("/app/napcat") if Path("/app/napcat").is_dir() else cwd
        return cmd, env, cwd

    def _resolve_executable(self, exe: str) -> str | None:
        """把命令解析为可执行绝对路径（支持相对路径与 PATH 查找）。"""
        from shutil import which

        candidate = Path(exe)
        if candidate.is_absolute():
            return str(candidate) if candidate.exists() else None
        if "/" in exe or "\\" in exe:
            resolved = candidate.resolve()
            return str(resolved) if resolved.exists() else None
        found = which(exe)
        return found

    def _find_windows_bootmain(self) -> Path | None:
        windows_dir = self.settings.root / "windows"
        if not windows_dir.is_dir():
            return None
        for name in _WINDOWS_BOOTMAIN_CANDIDATES:
            for candidate in windows_dir.rglob(name):
                return candidate
        return None

    def _find_windows_node_entry(self) -> tuple[Path, Path] | None:
        """定位 Node 便携版入口：windows/**/node.exe 且同目录存在 index.js。

        Returns:
            (node.exe 路径, index.js 路径)；未找到返回 None。
        """
        windows_dir = self.settings.root / "windows"
        if not windows_dir.is_dir():
            return None
        for node_exe in windows_dir.rglob("node.exe"):
            index_js = node_exe.parent / _WINDOWS_NODE_ENTRY_SCRIPT
            if index_js.is_file():
                return node_exe, index_js
        return None

    async def start(self) -> None:
        """拉起子进程并开始监督。不等待 WebUI 就绪（那由 wait_ready 完成）。"""
        cmd, extra_env, cwd = self.build_command()

        env = os.environ.copy()
        env.update(extra_env)
        # NapCat WebUI 端口固定偏好值（被占用时 NapCat 自动顺延，网关会发现）
        env.setdefault("NAPCAT_WEBUI_PREFERRED_PORT", str(self.settings.napcat_webui_port))

        popen_kwargs: dict = {
            "cwd": str(cwd),
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":  # pragma: no cover - 平台相关
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:  # pragma: no cover - 平台相关
            popen_kwargs["preexec_fn"] = _linux_set_pdeathsig

        print(f"[NapCat] 启动子进程: {' '.join(cmd)}  (cwd={cwd})")
        try:
            self.process = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError as e:
            raise NapCatProcessError(f"启动命令不存在: {e}") from e

        self._reader_task = asyncio.get_running_loop().create_task(
            self._read_output()
        )
        self._monitor_task = asyncio.get_running_loop().create_task(
            self._monitor_exit()
        )
        # 后台探测兜底（日志解析失败时也能找到端口）
        asyncio.get_running_loop().create_task(self._probe_discovery_loop())

    async def _read_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, process.stdout.readline)
            if not line:
                break
            try:
                text = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                continue
            if not text:
                continue
            print(f"[NapCat] {text}")
            m = _WEBUI_URL_LINE.search(text)
            if m:
                port = int(m.group(1))
                if self._port != port:
                    print(f"[NapCat] WebUI 端口发现（日志解析）: {port}")
                self._port = port
                self._ready_event.set()

    async def _monitor_exit(self) -> None:
        process = self.process
        if process is None:
            return
        loop = asyncio.get_running_loop()
        while process.poll() is None:
            await asyncio.sleep(1.0)
        code = process.returncode
        if self._stopped_by_us:
            return
        print(f"[NapCat] 子进程已退出 (code={code})")
        if self._exit_callback is not None:
            try:
                self._exit_callback(code)
            except Exception:
                pass

    async def _probe_discovery_loop(self) -> None:
        """日志解析失败时的兜底：对 127.0.0.1 顺延端口做 HTTP 探测。"""
        import httpx

        base = self.settings.napcat_webui_port
        deadline = asyncio.get_running_loop().time() + 180
        while not self._ready_event.is_set():
            if not self.is_running:
                return
            for offset in range(self.settings.napcat_webui_port_scan_range):
                port = base + offset
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(0.6)
                    ) as client:
                        resp = await client.get(
                            f"http://127.0.0.1:{port}/", follow_redirects=False
                        )
                    if resp.status_code in (301, 302) and "/webui" in resp.headers.get(
                        "location", ""
                    ):
                        print(f"[NapCat] WebUI 端口发现（端口探测）: {port}")
                        self._port = port
                        self._ready_event.set()
                        return
                except Exception:
                    continue
            if asyncio.get_running_loop().time() > deadline:
                return
            await asyncio.sleep(2.0)

    # ------------------------------------------------------------------ 就绪
    async def wait_ready(self, timeout: float = 120.0) -> int:
        """等待 WebUI 就绪，返回端口。"""
        if not self.is_running:
            raise NapCatProcessError("NapCat 子进程未在运行")
        if self._ready_event.is_set():
            return self._port
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise NapCatNotReadyError(
                f"等待 NapCat WebUI 就绪超时（{timeout}s）。请检查上方 NapCat 日志。"
            ) from e
        return self._port

    async def ensure_ready(self, timeout: float = 8.0) -> int:
        """轻量版：仅在请求到达时快速确认，不长期阻塞。"""
        return await self.wait_ready(timeout=timeout)

    # ------------------------------------------------------------------ 停止
    async def stop(self, grace: float = 12.0) -> None:
        self._stopped_by_us = True
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, process.wait),
                timeout=grace,
            )
        except asyncio.TimeoutError:
            process.kill()
        if sys.platform == "win32":  # pragma: no cover - 平台相关
            _windows_kill_tree(process.pid)
        for task in (self._reader_task, self._monitor_task):
            if task and not task.done():
                task.cancel()


def _windows_kill_tree(pid: int) -> None:  # pragma: no cover - 平台相关
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    except Exception:
        pass
