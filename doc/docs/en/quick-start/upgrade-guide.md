# Nexent Upgrade Guide

## 🚀 Upgrade Overview

Follow these steps to upgrade Nexent safely:

1. Pull the latest code
2. Execute the upgrade script
3. Open the site to confirm service availability

---

## 🔄 Step 1: Update Code

Before updating, record the current deployment version and data directory information.

- Current Deployment Version Location: root VERSION
- Data Directory Location: ROOT_DIR in .env

**Code downloaded via git**

Update the code using git commands:

```bash
git pull
```

**Code downloaded via ZIP package or other means**

1. Re-download the latest code from GitHub and extract it.
2. If it exists, copy the deploy.options file from the docker directory of your previous deployment script directory to the docker directory of the new code directory. (If the file doesn't exist, you can ignore this step).

## 🔄 Step 2: Execute the Upgrade

From the repository root of the updated code, run the Docker deployment entrypoint:

```bash
bash deploy.sh docker
```

If deploy.options is missing, the script will prompt you to select deployment settings again, such as components, port policy, and image source. Choose the same options you used for the previous deployment.

>💡 Tip
> Existing `deploy/env/.env` is kept as-is. If it is missing, the deploy script first reuses an existing legacy root `.env` or `docker/.env`, then falls back to `deploy/env/.env.example` or legacy templates.
> If you need to configure voice models (STT/TTS), add the relevant variables to `deploy/env/.env`. We will provide a front-end configuration interface as soon as possible.


## 🌐 Step 3: Verify the deployment

After deployment:

1. Open `http://localhost:3000` in your browser.
2. Review the [User Guide](https://doc.nexent.tech/en/user-guide/home-page) to validate agent functionality.


## Optional Operations

### 🧹 Clean Up Old Version Images

If images were not updated correctly, you can clean up old containers and images before upgrading:

```bash
# Stop and remove existing containers
docker compose down

# Inspect Nexent images
docker images --filter "reference=nexent/*"

# Remove Nexent images
# Windows PowerShell:
docker images -q --filter "reference=nexent/*" | ForEach-Object { docker rmi -f $_ }
# Linux/WSL:
docker images -q --filter "reference=nexent/*" | xargs -r docker rmi -f

# (Optional) prune unused images and caches
docker system prune -af
```

> ⚠️ Notes
> - Back up critical data before deleting images.
> - To preserve database data, do not delete the mounted database volume (`/nexent/docker/volumes` or your custom path).

---

## 🗄️ Database Migrations

SQL migrations are no longer executed manually. In Docker, only `nexent-config` runs `deploy/common/run-sql-migrations.sh` on startup and automatically applies `*.sql` files from `deploy/sql/migrations/` in filename order; the other backend containers only wait for migration records to reach the target state. SQL is mounted from `deploy/sql` into `/opt/nexent/sql`, so SQL-only changes require rerunning deployment, not rebuilding images.

The migration runner uses each SQL filename as the migration ID in `nexent.schema_migrations`. If a recorded file has the same checksum, it is skipped; if the checksum changes, the same file is rerun and the checksum, execution time, app version, and source file are updated.

> 💡 Tips
> - Always back up the database before upgrading, especially in production.
> - Check backend container logs for `[sql-migrations]` entries if a service fails during startup.
