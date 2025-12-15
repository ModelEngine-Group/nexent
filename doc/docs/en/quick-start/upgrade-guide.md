# Nexent Upgrade Guide

## 🚀 Upgrade Overview

Follow these steps to upgrade Nexent safely:

1. Pull the latest code
2. Execute the upgrade script
3. Open the site to confirm service availability

---

## 🔄 Step 1: Update Code

Before updating, record the current deployment version and data directory information.

- Current Deployment Version Location: APP_VERSION in backend/consts/const.py
- Data Directory Location: ROOT_DIR in docker/.env

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

If deploy.options is missing, the script will prompt you to manually enter configuration details from the previous deployment, such as the current version and data directory. Enter the information you recorded earlier.

>💡 Tip
> The default scenario is quick deployment, which uses .env.example.
> If you need to configure voice models (STT/TTS), please add the relevant variables to .env.example in advance. We will provide a front-end configuration interface as soon as possible.


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

## 🗄️ Manual Database Update

If some SQL files fail to execute during the upgrade, you can perform the update manually.

### ✅ Method A: Use a SQL editor (recommended)

1. Open your SQL client and create a new PostgreSQL connection.
2. Retrieve connection settings from `/nexent/docker/.env`:
   - Host
   - Port
   - Database
   - User
   - Password
3. Test the connection. When successful, you should see tables under the `nexent` schema.
4. Open a new query window.
5. Navigate to the /nexent/docker/sql directory and open the failed SQL file(s) to view the script.
6. Execute the failed SQL file(s) and any subsequent version SQL files in order.

> ⚠️ Important
> - Always back up the database first, especially in production.
> - Run scripts sequentially to avoid dependency issues.
> - `.env` keys may be named `POSTGRES_HOST`, `POSTGRES_PORT`, and so on—map them accordingly in your SQL client.

### 🧰 Method B: Use the command line (no SQL client required)

1. Switch to the Docker directory:

   ```bash
   cd nexent/docker
   ```

2. Read database connection details from `.env`, for example:

   ```bash
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=nexent
   POSTGRES_USER=root
   POSTGRES_PASSWORD=your_password
   ```

3. Execute SQL files sequentially (host machine example):

   ```bash
   # execute the following commands (please replace the placeholders with your actual values)
   docker exec -i nexent-postgresql psql -U [YOUR_POSTGRES_USER] -d [YOUR_POSTGRES_DB] < ./sql/v1.1.1_1030-update.sql
   docker exec -i nexent-postgresql psql -U [YOUR_POSTGRES_USER] -d [YOUR_POSTGRES_DB] < ./sql/v1.1.2_1105-update.sql
   ```

   Execute the corresponding scripts for your deployment versions in version order.

> 💡 Tips
> - Load environment variables first if they are defined in `.env`:
>
>   **Windows PowerShell:**
>   ```powershell
>   Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } | ForEach-Object { $key, $value = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), 'Process') }
>   ```
>
>   **Linux/WSL:**
>   ```bash
>   export $(grep -v '^#' .env | xargs)
>   # Or use set -a to automatically export all variables
>   set -a; source .env; set +a
>   ```
>
> - Create a backup before running migrations:
>
>   ```bash
>   docker exec -i nexent-postgres pg_dump -U [YOUR_POSTGRES_USER] [YOUR_POSTGRES_DB] > backup_$(date +%F).sql
>   ```
