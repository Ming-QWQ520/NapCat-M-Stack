# 宝塔面板部署教程（Linux）

适用场景：服务器上装有[宝塔面板](https://www.bt.cn/new/download.html)（宝塔 Linux 面板 7.x / 8.x），
希望在面板里统一管理进程、用宝塔 Nginx 挂域名/HTTPS 的用户。
纯命令行 / systemd 部署见 [deploy-linux-native.md](./deploy-linux-native.md)；
Docker 部署见仓库根 README；宝塔 **Windows** 面板请直接用仓库的
`windows\install.ps1`，本教程不适用。

教程目标：从一台只装了宝塔面板的服务器，到 `http://<服务器IP>:6185` 打开
AstrBot 控制台、`http://<服务器IP>:6185/napcat/` 打开 NapCat WebUI，扫码开聊。

---

## 0. 整体结构（与裸机部署相同）

```
bash start.sh（由宝塔守护进程常驻）        ← 唯一主进程
├── AstrBot 核心 + 仪表盘（进程内运行）
│   └── 统一网关 :6185
│       ├── /            AstrBot WebUI
│       └── /napcat/...  NapCat WebUI（代理到仅本机的 6099）
└── QQ（内嵌 NapCat-M）                  ← 受监督子进程
    └── 反向 WS → 127.0.0.1:6199 → AstrBot aiocqhttp 平台
```

宝塔面板在这里扮演三个角色：**终端**（装依赖）、**守护进程管理器**（常驻与自启）、
**可选的 Nginx 反代**（域名 / HTTPS / 只开 80、443 端口）。栈本身只占用
6185 一个端口，与宝塔的 80/443/888 不冲突。

## 1. 前置条件

| 依赖 | 说明 |
| --- | --- |
| 宝塔 Linux 面板 7.x / 8.x | 已安装并可登录面板 |
| Debian 11+ / Ubuntu 20.04+ / RHEL 8+ | 与宝塔自身要求一致 |
| 2 GB 以上内存 | QQ（Electron）本身约 600 MB |
| 磁盘 ≥ 5 GB | 代码 + 产物 + QQ + 数据 |
| root 或 sudo | 宝塔终端默认 root |

> QQ 风控提示：第三方 QQNT 方案存在风控风险，务必使用**专用小号**，
> 并保持服务器 IP 稳定、不要多端同时登录同一小号。

## 2. 一键准备（宝塔终端）

登录宝塔面板 → 左侧菜单「终端」，粘贴执行：

```bash
bash <(curl -sSL https://raw.githubusercontent.com/Ming-QWQ520/NapCat-M-Stack/main/scripts/baota-setup.sh) --mirror
```

脚本做的事（全部幂等，重跑安全）：

1. 安装系统依赖：`git`、`curl`、`xvfb`（无桌面服务器跑 QQ 必需）、`python3-venv`；
2. 克隆代码到 `/www/wwwroot/napcat-m-stack`（宝塔惯例目录）；
3. 下载 NapCat-M Shell 产物并完成 WebUI `/napcat` 子路径重写；
4. 创建 `venv/` 并安装 AstrBot 依赖（`--mirror` 走清华 pip 源，国内服务器建议带上）。

> GitHub 直连不畅时，可先在面板「文件」里上传代码 zip 解压到
> `/www/wwwroot/napcat-m-stack`，再进目录执行
> `bash scripts/baota-setup.sh --mirror`（脚本检测到代码已存在会跳过克隆）。

## 3. 安装 Linux 版 QQNT 并接线

宝塔终端继续执行（脚本结束时也会打印同样的提示）：

1. 从 [QQ 官网](https://linux.qq.com/) 下载最新版（NapCat-M 当前对应 QQ 9.9.x）：

   ```bash
   # Ubuntu / Debian（文件名以官网实际为准）
   sudo apt install ./linuxqq_*.deb
   # RHEL / CentOS / openEuler
   # sudo dnf install ./linuxqq_*.rpm
   ```

2. **先正常启动一次再退出**（QQ 需要初始化用户目录；无桌面用 xvfb 包装）：

   ```bash
   xvfb-run -a /opt/QQ/qq    # 等 10 秒左右 Ctrl+C
   ```

3. 把栈内 NapCat 接进 QQ（可逆，详细原理见裸机教程）：

   ```bash
   cd /www/wwwroot/napcat-m-stack
   sudo bash scripts/wire-qq.sh
   ```

   > QQ 装在非默认路径：`sudo bash scripts/wire-qq.sh --qq-dir <resources/app 路径>`，
   > 并在下一步的守护进程环境里加 `QQ_PATH=<qq 可执行文件>`。

## 4. 在宝塔里常驻运行（二选一）

### 方式 A：进程守护管理器（推荐，最省心）

1. 面板左侧「软件商店」→ 搜索 **进程守护管理器**（Supervisor）→ 安装并打开；
2. 「添加守护进程」，按下表填写：

   | 字段 | 值 |
   | --- | --- |
   | 名称 | `napcat-m-stack` |
   | 启动用户 | `root`（宝塔终端默认；QQ 需要能创建虚拟显示） |
   | 运行目录 | `/www/wwwroot/napcat-m-stack` |
   | 启动命令 | `bash /www/wwwroot/napcat-m-stack/start.sh` |
   | 进程数量 | 1 |

3. 保存后进程自动启动，状态应为「运行中」。日志在守护管理器里直接看
   （ stdout 即栈日志，含 `[NapCat]` 前缀的 QQ 输出）。

start.sh 会自己完成 venv / 依赖 / 产物检查后 `exec python main.py`，
退出后由 Supervisor 自动拉起——相当于面板版 systemd。

### 方式 B：网站 → Python 项目

新版宝塔（≥ 7.9）也可以用「网站 → Python项目 → 添加Python项目」：

| 字段 | 值 |
| --- | --- |
| 项目路径 | `/www/wwwroot/napcat-m-stack`（含 `main.py`） |
| Python 版本 | 面板安装的 3.10+，或直接用已就绪的栈内 venv |
| 启动方式 | python / 自定义命令：`/www/wwwroot/napcat-m-stack/venv/bin/python main.py` |
| 端口 | `6185` |
| 是否安装依赖 | 选**否**（`baota-setup.sh` 已用栈内 venv 装好，避免双 venv 重复安装） |

> 两种方式**不要同时用**，会双开抢占 6185 端口。

## 5. 放行端口并访问

1. 面板「安全」→ 放行端口 `6185`（TCP）；
2. 云服务器还需要在厂商控制台的安全组放行 `6185`；
3. 浏览器访问：

   | 地址 | 内容 | 登录 |
   | --- | --- | --- |
   | `http://<服务器IP>:6185/` | AstrBot 控制台 | 账户见 AstrBot 启动日志（首次为随机初始密码，登录后按提示修改） |
   | `http://<服务器IP>:6185/napcat/` | NapCat WebUI | 账户 `napcat`，**密码与 AstrBot 仪表盘一致**（以 AstrBot 为准，改密请去 AstrBot） |

4. NapCat WebUI 里用 QQ **专用小号**扫码；扫码成功后 AstrBot 日志出现
   `aiocqhttp(OneBot v11) 适配器已连接`，回 AstrBot 控制台填大模型 API Key 即可开聊。

> 生产环境建议走第 6 步的域名 + HTTPS，不开裸 6185。

## 6. （可选）宝塔 Nginx 反向代理 + HTTPS

给栈挂域名、套证书，只对外暴露 80/443：

1. 面板「网站」→「PHP项目/静态」随意添加一个站点绑定你的域名（不用真放内容），
   并在「SSL」里申请证书（Let's Encrypt 或宝塔证书）；
2. 站点「设置 → 反向代理 → 添加反向代理」：
   - 代理名称：`napcat-m-stack`
   - 目标 URL：`http://127.0.0.1:6185`
3. 宝塔生成的反代默认**不带 WebSocket 支持**，而栈的 WebUI 终端、日志实时流
   （SSE）和 QQ 扫码相关长连接都需要。打开该站点的配置文件
   （设置 → 配置文件），在 `server {}` 内加入/替换：

   ```nginx
   # -- NapCat-M Stack 反代（覆盖宝塔默认 proxy 配置） --
   location / {
       proxy_pass http://127.0.0.1:6185;
       proxy_http_version 1.1;
       # WebSocket（NapCat 终端 / 调试）
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       # 长连接：扫码 / 终端 / 日志流
       proxy_read_timeout 3600s;
       proxy_send_timeout 3600s;
       # SSE 日志流需要关闭缓冲
       proxy_buffering off;
   }
   ```

   保存后 Nginx 自动 reload。之后用 `https://<域名>/` 与
   `https://<域名>/napcat/` 访问，6185 端口可以在「安全」里关闭对外。

## 7. 日常升级

宝塔终端执行（或在守护管理器里先停止进程）：

```bash
cd /www/wwwroot/napcat-m-stack
git pull
bash scripts/prepare-napcat.sh      # NapCat-M 有新版本时刷新产物
sudo bash scripts/wire-qq.sh        # 仅当 QQ 客户端升级过才需要重跑
```

然后在进程守护管理器里「重启」。数据全部在 `data/`，升级不影响登录态。

## 8. 常见问题

**Q：守护进程一直重启 / 日志里 QQ 起不来**
先手动跑一次看真实报错：`cd /www/wwwroot/napcat-m-stack && bash start.sh`。
最常见原因是没装 xvfb（`apt install xvfb`）或 QQ 未完成首次初始化（第 3 步第 2 小步）。

**Q：用非 root 用户跑守护进程行不行**
可以，但该用户需要能启动 QQ、能写 `/www/wwwroot/napcat-m-stack/data/`；
QQ 在部分内核下还需要放宽限制（Supervisor 配置里加 `minfds=65535`）。
拿不准就用 root——宝塔本身也是 root 运行的。

**Q：想换端口**
守护进程的环境变量里加 `STACK_PORT=6190`（NapCat 内部端口用
`NAPCAT_WEBUI_PORT` 调整），Nginx 反代的 `proxy_pass` 同步修改。

**Q：内存占用偏高**
QQ（Electron）本身 600 MB+，属正常现象；1 GB 内存的小机器建议加 2 GB swap。

**Q：和宝塔自带的 Python 项目管理器冲突吗**
不冲突。栈自带独立 `venv/`，不使用面板安装的 Python 站点包；
方式 B 里记得勾选「不安装依赖」，避免面板再建一个 venv 重复下载。

**Q：数据怎么备份**
宝塔「文件」里把 `/www/wwwroot/napcat-m-stack/data/` 打包下载即可
（AstrBot 数据 + NapCat 配置 + QQ 登录态全在里面）。

## 附录：与其它部署方式的取舍

| | 宝塔（本教程） | 裸机 systemd | Docker |
| --- | --- | --- | --- |
| 进程管理 | 面板可视化守护 | systemd unit | 容器 restart 策略 |
| 域名/HTTPS | 面板一键证书 + 反代 | 手工 Nginx | 手工/面板反代 |
| 环境隔离 | 与系统共用 | 与系统共用 | 容器隔离，QQ 升级不烦人 |
| 适合 | 已在用宝塔的服务器 | 纯命令行运维 | 全新服务器、多实例 |
