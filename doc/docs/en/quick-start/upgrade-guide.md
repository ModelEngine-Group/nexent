# Nexent Docker Upgrade Guide

This guide applies to Nexent deployments managed with Docker Compose. Run the upgrade during an idle or low-traffic window whenever possible. Business writes must stop before the backup starts, but the containers do not need to be stopped.

> ⚠️ If business writes continue during the copy, data from PostgreSQL, Elasticsearch, Redis, MinIO, and other components may not represent the same point in time, and the backup may not be recoverable.

## 1. Pre-upgrade Preparation

### 1.1 Pre-upgrade Check

Start in the root of the Nexent repository currently used for deployment. For an offline deployment, start in the root of the previously extracted deployment package. Run the backup script with a local backup directory outside `ROOT_DIR`:

```bash
bash deploy/docker/backup.sh --backup-dir /mnt/backup/nexent
```

The script first prints `ROOT_DIR`, the named volumes used by this deployment, the total uncompressed data size, and the available space under the backup directory. `[PASS] Pre-upgrade space check passed.` means the destination has enough space. If space is insufficient, the script prints `[ERROR]` and exits before copying. Files are not compressed, so the check uses their original size.

### 1.2 Backup

After the space check passes, the script asks you to confirm that business writes have stopped. Stop writes from user operations, API requests, scheduled jobs, and similar sources before confirming. Keep the containers running; do not run `docker stop` or `docker compose down`.

Enter `y` at the interactive prompt. For non-interactive execution, provide explicit confirmation only after business writes have stopped:

```bash
bash deploy/docker/backup.sh \
  --backup-dir /mnt/backup/nexent \
  --confirm-writes-stopped
```

The script directly copies files from `ROOT_DIR` and the Docker named volumes. It does not use `sudo` and does not create compressed archives or SHA-256 files. Follow progress through `[INFO]` messages. The backup is complete only when `[PASS] Backup complete: <path>` appears; `<path>` is the actual backup directory. If `[ERROR]` appears, do not use the incomplete directory printed by the script.

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
