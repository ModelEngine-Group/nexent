# Nexent Docker Upgrade Guide

This guide applies to Nexent deployments managed with Docker Compose. Run the upgrade during an idle or low-traffic window whenever possible so fewer requests and writes occur while data is copied and services are upgraded. This is operational guidance, not a hard requirement: the procedure does not detect active users, block requests, or stop containers.

> ⚠️ This procedure creates a pre-upgrade copy by reading persistent files while containers remain running. If PostgreSQL, Elasticsearch, Redis, or MinIO writes occur during the copy, the files may not represent one point in time and are not guaranteed to be directly recoverable.

## 1. Pre-upgrade Preparation

### 1.1 Record the Version and Deployment Configuration

Start in the root of the Nexent repository currently used for deployment. For an offline deployment, start in the root of the previously extracted deployment package. The commands do not require the repository to be installed at any fixed system path. `BACKUP_BASE` must be outside `ROOT_DIR`.

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

These files and inventories can contain passwords or tokens. Store them only in a restricted directory, and never commit them to Git or attach them to a public ticket.

### 1.2 Check Available Space

```bash
du -sh "$ROOT_DIR"
df -h "$ROOT_DIR" "$BACKUP_BASE"
docker system df -v
```

The backup destination must have more free space than the persistent data to be copied, and the Docker data filesystem must also have room for the target-version images. Do not free upgrade space by deleting old images, volumes, or running containers.

### 1.3 Copy Persistent Data

First record the containers and mounts actually used by this deployment. Include the `monitor` Compose project when monitoring is enabled.

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

Keep the containers running and archive `ROOT_DIR` directly:

```bash
sudo tar --numeric-owner --acls --xattrs \
  -cpf "$BACKUP_DIR/root-dir.tar" -C "$ROOT_DIR" .
```

Review `bind-mounts.txt` and copy each persistent user directory, terminal directory, custom configuration directory, or other bind mount outside `ROOT_DIR`. Do not copy runtime interfaces such as `/var/run/docker.sock`.

```bash
EXTERNAL_SOURCE=/actual/persistent/path
EXTERNAL_NAME=external-data
sudo tar --numeric-owner --acls --xattrs \
  -cpf "$BACKUP_DIR/$EXTERNAL_NAME.tar" \
  -C "$(dirname "$EXTERNAL_SOURCE")" "$(basename "$EXTERNAL_SOURCE")"
```

Then archive every Docker named volume in the inventory. Prepare a trusted helper image containing GNU tar in advance; do not wait until the upgrade window to download it in an offline environment.

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

This procedure does not create SHA-256 files. Check the command exit status, archive readability, and space usage instead:

```bash
test -s "$BACKUP_DIR/root-dir.tar"
tar -tf "$BACKUP_DIR/root-dir.tar" >/dev/null
for archive in "$BACKUP_DIR"/volumes/*.tar; do
  test -f "$archive" || continue
  tar -tf "$archive" >/dev/null
done
du -sh "$ROOT_DIR" "$BACKUP_DIR"
```

## 2. Perform the Upgrade

### 2.1 Online Upgrade

In an environment that can reach GitHub and the required image registries, perform an online upgrade from the current Nexent repository. Confirm the current branch and target version, then update with fast-forward only. Do not use an unrecorded `latest` value in place of a specific version.

```bash
git branch --show-current
git pull --ff-only
bash deploy.sh docker --defaults --version X.Y.Z
```

`--defaults` reuses the saved deployment configuration and skips the interactive interface. Before upgrading, verify that `deploy/docker/deploy.options` exists and that its components, port policy, and image source match the current environment. See [Docker Installation and Deployment](./installation.md#online-deployment) for more information about online deployment.

### 2.2 Offline Upgrade

When the target host cannot access public image registries, follow [Docker Offline Deployment](./installation.md#offline-deployment) to download a target-version package matching the server architecture, copy it to the target host, and extract it into a new directory:

```bash
unzip nexent-<version>-amd64.zip -d nexent-<version>
cd nexent-<version>
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  --defaults \
  docker
```

`/path/to/previous/nexent` must be the actual root of the previously extracted deployment package and contain `deploy/env/.env`. `--reuse-from` reuses its `.env`, `monitoring.env`, and Docker deployment options, while `--load-images` loads images from the new package. Use the corresponding `arm64` package name on an ARM64 server.

During the upgrade, `nexent-config` runs automatic database migrations while the other backend containers wait for migrations to reach the target state. Existing merged SQL files must not be modified, renamed, or deleted.

## 3. Post-upgrade Checks

Inspect every container in the Nexent and optional monitoring projects:

```bash
docker ps -a --filter label=com.docker.compose.project=nexent \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker ps -a --filter label=com.docker.compose.project=monitor \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker logs --tail 200 nexent-config
```

The upgrade passes when:

- Every container for the selected components is `Up`, and every container with a healthcheck is `healthy`.
- No container is `Exited`, `Restarting`, or `unhealthy`.
- The `nexent-config` log has no `[sql-migrations]` failure, migration wait timeout, or persistent error.

If any condition fails, do not immediately remove old images or the pre-upgrade copy. Inspect the affected container logs first.
