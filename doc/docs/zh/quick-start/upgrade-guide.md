# Nexent Docker 升级指南

本文适用于使用 Docker Compose 部署的 Nexent。建议在无人使用或业务低峰窗口执行。备份前必须停止业务写入，但不需要停止容器。

升级前请保留原部署目录及其配置，并记录镜像版本。需要回滚时，先恢复升级前的备份，再从旧部署目录重新部署。详见 [Docker 回滚指南](./rollback-guide)。

> ⚠️ 如果复制期间仍有业务写入，PostgreSQL、Elasticsearch、Redis 和 MinIO 等组件的数据可能不属于同一时间点，备份可能无法恢复。

## 1. 升级前检查和备份

先进入当前正在使用的 Nexent 仓库根目录；离线部署则进入上一版已解压部署包的根目录。备份目录必须位于 `ROOT_DIR` 和 `NEXENT_USER_DIR` 之外。

执行以下命令前必须停止用户操作、接口请求和定时任务等业务写入；容器保持运行，不需要执行 `docker stop` 或 `docker compose down`。脚本不会检测业务写入状态，也不会要求输入确认：

```bash
bash deploy/docker/backup.sh --backup-dir /mnt/backup/nexent
```

脚本会先回显 `ROOT_DIR`、`NEXENT_USER_DIR`、本次部署使用的 named volumes、未压缩数据总量以及备份目录可用空间。`NEXENT_USER_DIR` 未显式设置时使用部署默认值 `${HOME}/nexent`。出现 `[PASS] Pre-upgrade space check passed.` 表示空间充足，随后脚本直接开始复制；空间不足时会在复制前输出 `[ERROR]` 并退出。数据不会压缩，因此空间检查按文件原始大小计算。

每次运行在 `--backup-dir` 下生成一个 `docker-时间戳/` 目录。其中包含 `ROOT_DIR`、`NEXENT_USER_DIR` 和检测到的 Docker 命名卷，子目录沿用各自的原名。脚本直接复制文件，不使用 `sudo`，也不生成压缩包或 SHA-256 文件。看到 `[PASS] Backup complete: <path>` 后，整份保留 `<path>` 指向的目录供回滚使用。以 `.partial` 结尾的目录尚未复制完成。

## 2. 执行升级

Web 默认给登录 Cookie 加上 `Secure`。如果内网仍通过 HTTP 直连 Web，升级前在 `deploy/env/.env` 中设置 `NEXENT_AUTH_COOKIE_SECURE=false`，让浏览器能保存会话。通过 HTTPS 反向代理访问时保留默认值 `true`，即使代理和 Web 之间使用 HTTP。

### 2.1 在线升级

在能够访问 GitHub 和所需镜像仓库的环境中，使用当前 Nexent 仓库执行在线升级。先确认当前分支和目标版本，再以快进方式更新。不要用未记录的 `latest` 代替明确版本。

```bash
git branch --show-current
git pull --ff-only
bash deploy.sh docker --defaults --version X.Y.Z
```

将 `X.Y.Z` 替换为目标镜像的实际版本标签。`--defaults` 会复用已保存的部署配置并跳过交互界面。升级前应确认 `deploy/docker/deploy.options` 中的组件、端口策略和镜像源与原环境一致。详见 [Docker 安装部署](./installation.md#在线部署)。

### 2.2 离线升级

目标主机无法访问公网镜像仓库时，按 [Docker 离线部署](./installation.md#离线部署) 下载与服务器架构匹配的目标版本包，复制到目标主机并解压到新目录：

```bash
unzip 'nexent-<version>-amd64.zip' -d 'nexent-<version>'
cd 'nexent-<version>'
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  --defaults \
  docker
```

`/path/to/previous/nexent` 必须是上一版已解压部署包的实际根目录，且包含 `deploy/env/.env`。`--reuse-from` 会复用旧包的 `.env`、`monitoring.env` 和 Docker 部署选项，`--load-images` 会加载新包中的镜像。ARM64 服务器应使用对应的 `arm64` 包名。

## 3. 升级后检查

部署脚本会在终端显示本次日志的路径，默认位于部署目录的 `logs/deploy/deploy-YYYYMMDD-HHMMSS.log`。镜像加载或数据库初始化失败时，打开本次日志查看详细输出。

升级到 v2.9.0 时，部署脚本使用临时的 `nexent-config` 容器应用数据库迁移，随后启动业务服务。此版本将相关迁移合并在 `v2.9.0_merged_migrations.sql` 中。常驻的 `nexent-config` 启动时会核对迁移记录和 SQL 校验和，已是目标版本时会跳过重复执行。

查看 Nexent 及可选监控项目的容器健康状态。

```bash
docker ps -a --filter label=com.docker.compose.project=nexent \
  --format 'table {{.Names}}\t{{.Status}}'
docker ps -a --filter label=com.docker.compose.project=monitor \
  --format 'table {{.Names}}\t{{.Status}}'
```

等待配置了健康检查的容器显示 `healthy`。如有 `unhealthy` 容器，检查部署日志和该容器的日志。再用已有账号登录并打开一段升级前的会话，确认应用能读取原数据。
