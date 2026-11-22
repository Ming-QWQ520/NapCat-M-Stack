# Linux 裸机（非 Docker）部署教程

适用场景：不想用 Docker 的 Linux 服务器 / 桌面 / NAS 系统。macOS 用户请看
文末「macOS 差异」；Docker 部署见仓库根 README。

教程目标：从一台干净的 Linux 机器，到 `http://<IP>:6185` 打开 AstrBot
控制台、`http://<IP>:6185/napcat/` 打开 NapCat WebUI，扫码开聊。

---

## 0. 你最终会得到什么

```
python main.py（由 start.sh / systemd 拉起）      ← 唯一主进程
├── AstrBot 核心 + 仪表盘（进程内运行）
│   └── 统一网关 :6185
│       ├── /            AstrBot WebUI
│       └── /napcat/...  NapCat WebUI（代理到仅本机的 6099）
└── QQ（内嵌 NapCat-M）                          ← 受监督子进程
    └── 反向 WS → 127.0.0.1:6199 → AstrBot aiocqhttp 平台
```

Docker 镜像里自带 QQ 和虚拟显示；裸机部署这两样需要你自己装——本教程
第 1、3 步就是在补齐它们。

## 1. 前置条件

| 依赖 | 说明 | 检查命令 |
| --- | --- | --- |
| Linux x64 / arm64 | Debian 11+、Ubuntu 20.04+、RHEL 系均可 | `uname -m` |
| Python 3.10+ | 3.12 最佳；`start.sh` 会自建 venv | `python3 --version` |
| git / curl | 拉代码、下产物 | `git --version` |
| QQNT（Linux 版） | NapCat 的宿主，见第 2 步 | `ls /opt/QQ` |
| xvfb | **仅无桌面环境的服务器需要** | `command -v xvfb-run` |
| sudo / root | 写入 `/opt/QQ`（接线用） | - |

Debian / Ubuntu 一键补齐（不含 QQ）：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl xvfb
```

## 2. 安装 Linux 版 QQNT

从 [QQ 官网](https://linux.qq.com/) 下载最新版（NapCat-M 当前对应
QQ 9.9.x），Debian 系用 deb、RHEL 系用 rpm：

```bash
# 示例：Ubuntu / Debian（文件名以官网实际为准）
sudo apt install ./linuxqq_*.deb

# RHEL / CentOS / openEuler
# sudo dnf install ./linuxqq_*.rpm
```

装好后**先正常启动一次再退出**（QQ 需要初始化用户目录）：

- 有桌面：直接启动 QQ，看到登录界面后关闭；
- 无桌面：`xvfb-run -a /opt/QQ/qq`，等 10 秒左右 Ctrl+C。

验证安装位置（后文脚本默认这个路径）：

```bash
ls /opt/QQ/resources/app/package.json   # 应当存在
```

> AppImage 用户：不能直接对 `.AppImage` 接线，见[附录 A](#附录-aappimage)。

## 3. 获取代码并接线

```bash
git clone https://github.com/Ming-QWQ520/NapCat-M-Stack
cd NapCat-M-Stack

# 3.1 下载 NapCat-M Shell 产物并完成 WebUI 子路径重写（/napcat 前缀）
bash scripts/prepare-napcat.sh

# 3.2 把 NapCat 接进 QQ（需要 root；QQ 不在默认路径时加 --qq-dir）
sudo bash scripts/wire-qq.sh
```

`wire-qq.sh` 做了三件事，全部可逆：

1. 备份 `package.json` → `package.json.stack-backup`；
2. 建立符号链接 `/opt/QQ/resources/app/napcat` → `仓库/napcat`
   （仓库产物更新后链接自动跟随；想物理复制用 `--copy`）；
3. 把 `package.json` 的 `main` 改为 `./napcat/napcat.mjs`。

回滚随时可用：

```bash
sudo bash scripts/wire-qq.sh --rollback
```

> QQ 不在 `/opt/QQ`：`sudo bash scripts/wire-qq.sh --qq-dir <resources/app 路径>`，
> 或设 `QQ_RESOURCES_DIR` 环境变量；启动侧还要 `export QQ_PATH=<qq 可执行文件>`。

## 4. 启动

```bash
./start.sh              # 前台运行，Ctrl+C 优雅停止
./start.sh --daemon     # 后台运行，日志在 data/stack.log
```

`start.sh` 自动完成：venv 创建、依赖安装、NapCat 产物检查，然后执行
`python main.py`。无显示服务器时会自动用 `xvfb-run` 包装 QQ（需已装 xvfb）。

启动成功后日志里会有：

```
统一网关: http://0.0.0.0:6185  （AstrBot 于 / ，NapCat 于 /napcat/）
 ✨ NapCat WebUI 已接入统一网关
   ➜  http://127.0.0.1:6185/napcat/webui/
   ➜  登录账户 napcat，初始密码见上方 [NapCat] 启动日志（首次登录后需修改）
[NapCat] [WebUi] 初始账户: napcat
[NapCat] [WebUi] 初始密码: xxxxxxxx
```

## 5. 扫码与三步上手

1. **AstrBot**：浏览器打开 `http://<主机IP>:6185`，按日志里的初始密码登录；
2. **NapCat**：访问 `http://<主机IP>:6185/napcat/`，用账户密码登录（默认账户
   `napcat`，初始密码在启动日志中打印，首次登录后强制修改密码），然后用
   QQ **专用小号**扫码登录；
3. **开聊**：扫码成功后日志出现 `aiocqhttp(OneBot v11) 适配器已连接`，
   回到 AstrBot 控制台填大模型 API Key 即可。

两个 WebUI 之间可以直接跳转：

- AstrBot → NapCat：浏览器地址改成 `/napcat`；
- NapCat → AstrBot：侧边栏顶部「AstrBot 控制台」。
  （该入口只在统一网关挂载下显示，独立部署的 NapCat 不受影响。）

登录凭证互相独立，两边来回切换**不会**要求重新登录。

## 6. 开机自启（systemd）

创建 `/etc/systemd/system/napcat-m-stack.service`（把路径和用户换成你的）：

```ini
[Unit]
Description=NapCat-M Stack (AstrBot + NapCat)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# 建议用普通用户跑（该用户需能启动 QQ；xvfb-run 会自动拉起虚拟显示）
User=youruser
WorkingDirectory=/home/youruser/NapCat-M-Stack
ExecStart=/home/youruser/NapCat-M-Stack/start.sh
Restart=on-failure
RestartSec=10
# QQ/Electron 在部分内核下需要放宽限制
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now napcat-m-stack
journalctl -u napcat-m-stack -f        # 跟踪日志
```

## 7. 日常升级

```bash
cd NapCat-M-Stack
git pull
bash scripts/prepare-napcat.sh         # NapCat-M 有新版本时刷新产物
sudo systemctl restart napcat-m-stack  # 或前台用户自行重启
```

符号链接接线方式的优点：`prepare-napcat.sh` 刷新仓库产物后无需重跑接线。

> **QQ 客户端升级会重写 `resources/app`，接线会丢失**：升级 QQ 后重跑一次
> `sudo bash scripts/wire-qq.sh` 即可（备份与链接都会重新建立）。

## 8. 常见问题

**Q：启动报「未找到 QQ 可执行文件」**
A：QQ 装在非默认位置。`export QQ_PATH=/path/to/qq` 后重启；或用
`NAPCAT_QQ_CMD` 直接覆盖整条启动命令（空格分隔，支持引号）。

**Q：服务器没有图形界面，QQ 起不来**
A：确认已装 xvfb（`sudo apt install xvfb`）。栈在检测不到 `DISPLAY` 时会
自动用 `xvfb-run -a` 包装 QQ。扫码不需要看到 QQ 窗口——用 NapCat WebUI
里的二维码即可。

**Q：6185 端口被占用**
A：`export STACK_PORT=6190` 换端口（NapCat 内部端口也可用
`NAPCAT_WEBUI_PORT` 调整）。

**Q：扫码登录后频繁掉线**
A：第三方 QQNT 方案存在风控风险，务必使用专用小号；服务器上保持 IP 稳定、
不要多端同时登录同一小号。

**Q：内存占用偏高**
A：QQ（Electron）本身占用 600MB+，属正常现象。

**Q：想把数据换个位置 / 备份**
A：所有状态都在 `data/`（AstrBot 数据 + NapCat 配置 + QQ 登录态），整体
打包备份即可。

**Q：wire-qq.sh 报「napcat 已存在且不是本脚本产物」**
A：这台机器以前手动装过 NapCat。把 `/opt/QQ/resources/app/napcat` 移走
（`sudo mv /opt/QQ/resources/app/napcat /opt/QQ/resources/app/napcat.old`）
后重跑。

## 附录 A：AppImage 部署

AppImage 是自包含镜像，`resources/app` 在内部只读文件系统里，不能直接
接线。两种办法：

1. **改用 deb/rpm 安装**（推荐）：从 [linux.qq.com](https://linux.qq.com/)
   下载对应包安装后走本教程主流程；
2. **解包 AppImage**：
   ```bash
   ./QQ_*.AppImage --appimage-extract
   sudo mv squashfs-root /opt/QQ
   ```
   之后 `export QQ_PATH=/opt/QQ/AppRun`，再照常 `wire-qq.sh --qq-dir
   /opt/QQ/resources/app`。注意 AppImage 解包目录里 `qq` 可执行文件名可能
   是 `AppRun` 或 `qq`，以实际为准。

## 附录 B：macOS 差异

- QQNT 安装：官网 dmg，资源目录在 `/Applications/QQ.app/Contents/Resources/app`；
- 接线：`sudo bash scripts/wire-qq.sh --qq-dir <该目录>`，逻辑相同；
- **接线后必须重签名**，否则 QQ 拒绝启动：
  `sudo codesign --force --deep --sign - /Applications/QQ.app`；
- `wire-qq.sh --rollback` 回滚后同样要重签一次；
- 无 xvfb：macOS 桌面环境通常不需要虚拟显示；
- WebUI 终端面板在 macOS 不可用（NapCat 上游 pty 原生库限制），消息收发不受影响。

## 附录 C：与 Docker 方式的取舍

| | Docker | 裸机（本教程） |
| --- | --- | --- |
| 环境隔离 | 容器内自带 QQ/Xvfb，宿主干净 | 与系统共用，QQ 升级需重接线 |
| 风控 | 容器痕迹对抗已内置 | 少一层对抗 |
| 资源开销 | 略高（多一层 overlay） | 略低 |
| 排查难度 | 进容器看日志 | 直接看 systemd journal / 前台日志 |
| 适合 | 服务器长期运行 | 桌面机、NAS、想用系统 Python 的场景 |

两种方式的 `data/` 目录结构一致，迁移时整体拷贝即可。
