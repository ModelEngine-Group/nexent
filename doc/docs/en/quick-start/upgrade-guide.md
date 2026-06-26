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

Navigate to the docker directory of the updated code and run the upgrade script:

```bash
bash upgrade.sh
```

If deploy.options is missing, the script will prompt you to select deployment settings again, such as components, port policy, and image source. Choose the same options you used for the previous deployment.

>💡 Tip
> If `.env` is missing, the deploy script automatically copies it from `.env.example`.
> If you need to configure voice models (STT/TTS), add the relevant variables to `.env`. We will provide a front-end configuration interface as soon as possible.


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

SQL migrations are no longer executed manually. In Docker, only `nexent-config` runs `deploy/common/run-sql-migrations.sh` on startup and automatically applies merged migration files from `deploy/sql/migrations/`, such as `v1_merged_migrations.sql`, `v2.0_merged_migrations.sql`, `v2.1_merged_migrations.sql`, and `v2.2_merged_migrations.sql`; the other backend containers only wait for migration records to reach the target state.

The migration runner records each source section in `nexent.schema_migrations`. If records are missing but business tables already exist, probes safely backfill `baselined` records; ambiguous cases fail instead of being skipped.

> 💡 Tips
> - Always back up the database before upgrading, especially in production.
> - Check backend container logs for `[sql-migrations]` entries if a service fails during startup.
