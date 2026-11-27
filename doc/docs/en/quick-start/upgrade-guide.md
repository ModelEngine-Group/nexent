# Nexent Docker Upgrade Guide

This guide applies to Nexent deployments managed with Docker Compose. Run the upgrade during an idle or low-traffic window whenever possible. Business writes must stop before the backup starts, but the containers do not need to be stopped.

Keep the original deployment directory and its configuration, and record the image version. If you need to roll back, restore the pre-upgrade backup and redeploy from the old directory. See the [Docker Rollback Guide](./rollback-guide).

> ⚠️ If business writes continue during the copy, data from PostgreSQL, Elasticsearch, Redis, MinIO, and other components may not represent the same point in time, and the backup may not be recoverable.

## 1. Pre-upgrade Check and Backup

Start in the root of the Nexent repository currently used for deployment. For an offline deployment, start in the root of the previously extracted deployment package. The backup directory must be outside both `ROOT_DIR` and `NEXENT_USER_DIR`.

Before running the following command, you must stop writes from user operations, API requests, scheduled jobs, and similar sources. Keep the containers running; do not run `docker stop` or `docker compose down`. The script does not detect write activity or request confirmation input:

```bash
bash deploy/docker/backup.sh --backup-dir /mnt/backup/nexent
```

The script first prints `ROOT_DIR`, `NEXENT_USER_DIR`, the named volumes used by this deployment, the total uncompressed data size, and the available space under the backup directory. If `NEXENT_USER_DIR` is not explicitly set, the deployment default `${HOME}/nexent` is used. `[PASS] Pre-upgrade space check passed.` means the destination has enough space, after which copying starts immediately. If space is insufficient, the script prints `[ERROR]` and exits before copying. Files are not compressed, so the check uses their original size.

Each run creates one `docker-<timestamp>/` directory under `--backup-dir`. Its subdirectories use the original names of `ROOT_DIR`, `NEXENT_USER_DIR`, and the Docker named volumes the script finds. The script copies files directly without `sudo`, compression, or SHA-256 files. When it reports `[PASS] Backup complete: <path>`, keep the entire directory at `<path>` for rollback. A directory ending in `.partial` contains an unfinished copy.

## 2. Perform the Upgrade

Web marks authentication cookies `Secure` by default. If users still connect directly over HTTP on an isolated network, set `NEXENT_AUTH_COOKIE_SECURE=false` in `deploy/env/.env` before upgrading so browsers can store the session. Keep the default `true` for HTTPS reverse proxies, including those that forward requests to Web over HTTP.

### 2.1 Online Upgrade

In an environment that can reach GitHub and the required image registries, perform an online upgrade from the current Nexent repository. Confirm the current branch and target version, then update with fast-forward only. Do not use an unrecorded `latest` value in place of a specific version.

```bash
git branch --show-current
git pull --ff-only
bash deploy.sh docker --defaults --version X.Y.Z
```

Replace `X.Y.Z` with the target image tag. `--defaults` reuses the saved deployment configuration and skips the interactive interface. Before upgrading, verify that the components, port policy, and image source in `deploy/docker/deploy.options` match the current deployment. See [Docker Installation and Deployment](./installation.md#online-deployment).

### 2.2 Offline Upgrade

When the target host cannot access public image registries, follow [Docker Offline Deployment](./installation.md#offline-deployment) to download a target-version package matching the server architecture, copy it to the target host, and extract it into a new directory:

```bash
unzip 'nexent-<version>-amd64.zip' -d 'nexent-<version>'
cd 'nexent-<version>'
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  --defaults \
  docker
```

`/path/to/previous/nexent` must be the actual root of the previously extracted deployment package and contain `deploy/env/.env`. `--reuse-from` reuses its `.env`, `monitoring.env`, and Docker deployment options, while `--load-images` loads images from the new package. Use the corresponding `arm64` package name on an ARM64 server.

## 3. Post-upgrade Checks

The deployment script prints the path to the log for this run. By default it is `logs/deploy/deploy-YYYYMMDD-HHMMSS.log` under the deployment directory. If image loading or database initialization fails, check this log for the detailed output.

When upgrading to v2.9.0, the script runs database migrations in a temporary `nexent-config` container before starting the application services. The migrations for this version are bundled in `v2.9.0_merged_migrations.sql`. At startup, the long-running `nexent-config` service checks the migration records and SQL checksums and skips migrations that are already current.

Check the health of the containers in the Nexent and optional monitoring projects.

```bash
docker ps -a --filter label=com.docker.compose.project=nexent \
  --format 'table {{.Names}}\t{{.Status}}'
docker ps -a --filter label=com.docker.compose.project=monitor \
  --format 'table {{.Names}}\t{{.Status}}'
```

Wait for containers with a configured health check to report `healthy`. If any report `unhealthy`, inspect the deployment log and that container's logs. Sign in with an existing account and open a conversation from before the upgrade to confirm the application can read the original data.
