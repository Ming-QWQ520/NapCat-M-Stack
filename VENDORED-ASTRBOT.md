# 内嵌 AstrBot 说明（Vendored）

本仓库内嵌（vendor）了 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的运行所需源码，
以实现「单仓库、单命令、单进程树」的一体化部署——而非把 AstrBot 当作外部程序用脚本调用。

- 上游仓库：https://github.com/AstrBotDevs/AstrBot
- 内嵌版本：`v4.30.0-beta.1`
- 内嵌基线提交：`feb3e82c3ed1a1d7fdd202f7b7711657e34b81ea`（2026-11-19）
- 许可证：AGPL-3.0（见 `astrbot/LICENSE`），本仓库整体同样以 AGPL-3.0 发布（见根目录 `LICENSE`）

## 内嵌内容

| 路径 | 说明 |
| --- | --- |
| `astrbot/` | AstrBot 主包（含内置插件/技能），逐文件复制自上游，未做任何修改 |
| `astrbot/LICENSE`、`astrbot/EULA.md` | 上游许可证与 EULA |
| `runtime_bootstrap.py` | 上游运行时引导（SSL/CA 兼容补丁） |
| `requirements.txt` | 与上游一致（未增删依赖；统一网关所需 fastapi/hypercorn/httpx/websockets 均为上游既有依赖） |

上游的测试、文档、changelog、dashboard 前端源码等非运行必需内容未纳入。

## 本仓库对 AstrBot 的调用方式

`main.py` 以**库方式**在进程内驱动 AstrBot，而非复制粘贴其入口逻辑：

- `astrbot.core.core_lifecycle.AstrBotCoreLifecycle` — 核心生命周期（进程内启动）
- `astrbot.dashboard.server.AstrBotDashboard` — 仪表盘（复用其 FastAPI 应用，见下）
- `astrbot.core.updater.AstrBotUpdater` — 仪表盘静态资源自愈

**唯一的关键插接点**：`stack/napcat_proxy.py::mount_napcat_proxy()` 把 `/napcat`
反向代理挂载到 AstrBot 仪表盘的同一个 FastAPI 应用上，实现双 WebUI 同端口。

## 同步上游更新

```bash
git remote add astrbot https://github.com/AstrBotDevs/AstrBot.git
git fetch astrbot master
git checkout astrbot/master -- astrbot/ runtime_bootstrap.py
# requirements.txt 需人工比对合并
# 然后更新本文件中的基线提交号
```

更新后请运行 `tests/` 下的测试确认集成层仍然兼容。
