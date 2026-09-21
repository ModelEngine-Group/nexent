# Nexent Docker 升级指南

本文适用于使用 Docker Compose 部署的 Nexent。建议在无人使用或业务低峰窗口执行。备份前必须停止业务写入，但不需要停止容器。

> ⚠️ 如果复制期间仍有业务写入，PostgreSQL、Elasticsearch、Redis 和 MinIO 等组件的数据可能不属于同一时间点，备份可能无法恢复。

## 1. 升级前检查和备份

先进入当前正在使用的 Nexent 仓库根目录；离线部署则进入上一版已解压部署包的根目录。备份目录必须位于 `ROOT_DIR` 和 `NEXENT_USER_DIR` 之外。

执行以下命令前必须停止用户操作、接口请求和定时任务等业务写入；容器保持运行，不需要执行 `docker stop` 或 `docker compose down`。脚本不会检测业务写入状态，也不会要求输入确认：

```bash
bash deploy/docker/backup.sh --backup-dir /mnt/backup/nexent
```

脚本会先回显 `ROOT_DIR`、`NEXENT_USER_DIR`、本次部署使用的 named volumes、未压缩数据总量以及备份目录可用空间。`NEXENT_USER_DIR` 未显式设置时使用部署默认值 `${HOME}/nexent`。出现 `[PASS] Pre-upgrade space check passed.` 表示空间充足，随后脚本直接开始复制；空间不足时会在复制前输出 `[ERROR]` 并退出。数据不会压缩，因此空间检查按文件原始大小计算。

脚本会直接复制 `ROOT_DIR`、`NEXENT_USER_DIR` 和 Docker named volumes 中的文件，不使用 `sudo`，不生成压缩包或 SHA-256 文件。实际备份目录的最外层使用数据源原名：两个宿主机目录使用各自的目录名，每个 named volume 使用其 volume 名；例如默认部署会生成 `nexent-data/`、`nexent/`、`nexent-agent-workspace/` 和 `nexent_db-config/`。通过 `[INFO]` 查看复制进度；只有出现 `[PASS] Backup complete: <path>` 才表示完成，`<path>` 是实际备份目录。出现 `[ERROR]` 时不要使用脚本回显的未完成目录。

## 2. 执行升级

### 2.1 在线升级

在能够访问 GitHub 和所需镜像仓库的环境中，使用当前 Nexent 仓库执行在线升级。先确认当前分支和目标版本，再以快进方式更新。不要用未记录的 `latest` 代替明确版本。

```bash
git branch --show-current
git pull --ff-only
bash deploy.sh docker --defaults --version X.Y.Z
```

`--defaults` 会复用已保存的部署配置并跳过交互界面。升级前应确认 `deploy/docker/deploy.options` 存在且组件、端口策略、镜像源与原环境一致。更多在线部署说明参见 [Docker 安装部署](./installation.md#在线部署)。

### 2.2 离线升级

目标主机无法访问公网镜像仓库时，按 [Docker 离线部署](./installation.md#离线部署) 下载与服务器架构匹配的目标版本包，复制到目标主机并解压到新目录：

```bash
unzip nexent-<version>-amd64.zip -d nexent-<version>
cd nexent-<version>
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  --defaults \
  docker
```

`/path/to/previous/nexent` 必须是上一版已解压部署包的实际根目录，且包含 `deploy/env/.env`。`--reuse-from` 会复用旧包的 `.env`、`monitoring.env` 和 Docker 部署选项，`--load-images` 会加载新包中的镜像。ARM64 服务器应使用对应的 `arm64` 包名。

升级时由 `nexent-config` 执行数据库自动迁移，其他后端容器会等待迁移达到目标状态。已合并的 SQL 文件不可修改、改名或删除。

## 3. 升级后检查

查看 Nexent 及可选监控项目的容器健康状态：

```bash
docker ps -a --filter label=com.docker.compose.project=nexent \
  --format 'table {{.Names}}\t{{.Status}}'
docker ps -a --filter label=com.docker.compose.project=monitor \
  --format 'table {{.Names}}\t{{.Status}}'
```

所有配置了健康检查的容器均显示 `healthy` 即表示检查通过；显示 `starting` 时继续等待，显示 `unhealthy` 时检查不通过。未配置健康检查的容器不会显示 `healthy`，不在本项检查范围内。
