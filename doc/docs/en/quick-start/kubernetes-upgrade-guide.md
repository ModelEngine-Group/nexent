# Nexent Kubernetes Upgrade Guide

This guide applies to Nexent deployments managed with Helm. Run the upgrade during an idle or low-traffic window whenever possible. Business writes must stop before the backup starts, but the Pods do not need to be stopped.

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

The actual backup directory preserves each PVC's name at the top level, for example `nexent-postgresql/`, `nexent-workspace/`, `nexent-skills/`, and the names of PVCs for enabled monitoring components. Follow the source selection and copy progress through `[INFO]` messages. The backup is complete only when `[PASS] Backup complete: <path>` appears; this means every PVC in the specified namespace was copied, and `<path>` is the actual backup directory. If `[ERROR]` appears, do not use the incomplete `.partial` directory printed by the script.

## 2. Perform the Upgrade

### 2.1 Online Upgrade

In an environment that can reach GitHub and the required image registries, perform an online upgrade from the current Nexent repository. Confirm the current branch and target version, then update with fast-forward only.

```bash
git branch --show-current
git pull --ff-only
bash deploy.sh k8s --defaults --version X.Y.Z
```

`--defaults` reuses the saved Kubernetes deployment configuration and skips the interactive interface. Before upgrading, verify that the components, port policy, image source, persistence mode, and namespace in `deploy/k8s/deploy.options` match the current environment. See [Kubernetes Installation and Deployment](./kubernetes-installation.md#online-deployment) for more information about online deployment.

### 2.2 Offline Upgrade

When the target cluster cannot access public image registries, follow [Kubernetes Offline Deployment](./kubernetes-installation.md#offline-deployment) to download a target-version package matching the cluster node architecture, copy it to a management host that can reach the cluster, and extract it:

```bash
unzip nexent-<version>-amd64.zip -d nexent-<version>
cd nexent-<version>
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

During the upgrade, `nexent-config` runs automatic database migrations while the other backend services wait for migrations to reach the target state. Existing merged SQL files must not be modified, renamed, or deleted.

## 3. Post-upgrade Checks

Inspect Pod status in the target namespace. The following example uses the default `nexent` namespace:

```bash
kubectl get pods -n nexent -o wide
```

The check passes when every Nexent Pod is `Running` and its READY count matches the expected value. Continue waiting while a Pod reports `ContainerCreating`; the check fails if a Pod reports `CrashLoopBackOff`, `Error`, or remains `Pending` for an extended period.
