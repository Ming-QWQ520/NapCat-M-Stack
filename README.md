<div align="center">

# NapCat-M Stack

**NapCat-M + AstrBot 真正的一体化项目：一个仓库、一条命令、一个进程树、一个端口。**

`python main.py` → 扫码 → 填 Key → 开聊 🎣

</div>

---

## 这是什么

本仓库把 **[NapCat-M](https://github.com/Ming-QWQ520/NapCatQQ-M)**（QQNT / OneBot v11 协议端）与
**[AstrBot](https://github.com/AstrBotDevs/AstrBot)**（LLM Bot 框架）整合为**一个项目**：

- **不再是脚本编排**——AstrBot 以源码内嵌于本仓库（见 [VENDORED-ASTRBOT.md](VENDORED-ASTRBOT.md)），
  由统一入口 `main.py` 在**同一进程内**驱动其核心生命周期与仪表盘
- **一个进程树**——`python main.py` 是唯一主进程，QQ（内嵌 NapCat-M）是其受监督子进程；
  QQ 崩溃则整栈退出，交给 `restart: unless-stopped` 或用户重启
- **一个端口**——6185 同时服务两套 WebUI：
  - `/` → **AstrBot 控制台**（填大模型 API Key / 人格 / 插件市场 / 对话）
  - `/napcat/` → **NapCat WebUI**（QQ 扫码登录 / 协议端网络配置 / 日志 / 终端）
  - NapCat 自带的 WebUI 被固定绑定在容器内 `127.0.0.1:6099`，只经统一网关的
    `/napcat` 反向代理对外，**不再需要暴露第二个端口**
- **零接线**——首次启动自动完成全部配置：
  - AstrBot 侧自动创建 `aiocqhttp`（OneBot v11）平台，监听 `6199` 反向 WS
  - NapCat 侧预置反向 WS 配置（`ws://127.0.0.1:6199/ws`），新登录的 QQ 号自动继承
  - NapCat WebUI 静态资源自动重写为 `/napcat` 子路径（挂载进 AstrBot 的同一 FastAPI 应用）

```
python main.py                     ← 唯一主进程
├── AstrBot 核心 + 仪表盘（进程内运行，非子进程）
│   └── 统一网关 :6185
│       ├── /             AstrBot WebUI
│       └── /napcat/...   ──反向代理──▶  NapCat WebUI（127.0.0.1:6099，仅本机）
└── QQ（内嵌 NapCat-M）             ← 受监督子进程
    └── 反向 WS ──▶ 127.0.0.1:6199 ──▶ AstrBot aiocqhttp 平台
```

> [!WARNING]
> 请使用 **QQ 专用小号**，协议端方案存在风控风险。6185 是唯一需要开放的端口，
> 请勿把本服务直接暴露到公网（如需远程访问，建议套 SSH 隧道或带鉴权的前置反代）。

## 快速开始

### 方式一：Docker（推荐，服务器/Linux）

```bash
git clone https://github.com/Ming-QWQ520/NapCat-M-Stack
cd NapCat-M-Stack
docker compose up -d --build
```

构建时会自动下载 NapCat-M 产物并完成 WebUI 子路径重写（网络受限可用
`--build-arg NAPCAT_ZIP_URL=` 指向镜像源；也可先跑
`bash scripts/prepare-napcat.sh` 把产物放进构建上下文）。

### 方式二：Windows 原生

```powershell
git clone https://github.com/Ming-QWQ520/NapCat-M-Stack
cd NapCat-M-Stack\windows
powershell -ExecutionPolicy Bypass -File install.ps1
```

安装器会交互选择部署形态（也可用 `-Flavor` 参数直接指定，便于无人值守）：

| 形态 | 说明 | 适用 |
| --- | --- | --- |
| **Node 便携版**（默认，推荐） | 下载 `NapCat.Shell.Windows.Node.zip`（约 118 MB）：自带无头 QQ 与 Node.js 运行时，**免安装 QQ、免注入**，装完即用 | 干净机器 / 不想装 QQ |
| **OneKey 注入版** | 下载 `NapCat.Shell.Windows.OneKey.zip`（约 1 MB）：由 `NapCatInstaller.exe` 部署便携 QQ 并注入 NapCat，需在安装后**手动运行一次**；注意其内置的 NapCat 下载源已随上游停维失效，失败时请改用 Node 便携版 | 带宽受限 / 愿意多一步手动操作 |

两种形态可随时重跑 `install.ps1 -Flavor ...` 切换；同时存在时默认优先 Node 版，
可用环境变量 `NAPCAT_FLAVOR=onekey` 强制。

之后日常使用：双击 `windows\start.bat`。

### 方式三：Linux / macOS 原生

```bash
git clone https://github.com/Ming-QWQ520/NapCat-M-Stack
cd NapCat-M-Stack
bash scripts/prepare-napcat.sh   # 下载 NapCat-M 产物并完成 /napcat 子路径重写
sudo bash scripts/wire-qq.sh     # 把 NapCat 接进 QQ（可逆：--rollback）
./start.sh                       # 自动准备 venv、依赖，然后启动整栈
```

> 原生 Linux/macOS 需要**已安装 QQNT**（Linux 版安装方法见
> [NapCatQQ-M 文档](https://github.com/Ming-QWQ520/NapCatQQ-M/blob/main/docs/INSTALL-Linux-macOS.md)）。
> 若 QQ 不在默认路径，用环境变量 `QQ_PATH` 指定，或用 `NAPCAT_QQ_CMD` 覆盖整条启动命令。
> 无显示服务器时自动尝试 `xvfb-run`。
>
> **完整教程**（QQNT 安装、接线原理、systemd 开机自启、升级与排障）：
> [docs/deploy-linux-native.md](./docs/deploy-linux-native.md)

### 方式四：宝塔面板（Linux 服务器）

已在用宝塔面板的服务器，一条命令完成环境准备，再用面板的
「进程守护管理器」常驻，可选挂域名 + HTTPS：

```bash
bash <(curl -sSL https://raw.githubusercontent.com/Ming-QWQ520/NapCat-M-Stack/main/scripts/baota-setup.sh) --mirror
```

> **完整教程**（QQNT 安装、守护进程配置、Nginx 反代 WebSocket/SSE 片段、
> 升级与 FAQ）：[docs/deploy-baota.md](./docs/deploy-baota.md)

## 三步上手

```
起栈 → 扫码 → 填 Key
```

1. **起栈**：按上面任一方式启动，浏览器打开 `http://<主机IP>:6185`
2. **扫码**：进入 `http://<主机IP>:6185/napcat/`，用账户 `napcat` + **与
   AstrBot 仪表盘相同的密码**登录（密码以 AstrBot 为准：在 AstrBot 控制台
   改密后 NapCat 无需重启即同步生效），然后用 QQ 专用小号扫码登录
3. **填 Key**：回到 `http://<主机IP>:6185/`，AstrBot 控制台里填大模型 API Key、
   设人格、逛插件市场

接线已经自动完成——扫码成功后 NapCat 会反向 WS 连上 AstrBot（日志出现
`aiocqhttp(OneBot v11) 适配器已连接`），用另一个 QQ 给小号发消息即可开聊。

两个 WebUI 之间可直接跳转：AstrBot → NapCat 把地址改为 `/napcat`；
NapCat → AstrBot 点侧边栏顶部「AstrBot 控制台」。两边登录凭证相互独立，
来回切换不会被登出；而登录**密码**两边一致（以 AstrBot 为准），
只需记一套（需 NapCat-M v4.18.44 及以上）。

## 端口与路径

| 端口 | 用途 | 是否对外 |
| --- | --- | --- |
| **6185** | 统一网关（AstrBot `/` + NapCat `/napcat/`） | ✅ 唯一需要开放的端口 |
| 6199 | AstrBot aiocqhttp 反向 WS 监听 | ❌ 仅本机/容器内 |
| 6099 | NapCat WebUI 内部端口 | ❌ 仅绑定 127.0.0.1，经网关代理 |

| 路径 | 说明 |
| --- | --- |
| `data/` | AstrBot 数据 + NapCat 配置（`data/napcat/config/`）+ QQ 登录态（Docker 与 Windows Node 便携版：`data/qq/`） |
| `napcat/` | NapCat-M Shell 产物（prepare 脚本生成，已含子路径重写） |
| `astrbot/` | 内嵌的 AstrBot 源码（未修改，AGPL-3.0） |
| `stack/` | 集成层：网关代理、子进程监督、WebUI 重写器、自动接线 |
| `main.py` | 唯一入口 |

## 统一网关是怎么做到的

NapCat WebUI 前端（vite 构建）把所有网络路径硬编码为根绝对路径（`/webui/*`、`/api/*`、
`/files/*`、`/plugin/*`），而 AstrBot 仪表盘同样占用 `/` 与 `/api/*`。同端口共存的关键在
`stack/webui_patch.py`：在准备阶段对 NapCat WebUI 静态产物做**确定性的子路径重写**
（axios 基址、SPA 路由 basename、SSE/WS 端点、资源 URL、CSS 字体引用共 30+ 处，
规则幂等且对真实构建产物逐处验证），再由 `stack/napcat_proxy.py` 把 `/napcat/<path>`
剥前缀转发给只监听本机的 NapCat 后端：

- HTTP 全方法流式透传（SSE 长连接友好）
- WebSocket 双向泵（WebUI 终端 `/api/ws/terminal` 与调试 `/api/Debug/ws`）
- JSON 响应体站内路径自动加前缀（如插件图标 URL）
- `Location` 重定向头改写（`/` → `/napcat/webui`）
- NapCat 未就绪时返回 503（API 走 NapCat 风格 JSON，页面走自动刷新的等待页）

代理被挂载进 AstrBot 仪表盘的**同一个 FastAPI 应用**（插入路由表最前，避开其静态
兜底路由），因此两套 WebUI 共享同一个 hypercorn 监听、同一套 TLS/日志配置。

## 常用配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `STACK_PORT` | `6185` | 统一网关端口 |
| `NAPCAT_ACCOUNT` | 空 | 预先指定 QQ 号（配合快速登录） |
| `NAPCAT_QQ_CMD` | 平台自动 | 完整覆盖 QQ/NapCat 启动命令（空格分隔，路径含空格时用引号包裹） |
| `NAPCAT_FLAVOR` | `auto` | Windows 部署形态偏好：`auto`（Node 优先）/ `node` / `onekey` |
| `QQ_PATH` | `/opt/QQ/qq` | Linux 原生部署时 QQ 可执行文件路径 |
| `STACK_AUTO_WIRE` | `1` | 首次启动自动创建 AstrBot 的 OneBot 平台 |
| `STACK_EXIT_WITH_NAPCAT` | `1` | QQ 子进程退出时整栈退出 |
| `STACK_SHARED_NAPCAT_PASSWORD` | `1` | NapCat WebUI 与 AstrBot 仪表盘共用登录密码（以 AstrBot 为准）；置 `0` 回退为 NapCat 独立密码 |
| `NAPCAT_UID` / `NAPCAT_GID` | `1000` | Docker 下运行用户（对齐宿主机避免权限问题） |

AstrBot 自身配置（仪表盘端口/用户名密码/提供商等）照常在 AstrBot WebUI 里改。

## 常见问题

**Q: 打开 `/napcat/` 一直显示「NapCat 正在启动」？**
QQ 启动需要 10~60 秒（容器内首次更慢）。长时间停留请看启动日志中 `[NapCat]` 前缀
的输出；若 QQ 崩溃，整栈会退出并由 restart 策略拉起。

**Q: 重新部署后要重新扫码吗？**
不用。QQ 登录态持久化在数据卷（Docker：`./data/qq`；原生：QQ 自身数据目录）。

**Q: 我想分别访问原来的两个端口？**
NapCat 的 6099 已固定只绑 127.0.0.1（安全考虑，统一走 `/napcat`）。AstrBot 仪表盘
就是 6185 本身。如确实需要独立端口，请自行在宿主机配置反代。

**Q: NapCat WebUI 的登录账户和密码是什么？**
账户固定 `napcat`；**密码与 AstrBot 仪表盘完全一致（以 AstrBot 为准）**——
AstrBot 首次启动会在控制台打印随机初始密码（搜索 `初始密码` 或
`generated`），登录 AstrBot 后按提示修改；在 AstrBot 控制台改密后，
NapCat 无需重启即接受新密码（按配置文件 mtime 实时同步）。想改密码请
去 AstrBot 控制台，NapCat 侧不再单独改密。

> 想让 NapCat 用独立密码：设 `STACK_SHARED_NAPCAT_PASSWORD=0` 重启，
> NapCat 会在启动日志里生成并打印自己的初始密码（首次登录强制修改，
> 需含英文和数字，长度 6-12 位，保存在 `data/napcat/config/webui.json`）。

**Q: AstrBot 怎么升级？**
按 [VENDORED-ASTRBOT.md](VENDORED-ASTRBOT.md) 的流程同步上游源码即可；集成层
（`stack/`）对 AstrBot 只依赖其公开的库接口，改动面极小。

**Q: 支持别的 OneBot 框架吗？**
NapCat-M 是标准 OneBot v11 协议端。想换 Lagrange 等其它实现：停用栈内 QQ
（`STACK_EXIT_WITH_NAPCAT=0`），把 `NAPCAT_QQ_CMD` 指向你的协议端启动命令即可，
AstrBot 侧无需任何改动。

## 开发与测试

```bash
./venv/bin/python -m pytest tests/test_webui_patch.py   # 重写器单元测试
bash scripts/e2e-test.sh                                # 需先以 mock 后端启动整栈：
NAPCAT_QQ_CMD="./venv/bin/python tests/mock_napcat_webui.py 6099" ./venv/bin/python main.py
```

`tests/mock_napcat_webui.py` 是 NapCat WebUI 后端的行为模拟器（静态/SSE/WS/JSON 路径
改写均有覆盖），用于无 QQ 环境下端到端验证统一网关。

## 许可

本仓库整体以 **AGPL-3.0** 发布（与内嵌的 AstrBot 一致），见 [LICENSE](LICENSE) 与
[VENDORED-ASTRBOT.md](VENDORED-ASTRBOT.md)。NapCat-M 产物在部署时从其 Release 下载，
许可遵循上游。使用请遵守当地法律法规，QQ 账号风控风险自负。
