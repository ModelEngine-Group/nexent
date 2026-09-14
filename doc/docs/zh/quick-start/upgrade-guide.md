# Nexent Docker 升级指南

本文适用于使用 Docker Compose 部署的 Nexent。建议在无人使用或业务低峰窗口执行，尽量减少备份和升级期间的新请求与数据写入。这是操作建议，不要求检测在线用户、拦截请求或停止容器。

> ⚠️ 本文按照“容器保持运行，直接复制持久化文件”的方式生成升级前副本。如果复制期间 PostgreSQL、Elasticsearch、Redis 或 MinIO 仍在写入，副本可能不属于同一时间点，不保证能够直接恢复。

## 1. 升级前准备

### 1.1 记录版本与部署配置

先进入当前正在使用的 Nexent 仓库根目录；离线部署则进入上一版已解压部署包的根目录。以下命令不要求仓库位于某个固定系统路径。`BACKUP_BASE` 必须位于 `ROOT_DIR` 之外。

```bash
set -euo pipefail

TARGET_VERSION=X.Y.Z
BACKUP_BASE=/backup/nexent
STAMP=$(date -u +%Y%m%d-%H%M%S)
BACKUP_DIR="$BACKUP_BASE/docker-$STAMP"

mkdir -p "$BACKUP_DIR/config"

set -a
source deploy/env/.env
set +a
: "${ROOT_DIR:?ROOT_DIR is not set in deploy/env/.env}"
ROOT_DIR=$(cd "$ROOT_DIR" && pwd)

printf 'target_version=%s\n' "$TARGET_VERSION" > "$BACKUP_DIR/version.txt"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git rev-parse HEAD >> "$BACKUP_DIR/version.txt"
  git status --short > "$BACKUP_DIR/git-status.txt"
fi
cp -p deploy/env/.env "$BACKUP_DIR/config/deploy.env"
if test -f deploy/env/monitoring.env; then
  cp -p deploy/env/monitoring.env "$BACKUP_DIR/config/monitoring.env"
fi
if test -f deploy/docker/deploy.options; then
  cp -p deploy/docker/deploy.options "$BACKUP_DIR/config/docker-deploy.options"
fi
```

这些配置和清单可能包含密码或令牌，只应保存到受限目录，不能提交到 Git 或公开工单。

### 1.2 检查空间

```bash
du -sh "$ROOT_DIR"
df -h "$ROOT_DIR" "$BACKUP_BASE"
docker system df -v
```

确认备份目录可用空间大于待复制的持久化数据，Docker 数据盘还能容纳目标版本镜像。不要通过删除旧镜像、volume 或运行中容器来腾出升级空间。

### 1.3 复制持久化数据

先保存本次部署实际使用的容器和挂载清单。已启用监控时，同时纳入 `monitor` Compose 项目。

```bash
{
  docker ps -q --filter label=com.docker.compose.project=nexent
  docker ps -q --filter label=com.docker.compose.project=monitor
} | sort -u > "$BACKUP_DIR/container-ids.txt"

mapfile -t CONTAINERS < "$BACKUP_DIR/container-ids.txt"
test "${#CONTAINERS[@]}" -gt 0
docker inspect "${CONTAINERS[@]}" > "$BACKUP_DIR/containers.inspect.json"
docker inspect --format '{{range .Mounts}}{{if eq .Type "bind"}}{{println .Source}}{{end}}{{end}}' \
  "${CONTAINERS[@]}" | sed '/^$/d' | sort -u > "$BACKUP_DIR/bind-mounts.txt"
docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}' \
  "${CONTAINERS[@]}" | sed '/^$/d' | sort -u > "$BACKUP_DIR/volumes.txt"
```

容器保持运行，直接归档 `ROOT_DIR`：

```bash
sudo tar --numeric-owner --acls --xattrs \
  -cpf "$BACKUP_DIR/root-dir.tar" -C "$ROOT_DIR" .
```

检查 `bind-mounts.txt`，将不在 `ROOT_DIR` 内的用户目录、终端目录、自定义配置和其他持久化 bind mount 分别复制。不要复制 `/var/run/docker.sock` 等运行时接口。

```bash
EXTERNAL_SOURCE=/actual/persistent/path
EXTERNAL_NAME=external-data
sudo tar --numeric-owner --acls --xattrs \
  -cpf "$BACKUP_DIR/$EXTERNAL_NAME.tar" \
  -C "$(dirname "$EXTERNAL_SOURCE")" "$(basename "$EXTERNAL_SOURCE")"
```

再归档清单中的 Docker named volumes。提前准备可信且包含 GNU tar 的辅助镜像；离线环境不要等到升级窗口再下载。

```bash
BACKUP_HELPER_IMAGE=ubuntu:24.04
docker image inspect "$BACKUP_HELPER_IMAGE" >/dev/null
mkdir -p "$BACKUP_DIR/volumes"

while IFS= read -r volume; do
  test -n "$volume" || continue
  docker run --rm --network none --user 0 \
    -v "$volume:/source:ro" "$BACKUP_HELPER_IMAGE" \
    tar --numeric-owner --acls --xattrs -cpf - -C /source . \
    > "$BACKUP_DIR/volumes/$volume.tar"
done < "$BACKUP_DIR/volumes.txt"
```

本流程不生成 SHA-256 文件。通过命令退出状态、归档可读性和空间占用核对复制结果：

```bash
test -s "$BACKUP_DIR/root-dir.tar"
tar -tf "$BACKUP_DIR/root-dir.tar" >/dev/null
for archive in "$BACKUP_DIR"/volumes/*.tar; do
  test -f "$archive" || continue
  tar -tf "$archive" >/dev/null
done
du -sh "$ROOT_DIR" "$BACKUP_DIR"
```

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
