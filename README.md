<div align="center">

# NapCat-M Stack

**NapCat-M + AstrBot 开箱即用整合包：几条命令，从零到「扫码 → 填 Key → 养鱼」。**

</div>

---

> [!IMPORTANT]
> 本项目把 **[NapCat-M](https://github.com/Ming-QWQ520/NapCatQQ-M)**（QQNT / OneBot v11 协议端，上游 NapCatQQ 停维后的延续分支）与 **[AstrBot](https://github.com/AstrBotDevs/AstrBot)**（LLM Bot 框架）编排为一个开箱即用的栈：
>
> - 协议层**零改动**兼容——AstrBot 原生 aiocqhttp 适配器（OneBot v11）直连 NapCat-M
> - NapCat-M 预配置已内置：新 QQ 号登录后自动以反向 WS 连接 AstrBot，不用手动建网络配置
> - 支持 Docker Compose（Linux / Windows / macOS 服务器）与 Windows 原生一键包两种形态
>
> ⚠️ 请使用 **QQ 专用小号**，协议端方案存在风控风险。切勿把 NapCat 端口暴露到公网。

## 五步上手

```
起栈 → 扫码 → 进 AstrBot → 填 Key/人格 → 开聊
```

### 1. 起栈

**服务器 / Docker（推荐）：**

```bash
git clone https://github.com/Ming-QWQ520/NapCat-M-Stack
cd NapCat-M-Stack
bash scripts/prepare-napcat-m.sh        # 下载 NapCat-M 产物（国内网络可手动下载 zip 放到 scripts/）
docker compose up -d --build
```

**Windows 原生（不用 Docker）：**

```powershell
git clone https://github.com/Ming-QWQ520/NapCat-M-Stack
cd NapCat-M-Stack\windows
powershell -ExecutionPolicy Bypass -File install.ps1    # 需已安装 QQNT 客户端与 Python 3.12+
```

安装完成后运行 `windows\NapCatInstaller.exe` 完成对本机 QQ 的注入，然后双击 `windows\start.bat`。

### 2. 扫码

- Docker 形态：浏览器打开 `http://<服务器IP>:6099`，扫码登录 **QQ 专用小号**
- Windows 形态：NapCat-M 启动时会打印 WebUI 地址与 token（默认 `http://127.0.0.1:6099`）

### 3. 进入 AstrBot

- Docker 形态：`http://<服务器IP>:6185`；首次密码在启动日志里查看：

  ```bash
  docker logs astrbot | grep -i password
  ```

- Windows 形态：`http://127.0.0.1:6185`，密码同样在 AstrBot 控制台窗口中打印

### 4. 接线（通常已自动完成）

NapCat-M 的预配置已包含指向 AstrBot 的反向 WS（`ws://astrbot:6199/ws`）。你只需在 AstrBot WebUI 建一次适配器：

> 机器人 → 创建机器人 → **OneBot v11** → 反向 WebSocket 主机 `0.0.0.0`、端口 `6199` → 保存

连接成功时 AstrBot 日志会出现蓝色字样 `aiocqhttp(OneBot v11) 适配器已连接`（NapCat-M 每隔 5 秒自动重连，建立适配器后即刻接通）。

> Windows 原生形态下，NapCat-M 预配置指向的是容器名 `astrbot`，需在 NapCat WebUI「网络配置」里把该连接的 URL 改为 `ws://127.0.0.1:6199/ws`。

### 5. 填 Key、养鱼

AstrBot WebUI 内：

1. **服务提供商**：填入大模型 API Key（OpenAI / DeepSeek / Gemini 等均支持）
2. **人格情景**：设置 bot 人设与语气
3. **插件市场**：按需安装插件
4. 用另一个 QQ 号给你的小号发消息，开聊 🎣

## 文件结构

```
NapCat-M-Stack/
├── docker-compose.yml          # astrbot + napcat-m 双容器编排
├── napcat-m/
│   ├── Dockerfile              # 基于 NapCat-Docker 官方镜像，覆盖注入 NapCat-M 修复版
│   ├── napcat/                 # NapCat-M 产物（由 scripts/prepare-napcat-m.* 生成，不入库）
│   └── config/onebot11.json    # NapCat-M 基线预配置：反向 WS → astrbot:6199（新账号自动继承）
├── scripts/
│   ├── prepare-napcat-m.ps1    # 下载并解压 NapCat.Shell.zip（Windows）
│   └── prepare-napcat-m.sh     # 同上（Linux / macOS）
└── windows/
    ├── install.ps1             # Windows 一键安装（NapCat-M Shell + AstrBot venv）
    ├── start.bat               # 一键拉起两端
    ├── run-napcat.bat          # 单独启动 NapCat-M
    └── run-astrbot.bat         # 单独启动 AstrBot
```

## 常见问题

**Q: NapCat-M 一直重连但 AstrBot 日志显示「适配器已被关闭」？**
AstrBot 侧还没创建 OneBot v11 适配器（见第 4 步），或两端不在同一 docker 网络（本 compose 已在同一网络，容器名 `astrbot` 可直接解析）。

**Q: 服务器上公网访问 6099 安全吗？**
NapCat WebUI 有 token 保护，但仍建议仅临时放行扫码，登录后关闭公网端口，或用 SSH 隧道：`ssh -L 6099:127.0.0.1:6099 user@server`。

**Q: 重新部署后要重新扫码吗？**
不用。QQ 登录态持久化在 `data/napcat/QQ`（Docker）或 QQ 数据目录（Windows），只要卷还在。

**Q: 想换别的 Bot 框架？**
NapCat-M 是标准 OneBot v11 协议端，任何支持 OneBot v11（HTTP / 正反向 WS）的框架都能接：在 NapCat WebUI「网络配置」里加对应连接即可，预配置的 AstrBot 连接可以停用。

**Q: NapCat-M 和上游 NapCatQQ 什么关系？**
NapCat-M 是上游 NapNeko/NapCatQQ 停止维护并清空仓库后，基于其最后完整源码（4.18.4）的延续分支，已修复 30+ 处遗留 bug 与安全漏洞。见 [NapCatQQ-M 仓库](https://github.com/Ming-QWQ520/NapCatQQ-M)。

## License

遵循所编排组件的原始许可：NapCat-M 与 AstrBot 各自的 LICENSE。使用请遵守当地法律法规，QQ 账号风控风险自负。
