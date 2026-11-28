# Nexent Docker Rollback Guide

Locate the pre-upgrade backup directory, `docker-<timestamp>/`, and the deployment directory used for that version. The deployment directory should contain the original `deploy.sh`, `VERSION`, `deploy/env/.env`, `deploy/docker/deploy.options`, and the `deploy/env/monitoring.env` used at the time. See the [Docker Upgrade Guide](./upgrade-guide) for backup instructions.

## 1. Stop writes

Pause user requests and scheduled tasks, wait for work in progress to finish, and save any data created since the backup that you need to keep. If the application containers are still running, stop every container that writes to the target directories or volumes. If the containers have already been removed, restore the data and recreate them with the script in the old deployment directory.

## 2. Restore the backup to the original mounts

**Each backup produces one timestamped directory.** With `--backup-dir /mnt/backup/nexent`, the script creates a `docker-<timestamp>/` directory under that path. The example below uses the directory and volume names from a typical deployment. Your backup uses the names from your original deployment.

```text
/mnt/backup/nexent/
└── docker-20261126-010000/
    ├── nexent-data/             ← Contents of the original ROOT_DIR
    ├── nexent/                  ← Contents of the original NEXENT_USER_DIR
    └── nexent-agent-workspace/  ← Contents of a Docker named volume
```

**Keep or transfer the entire `docker-20261126-010000/` directory.** For rollback, use the directory identified by `[PASS] Backup complete` in the pre-upgrade backup log.

**You can move ordinary files back to their original directories.** Check the target paths against the old deployment's `ROOT_DIR` and `NEXENT_USER_DIR`. Keep each mount directory in place, clear its contents, and use `mv` to move the contents of the corresponding backup subdirectory into it. Include hidden files and preserve ownership and permissions. Use a working copy of the backup so the original remains available.

For example, if the deployment user is `admin` and `ROOT_DIR=/home/admin/nexent-data`, move the contents of `nexent-data/skills/` from the working copy into the empty `/home/admin/nexent-data/skills/` directory. Move the contents of `nexent/` into the original `NEXENT_USER_DIR`, such as `/home/admin/nexent/`.

The file move applies to ordinary files. Restore PostgreSQL from a verified database backup and Elasticsearch from a compatible snapshot. Both should represent the same point in time.

## 3. Redeploy from the old deployment directory

Confirm that the image version matches the version used before the upgrade. Run the deployment script from the directory that contains the old `deploy.sh`. Replace the example path with your own.

```bash
cd /opt/nexent/previous && bash deploy.sh docker
```

To select the old image tag explicitly, append `--version X.Y.Z` and replace `X.Y.Z` with that tag. If you need to reload images from the old offline package, run `bash deploy.sh --load-images --defaults docker` from the package root.

After deployment, check the containers with `docker ps -a --filter label=com.docker.compose.project=nexent`. Sign in and open a conversation or attachment that predates the backup. Resume traffic and scheduled tasks after confirming that the restored data is readable.
