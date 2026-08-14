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
2. Copy the `deploy.options` file from the `deploy/k8s` directory of your previous deployment to the same directory in the new code. (If the file does not exist, you can ignore this step).

## 🔄 Step 2: Execute the Upgrade

From the repository root of the updated code, run the Kubernetes deployment entrypoint:

```bash
bash deploy.sh k8s
```

The script will detect your saved deployment settings (components, port policy, image source, etc.) from `deploy.options`. If the file is missing, you will be prompted to enter configuration details.

> 💡 Tip
> Existing values, comments, ordering, and old-only variables in `deploy/env/.env` are preserved, while variables newly introduced by the current `deploy/env/.env.example` are appended automatically. A readable template is required before deployment starts. Generated Helm values are then recreated from the merged `.env`; do not edit them directly. Configure voice models (STT/TTS) in `deploy/env/.env`.

---

## 🌐 Step 3: Verify the Deployment

After deployment:

1. Open `http://localhost:30000` in your browser.
2. Review the [User Guide](../user-guide/home-page) to validate agent functionality.

---

## 🗄️ Database Migrations

SQL migrations are no longer executed manually. In Kubernetes, only `nexent-config` runs `deploy/common/run-sql-migrations.sh` on startup and automatically applies `*.sql` files from `deploy/sql/migrations/` in filename order; the other backend services only wait for migration records to reach the target state. The deploy script renders `deploy/sql` into the shared SQL ConfigMap mounted at `/opt/nexent/sql`, so SQL-only changes require rerunning deployment, not rebuilding images.

The migration runner uses each SQL filename as the migration ID in `nexent.schema_migrations`. If a recorded file has the same checksum, it is skipped; if the checksum changes, the same file is rerun and the checksum, execution time, app version, and source file are updated.

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
bash deploy/k8s/init-elasticsearch.sh
```
