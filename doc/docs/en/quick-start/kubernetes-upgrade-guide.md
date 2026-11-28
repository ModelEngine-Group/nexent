# Nexent Kubernetes Upgrade Guide

This guide applies to Nexent deployments managed with Helm. Run the upgrade during an idle or low-traffic window whenever possible. Business writes must stop before the backup starts, but the Pods do not need to be stopped.

Keep the original deployment directory and configuration, and record the image version. If you need to roll back, restore the backup to the corresponding persistent volumes, then redeploy from the old directory. See the [Kubernetes Rollback Guide](./kubernetes-rollback-guide).

> ⚠️ If business writes continue during the copy, data from PostgreSQL, Elasticsearch, Redis, MinIO, and other components may not represent the same point in time, and the backup may not be recoverable.

## 1. Pre-upgrade Check and Backup

Start in the root of the Nexent repository currently used for deployment. For an offline deployment, start in the root of the previously extracted deployment package. The local machine running `kubectl` is the backup destination and must be able to access the target cluster. The default namespace is `nexent`; adjust it for the actual environment.

Before running the following command, you must stop writes from user operations, API requests, scheduled jobs, and similar sources. Keep the Pods running; do not scale them down or stop them. The script does not detect write activity or request confirmation input:

```bash
bash deploy/k8s/backup.sh \
  --backup-dir /mnt/backup/nexent \
  --namespace nexent
```

The script discovers every PVC in the specified namespace and selects a running container that fully mounts each volume. Every PVC must be `Bound` and have a complete mount that does not use `subPath`; otherwise the script prints `[ERROR]`, names the affected PVC, and exits before copying so that no volume is silently omitted. When custom `existingClaim` values are used, the script works with the actual PVC names in the cluster instead of relying on default component names.

The script runs `du` in the containers and prints the uncompressed size of each PVC and their total, then uses local `df` to print the space available under the backup directory. `[PASS] Pre-upgrade space check passed.` means the local machine has enough space, after which copying starts immediately. If space is insufficient, the script exits before copying. Files are not compressed, so the check uses their original size.

The script first uses `kubectl cp` to copy each PVC's files to the local machine. If that command fails and the target container contains `tar`, it uses `kubectl exec ... tar -cf -` to stream the files and immediately extract them locally without retaining a tar file. When a minimal image such as MinIO does not contain `tar`, the script uses Bash and basic coreutils in the container to enumerate the directory tree, then exports each file through `kubectl exec ... cat`; this path is slower when a volume contains many files. The script does not use `sudo`, create temporary Pods, or generate compressed archives or SHA-256 files.

Each run creates one `k8s-<timestamp>/` directory under `--backup-dir` on the management host. Each subdirectory uses the actual name of its PVC. When the script reports `[PASS] Backup complete: <path>`, it has finished copying every PVC in the specified namespace. Keep the entire directory at `<path>` for rollback. A directory ending in `.partial` contains an unfinished copy.

## 2. Perform the Upgrade

**Keep the existing cluster's storage mode and volumes.** When no storage mode is saved or specified, the current script uses `dynamic`. If you omit `--storage-class`, it uses the cluster's default StorageClass. Before upgrading, check `deploy/k8s/deploy.options`, the target namespace, and the existing PVCs. If the previous deployment uses static hostPath storage and has no saved storage mode, add `--persistence-mode local` to the deployment command. If it uses pre-created PVCs, retain the original `existing` setting and claim names.

Web marks authentication cookies `Secure` by default. Use the configured HTTPS endpoint to verify login from another machine. For a local check, forward the Web port as described in [Access Your Installation](./kubernetes-installation#access-your-installation).

### 2.1 Online Upgrade

In an environment that can reach GitHub and the required image registries, perform an online upgrade from the current Nexent repository. Confirm the current branch and target version, then update with fast-forward only.

```bash
git branch --show-current
git pull --ff-only
bash deploy.sh k8s --defaults --version X.Y.Z
```

Replace `X.Y.Z` with the target image tag. If you omit `--version`, the script reads `VERSION` from the current deployment directory. `--defaults` reuses the saved components, port policy, image source, and storage settings. The version selected for this run takes precedence over any application version in an old options file. See [Kubernetes Installation and Deployment](./kubernetes-installation.md#online-deployment).

### 2.2 Offline Upgrade

When the target cluster cannot access public image registries, follow [Kubernetes Offline Deployment](./kubernetes-installation.md#offline-deployment) to download a target-version package matching the cluster node architecture, copy it to a management host that can reach the cluster, and extract it:

```bash
unzip 'nexent-<version>-amd64.zip' -d 'nexent-<version>'
cd 'nexent-<version>'
```

For a single-node cluster backed by the Docker container runtime, load the new package images directly and upgrade:

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  --defaults \
  k8s
```

For other single-node or multi-node clusters, push the new package images to an internal registry accessible to the cluster:

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --push-images \
  --image-registry-prefix registry.example.com/nexent \
  --defaults \
  k8s
```

`/path/to/previous/nexent` must be the actual root of the previously extracted deployment package and contain `deploy/env/.env`. `--reuse-from` reuses its `.env`, `monitoring.env`, and Kubernetes deployment options. Use the corresponding `arm64` package name for ARM64 cluster nodes.

## 3. Post-upgrade Checks

A standard application upgrade pauses the application Pods while the bootstrap Job runs database migrations and initializes the system agents. Application services start after the Job succeeds. The v2.9.0 migrations are bundled in `v2.9.0_merged_migrations.sql`. At startup, Config checks the migration records and checksums and skips migrations that are already current. If initialization fails, the application stays paused. The deployment log includes the Job output. The terminal prints the log path, which defaults to `logs/deploy/deploy-YYYYMMDD-HHMMSS.log` under the deployment directory.

Check the application and its storage in the target namespace. This example uses the default namespace, `nexent`.

```bash
kubectl get pods -n nexent -o wide
```

Confirm that each application Deployment has the expected number of ready replicas and that the original PVCs are still `Bound` to the expected PVs. If a Pod stays `Pending`, check PVC events and the StorageClass. Finally, sign in with an existing account and open a conversation or attachment from before the upgrade to confirm the application is reading the original data.
