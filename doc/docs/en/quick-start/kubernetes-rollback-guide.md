# Nexent Kubernetes Rollback Guide

Locate the pre-upgrade backup directory, `k8s-<timestamp>/`, and the deployment directory used for that version. The deployment directory should contain the original `deploy.sh`, `VERSION`, Helm chart, `deploy/env/.env`, `deploy/k8s/deploy.options`, and the `deploy/env/monitoring.env` used at the time. See the [Kubernetes Upgrade Guide](./kubernetes-upgrade-guide) for backup instructions.

## 1. Stop writes

Confirm that `kubectl` points to the original cluster and the intended namespace. Pause user requests and scheduled tasks, wait for work in progress to finish, and save any data created since the backup that you need to keep. Stop workloads that write to the target volumes and confirm their Pods have stopped writing. You can restore data after the original application Pods have been removed. Deployment recreates them.

## 2. Restore the backup to the corresponding persistent volumes

**Each backup produces one timestamped directory** on the management host where you ran the script. With `--backup-dir /mnt/backup/nexent`, the script creates a `k8s-<timestamp>/` directory under that path. It contains the files from the PVCs in the specified namespace. A few example subdirectories are shown below.

```text
/mnt/backup/nexent/
└── k8s-20261126-010000/
    ├── nexent-postgresql/
    ├── nexent-workspace/
    └── nexent-skills/
```

**Keep or transfer the entire `k8s-20261126-010000/` directory.** For rollback, use the directory identified by `[PASS] Backup complete` in the pre-upgrade backup log.

Run `kubectl -n nexent get pvc` to check the original deployment's PVCs and the PV bound to each one. Substitute your namespace for `nexent`. When restoring ordinary files, keep each PVC and its mount point in place and clear only the contents of the target data directory.

- **Node-local directories (`hostPath`).** On the node that holds the data, use `mv` to move the contents of the corresponding subdirectory from a working copy of the backup to the original path. For example, with the default local storage settings, move the contents of `nexent-skills/` to `/var/lib/nexent-data/skills/`.

The file move applies to ordinary files. Restore PostgreSQL from a verified database backup and Elasticsearch from a compatible snapshot. Both should represent the same point in time.

## 3. Redeploy from the old deployment directory

Check the namespace, storage mode, and PVCs in the old configuration. Confirm that `VERSION` in the old directory matches the pre-upgrade image tag and that the cluster nodes can obtain that image. Run the deployment script from the directory that contains the old `deploy.sh` and Helm chart. Replace the example path with your own.

```bash
cd /opt/nexent/previous && bash deploy.sh k8s
```

To select the old image tag explicitly, append `--version X.Y.Z` and replace `X.Y.Z` with that tag. On a single-node cluster with the Docker runtime, you can load the old offline package images by running `bash deploy.sh --load-images --defaults k8s` from the package root. For other runtimes or multi-node clusters, prepare the old images as described in [Kubernetes Offline Deployment](./kubernetes-installation#offline-deployment).

After deployment, run `kubectl -n nexent get deploy,pods,pvc` to check that the applications are ready and the volumes are bound. Substitute your namespace for `nexent`. Sign in and open a conversation or attachment that predates the backup. Resume traffic and scheduled tasks after confirming that the restored data is readable.
