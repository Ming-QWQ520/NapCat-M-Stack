# NapCat-M 容器：基于 NapCat-Docker 官方镜像（内含 QQ），用 NapCat-M 修复版覆盖 NapCat 程序
#
# 构建前需要先准备 napcat/ 目录（NapCat-M Shell 产物）：
#   在仓库根目录执行 scripts/prepare-napcat-m.ps1（Windows）或 scripts/prepare-napcat-m.sh（Linux/macOS）
FROM mlikiowa/napcat-docker:latest

# NapCat-M 产物覆盖镜像内的 NapCat 程序目录（/app/napcat）。
# QQ 的 resources/app/package.json 的 main 已由基础镜像指向 ./napcat/napcat.mjs，
# 覆盖文件后启动加载的即 NapCat-M。config/ 由 docker-compose 的 volume 挂载提供，不会被镜像内容覆盖。
COPY napcat/ /app/napcat/
