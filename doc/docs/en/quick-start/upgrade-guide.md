# Nexent Upgrade Guide

Before upgrading a production environment, complete the backup and recovery drill in the [Backup, Upgrade, and Rollback Guide](./backup-upgrade-rollback.md) and confirm the rollback window. This page only covers the basic deployment entrypoint.

## 🚀 Upgrade Overview

Follow these steps to upgrade Nexent safely:

1. Pull the latest code
2. Execute the upgrade script
3. Open the site to confirm service availability

---

## 🔄 Step 1: Update Code

Before updating, record the current version and data directory, and back up PostgreSQL, MinIO, and other important data.

- Current deployment version: `VERSION` in the repository root
- Data directory: `ROOT_DIR` in `deploy/env/.env`

**Code downloaded via git**

Make sure you are on the branch used for deployment, then pull changes with fast-forward only:

```bash
git branch --show-current
git pull --ff-only
```

**Code downloaded via ZIP package or other means**

Download and extract the target version from GitHub. Then copy `deploy/docker/deploy.options` from the old deployment directory to the same location in the new code. Skip this step if the file does not exist. Alternatively, use `--reuse-from` during deployment to reuse the environment configuration and deployment options from the old directory directly.

## 🔄 Step 2: Execute the Upgrade

From the repository root of the updated code, run the Docker deployment entrypoint:

```bash
bash deploy.sh docker
```

If `deploy.options` is missing, the script asks you to select the components, port policy, and image source again. Choose the same configuration as the existing environment.

> 💡 Tips
> - The upgrade preserves existing values, comments, ordering, and legacy-only variables in `deploy/env/.env`, then appends variables introduced in the current `deploy/env/.env.example`. If `.env` is missing, the script first reuses the legacy `docker/.env` and otherwise falls back to the current template. A readable `.env.example` must exist before loading images or starting services.
> - v2.5.0 adds sandbox-related variables and pulls the `nexent-sandbox` image. If you use a private registry or an offline environment, make sure the sandbox image is synchronized as well.


## 🌐 Step 3: Verify the deployment

After deployment:

1. Open `http://localhost:3000` in your browser.
2. Check that the selected Config, Runtime, MCP, Northbound, Web, and Data Process services are running properly.
3. Confirm that the `nexent-agent-workspace` volume exists and that the Runtime service can create sandbox execution environments.
4. Follow the [User Guide](../user-guide/home-page) to validate agent configuration and chat.


## Optional Operations

### 🧹 Clean Up Old Version Images

Only after upgrade validation succeeds, the rollback observation period ends, and old images have been archived separately should you remove images that are no longer needed by their specific image IDs. If an image did not update, first verify the image source, version, actual image ID, and `local-latest` setting; do not prepare an upgrade by deleting images in bulk.

Keep old images and persistent volumes throughout upgrade and rollback. Do not run `docker system prune -af`, `down -v`, or volume prune. See the [Backup, Upgrade, and Rollback Guide](./backup-upgrade-rollback.md) for the complete recovery procedure.

---

### 🗄️ Database Migrations

SQL migrations are no longer executed manually. In Docker, only `nexent-config` runs `deploy/common/run-sql-migrations.sh` on startup and automatically applies `*.sql` files from `deploy/sql/migrations/` in filename order; the other backend containers only wait for migration records to reach the target state. SQL is mounted from `deploy/sql` into `/opt/nexent/sql`, so SQL-only changes require rerunning deployment, not rebuilding images.

The migration runner uses each SQL filename as the migration ID in `nexent.schema_migrations`. If a recorded file has the same checksum, it is skipped; if the checksum changes, the same file is rerun and the checksum, execution time, app version, and source file are updated.

Published migration files must not be modified, renamed, or deleted. To change the database schema, add a new versioned migration under `deploy/sql/migrations/`. v2.5.0 uses a consolidated migration file to apply the database changes for this release.

> 💡 Tips
> - Always back up the database before upgrading, especially in production.
> - Check backend container logs for `[sql-migrations]` entries if a service fails during startup.
