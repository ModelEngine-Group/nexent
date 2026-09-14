# Nexent Kubernetes Upgrade Guide

This guide applies to Nexent deployments managed with Helm. Run the upgrade during an idle or low-traffic window whenever possible so fewer requests and writes occur while data is copied and workloads are upgraded. This is operational guidance, not a hard requirement: the procedure does not detect active users, block requests, scale Deployments down, or stop Pods.

> ⚠️ This procedure uses `kubectl cp` or `kubectl exec` to copy persistent files directly from running containers. If PostgreSQL, Elasticsearch, Redis, or MinIO writes occur during the copy, the files may not represent one point in time and are not guaranteed to be directly recoverable.

## 1. Pre-upgrade Preparation

### 1.1 Record the Version, Helm, and Storage State

The default namespace is `nexent`; adjust it for the actual environment. The machine running `kubectl` is the backup destination.

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

Helm values and resource inventories may contain passwords or tokens. Store them only in a restricted local directory. `kubectl get pv` requires cluster-wide read access; if the operator lacks that permission, record that the item was not collected and continue with the other checks.

### 1.2 Check Available Space

First inspect PVC capacities and free space on the local backup machine:

```bash
kubectl get pvc -n "$NS"
df -h "$BACKUP_BASE"
```

Use the following function to inspect the actual data size inside enabled component containers:

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

If Supabase or monitoring is enabled, inspect its container directories as well. The local machine must have more free space than the total data to be copied, plus additional room for temporary files created by `kubectl cp`.

### 1.3 Copy Data from Running Containers

The following function selects one running Pod by its `app` label and copies a directory to the local machine. It prints `SKIP` for optional components that are not enabled.

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

When monitoring is enabled, use the same function for each enabled persistent component:

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

`kubectl cp` depends on `tar` in the target container. If the copy command is unavailable, stream a tar archive to the local machine instead:

```bash
POD=$(kubectl get pods -n "$NS" -l app=nexent-postgresql \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NS" "$POD" -c postgresql -- \
  tar -C /var/lib/postgresql -cf - data \
  > "$K8S_BACKUP_DIR/data/postgresql.tar"
```

If the target container has no `tar`, select another existing container that mounts the same PVC and contains `tar`. This procedure does not create a temporary Pod; all data is exported from existing containers to the local machine.

This procedure does not create SHA-256 files. Check the command exit status, destination existence, and local space usage instead:

```bash
test -d "$K8S_BACKUP_DIR/data"
find "$K8S_BACKUP_DIR/data" -mindepth 1 -maxdepth 2 -print
du -sh "$K8S_BACKUP_DIR/data"/*
```

## 2. Perform the Upgrade

For a Git-managed deployment, confirm the current branch and target version, then update with fast-forward only.

```bash
cd "$CODE_DIR"
git branch --show-current
git pull --ff-only
bash deploy.sh --defaults k8s --version X.Y.Z
```

`--defaults` reuses the saved Kubernetes deployment configuration and skips the interactive interface. Before upgrading, verify that the components, port policy, image source, persistence mode, and namespace in `deploy/k8s/deploy.options` match the current environment.

For a complete offline deployment package, run the following from the new package root:

```bash
bash deploy.sh --load-images --reuse-from /opt/nexent-old-package --defaults k8s
```

`--reuse-from` is available only through the offline-package entrypoint. It reuses `.env`, `monitoring.env`, and Kubernetes deployment options from the old package.

During the upgrade, `nexent-config` runs automatic database migrations while the other backend services wait for migrations to reach the target state. Existing merged SQL files must not be modified, renamed, or deleted.

## 3. Post-upgrade Checks

Check Deployment rollouts, Pods, and PVCs:

```bash
kubectl get deployment -n "$NS"
kubectl get pods -n "$NS" -o wide
kubectl get pvc -n "$NS"

while IFS= read -r deployment; do
  kubectl rollout status -n "$NS" "$deployment" --timeout=600s
done < <(kubectl get deployment -n "$NS" -o name)

kubectl logs -n "$NS" deployment/nexent-config --tail=200
```

The upgrade passes when:

- Every Deployment for the selected components completes its rollout, and its Pods are `Running` with the expected READY count.
- No Pod is `CrashLoopBackOff`, `Error`, or persistently `Pending`, and RESTARTS is not continually increasing.
- Every required PVC is `Bound`.
- The `nexent-config` log has no `[sql-migrations]` failure, migration wait timeout, or persistent error.

If any condition fails, preserve the current environment and pre-upgrade copy, then inspect Pod events and container logs first.
