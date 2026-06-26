# Nexent Kubernetes Upgrade Guide

## 🚀 Upgrade Overview

Follow these steps to upgrade Nexent on Kubernetes safely:

1. Pull the latest code
2. Execute the Helm deployment script
3. Open the site to confirm service availability

---

## 🔄 Step 1: Update Code

Before updating, record the current deployment version and data directory information.

- Current Deployment Version Location: root `VERSION`
- Local volume directories: each Helm sub-chart's `storage.hostPath`, defaulting to `/var/lib/nexent-data/nexent-*`

**Code downloaded via git**

Update the code using git commands:

```bash
git pull
```

**Code downloaded via ZIP package or other means**

1. Re-download the latest code from GitHub and extract it.
2. Copy the `deploy.options` file from the `k8s/helm` directory of your previous deployment to the new code directory. (If the file doesn't exist, you can ignore this step).

## 🔄 Step 2: Execute the Upgrade

Navigate to the k8s/helm directory of the updated code and run the deployment script:

```bash
cd deploy/k8s
./deploy.sh
```

The script will detect your saved deployment settings (components, port policy, image source, etc.) from `deploy.options`. If the file is missing, you will be prompted to enter configuration details.

> 💡 Tip
> If you need to configure voice models (STT/TTS), please edit the corresponding values in `values.yaml` or pass them via command line.

---

## 🌐 Step 3: Verify the Deployment

After deployment:

1. Open `http://localhost:30000` in your browser.
2. Review the [User Guide](../user-guide/home-page) to validate agent functionality.

---

## 🗄️ Database Migrations

SQL migrations are no longer executed manually. In Kubernetes, only `nexent-config` runs `deploy/common/run-sql-migrations.sh` on startup and automatically applies merged migration files from `deploy/sql/migrations/`, such as `v1_merged_migrations.sql`, `v2.0_merged_migrations.sql`, `v2.1_merged_migrations.sql`, and `v2.2_merged_migrations.sql`; the other backend services only wait for migration records to reach the target state.

The migration runner records each source section in `nexent.schema_migrations`. If records are missing but business tables already exist, probes safely backfill `baselined` records; ambiguous cases fail instead of being skipped.

> 💡 Tips
> - Create a backup before running migrations:

   ```bash
   POSTGRES_POD=$(kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}')
   kubectl exec nexent/$POSTGRES_POD -n nexent -- pg_dump -U root nexent > backup_$(date +%F).sql
   ```

> - Supabase initialization SQL is rendered from `deploy/sql/supabase/` into Helm values by the deploy script. It does not need to be copied or executed manually.

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

### Restart Services After Migration Retry

```bash
kubectl rollout restart deployment/nexent-config -n nexent
kubectl rollout restart deployment/nexent-runtime -n nexent
```

### Re-initialize Elasticsearch (if needed)

```bash
cd deploy/k8s
bash init-elasticsearch.sh
```
