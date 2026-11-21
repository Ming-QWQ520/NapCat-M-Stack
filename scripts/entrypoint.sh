#!/usr/bin/env bash
# NapCat-M Stack 容器入口（root 阶段）
#
# 职责（对齐 mlikiowa/napcat-docker 官方 entrypoint 的容器环境处理）：
#   1. NapCat 产物安装与 WebUI 令牌/端口预置（幂等）
#   2. 容器痕迹对抗（QQ 风控缓解，逻辑与上游一致）
#   3. UID/GID 映射 + Xvfb
#   4. exec 统一入口 main.py（由其拉起 QQ 子进程并接管生命周期）
set -e

trap "" SIGPIPE

# ---------- 1. NapCat 产物 ----------
# /app/napcat 由镜像构建阶段写入（scripts/docker-prepare.py）。
# 这里只做完整性校验与 QQ 加载接线。
if [ ! -f /app/napcat/napcat.mjs ]; then
    echo "[entrypoint] 缺少 /app/napcat/napcat.mjs，镜像构建异常。"
    exit 1
fi

# 确保 QQ(Electron) 启动即加载 /app/napcat/napcat.mjs（与上游 NapCat-Docker 同法）
if [ -d /opt/QQ/resources/app ]; then
    echo "(async () => {await import('file:///app/napcat/napcat.mjs');})();" > /opt/QQ/resources/app/loadNapCat.js
    sed -i 's|"main": "[^"]*"|"main": "./loadNapCat.js"|' /opt/QQ/resources/app/package.json
fi

rm -rf "/tmp/.X1-lock"

# ---------- 2. 容器痕迹对抗（与上游 entrypoint 一致） ----------
rm -f "/.dockerenv" "/.dockerinit" "/run/.containerenv" "/run/systemd/container" "/dev/.dockerenv"

HOSTNAME_VAL="$(hostname)"
if [[ "${HOSTNAME_VAL}" == *docker* || "${HOSTNAME_VAL}" == *container* || "${HOSTNAME_VAL}" == *lxc* ]] \
   || [[ "${HOSTNAME_VAL}" =~ ^[a-f0-9]{12,}$ ]]; then
    hostname "localhost" 2>/dev/null || true
    echo "localhost" > /etc/hostname 2>/dev/null || true
fi

mkdir -p /tmp/fake_cgroup
FAKE_CGROUP_DIR="/tmp/fake_cgroup"
for cfile in /proc/self/cgroup /proc/1/cgroup; do
    if [ -f "$cfile" ]; then
        FAKE_CG="$FAKE_CGROUP_DIR/cgroup_$(basename $(dirname $cfile))_$(basename $cfile)"
        cat "$cfile" | sed \
            -e 's|/docker/|/system.slice/|g' \
            -e 's|/docker-|/system.slice/|g' \
            -e 's|/lxc/|/system.slice/|g' \
            -e 's|/podmaster|/system.slice/|g' \
            -e 's|/podman/|/system.slice/|g' \
            -e 's|/kubepods/|/system.slice/|g' \
            -e 's|/containerd/|/system.slice/|g' \
            -e 's|/buildkit/|/system.slice/|g' \
            > "$FAKE_CG"
        mount --bind "$FAKE_CG" "$cfile" 2>/dev/null || true
    fi
done

for dmi_file in /sys/class/dmi/id/product_name /sys/class/dmi/id/product_uuid /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/board_vendor /sys/class/dmi/id/board_name; do
    if [ -f "$dmi_file" ]; then
        FAKE_DMI="/tmp/fake_cgroup/$(echo $dmi_file | tr '/' '_')"
        case "$(basename $dmi_file)" in
            product_name)  echo "Standard PC" > "$FAKE_DMI" ;;
            product_uuid)  echo "00000000-0000-0000-0000-000000000000" > "$FAKE_DMI" ;;
            sys_vendor|board_vendor) echo "Intel Corporation" > "$FAKE_DMI" ;;
            board_name)    echo "Default string" > "$FAKE_DMI" ;;
        esac
        mount --bind "$FAKE_DMI" "$dmi_file" 2>/dev/null || true
    fi
done

if [ -S /var/run/docker.sock ]; then
    mv /var/run/docker.sock /var/run/.docker.sock.hidden 2>/dev/null || true
fi

for mfile in /proc/self/mountinfo /proc/1/mountinfo; do
    if [ -f "$mfile" ]; then
        FAKE_MOUNT="$FAKE_CGROUP_DIR/mountinfo_$(basename $(dirname $mfile))_$(basename $mfile)"
        cat "$mfile" | sed \
            -e 's|overlay / |ext4 / |g' \
            -e 's|overlay /|ext4 /|g' \
            -e '/docker/d' \
            -e '/containerd/d' \
            -e '/\.dockerenv/d' \
            -e '/cgroup2.*docker/d' \
            > "$FAKE_MOUNT"
        mount --bind "$FAKE_MOUNT" "$mfile" 2>/dev/null || true
    fi
done

if [ -f /proc/1/cmdline ]; then
    FAKE_CMDLINE="$FAKE_CGROUP_DIR/cmdline_1"
    printf '/sbin/init\0' > "$FAKE_CMDLINE"
    mount --bind "$FAKE_CMDLINE" /proc/1/cmdline 2>/dev/null || true
fi

if [ -f /proc/1/sched ]; then
    FAKE_SCHED="$FAKE_CGROUP_DIR/sched_1"
    head -1 /proc/1/sched | sed 's|([^)]*)|(1, #threads=1)|' > "$FAKE_SCHED"
    tail -n +2 /proc/1/sched >> "$FAKE_SCHED"
    sed -i 's/^[a-zA-Z0-9_-]*\s/systemd /' "$FAKE_SCHED"
    mount --bind "$FAKE_SCHED" /proc/1/sched 2>/dev/null || true
fi

if [ -f /proc/1/environ ]; then
    FAKE_ENVIRON="$FAKE_CGROUP_DIR/environ_1"
    cat /proc/1/environ | tr '\0' '\n' | \
        grep -v -i 'container=docker\|container=lxc\|container=podman\|container=containerd' | \
        tr '\n' '\0' > "$FAKE_ENVIRON"
    mount --bind "$FAKE_ENVIRON" /proc/1/environ 2>/dev/null || true
fi

for sfile in /proc/1/status /proc/self/status; do
    if [ -f "$sfile" ]; then
        FAKE_STATUS="$FAKE_CGROUP_DIR/status_$(basename $(dirname $sfile))_$(basename $sfile)"
        cat "$sfile" | sed 's/^NSpid:.*/NSpid:\t1/' > "$FAKE_STATUS"
        mount --bind "$FAKE_STATUS" "$sfile" 2>/dev/null || true
    fi
done

if [ -f /proc/1/stat ]; then
    FAKE_STAT="$FAKE_CGROUP_DIR/stat_1"
    cat /proc/1/stat | sed 's/^\([0-9]*\) ([-a-zA-Z0-9_]*)/\1 (systemd)/' > "$FAKE_STAT"
    mount --bind "$FAKE_STAT" /proc/1/stat 2>/dev/null || true
fi

if [ -f /etc/hosts ]; then
    FAKE_HOSTS="$FAKE_CGROUP_DIR/hosts"
    cat /etc/hosts | grep -v "$(hostname)" > "$FAKE_HOSTS" 2>/dev/null || true
    grep -q '^127\.0\.0\.1.*localhost' "$FAKE_HOSTS" || echo "127.0.0.1\tlocalhost" >> "$FAKE_HOSTS"
    grep -q '^::1.*localhost' "$FAKE_HOSTS" || echo "::1\tlocalhost ip6-localhost ip6-loopback" >> "$FAKE_HOSTS"
    mount --bind "$FAKE_HOSTS" /etc/hosts 2>/dev/null || true
fi

if [ -f /sys/hypervisor/type ] && [ -d /sys/hypervisor ]; then
    FAKE_HYPER="$FAKE_CGROUP_DIR/hypervisor_type"
    echo "" > "$FAKE_HYPER"
    mount --bind "$FAKE_HYPER" /sys/hypervisor/type 2>/dev/null || true
fi

if [ -f /proc/self/mounts ]; then
    FAKE_MOUNTS="$FAKE_CGROUP_DIR/mounts_self"
    cat /proc/self/mounts | sed \
        -e 's|overlay / |ext4 / |g' \
        -e 's|overlay /|ext4 /|g' \
        -e '/docker/d' \
        -e '/containerd/d' \
        > "$FAKE_MOUNTS"
    mount --bind "$FAKE_MOUNTS" /proc/self/mounts 2>/dev/null || true
fi

if [ -f /proc/self/cpuset ]; then
    FAKE_CPUSET="$FAKE_CGROUP_DIR/cpuset_self"
    cat /proc/self/cpuset | sed \
        -e 's|/docker/|/|g' \
        -e 's|/docker-[^/]*/|/|g' \
        -e 's|/kubepods/|/|g' \
        -e 's|/containerd/|/|g' \
        > "$FAKE_CPUSET"
    mount --bind "$FAKE_CPUSET" /proc/self/cpuset 2>/dev/null || true
fi

# ---------- 3. UID/GID + 虚拟显示 ----------
: ${NAPCAT_GID:=1000}
: ${NAPCAT_UID:=1000}
usermod -o -u ${NAPCAT_UID} napcat 2>/dev/null || true
groupmod -o -g ${NAPCAT_GID} napcat 2>/dev/null || true
usermod -g ${NAPCAT_GID} napcat 2>/dev/null || true
chown -R ${NAPCAT_UID}:${NAPCAT_GID} /app 2>/dev/null || true
mkdir -p /app/data /app/.config/QQ
chown -R ${NAPCAT_UID}:${NAPCAT_GID} /app/data /app/.config/QQ 2>/dev/null || true

gosu napcat Xvfb :1 -screen 0 1080x760x16 +extension GLX +render > /dev/null 2>&1 &
sleep 2

export FFMPEG_PATH=/usr/bin/ffmpeg
export DISPLAY=:1
export HOME=/app

# ---------- 4. 统一入口 ----------
cd /app
exec gosu napcat /opt/venv/bin/python /app/main.py
