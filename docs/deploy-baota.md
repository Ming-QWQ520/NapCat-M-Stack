# 宝塔面板（BT Panel）部署教程

适用场景：服务器装了**宝塔面板**，想用面板自带的 **Python 项目管理器**托管
NapCatQQ-M（进程守护、日志、开机自启全交给面板），一条命令 `python bt-main.py`
直接启动。

Docker 部署见仓库根 README；不依赖面板的裸机部署见
[deploy-linux-native.md](./deploy-linux-native.md)（本教程与其共享 QQ 安装、
接线原理等章节）。

---

## 0. 你最终会得到什么

```
python bt-main.py（由宝塔 Python 项目管理器拉起）  ← 唯一主进程
├── AstrBot 核心 + 仪表盘（进程内运行）
│   └── 统一网关 :6185
│       ├── /            AstrBot WebUI
│       └── /napcat/...  NapCat WebUI（代理到仅本机的 6099）
└── QQ（内嵌 NapCat）                          ← 受监督子进程
    └── 反向 WS → 127.0.0.1:6199 → AstrBot aiocqhttp 平台
```

`bt-main.py` 是 `main.py` 的**宝塔适配外壳**：自动检查并补齐 Python 依赖、
NapCat 产物、QQ 接线，然后把控制权原样交给统一入口 `main.py`。两者的进程树、
端口、行为完全一致。

## 1. 前置条件

| 依赖 | 说明 | 检查命令 |
| --- | --- | --- |
| 宝塔面板 7.x / 8.x / 9.x | 软件商店安装「**Python 项目管理器**」 | 面板 → 软件商店 |
| Python ≥ 3.10 | 项目管理器里可安装多版本，推荐 3.12 | 项目管理器 → 版本列表 |
| Linux QQNT | NapCat 的宿主，见第 2 步 | `ls /opt/QQ` |
| xvfb | 无桌面服务器必需 | `command -v xvfb-run` |
| 磁盘 ≥ 3 GB | QQ + 依赖 + 数据 | - |

SSH 一键补齐系统包（不含 QQ）：

```bash
sudo apt update
sudo apt install -y git xvfb          # Debian / Ubuntu
# sudo dnf install -y git xorg-x11-server-Xvfb   # RHEL / CentOS / openEuler
```

## 2. 安装 Linux 版 QQNT

与裸机部署完全相同，见
[deploy-linux-native.md 第 2 步](./deploy-linux-native.md#2-安装-linux-版-qqnt)：
从 [linux.qq.com](https://linux.qq.com/) 下载 deb/rpm 安装，装好后初始化一次
（无桌面：`xvfb-run -a /opt/QQ/qq` 等 10 秒左右 Ctrl+C）。

> 不想装完整 QQ？Windows 用户可用 Node 便携版（免 QQ 免注入），但 Linux 侧
> 目前需要 QQNT 宿主。

## 3. 获取代码

方式 A（面板）：宝塔「文件」上传代码 zip 到 `/www/wwwroot/` 并解压为
`/www/wwwroot/napcatqq-m`；

方式 B（SSH）：

```bash
cd /www/wwwroot
git clone https://github.com/Ming-QWQ520/NapCatQQ-M napcatqq-m
```

## 4. 面板创建 Python 项目

宝塔面板 → **网站** → **Python 项目** → **添加 Python 项目**
（若菜单里没有，先去「软件商店」安装「Python 项目管理器」）：

| 表单项 | 填写 | 说明 |
| --- | --- | --- |
| 项目目录 | `/www/wwwroot/napcatqq-m` | 第 3 步的代码目录 |
| Python 版本 | 3.10 及以上 | 项目管理器内可安装 |
| 框架/启动方式 | `python`（通用命令行） | 不是 Flask/Django，选通用 |
| 启动文件 | `bt-main.py` | 仓库根目录下 |
| 端口 | `6185` | 统一网关唯一对外端口 |
| 依赖安装 | 可留空 | `bt-main.py` 首次启动会自动 `pip install -r requirements.txt`（镜像优先） |

点击启动。首次启动耗时较长（装依赖 + 下载 NapCat 产物约 60 MB + QQ 接线），
在面板「日志」里能看到全部过程：

```
==================== NapCatQQ-M · 宝塔适配入口 ====================
[OK] 项目根目录: /www/wwwroot/napcatqq-m
[OK] 检测到宝塔面板环境（/www/server）。
[..] 首次运行：安装 Python 依赖（耗时数分钟，请耐心等待）……
[OK] Python 依赖就位。
[..] 首次运行：准备 NapCat 产物（下载 + WebUI 子路径重写）……
[OK] NapCat WebUI 子路径重写完成: ...
[..] 检测到 QQ（/opt/QQ/resources/app）尚未接入 NapCat，自动执行 scripts/wire-qq.sh ……
[OK] 已建立符号链接: /opt/QQ/resources/app/napcat -> ...
[OK] 自举完成，交棒统一入口 main.py ……
（NapCatQQ-M 大横幅）
[NapCat] [WebUi] WebUI 已启用账户密码登录（与 AstrBot 共用密码）
[NapCat] [WebUi] 登录账户: napcat
```

## 5. 放行端口与三步上手

1. 宝塔「安全」+ 云厂商安全组放行 **6185**（TCP）；
2. 浏览器打开 `http://<服务器IP>:6185`，按日志里的初始密码登录 AstrBot；
3. 进入 `http://<服务器IP>:6185/napcat/`，用账户 `napcat` + **AstrBot 的
   同一密码**登录（两套面板共用密码，以 AstrBot 为准），用 QQ **专用小号**
   扫码；
4. 扫码成功后日志出现 `aiocqhttp(OneBot v11) 适配器已连接`，回 AstrBot
   控制台填大模型 API Key 即可开聊。

> [!WARNING]
> 请勿把 6185 直接暴露到公网长期使用；如需远程访问，建议在宝塔建站点做
> 反向代理并加证书/密码，或用 SSH 隧道。

## 6. 命令行直接运行（调试等价入口）

面板外用 SSH 直接跑，行为与面板内完全一致（Ctrl+C 优雅退出）：

```bash
cd /www/wwwroot/napcatqq-m
python bt-main.py               # 用当前 Python；缺依赖自动装
python bt-main.py --port 6200   # 换统一网关端口
```

传统入口也依然可用：`./start.sh`（自动建 venv 后执行 `python main.py`）。

## 7. QQ 接线与权限说明

`bt-main.py` 启动时会自检 QQ 接线状态（`/opt/QQ/resources/app` 的 `napcat`
链接与 `package.json` 的 `main` 字段）：

- **以 root 运行**（宝塔 Python 项目默认多为 root）：未接线时自动执行
  `scripts/wire-qq.sh`，全程无需人工介入；QQ 升级导致接线丢失时，重启项目
  即自动重接；
- **以普通用户（如 www）运行**：无写入 `/opt/QQ` 权限时跳过自动接线，
  请先手动执行一次：

  ```bash
  sudo bash /www/wwwroot/napcatqq-m/scripts/wire-qq.sh
  ```

  并把项目目录属主交给运行用户：`chown -R www:www /www/wwwroot/napcatqq-m`。

接线可随时回滚：`sudo bash scripts/wire-qq.sh --rollback`（原理与细节见
[deploy-linux-native.md 第 3 步](./deploy-linux-native.md#3-获取代码并接线)）。

## 8. 常见问题

**Q：项目启动失败 / 反复重启？**
看面板「日志」，自举阶段的 `[!]` 行会给出明确原因（缺 QQ、依赖装失败、
端口占用等）；修好后重启项目。

**Q：日志提示「未检测到 Linux QQNT」**
按第 2 步安装 QQ；装在非默认位置时在项目的环境变量里加
`QQ_PATH=<qq 可执行文件路径>` 后重启。

**Q：日志提示「未找到 xvfb-run」**
`sudo apt install -y xvfb`（RHEL 系：`dnf install xorg-x11-server-Xvfb`）。

**Q：6185 端口被占用**
启动文件参数改 `bt-main.py --port 6200`（或环境变量 `STACK_PORT`），并在
面板项目设置、安全组同步改端口。

**Q：依赖安装很慢 / 失败**
`bt-main.py` 默认优先清华镜像源；也可在项目环境变量里设
`PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/` 换源。

**Q：想用域名 + HTTPS 访问**
宝塔「网站 → 添加站点（纯静态）」→「反向代理」目标填
`http://127.0.0.1:6185`，并开启「WebSocket 支持」（NapCat WebUI 终端与
实时日志需要）。

**Q：升级**
```bash
cd /www/wwwroot/napcatqq-m
git pull
bash scripts/prepare-napcat.sh      # NapCat 有新版本时刷新产物
```
然后在面板里重启项目。

**Q：备份 / 迁移**
所有状态都在项目的 `data/` 目录（AstrBot 数据 + NapCat 配置 + QQ 登录态），
整体打包即可。

**Q：内存占用偏高**
QQ（Electron）本身占用 600MB+，属正常现象。

## 9. 与其它部署方式的取舍

| | Docker | 裸机（systemd） | 宝塔（本教程） |
| --- | --- | --- | --- |
| 环境隔离 | 容器自带 QQ/Xvfb | 与系统共用 | 与系统共用 |
| 进程守护 | restart 策略 | systemd | 面板项目管理器 |
| 日志 | docker logs | journalctl | 面板日志页 |
| 适合 | 服务器长期运行 | 桌面机、NAS | 已在用宝塔的服务器 |

三种方式的 `data/` 目录结构一致，迁移时整体拷贝即可。
