# Nexent Kubernetes 升级指南

本文适用于使用 Helm 部署的 Nexent。建议在无人使用或业务低峰窗口执行，尽量减少备份和升级期间的新请求与数据写入。这是操作建议，不要求检测在线用户、拦截请求、缩容 Deployment 或停止 Pod。

> ⚠️ 本文通过 `kubectl cp` 或 `kubectl exec` 从运行中的容器直接复制持久化文件。如果复制期间 PostgreSQL、Elasticsearch、Redis 或 MinIO 仍在写入，副本可能不属于同一时间点，不保证能够直接恢复。

## 1. 升级前准备

### 1.1 记录版本、Helm 和存储状态

默认 namespace 为 `nexent`，应按实际环境调整。执行 `kubectl` 的本地机器是备份目标。

```bash
set -euo pipefail

CODE_DIR=/opt/nexent
TARGET_VERSION=X.Y.Z
NS=nexent
APP_RELEASE=nexent
INFRA_RELEASE=nexent-infrastructure
BACKUP_BASE=/backup/nexent
STAMP=$(date -u +%Y%m%d-%H%M%S)
K8S_BACKUP_DIR="$BACKUP_BASE/k8s-$STAMP"

mkdir -p "$K8S_BACKUP_DIR/data"
cd "$CODE_DIR"

printf 'target_version=%s\n' "$TARGET_VERSION" > "$K8S_BACKUP_DIR/version.txt"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git rev-parse HEAD >> "$K8S_BACKUP_DIR/version.txt"
  git status --short > "$K8S_BACKUP_DIR/git-status.txt"
fi

helm history "$INFRA_RELEASE" -n "$NS" > "$K8S_BACKUP_DIR/helm-infrastructure-history.txt"
helm history "$APP_RELEASE" -n "$NS" > "$K8S_BACKUP_DIR/helm-application-history.txt"
helm get values "$INFRA_RELEASE" -n "$NS" --all > "$K8S_BACKUP_DIR/helm-infrastructure-values.yaml"
helm get values "$APP_RELEASE" -n "$NS" --all > "$K8S_BACKUP_DIR/helm-application-values.yaml"
kubectl get deployment -n "$NS" -o wide > "$K8S_BACKUP_DIR/deployments.txt"
kubectl get pods -n "$NS" -o wide > "$K8S_BACKUP_DIR/pods.txt"
kubectl get pvc -n "$NS" -o wide > "$K8S_BACKUP_DIR/pvc.txt"
kubectl get pv -o wide > "$K8S_BACKUP_DIR/pv.txt"
```

Helm values 和资源清单可能包含密码或令牌，只能保存在受限的本地目录中。`kubectl get pv` 需要集群级读权限；如果操作账号无此权限，应记录该项未采集，不得忽略其他检查。

### 1.2 检查空间

先查看 PVC 申请容量和本地备份目录的可用空间：

```bash
kubectl get pvc -n "$NS"
df -h "$BACKUP_BASE"
```

使用以下函数查看已启用组件在容器内的实际数据量：

```bash
show_remote_size() {
  local app="$1"
  local container="$2"
  local source="$3"
  local pod

  pod=$(kubectl get pods -n "$NS" -l "app=$app" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}')
  test -n "$pod"
  kubectl exec -n "$NS" "$pod" -c "$container" -- du -sh "$source"
}

show_remote_size nexent-postgresql postgresql /var/lib/postgresql/data
show_remote_size nexent-elasticsearch elasticsearch /usr/share/elasticsearch/data
show_remote_size nexent-minio minio /data
show_remote_size nexent-redis redis /data
show_remote_size nexent-runtime nexent-runtime /mnt/nexent
show_remote_size nexent-runtime nexent-runtime /mnt/nexent-data/skills
show_remote_size nexent-runtime nexent-runtime /mnt/nexent-data/memory-provider-plugins
show_remote_size nexent-runtime nexent-runtime /mnt/nexent-data/logs
```

如果启用了 Supabase 或监控，还需查看对应容器目录。确认本地可用空间大于所有待复制数据之和，并为 `kubectl cp` 的临时文件预留额外空间。

### 1.3 从运行中的容器复制数据

以下函数根据 `app` label 选择一个运行中的 Pod，将指定目录复制到本地。对未启用的可选组件会输出 `SKIP`。

```bash
copy_from_app() {
  local app="$1"
  local container="$2"
  local source="$3"
  local target="$4"
  local pod

  if ! kubectl get deployment "$app" -n "$NS" >/dev/null 2>&1; then
    printf 'SKIP: deployment/%s is not enabled\n' "$app"
    return 0
  fi

  pod=$(kubectl get pods -n "$NS" -l "app=$app" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}')
  test -n "$pod"
  mkdir -p "$(dirname "$K8S_BACKUP_DIR/data/$target")"
  kubectl exec -n "$NS" "$pod" -c "$container" -- du -sh "$source"
  kubectl cp -n "$NS" -c "$container" \
    "$pod:$source" "$K8S_BACKUP_DIR/data/$target"
}

copy_from_app nexent-postgresql postgresql \
  /var/lib/postgresql/data postgresql
copy_from_app nexent-elasticsearch elasticsearch \
  /usr/share/elasticsearch/data elasticsearch
copy_from_app nexent-minio minio /data minio
copy_from_app nexent-redis redis /data redis
copy_from_app nexent-supabase-db supabase-db \
  /var/lib/postgresql/data supabase-postgresql
copy_from_app nexent-runtime nexent-runtime \
  /mnt/nexent workspace
copy_from_app nexent-runtime nexent-runtime \
  /mnt/nexent-data/skills skills
copy_from_app nexent-runtime nexent-runtime \
  /mnt/nexent-data/memory-provider-plugins memory-provider-plugins
copy_from_app nexent-runtime nexent-runtime \
  /mnt/nexent-data/logs logs
```

启用监控时，使用同一函数复制已启用的持久化组件：

```bash
copy_from_app nexent-phoenix phoenix /mnt/data monitoring/phoenix
copy_from_app nexent-tempo tempo /var/tempo monitoring/tempo
copy_from_app nexent-grafana grafana /var/lib/grafana monitoring/grafana
copy_from_app nexent-langfuse-postgres postgres \
  /var/lib/postgresql/data monitoring/langfuse-postgresql
copy_from_app nexent-langfuse-clickhouse clickhouse \
  /var/lib/clickhouse monitoring/langfuse-clickhouse
copy_from_app nexent-langfuse-minio minio /data monitoring/langfuse-minio
copy_from_app nexent-langfuse-redis redis /data monitoring/langfuse-redis
```

`kubectl cp` 依赖目标容器内的 `tar`。如果复制命令不可用，可将 tar 流直接保存到本地：

```bash
POD=$(kubectl get pods -n "$NS" -l app=nexent-postgresql \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NS" "$POD" -c postgresql -- \
  tar -C /var/lib/postgresql -cf - data \
  > "$K8S_BACKUP_DIR/data/postgresql.tar"
```

如果目标容器没有 `tar`，只能选择另一个已经挂载同一 PVC 且包含 `tar` 的现有容器。本流程不创建临时 Pod，所有数据均从现有容器导出到本地机器。

本流程不生成 SHA-256 文件。通过命令退出状态、目标文件存在性和空间占用核对结果：

```bash
test -d "$K8S_BACKUP_DIR/data"
find "$K8S_BACKUP_DIR/data" -mindepth 1 -maxdepth 2 -print
du -sh "$K8S_BACKUP_DIR/data"/*
```

## 2. 执行升级

通过 Git 管理部署代码时，先确认当前分支和目标版本，再以快进方式更新。

```bash
cd "$CODE_DIR"
git branch --show-current
git pull --ff-only
bash deploy.sh --defaults k8s --version X.Y.Z
```

`--defaults` 会复用已保存的 Kubernetes 部署配置并跳过交互界面。升级前应确认 `deploy/k8s/deploy.options` 中的组件、端口策略、镜像源、持久化模式和 namespace 与原环境一致。

使用完整离线部署包时，在新包根目录执行：

```bash
bash deploy.sh --load-images --reuse-from /opt/nexent-old-package --defaults k8s
```

`--reuse-from` 仅用于离线包入口，会复用旧包的 `.env`、`monitoring.env` 和 Kubernetes 部署选项。

升级时由 `nexent-config` 执行数据库自动迁移，其他后端服务会等待迁移达到目标状态。已合并的 SQL 文件不可修改、改名或删除。

## 3. 升级后检查

检查 Deployment rollout、Pod 和 PVC：

```bash
kubectl get deployment -n "$NS"
kubectl get pods -n "$NS" -o wide
kubectl get pvc -n "$NS"

while IFS= read -r deployment; do
  kubectl rollout status -n "$NS" "$deployment" --timeout=600s
done < <(kubectl get deployment -n "$NS" -o name)

kubectl logs -n "$NS" deployment/nexent-config --tail=200
```

升级通过需要满足：

- 所有已选组件的 Deployment 都完成 rollout，Pod 为 `Running` 且 READY 数量符合预期。
- 不存在 `CrashLoopBackOff`、`Error` 或长时间 `Pending` 的 Pod，RESTARTS 没有持续增长。
- 所有需要的 PVC 都为 `Bound`。
- `nexent-config` 日志中没有 `[sql-migrations]` 失败、迁移等待超时或持续报错。

如果不满足上述条件，先保留现场和升级前副本，根据 Pod events 和容器日志定位问题。
