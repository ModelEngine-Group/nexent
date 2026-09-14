# Nexent Kubernetes Upgrade Guide

## 🚀 Upgrade Overview

Follow these steps to upgrade Nexent on Kubernetes safely:

1. Pull the latest code
2. Execute the Helm deployment script
3. Open the site to confirm service availability

---

## 🔄 Step 1: Update Code

Before updating, record the current version, storage configuration, and deployment options, and back up PostgreSQL, MinIO, and other important data.

- Current Deployment Version Location: root `VERSION`
- Local volume directories: each Helm sub-chart's `storage.hostPath`, defaulting to `/var/lib/nexent-data/nexent-*`

**Code downloaded via git**

Make sure you are on the branch used for deployment, then pull changes with fast-forward only:

```bash
git branch --show-current
git pull --ff-only
```

**Code downloaded via ZIP package or other means**

1. Download and extract the target version from GitHub.
2. Copy `deploy/k8s/deploy.options` from the old deployment directory to the same location in the new code. Skip this step if the file does not exist.
3. Alternatively, use `--reuse-from` during deployment to reuse the environment configuration and deployment options from the old directory.

## 🔄 Step 2: Execute the Upgrade

From the repository root of the updated code, run the Kubernetes deployment entrypoint:

```bash
bash deploy.sh k8s
```

The script will detect your saved deployment settings (components, port policy, image source, etc.) from `deploy.options`. If the file is missing, you will be prompted to enter configuration details.

> 💡 Tips
> - Existing values, comments, ordering, and legacy-only variables in `deploy/env/.env` are preserved, while variables introduced in the current `deploy/env/.env.example` are appended automatically. A readable template must exist before deployment. Generated Helm values are recreated from the merged `.env`; do not edit them directly.
> - v2.5.0 adds a shared runtime workspace and sandbox image. In offline or multi-node clusters, make sure every node that may run a related Pod can obtain the sandbox image.

---

## 🌐 Step 3: Verify the Deployment

After deployment:

1. Open `http://localhost:30000` in your browser.
2. Check that the selected application Pods are ready.
3. Confirm that the `nexent-workspace` PVC is bound and can be mounted by the relevant Config, Runtime, MCP, Northbound, and Data Process Pods.
4. Follow the [User Guide](../user-guide/home-page) to validate agent configuration and chat.

---

## 🗄️ Database Migrations

SQL migrations are no longer executed manually. In Kubernetes, only `nexent-config` runs `deploy/common/run-sql-migrations.sh` on startup and automatically applies `*.sql` files from `deploy/sql/migrations/` in filename order; the other backend services only wait for migration records to reach the target state. The deploy script renders `deploy/sql` into the shared SQL ConfigMap mounted at `/opt/nexent/sql`, so SQL-only changes require rerunning deployment, not rebuilding images.

The migration runner uses each SQL filename as the migration ID in `nexent.schema_migrations`. If a recorded file has the same checksum, it is skipped; if the checksum changes, the same file is rerun and the checksum, execution time, app version, and source file are updated.

Published migration files must not be modified, renamed, or deleted. Database schema changes must be implemented in a new versioned migration under `deploy/sql/migrations/`. v2.5.0 uses a consolidated migration file to apply the database changes for this release.

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
kubectl get pvc nexent-workspace -n nexent
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
