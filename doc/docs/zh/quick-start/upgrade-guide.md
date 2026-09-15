# Nexent Docker 升级指南

本文适用于使用 Docker Compose 部署的 Nexent。建议在无人使用或业务低峰窗口执行。备份前必须停止业务写入，但不需要停止容器。

> ⚠️ 如果复制期间仍有业务写入，PostgreSQL、Elasticsearch、Redis 和 MinIO 等组件的数据可能不属于同一时间点，备份可能无法恢复。

## 1. 升级前准备

### 1.1 升级前检查

先进入当前正在使用的 Nexent 仓库根目录；离线部署则进入上一版已解压部署包的根目录。调用备份脚本并指定 `ROOT_DIR` 之外的本地备份目录：

```bash
bash deploy/docker/backup.sh --backup-dir /mnt/backup/nexent
```

脚本会先回显 `ROOT_DIR`、本次部署使用的 named volumes、未压缩数据总量以及备份目录可用空间。出现 `[PASS] Pre-upgrade space check passed.` 表示空间充足；空间不足时脚本会在复制前输出 `[ERROR]` 并退出。数据不会压缩，因此空间检查按文件原始大小计算。

### 1.2 备份

空间检查通过后，脚本会要求确认业务写入已经停止。确认前应停止用户操作、接口请求和定时任务等业务写入；容器保持运行，不需要执行 `docker stop` 或 `docker compose down`。

交互执行时按提示输入 `y`。非交互执行时，只有在已经停止业务写入后才能显式确认：

```bash
bash deploy/docker/backup.sh \
  --backup-dir /mnt/backup/nexent \
  --confirm-writes-stopped
```

脚本会直接复制 `ROOT_DIR` 和 Docker named volumes 中的文件，不使用 `sudo`，不生成压缩包或 SHA-256 文件。通过 `[INFO]` 查看复制进度；只有出现 `[PASS] Backup complete: <path>` 才表示完成，`<path>` 是实际备份目录。出现 `[ERROR]` 时不要使用脚本回显的未完成目录。

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

查看 Nexent 及可选监控项目的全部容器：

```bash
docker ps -a --filter label=com.docker.compose.project=nexent \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker ps -a --filter label=com.docker.compose.project=monitor \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker logs --tail 200 nexent-config
```

升级通过需要满足：

- 已选组件对应的容器全部为 `Up`，定义了健康检查的容器为 `healthy`。
- 不存在 `Exited`、`Restarting` 或 `unhealthy` 容器。
- `nexent-config` 日志中没有 `[sql-migrations]` 失败、迁移等待超时或持续报错。

如果不满足上述条件，不要立即删除旧镜像或升级前副本；先根据容器日志定位问题。
