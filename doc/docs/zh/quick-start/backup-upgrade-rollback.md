# Nexent 备份、升级与回滚指导

本文用于已有 Nexent 环境的版本变更和故障恢复，覆盖 Docker Compose 在线部署、离线部署包及 Kubernetes。推荐流程是：**准备目标版本 → 暂停写入 → 完成并验证备份 → 升级 → 验收 → 恢复流量**。验收失败时，根据数据库及存储是否已经变化，选择应用回退或整套数据恢复。

Docker 命令以 Linux、Bash 4+、GNU tar 和 Docker Compose v2 为例，需要 Docker 操作权限，以及读取数据目录所需的 sudo 权限。Docker Engine 18.09 环境也应使用与其兼容的 Compose CLI；本文命令不依赖新版 daemon 的 GPU、cgroup namespace 或 healthcheck `start_interval` 功能。macOS、Windows 或远程 Docker daemon 的数据路径不能直接套用 Linux 宿主机路径。

## 1. 升级前确认

先完成以下检查，再进入维护窗口：

- **确认版本**：保存当前代码提交、部署包版本、实际运行镜像 ID 和镜像 digest；确定目标发布版本，不以 `git pull` 或 `latest` 作为版本记录。当前脚本优先读取根目录 `VERSION`，不存在时读取 `backend/consts/const.py` 中的 `APP_VERSION`；实际运行镜像还可能受部署参数影响。
- **核对变更**：检查目标版本发布说明、`deploy/sql/` 新增迁移、环境变量和中间件镜像变化。PostgreSQL、Elasticsearch 等中间件跨版本升级须另外验证数据格式兼容性。
- **准备恢复资源**：保留旧代码或完整部署包、旧镜像、旧配置和可用备份；预先下载新镜像及备份辅助镜像，确认架构匹配。磁盘需同时容纳备份、镜像和故障现场副本，按实际数据量及演练结果预留空间。
- **约定维护窗口**：记录负责人、开始时间、允许停机时长、最迟回滚时间、RPO（允许丢失的数据时间范围）和 RTO（恢复时限）。恢复升级前备份会丢失备份点之后的写入；开放流量后再回滚，需要先确认如何处理这部分数据。
- **先做恢复演练**：在隔离环境验证备份能恢复，并测量耗时。演练环境禁用定时任务、外部通知、生产工具调用，避免连接生产数据库或存储。
- **保存验收基线**：记录用户、智能体、知识库等关键记录数量和抽样 ID，保存 ES 索引/文档数量及重要对象、工作区文件的校验值，供升级和回滚后核对。

部署配置应沿用原环境的组件、端口策略、镜像源和数据位置。现有 `.env` 会保留已有值并补充 `.env.example` 中的新变量；不要用新版示例文件覆盖旧 `.env`，也不要在普通升级时附带 `--rotate-secrets`。

## 2. 必须备份哪些内容

以下 Docker 路径来自当前 Compose 配置，**以实际容器的 Mounts 为准**。不能仅备份 `ROOT_DIR`，也不能把 `docker export` 当作数据卷备份。

| 内容 | Docker 默认位置或来源 | 恢复用途 |
| --- | --- | --- |
| 部署代码及配置 | 原部署目录，尤其是 `deploy/env/`、`deploy/docker/deploy.options`、`deploy/docker/.env.generated`、Compose 文件、`deploy/sql/`、`VERSION` | 还原脚本、版本、组件、密钥和 SQL 集合 |
| 业务 PostgreSQL | `${ROOT_DIR}/postgresql/data` | 智能体、租户业务数据、配置、会话及数据库迁移记录 |
| Supabase PostgreSQL（启用时） | `${ROOT_DIR}/volumes/db/data`，以及命名卷 `db-config` 的实际卷名 | 用户、认证信息和数据库配置；不能用业务 PostgreSQL 备份代替 |
| Elasticsearch | `${ROOT_DIR}/elasticsearch` 对应的集群 | 知识库索引、映射和向量；使用 Elasticsearch Snapshot API 备份 |
| MinIO | `${ROOT_DIR}/minio/data` | 原始文档、附件及对象存储元数据 |
| Redis | `${ROOT_DIR}/redis` | 持久化队列及运行状态；备份前排空任务，恢复后核对任务是否重复执行 |
| 用户目录、技能和终端文件 | 实际挂载到 `/mnt/nexent` 的宿主机目录、`${ROOT_DIR}/skills`、SSH 密钥目录、`TERMINAL_MOUNT_DIR` | 技能包、用户文件、SSH 访问和终端工作成果 |
| 智能体工作区 | `NEXENT_SANDBOX_WORKSPACE_VOLUME`，默认 `nexent-agent-workspace`，挂载到 `/mnt/nexent/workdir` | 被父目录挂载遮蔽的独立工作区数据，须单独备份 |
| 监控（启用时） | `monitor` Compose 项目的实际挂载和命名卷 | Phoenix、Grafana、Tempo 或 Langfuse 的历史数据；Langfuse 包含独立 PostgreSQL、ClickHouse、MinIO 等存储 |
| 外部依赖及定制挂载 | 外部数据库、对象存储、MCP/沙箱卷、反向代理配置、证书、符号链接指向的目录 | 在各自平台备份并记录对应的恢复点 |

`.env`、Helm values、Secret 导出、数据库备份和容器 inspect 结果可能包含密码或令牌。备份目录设为仅维护人员可读，异地副本使用加密存储；不要提交到 Git 或放入公开工单。至少保留一份不在原主机上的副本，并在回滚观察期结束前保留旧镜像及备份。

## 3. Docker：生成升级前备份

### 3.1 设置路径并保存现场

在同一个 Bash 会话中依次执行。将路径改为实际部署位置；`BACKUP_BASE` 必须位于部署目录和数据目录之外。后续任何命令失败都应停止，查明原因后继续，不能把生成了文件等同于备份成功。

```bash
set -euo pipefail
umask 077

CODE_DIR=/opt/nexent
BACKUP_BASE=/backup/nexent
STAMP=$(date -u +%Y%m%d-%H%M%S)
BAK="$BACKUP_BASE/$STAMP"
mkdir -p "$BAK"
cd "$CODE_DIR"

docker version > "$BAK/docker-version.txt"
docker compose version > "$BAK/compose-version.txt"
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > "$BAK/containers-all.txt"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git rev-parse HEAD > "$BAK/git-commit.txt"
  git status --short > "$BAK/git-status.txt"
fi

{
  docker ps -a --filter label=com.docker.compose.project=nexent --format '{{.Names}}'
  docker ps -a --filter label=com.docker.compose.project=monitor --format '{{.Names}}'
} | sort -u > "$BAK/containers.txt"
```

人工核对 `containers.txt`：删除不属于本次维护的容器，补充动态 MCP、沙箱、自定义项目名以及其他会写入本次备份存储的容器。不要使用“停止本机所有容器”的命令。随后生成挂载、镜像及原运行状态清单：

```bash
mapfile -t TARGETS < "$BAK/containers.txt"
test "${#TARGETS[@]}" -gt 0
docker inspect "${TARGETS[@]}" > "$BAK/containers.inspect.json"
docker inspect --format '{{.Name}}{{range .Mounts}}{{printf "\n  %s %s -> %s" .Type .Source .Destination}}{{end}}' \
  "${TARGETS[@]}" > "$BAK/mounts.txt"
docker inspect --format '{{.Name}} {{.Config.Image}} {{.Image}}' \
  "${TARGETS[@]}" > "$BAK/images.txt"
docker inspect --format '{{if .State.Running}}{{.Name}}{{end}}' \
  "${TARGETS[@]}" | sed '/^$/d' > "$BAK/running-before.txt"
docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}' \
  "${TARGETS[@]}" | sed '/^$/d' | sort -u > "$BAK/volumes.txt"

mapfile -t IMAGE_IDS < <(docker inspect --format '{{.Image}}' "${TARGETS[@]}" | sort -u)
docker image inspect "${IMAGE_IDS[@]}" > "$BAK/images.inspect.json"
docker image save "${IMAGE_IDS[@]}" > "$BAK/images.tar"
```

这里保存的是容器实际使用的镜像 ID。未运行但回滚仍需使用的 MCP、沙箱等镜像也应另行保存。通过 ID 导出的镜像加载后可能没有原标签，恢复时需要按 `images.txt` 重新打标。若同一标签对应多个运行中的镜像 ID，应先为各版本分配独立标签并记录服务映射。

根据 `mounts.txt` 设置并记录以下变量。用户目录不一定属于 `ROOT_DIR`；当前 Docker 部署脚本会使用执行部署用户的 `$HOME/nexent`，升级应由同一账号执行，并核对实际挂载。

```bash
DATA_DIR=/srv/nexent-data
USER_DATA_DIR=/home/deploy/nexent
test -d "$DATA_DIR"
test -d "$USER_DATA_DIR"
printf 'CODE_DIR=%s\nDATA_DIR=%s\nUSER_DATA_DIR=%s\n' \
  "$CODE_DIR" "$DATA_DIR" "$USER_DATA_DIR" > "$BAK/paths.txt"
```

上面的值是示例，须与实际 Mounts 一致。若用户目录已经包含在数据目录中，不要在恢复时重复覆盖；其他外部 bind mount 和符号链接目标也需要单独列入清单。不要复制 `/var/run/docker.sock` 等运行时接口。

### 3.2 暂停入口与写入

1. 在网关或负载均衡上切换到维护状态，同时限制直连 API 入口。
2. 暂停定时任务、上传任务和外部调用，等待智能体运行、Celery 队列及文档处理任务结束；记录未完成任务。
3. 停止应用和所有其他写入方，保留数据库、Elasticsearch、MinIO、Redis，供下一步生成备份。启用 Supabase 时也应停止认证入口及认证服务，防止产生新的用户或会话。

默认应用容器的停止示例：

```bash
APP_WRITERS=(nexent-web nexent-config nexent-runtime nexent-mcp nexent-northbound nexent-data-process)
for container in "${APP_WRITERS[@]}"; do
  if docker container inspect "$container" >/dev/null 2>&1; then
    docker stop --time 120 "$container"
  fi
done
```

按实际清单继续停止 Supabase auth/Kong、终端、动态沙箱和监控写入方。`docker stop` 超时会强制终止进程，应结合日志确认数据库后续能够正常关闭。只有全部业务写入停止后，各存储在同一维护窗口内产生的备份才能作为配套恢复点。

### 3.3 导出两套 PostgreSQL

业务数据库使用容器内环境变量，避免手工拼接密码：

```bash
docker exec nexent-postgresql sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$BAK/nexent.dump"
docker exec nexent-postgresql sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dumpall -U "$POSTGRES_USER" --globals-only' \
  > "$BAK/nexent-globals.sql"
docker exec -i nexent-postgresql pg_restore --list \
  < "$BAK/nexent.dump" > "$BAK/nexent-dump-toc.txt"
```

启用内置 Supabase 时，额外导出其数据库及角色：

```bash
docker exec supabase-db-mini sh -c \
  'pg_dump -U postgres -d "$POSTGRES_DB" -Fc' > "$BAK/supabase.dump"
docker exec supabase-db-mini sh -c \
  'pg_dumpall -U postgres --globals-only' > "$BAK/supabase-globals.sql"
docker exec -i supabase-db-mini pg_restore --list \
  < "$BAK/supabase.dump" > "$BAK/supabase-dump-toc.txt"
```

Supabase 容器已配置 `PGPORT` 和 `PGPASSWORD`。实际容器名、数据库名或部署方式不同，应据实调整；如果有额外业务数据库，应分别导出。`pg_restore --list` 仅验证归档可读取，完整性仍以隔离环境恢复验证为准。

### 3.4 创建 Elasticsearch 快照

**不要使用 Elasticsearch 数据目录的文件复制作为受支持的恢复方案，即使已经停机。** 升级前必须已有可用的 Snapshot repository，并确认其存储不依赖将被覆盖的生产数据目录。仓库的存储、注册信息和凭证也应保留。

仓库需提前配置并演练。使用 `fs` 仓库时，先在 ES 节点配置 `path.repo`，挂载专用备份目录并设置权限，重启后注册仓库；使用 S3 仓库时，按实际存储配置 endpoint 和 keystore 凭证。当前 Compose 默认没有配置快照仓库，这些设置需要作为部署定制项保存，并在升级、恢复时重新挂载，不能只调用 API 而不准备底层存储。参见 [Elasticsearch 快照仓库配置](https://www.elastic.co/guide/en/elasticsearch/reference/8.17/snapshots-register-repository.html)。

以下示例要求仓库已注册。`ES_INDICES` 必须替换为实际业务索引或数据流列表；通过索引清单及业务配置核对，不能遗漏知识库，也不要包含 `.security*` 等系统索引。

```bash
ES_REPO=nexent-backup
ES_SNAPSHOT="pre-upgrade-$STAMP"
ES_INDICES='knowledge_index_a,knowledge_index_b'

es_request() {
  docker exec nexent-elasticsearch sh -c \
    'curl -fsS -u "elastic:$ELASTIC_PASSWORD" -H "Content-Type: application/json" "$@"' \
    sh "$@"
}

es_request 'http://localhost:9200/_cat/indices?format=json&expand_wildcards=all' \
  > "$BAK/es-indices.json"
es_request "http://localhost:9200/_snapshot/$ES_REPO" > "$BAK/es-repository.json"
es_request -X POST "http://localhost:9200/_snapshot/$ES_REPO/_verify" \
  > "$BAK/es-repository-verify.json"
es_request 'http://localhost:9200/_index_template' > "$BAK/es-index-templates.json"
es_request 'http://localhost:9200/_component_template' > "$BAK/es-component-templates.json"
es_request 'http://localhost:9200/_template' > "$BAK/es-legacy-templates.json"
es_request -X PUT \
  "http://localhost:9200/_snapshot/$ES_REPO/$ES_SNAPSHOT?wait_for_completion=true" \
  -d "{\"indices\":\"$ES_INDICES\",\"ignore_unavailable\":false,\"include_global_state\":false,\"feature_states\":[\"none\"]}" \
  > "$BAK/es-snapshot-result.json"
es_request "http://localhost:9200/_snapshot/$ES_REPO/$ES_SNAPSHOT" \
  > "$BAK/es-snapshot-status.json"
printf 'repository=%s\nsnapshot=%s\nindices=%s\n' \
  "$ES_REPO" "$ES_SNAPSHOT" "$ES_INDICES" > "$BAK/es-restore-point.txt"
```

检查结果必须为 `SUCCESS` 且失败分片为 0，并核对索引清单。HTTP 请求成功或 JSON 文件存在都不能代替这一步。请求超时后先查询快照状态；不要在快照进行中复制或清理仓库。

此方案备份业务索引，不恢复 ES 系统安全状态。自定义 ILM policy、ingest pipeline、集群设置、用户和角色需另外导出并演练重建；后续恢复业务索引时，须重新生成 Nexent 的 Elasticsearch API key。快照的索引数据、映射和别名随快照恢复，模板按导出内容逐项重建。

### 3.5 停止存储并归档数据目录、命名卷

完成逻辑备份和 ES 快照后，停止清单中的其余容器。所有备份数据的写入方均须保持停止，包括监控组件及外部客户端；归档期间不要运行部署脚本或让自动运维系统重启服务。

```bash
for container in "${TARGETS[@]}"; do
  docker stop --time 120 "$container"
done
docker inspect --format '{{.Name}} {{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}' \
  "${TARGETS[@]}" > "$BAK/stopped-state.txt"
```

核对所有容器均为停止状态，存储日志显示正常关闭，没有被强制结束或 OOM。确认后归档。示例用户目录与数据目录互相独立；Elasticsearch 原始数据目录明确排除。

```bash
sudo tar --numeric-owner --acls --xattrs --exclude='./elasticsearch' \
  -cpf - -C "$DATA_DIR" . > "$BAK/data-root.tar"
sudo tar --numeric-owner --acls --xattrs \
  -cpf - -C "$USER_DATA_DIR" . > "$BAK/user-data.tar"

tar --exclude='./.git' --exclude='node_modules' --exclude='.venv' \
  -cpf "$BAK/release.tar" -C "$CODE_DIR" .
```

外部终端目录、代理配置、证书、自定义 bind mount 按同样方式分别归档，并记录原路径。`release.tar` 保存现场文件，包括未跟踪的部署配置；如包含仅 root 可读文件，应使用有读取权限的账号归档，不能忽略 tar 的报错。

命名卷在 Docker daemon 所在主机读取，通过辅助容器归档。提前准备可信且包含 GNU tar 的辅助镜像，生产环境可将下列引用替换为已核验的 digest；离线环境须预先加载。

```bash
BACKUP_HELPER_IMAGE=ubuntu:24.04
docker image inspect "$BACKUP_HELPER_IMAGE" >/dev/null
mkdir -p "$BAK/volumes"
while IFS= read -r volume; do
  docker volume inspect "$volume" > "$BAK/volumes/$volume.inspect.json"
  docker run --rm --network none --user 0 \
    -v "$volume:/source:ro" "$BACKUP_HELPER_IMAGE" \
    tar --numeric-owner --acls --xattrs -cpf - -C /source . \
    > "$BAK/volumes/$volume.tar"
done < "$BAK/volumes.txt"
```

核对清单包含实际使用的智能体工作区、Supabase 配置卷及所有启用的监控持久卷。远程卷驱动的权限和一致性要求由存储平台确认；此归档流程仅用于已停止写入、支持文件级归档的卷。

### 3.6 校验与异地保存

```bash
test -s "$BAK/nexent.dump"
tar -tf "$BAK/data-root.tar" > "$BAK/data-root-files.txt"
tar -tf "$BAK/user-data.tar" > "$BAK/user-data-files.txt"
tar -tf "$BAK/release.tar" > "$BAK/release-files.txt"
for archive in "$BAK"/volumes/*.tar; do
  test -f "$archive" || continue
  tar -tf "$archive" >/dev/null
done
(
  cd "$BAK"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
```

将目录及 ES 快照仓库副本保存到另一台主机或独立备份存储，并在接收端校验。复制 ES 仓库前，应确保没有快照、删除或其他仓库写入任务；保留完整仓库结构，不能只复制某个快照名称对应的文件。ES JSON 结果文件本身不包含索引数据。

记录备份完成时间、各存储恢复点、校验结果和演练结果。备份失败时不进入升级；若取消维护，按原依赖顺序恢复 `running-before.txt` 中原本运行的服务并验收，避免误启动原本停用的服务。

## 4. Docker：执行升级

### 4.1 在线代码或发布包

建议提前把目标版本放到独立目录，并保留旧部署目录。通过 Git 获取发布版本时使用已经确认存在的 tag，例如：

```bash
TARGET_REF=vX.Y.Z
NEW_CODE_DIR=/opt/nexent-release-X.Y.Z
git clone --branch "$TARGET_REF" --depth 1 \
  https://github.com/ModelEngine-Group/nexent.git "$NEW_CODE_DIR"
```

在新目录复用旧环境配置，不覆盖新版本的模板和 SQL：

```bash
cp -p "$CODE_DIR/deploy/env/.env" "$NEW_CODE_DIR/deploy/env/.env"
if test -f "$CODE_DIR/deploy/env/monitoring.env"; then
  cp -p "$CODE_DIR/deploy/env/monitoring.env" "$NEW_CODE_DIR/deploy/env/monitoring.env"
fi
cp -p "$CODE_DIR/deploy/docker/deploy.options" "$NEW_CODE_DIR/deploy/docker/deploy.options"
```

没有旧 `deploy.options` 时，按原部署记录重新配置，不能接受未核对的默认值。迁移定制 Compose、反向代理和快照仓库配置时逐项合并，勿把整个旧 `deploy/` 复制到新版本。

检查新目录的 `ROOT_DIR`、密钥、组件、端口、用户目录、镜像源和目标版本，然后在**新目录**执行：

```bash
cd "$NEW_CODE_DIR"
set -o pipefail
bash deploy.sh docker --defaults --version X.Y.Z 2>&1 | tee "$BAK/upgrade.log"
```

`X.Y.Z` 是镜像使用的应用版本，未必与 Git tag 的前缀完全相同，请按发布包及镜像仓库核对。保存的 `local-latest` 会使用本地 `latest` 镜像，不能仅凭 `--version` 认为已升级；需要核对本地新镜像 ID，或明确切换到发布版本对应的镜像源。部署摘要和实际镜像与预期不符时立即停止。

### 4.2 离线部署包

提前校验并解压目标版本的完整离线包，保留旧包和旧镜像。在新离线包根目录执行：

```bash
bash deploy.sh --load-images --reuse-from /opt/nexent-old-package --defaults docker
```

`--reuse-from` 仅由离线部署包入口支持，会复用旧包的 `.env`、`monitoring.env` 及 Docker 部署选项；源码仓库入口不支持该参数。原部署不属于此目录结构时，按上一节手工迁移配置。离线包的镜像加载工具、架构和全部依赖镜像须在维护前验证，不要等停机后再下载缺失镜像。

### 4.3 理解自动数据库迁移

- Docker 和 Kubernetes 都只有 `nexent-config` 负责运行自动迁移；其他相关后端服务等待迁移达到目标状态。
- `deploy/sql/init.sql` 会在迁移流程中执行，`deploy/sql/migrations/*.sql` 按版本文件名顺序处理，记录位于 `nexent.schema_migrations`。
- 迁移文件 checksum 相同会跳过；checksum 改变会触发重执行，并可能连带重执行后续文件。因此，**已合并的所有 SQL 文件都不可修改、改名或删除**，包括 init 和 Supabase SQL；数据库变更只能添加新的版本化迁移文件。
- 自动迁移不提供通用的反向迁移。失败时可能已有部分 SQL 生效，应检查日志和数据库实际状态，不能假设“脚本报错等于什么都没改”。

`deploy/docker/upgrade.sh` 已废弃，只转发到部署脚本。升级统一使用 `bash deploy.sh docker`，不要使用卸载脚本、`down -v`、volume prune 或镜像强制清理命令准备升级。

## 5. 升级验收与开放流量

先保持维护状态，依次检查以下项目；仅看到 Web 页面或容器为 `Up` 不足以验收。

```bash
docker ps -a --filter label=com.docker.compose.project=nexent
docker logs --tail 200 nexent-config
docker logs --tail 200 nexent-runtime
docker exec nexent-postgresql sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT migration_id, status, app_version, executed_at FROM nexent.schema_migrations ORDER BY migration_id;"'
docker exec nexent-redis redis-cli ping
```

检查 `nexent-config` 的 `[sql-migrations]` 日志，并将迁移记录与目标版本 SQL 文件集合核对。启用数据处理、Supabase、MCP 或监控时，额外查看对应容器状态与日志。

| 验收项 | 通过标准 |
| --- | --- |
| 版本与启动 | 实际镜像为目标 ID/digest；服务稳定，无持续重启、OOM、迁移失败或等待超时 |
| 登录与权限 | 原有用户能登录；租户、角色及权限正常；启用 Supabase 时验证已有账户 |
| 智能体 | 原有配置可读取；选择测试智能体完成一次模型请求、流式响应及工具调用 |
| 知识库 | 原有知识库可检索，引用来源可打开；索引数量和文档数量与基线一致；无未分配主分片 |
| 文件处理 | 测试文件上传、解析、入库、检索、下载成功；验收文件可追踪并在验收后清理 |
| 持久化数据 | 关键业务记录、MinIO 对象和工作区文件抽样一致；不能以总数量接近代替关键记录核对 |
| 可选组件 | 按启用情况验证 MCP、沙箱、终端和监控 Trace；队列无异常积压或重复任务 |

ES 单节点环境可能因副本未分配而呈 `yellow`，需要确认主分片正常；`red` 或业务索引丢失不能通过。完成验收后逐步恢复入口、定时任务和外部调用，并在约定观察期内监测错误率、延迟和队列。保留本次升级日志，不要立即清理旧镜像或备份。

## 6. Docker：回滚

### 6.1 选择恢复范围

| 现场情况 | 处理方式 |
| --- | --- |
| 新版本未启动，没有迁移及新写入 | 恢复旧代码、配置、镜像，使用原数据启动 |
| 已启动新版本，但已验证旧应用兼容现有 schema 和存储格式 | 可只回退应用；仍须使用旧配置和旧 SQL 集合，并完成验收 |
| 迁移失败、数据已转换、中间件数据格式变化，或兼容性不能确认 | 恢复同一维护窗口的数据库、对象、索引、工作区等配套备份，再启动旧版本 |
| 升级后已经开放流量并产生新数据 | 先保留现场、评估新增数据处理方式；不能直接覆盖为旧备份而声称无数据损失 |

**只改回镜像 tag、Git 提交或 Helm revision，不会自动回滚数据库、MinIO、ES 和持久卷。** 回滚前再次关闭入口、停止写入，保存失败日志、当前镜像、迁移记录和必要的现场数据副本。

### 6.2 恢复旧部署资料

以下按“整套数据恢复”执行；已确认仅应用回退时跳过数据恢复步骤。重新打开终端时，先根据备份记录设置 `BAK`、`CODE_DIR`、`DATA_DIR`、`USER_DATA_DIR`，不能沿用未经核对的示例值。

1. 校验 `SHA256SUMS` 和 ES 快照状态。停止当前环境全部写入方及存储服务。
2. 将失败现场另存，保留其目录或存储快照。把 `release.tar` 解压到原部署绝对路径的空目录，或使用完整保留的旧部署目录；不要混入新版 SQL、配置和脚本。
3. 加载旧镜像并按备份映射恢复标签。**只在目标部署主机操作**，该步骤会改变相同标签在本机的指向。

```bash
docker image load < "$BAK/images.tar"
while read -r container image_ref image_id; do
  docker image inspect "$image_id" >/dev/null
  case "$image_ref" in
    *@sha256:*)
      printf 'Verify digest reference separately: %s\n' "$image_ref"
      continue
      ;;
  esac
  docker image tag "$image_id" "$image_ref"
done < "$BAK/images.txt"
```

脚本会跳过 `repository@sha256:...` 引用，须另外验证该 digest 可用且对应已保存的 ID，或将保存的 ID 赋予专用回滚标签并在旧配置中显式引用；tag 命令不能以 digest 为目标。镜像恢复前还需解决前文提到的同标签多 ID 情况，不能让循环最后一行决定多个服务的版本。

### 6.3 恢复数据到空目录或空卷

物理归档恢复只用于相同数据库/存储镜像版本及兼容平台。不能把旧 PostgreSQL 物理数据交给不同大版本，也不能把备份直接解压覆盖到已有数据库文件上。下例要求数据目录与用户目录独立，且不包含仍被其他服务使用的挂载点：

```bash
FAILED_STAMP=$(date -u +%Y%m%d-%H%M%S)
sudo mv "$DATA_DIR" "${DATA_DIR}.failed-$FAILED_STAMP"
sudo mkdir -p "$DATA_DIR"
sudo tar --numeric-owner --same-owner --acls --xattrs \
  -xpf "$BAK/data-root.tar" -C "$DATA_DIR"
sudo mkdir -p "$DATA_DIR/elasticsearch"
sudo chown --reference="${DATA_DIR}.failed-$FAILED_STAMP/elasticsearch" "$DATA_DIR/elasticsearch"
sudo chmod --reference="${DATA_DIR}.failed-$FAILED_STAMP/elasticsearch" "$DATA_DIR/elasticsearch"

sudo mv "$USER_DATA_DIR" "${USER_DATA_DIR}.failed-$FAILED_STAMP"
sudo mkdir -p "$USER_DATA_DIR"
sudo tar --numeric-owner --same-owner --acls --xattrs \
  -xpf "$BAK/user-data.tar" -C "$USER_DATA_DIR"
```

示例为 ES 新建空目录，并沿用现场 ES 目录的属主与权限，避免 Docker 自动创建 root 所属目录导致 ES 无法启动；如果实际 ES 路径不同或现场已经损坏，应使用升级前记录和旧镜像要求设置权限。数据目录本身为独立磁盘挂载点时，不执行 `mv` 示例；改用存储平台快照保留现场，再恢复到新的空目录/磁盘并更新挂载。按清单恢复其他 bind mount，保留 UID/GID、ACL 和必要的 SELinux 标签。

命名卷推荐恢复到**新空卷**，保留旧卷用于现场分析。例如恢复智能体工作区：

```bash
SOURCE_VOLUME=nexent-agent-workspace
RESTORED_VOLUME="nexent-agent-workspace-restored-$FAILED_STAMP"
BACKUP_HELPER_IMAGE=ubuntu:24.04
docker volume create "$RESTORED_VOLUME"
docker run --rm -i --network none --user 0 \
  -v "$RESTORED_VOLUME:/restore" "$BACKUP_HELPER_IMAGE" \
  tar --numeric-owner --same-owner --acls --xattrs -xpf - -C /restore \
  < "$BAK/volumes/$SOURCE_VOLUME.tar"
```

将旧 `.env` 的 `NEXENT_SANDBOX_WORKSPACE_VOLUME` 指向该新卷。其他卷同样恢复，使用 Compose override 的卷 `name`/`external` 配置显式绑定新卷，并核对实际 Mounts。不指定驱动的 `docker volume create` 只适用于本地卷；自定义卷驱动按原记录创建。监控和 Supabase 命名卷不能遗漏。

这里已经恢复业务 PostgreSQL 和 Supabase 的停机物理归档，不再向其中重复导入 `.dump`。如果选择逻辑恢复，应使用对应版本的独立空 PostgreSQL 实例，先核对角色与扩展，再以 `pg_restore --exit-on-error` 恢复到新建空数据库；Supabase 还需其专用角色、扩展及初始化顺序。逻辑恢复必须先经过演练，禁止直接对生产库使用 `--clean` 或执行未经核对的 globals SQL。

### 6.4 先恢复存储，再启动旧应用

**不要在 ES 恢复前运行完整部署脚本**，它会启动应用和自动迁移。先用旧版本 Compose 仅启动存储。下面的函数用于默认项目，若有恢复卷或 ES 仓库 override，应追加对应 `-f` 参数并先检查最终配置。

```bash
cd "$CODE_DIR"
set -a
source "$CODE_DIR/deploy/docker/.env.generated"
set +a
export NEXENT_USER_DIR="$USER_DATA_DIR"
COMPOSE_MAIN="$CODE_DIR/deploy/docker/compose/docker-compose.yml"
COMPOSE_AUTH="$CODE_DIR/deploy/docker/compose/docker-compose-supabase.yml"

dc() {
  docker compose --env-file "$CODE_DIR/deploy/env/.env" -p nexent \
    -f "$COMPOSE_MAIN" "$@"
}
dc config --quiet
dc up -d --no-build --force-recreate nexent-postgresql redis nexent-minio nexent-elasticsearch
```

生产端口策略需改用 `docker-compose.prod.yml` 和 `docker-compose-supabase.prod.yml`。这里只加载自己保存并核验过的 `.env.generated`，它保存 Compose 所需镜像变量；不要以为只指定 `.env` 就能解析全部镜像。若该文件不存在，应按旧版部署记录准备镜像变量，不能先启动应用来生成它。启动前检查引用对应已加载的旧镜像，避免从仓库获得被覆盖的同名标签。

启用 Supabase 时，仅启动其数据库并检查就绪状态：

```bash
docker compose --env-file "$CODE_DIR/deploy/env/.env" -p nexent \
  -f "$COMPOSE_AUTH" up -d --no-build --force-recreate db
```

ES 原始目录未包含在备份中，因此此时应为使用旧版本镜像的空集群。先重新定义第 3.4 节的 `es_request` 函数，并从 `es-restore-point.txt` 恢复 `ES_REPO`、`ES_SNAPSHOT` 和 `ES_INDICES`。挂载并注册升级前快照仓库，恢复目标对同一仓库仅使用只读注册，避免多个集群同时写入。`fs` 仓库注册示例仅在 `path.repo` 和备份目录挂载已准备好时可用：

```bash
es_request -X PUT "http://localhost:9200/_snapshot/$ES_REPO" \
  -d '{"type":"fs","settings":{"location":"/mnt/es-backup","readonly":true}}'
```

确认快照版本与运行中的 ES 兼容、业务索引不存在冲突；先重建必要模板，数据流尤其需要对应模板，再恢复业务快照：

```bash
es_request -X POST \
  "http://localhost:9200/_snapshot/$ES_REPO/$ES_SNAPSHOT/_restore?wait_for_completion=true" \
  -d "{\"indices\":\"$ES_INDICES\",\"include_global_state\":false,\"feature_states\":[\"none\"]}"
es_request 'http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=120s'
es_request 'http://localhost:9200/_cat/indices?format=json&expand_wildcards=all'
```

检查恢复请求失败分片为 0、健康检查未超时、所有业务主分片已就绪，核对索引和文档基线。MinIO 对象、两套 PostgreSQL 和工作区恢复确认后，才能启动旧应用。

ES 系统安全状态没有随业务快照恢复，旧 `ELASTICSEARCH_API_KEY` 应重新生成。默认部署可在**旧目录、旧应用版本**下执行 `bash deploy.sh docker --defaults --version OLD_VERSION --refresh-es-key`，然后按第 5 节验收。该入口还可能拉取 MCP、沙箱镜像，执行前必须确保旧版本引用指向已归档的正确镜像。当前部署入口不会自动带上人工新增的 Compose override；如果用了新命名卷或快照仓库 override，先将这些定制正确接入恢复用部署配置，或按已演练的 Compose 启动流程执行，确保完整部署不会把挂载切回旧卷。

恢复后继续保持维护状态，确认旧版本不会重复处理未完成任务，再恢复认证入口、应用入口及定时任务。只有验收通过才结束回滚。

## 7. Kubernetes：备份、升级与回滚

Kubernetes 遵循相同的一致性和版本原则，但数据由 PVC/PV 及存储平台管理。**Helm release 导出不是数据备份，`helm rollback` 不会恢复 PVC 内容或数据库 schema。**

### 7.1 保存 release、配置和存储清单

默认 namespace 和 release 都是 `nexent`，按实际修改。备份目录应位于可靠的管理端存储中，同样使用限制权限的 Bash 会话。

```bash
set -euo pipefail
umask 077
NS=nexent
RELEASE=nexent
K8S_BAK="/backup/nexent/k8s-$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$K8S_BAK"

helm history "$RELEASE" -n "$NS" > "$K8S_BAK/helm-history.txt"
helm get values "$RELEASE" -n "$NS" --all > "$K8S_BAK/helm-values.yaml"
helm get manifest "$RELEASE" -n "$NS" > "$K8S_BAK/helm-manifest.yaml"
kubectl get deployment,statefulset,cronjob,hpa -n "$NS" -o yaml > "$K8S_BAK/workloads.yaml"
kubectl get pods -n "$NS" -o json > "$K8S_BAK/pods.json"
kubectl get pvc -n "$NS" -o yaml > "$K8S_BAK/pvc.yaml"
kubectl get pv -o yaml > "$K8S_BAK/pv.yaml"
kubectl get configmap,secret -n "$NS" -o yaml > "$K8S_BAK/config-and-secrets.yaml"
```

PV 查询是集群级读取，需要相应权限；仅保留本次恢复需要的 PV 记录。Secret 的 base64 编码不等于加密。以上清单用于恢复比对，不应把含 `uid`、`resourceVersion`、`status` 等服务器字段的导出文件直接当作可重复部署的模板。

另行保存原部署目录中的 `.env`、`monitoring.env`、`deploy/k8s/deploy.options`、Chart 及 `generated-*.yaml`，记录 Pod 中的实际 `imageID` 并归档旧镜像。生成的 values 可能包含密钥，不能提交版本库。

### 7.2 暂停写入并备份持久化数据

先切换 Ingress/网关维护状态，暂停 CronJob、外部调用、GitOps 自动同步和可能重新扩容的 HPA，记录原副本数。排空任务后将应用写入方缩容到 0，保留存储服务用于逻辑备份。例如：

```bash
kubectl scale deployment/nexent-web deployment/nexent-config \
  deployment/nexent-runtime deployment/nexent-mcp deployment/nexent-northbound \
  -n "$NS" --replicas=0
```

按实际启用情况补充 data-process、Supabase auth、终端、动态工作负载及监控写入方；等待相关 Pod 完全退出，不能只看 scale 命令成功。业务数据库逻辑备份示例：

```bash
kubectl exec -n "$NS" deployment/nexent-postgresql -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$K8S_BAK/nexent.dump"
kubectl exec -n "$NS" deployment/nexent-postgresql -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dumpall -U "$POSTGRES_USER" --globals-only' \
  > "$K8S_BAK/nexent-globals.sql"
```

启用 Supabase 时，在 `deployment/nexent-supabase-db` 内按第 3.3 节另外导出数据库与角色。ES 按第 3.4 节通过集群内部访问或受控 port-forward 创建业务快照；仍不使用 ES 数据目录复制作为恢复方案。

其余 PVC 按存储类型处理，覆盖 PostgreSQL、Supabase、MinIO、Redis、`nexent-workspace`、`nexent-skills` 及监控 PVC：

| 持久化方式 | 备份与恢复要求 |
| --- | --- |
| `local` | 保存 PV 路径、节点和亲和性；正常停止对应存储 Pod 后，在实际节点归档目录。默认数据位于 `/var/lib/nexent-data`，共享工作区默认位于 `/var/lib/nexent`，必须分别核对 |
| `dynamic`，CSI 支持快照 | 按驱动创建 VolumeSnapshot，确认 `readyToUse`、快照保留策略及异地保护；应用写入和数据库须按备份策略停止，单卷快照不自动提供跨卷一致性 |
| `existing` 或外部存储 | 按实际存储平台备份；记录 claim、驱动、快照 ID、容量、访问模式和恢复绑定步骤 |

Kubernetes 不保证已安装 VolumeSnapshot CRD 或可用的 VolumeSnapshotClass，不能直接套用其他集群的快照 YAML。完成备份后做校验和隔离恢复演练，记录对应的 release revision。

### 7.3 升级

按第 4 节准备目标版本目录，复用 `.env`、`monitoring.env` 和 `deploy/k8s/deploy.options`，逐项合并持久化及其他定制配置。在目标目录执行：

```bash
set -o pipefail
bash deploy.sh k8s --defaults --version X.Y.Z 2>&1 | tee "$K8S_BAK/upgrade.log"
kubectl get pods,pvc -n "$NS"
kubectl rollout status deployment/nexent-config -n "$NS" --timeout=600s
kubectl rollout status deployment/nexent-runtime -n "$NS" --timeout=600s
kubectl logs -n "$NS" deployment/nexent-config --tail=200
```

当前脚本使用 `helm upgrade --install`，不代表数据库具有自动回滚能力。按实际启用服务检查 rollout 和业务功能，完成第 5 节验收后再开放流量。`generated-*.yaml` 会在部署时重新生成，持久配置应修改来源文件或部署参数。

### 7.4 回滚

**仅应用回退、且已验证 schema/存储兼容时**，在维护状态下使用备份记录中的 revision：

```bash
ROLLBACK_REVISION=3
helm rollback "$RELEASE" "$ROLLBACK_REVISION" -n "$NS" --wait --timeout 10m
kubectl get pods,pvc -n "$NS"
```

`3` 仅为示例，不要默认“上一条 revision 就是可用版本”。Helm 回滚会恢复旧资源配置，也可能立即启动应用；因此不适合作为完整数据恢复的第一步。旧镜像必须仍可拉取或已在节点准备好。

需要整套数据恢复时，按以下顺序执行：

1. 关闭入口，暂停控制器自动恢复副本，停止全部写入方；保存失败现场及当前 PVC 快照。
2. 从同一备份窗口恢复新的空 PVC 或 local 目录，保留旧 PVC，检查 PV reclaim policy，避免删除 claim 导致底层数据删除。恢复两套数据库、MinIO、Redis、工作区、技能及需要保留的监控数据。
3. 使用旧 Chart 和旧配置制作恢复 values：所有应用写入方副本为 0，所有持久卷显式绑定到恢复出来的 claim。先用 `helm template` 核对实际副本和卷绑定，再由恢复用 Helm 配置启动旧版存储；不要直接运行会重新生成 values 并启动应用的完整部署入口。
4. 恢复业务 ES 快照及模板，核对各存储数据；重建必要凭证。不要用新版本 ES 创建的快照恢复到更旧、不兼容的版本，应使用升级前快照与原 ES 版本。
5. 将恢复后的凭证和卷绑定同步到持久配置来源，再逐步恢复旧应用的原副本数。检查迁移日志，按第 5 节验收，再恢复流量、定时任务、HPA 和 GitOps。

## 8. 操作记录模板

每次维护保留一份记录，便于定位恢复点和交接：

| 项目 | 填写内容 |
| --- | --- |
| 环境与负责人 | 部署主机或集群、namespace、执行人、复核人 |
| 版本 | 旧/新 Git 提交或发布包版本、镜像 ID/digest、Helm revision |
| 配置 | 部署路径、组件、端口、镜像源、数据目录或 PVC 清单 |
| 备份 | 备份目录、异地位置、完成时间、checksum、ES snapshot 名称 |
| 恢复验证 | 演练日期、恢复耗时、关键数据抽样结果 |
| 时间安排 | 维护窗口、最迟回滚时间、RPO/RTO、观察期及保留期限 |
| 执行结果 | 升级日志、迁移状态、验收结果、开放流量时间 |
| 回滚情况 | 触发原因、恢复点、新增数据处理方式、恢复后的验收结果 |

相关入口：[Docker 安装部署](./installation.md)、[Kubernetes 安装部署](./kubernetes-installation.md)。
