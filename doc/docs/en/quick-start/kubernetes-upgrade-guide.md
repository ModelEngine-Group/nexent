# Nexent Kubernetes Upgrade Guide

## 🚀 Upgrade Overview

Follow these steps to upgrade Nexent on Kubernetes safely:

1. Pull the latest code
2. Execute the Helm deployment script
3. Open the site to confirm service availability

---

## 🔄 Step 1: Update Code

Before updating, record the current deployment version and data directory information.

- Current Deployment Version Location: `APP_VERSION` in `backend/consts/const.py`
- Data Directory Location: `global.dataDir` in `k8s/helm/nexent/values.yaml`

**Code downloaded via git**

Update the code using git commands:

```bash
git pull
```

**Code downloaded via ZIP package or other means**

1. Re-download the latest code from GitHub and extract it.
2. Copy the `.deploy.options` file from the `k8s/helm` directory of your previous deployment to the new code directory. (If the file doesn't exist, you can ignore this step).

## 🔄 Step 2: Execute the Upgrade

Navigate to the k8s/helm directory of the updated code and run the deployment script:

```bash
cd k8s/helm
./deploy-helm.sh apply
```

The script will detect your previous deployment settings (version, image source, etc.) from the `.deploy.options` file. If the file is missing, you will be prompted to enter configuration details.

> 💡 Tip
> If you need to configure voice models (STT/TTS), please edit the corresponding values in `values.yaml` or pass them via command line.

---

## 🌐 Step 3: Verify the Deployment

After deployment:

1. Open `http://localhost:30000` in your browser.
2. Review the [User Guide](../user-guide/home-page) to validate agent functionality.

---

## 🗄️ Manual Database Update

If some SQL files fail to execute during the upgrade, or if you need to run incremental SQL scripts manually, you can perform the update using the methods below.

### 📋 Find SQL Scripts

SQL migration scripts are located in the repository at:

```
docker/sql/
```

Check the [upgrade-guide](./upgrade-guide.md) or release notes to identify which SQL scripts need to be executed for your upgrade path.

### ✅ Method A: Use a SQL Editor (recommended)

1. Open your SQL client and create a new PostgreSQL connection.
2. Get connection settings from the running PostgreSQL pod:

   ```bash
   # Get PostgreSQL pod name
   kubectl get pods -n nexent -l app=nexent-postgresql

   # Port-forward to access PostgreSQL locally
   kubectl port-forward svc/nexent-postgresql 5433:5432 -n nexent &
   ```

3. Connection details:
   - Host: `localhost`
   - Port: `5433` (forwarded port)
   - Database: `nexent`
   - User: `root`
   - Password: Check in `k8s/helm/nexent/charts/nexent-common/values.yaml`

4. Test the connection. When successful, you should see tables under the `nexent` schema.
5. Execute the required SQL file(s) in version order.

> ⚠️ Important
> - Always back up the database first, especially in production.
> - Run scripts sequentially to avoid dependency issues.

### 🧰 Method B: Use kubectl exec (no SQL client required)

Execute SQL scripts directly via stdin redirection:

1. Get the PostgreSQL pod name:

   ```bash
   kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}'
   ```

2. Execute the SQL file directly from your host machine:

   ```bash
   kubectl exec -i <pod-name> -n nexent -- psql -U root -d nexent < ./sql/v1.1.1_1030-update.sql
   ```

   Or if you want to see the output interactively:

   ```bash
   cat ./sql/v1.1.1_1030-update.sql | kubectl exec -i <pod-name> -n nexent -- psql -U root -d nexent
   ```

**Example - Execute multiple SQL files:**

```bash
# Get PostgreSQL pod name
POSTGRES_POD=$(kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}')

# Execute SQL files in order
kubectl exec -i $POSTGRES_POD -n nexent -- psql -U root -d nexent < ./sql/v1.8.0_xxxxx-update.sql
kubectl exec -i $POSTGRES_POD -n nexent -- psql -U root -d nexent < ./sql/v2.0.0_0314_add_context_skill_t.sql
```

> 💡 Tips
> - Create a backup before running migrations:

   ```bash
   POSTGRES_POD=$(kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}')
   kubectl exec nexent/$POSTGRES_POD -n nexent -- pg_dump -U root nexent > backup_$(date +%F).sql
   ```

> - For Supabase database (full version only), use `nexent-supabase-db` pod instead:

   ```bash
   SUPABASE_POD=$(kubectl get pods -n nexent -l app=nexent-supabase-db -o jsonpath='{.items[0].metadata.name}')
   kubectl cp docker/sql/xxx.sql nexent/$SUPABASE_POD:/tmp/update.sql
   kubectl exec -it nexent/$SUPABASE_POD -n nexent -- psql -U postgres -f /tmp/update.sql
   ```

---

## 🔍 Troubleshooting

### Check Deployment Status

```bash
kubectl get pods -n nexent
kubectl rollout status deployment/nexent-config -n nexent
```

### View Logs

```bash
kubectl logs -n nexent -l app=nexent-config --tail=100
kubectl logs -n nexent -l app=nexent-web --tail=100
```

### Restart Services After Manual SQL Update（if needed）

If you executed SQL scripts manually, restart the affected services:

```bash
kubectl rollout restart deployment/nexent-config -n nexent
kubectl rollout restart deployment/nexent-runtime -n nexent
```

### Re-initialize Elasticsearch (if needed)

```bash
cd k8s/helm
bash init-elasticsearch.sh
```
