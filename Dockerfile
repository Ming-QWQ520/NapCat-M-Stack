# NapCat-M Stack 单容器镜像：QQ + NapCat-M + AstrBot + 统一网关
#
# 构建上下文优先级（scripts/docker-prepare.py）：
#   1. napcat/（已运行 scripts/prepare-napcat.sh）
#   2. scripts/NapCat.Shell.zip（手动下载）
#   3. 在线下载（--build-arg NAPCAT_ZIP_URL 可指定镜像源）
#
# 使用：
#   docker compose up -d --build
FROM mlikiowa/napcat-docker:latest

# Debian bookworm 自带 python3.11（AstrBot 要求 >= 3.10）
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（独立层，利用构建缓存）
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -U pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

# 预取 AstrBot 仪表盘静态资源（离线环境可 --build-arg 指定镜像；
# 失败不阻断构建，运行时会再次尝试下载）
ARG ASTRBOT_DASHBOARD_ZIP_URL=https://github.com/AstrBotDevs/AstrBot/releases/download/v4.30.0-beta.1/AstrBot-v4.30.0-beta.1-dashboard.zip
RUN mkdir -p /app/data/dist \
    && curl -fsSL --connect-timeout 20 --max-time 300 -o /tmp/dashboard.zip \
        "${ASTRBOT_DASHBOARD_ZIP_URL}" \
    && python3 -c "import zipfile, shutil, pathlib; z = zipfile.ZipFile('/tmp/dashboard.zip'); z.extractall('/tmp/dash'); src = pathlib.Path('/tmp/dash'); base = src / 'dist' if (src / 'dist').is_dir() else src; shutil.copytree(base, '/app/data/dist', dirs_exist_ok=True)" \
    && rm -rf /tmp/dashboard.zip /tmp/dash \
    || echo "[!] 仪表盘预取失败，运行时将自动下载"

# 栈代码与内嵌 AstrBot
COPY main.py runtime_bootstrap.py /app/
COPY stack /app/stack
COPY astrbot /app/astrbot
COPY scripts/entrypoint.sh /app/entrypoint.sh
COPY scripts/docker-prepare.py /app/docker-prepare.py

# NapCat-M 产物（下载/解压/子路径重写）
ARG NAPCAT_VERSION=v4.18.43
ARG NAPCAT_ZIP_URL=""
COPY . /src
RUN python3 /src/scripts/docker-prepare.py \
        --src /src --dest /app/napcat --version ${NAPCAT_VERSION} \
        --url ${NAPCAT_ZIP_URL} \
    && chmod +x /app/entrypoint.sh \
    && rm -rf /src

ENV TZ=Asia/Shanghai \
    HOME=/app \
    ASTRBOT_ROOT=/app

VOLUME ["/app/data", "/app/.config/QQ"]

HEALTHCHECK --interval=60s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -sf http://127.0.0.1:6185/napcat/healthz || exit 1

EXPOSE 6185
ENTRYPOINT ["/app/entrypoint.sh"]
