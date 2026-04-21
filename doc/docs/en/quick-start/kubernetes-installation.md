# Kubernetes Installation & Deployment

## 🎯 Prerequisites

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU**  | 4 cores | 8 cores |
| **RAM**  | 16 GiB | 64 GiB |
| **Disk** | 100 GiB | 200 GiB |
| **Architecture** | x86_64 / ARM64 | x86_64 |
| **Software** | Kubernetes 1.24+, Helm 3+, kubectl configured | Kubernetes 1.28+ |

> **💡 Note**: The recommended configuration of **8 cores and 64 GiB RAM** provides optimal performance for production workloads.

## 🚀 Quick Start

### 1. Prepare Kubernetes Cluster

Ensure your Kubernetes cluster is running and kubectl is configured with cluster access:

```bash
kubectl cluster-info
kubectl get nodes
```

### 2. Clone and Navigate

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/k8s/helm
```

### 3. Deployment

Run the deployment script:

```bash
./deploy-helm.sh apply
```

After executing this command, the system will prompt for configuration options:

**Version Selection:**
- **Speed version (Lightweight & Fast Deployment, Default)**: Quick startup of core features, suitable for individual users and small teams
- **Full version (Complete Feature Edition)**: Provides enterprise-level tenant management and resource isolation features, includes Supabase authentication

**Image Source Selection:**
- **Mainland China**: Uses optimized regional mirrors for faster image pulling
- **General**: Uses standard Docker Hub registries

**Optional Components:**
- **Terminal Tool**: Enables openssh-server for AI agent shell command execution

### ⚠️ Important Notes

1️⃣ **When deploying v1.8.0 or later for the first time**, you will be prompted to set a password for the `suadmin` super administrator account during the deployment process. This account has the highest system privileges. Please enter your desired password and **save it securely** after creation - it cannot be retrieved later.

2️⃣ Forgot to note the `suadmin` account password? Follow these steps:

```bash
# Step 1: Delete su account record in Supabase database
kubectl exec -it -n nexent deploy/nexent-supabase-db -- psql -U postgres -c \
  "SELECT id, email FROM auth.users WHERE email='suadmin@nexent.com';"
# Get the user_id and delete
kubectl exec -it -n nexent deploy/nexent-supabase-db -- psql -U postgres -c \
  "DELETE FROM auth.identities WHERE user_id='your_user_id';"
kubectl exec -it -n nexent deploy/nexent-supabase-db -- psql -U postgres -c \
  "DELETE FROM auth.users WHERE id='your_user_id';"

# Step 2: Delete su account record in nexent database
kubectl exec -it -n nexent deploy/nexent-postgresql -- psql -U root -d nexent -c \
  "DELETE FROM nexent.user_tenant_t WHERE user_id='your_user_id';"

# Step 3: Re-deploy and record the su account password
./deploy-helm.sh apply
```

### 4. Access Your Installation

When deployment completes successfully:

| Service | Default Address |
|---------|-----------------|
| Web Application | http://localhost:30000 |
| SSH Terminal | localhost:30022 (if enabled) |

Access steps:
1. Open **http://localhost:30000** in your browser
2. Log in with the super administrator account
3. Access tenant resources → Create tenant and tenant administrator
4. Log in with the tenant administrator account
5. Refer to the [User Guide](../user-guide/home-page) to develop agents

## 🏗️ Service Architecture

Nexent uses a microservices architecture deployed via Helm charts:

**Application Services:**
| Service | Description | Default Port |
|---------|-------------|--------------|
| nexent-config | Configuration service | 5010 |
| nexent-runtime | Runtime service | 5010 |
| nexent-mcp | MCP container service | 5010 |
| nexent-northbound | Northbound API service | 5010 |
| nexent-web | Web frontend | 3000 |
| nexent-data-process | Data processing service | 5012 |

**Infrastructure Services:**
| Service | Description |
|---------|-------------|
| nexent-elasticsearch | Search and indexing engine |
| nexent-postgresql | Relational database |
| nexent-redis | Caching layer |
| nexent-minio | S3-compatible object storage |

**Supabase Services (Full Version Only):**
| Service | Description |
|---------|-------------|
| nexent-supabase-kong | API Gateway |
| nexent-supabase-auth | Authentication service |
| nexent-supabase-db | Database service |

**Optional Services:**
| Service | Description |
|---------|-------------|
| nexent-openssh-server | SSH terminal for AI agents |

## 🔌 Port Mapping

| Service | Internal Port | NodePort | Description |
|---------|---------------|----------|-------------|
| Web Interface | 3000 | 30000 | Main application access |
| Northbound API | 5010 | 30013 | Northbound API service |
| SSH Server | 22 | 30022 | Terminal tool access |

For internal service communication, services use Kubernetes internal DNS (e.g., `http://nexent-config:5010`).

## 💾 Data Persistence

Nexent uses PersistentVolumes for data persistence:

| Data Type | PersistentVolume | Default Host Path |
|-----------|------------------|-------------------|
| Elasticsearch | nexent-elasticsearch-pv | `{dataDir}/elasticsearch` |
| PostgreSQL | nexent-postgresql-pv | `{dataDir}/postgresql` |
| Redis | nexent-redis-pv | `{dataDir}/redis` |
| MinIO | nexent-minio-pv | `{dataDir}/minio` |
| Supabase DB (Full) | nexent-supabase-db-pv | `{dataDir}/supabase-db` |

Default `dataDir` is `/var/lib/nexent-data` (configurable in `values.yaml`).

## 🔧 Deployment Commands

```bash
# Deploy with interactive prompts
./deploy-helm.sh apply

# Deploy with mainland China image sources
./deploy-helm.sh apply --is-mainland Y

# Deploy full version (with Supabase)
./deploy-helm.sh apply --deployment-version full

# Clean helm state only (fixes stuck releases)
./deploy-helm.sh clean

# Uninstall but preserve data
./deploy-helm.sh delete

# Complete uninstall including all data
./deploy-helm.sh delete-all
```

## 🔍 Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n nexent
kubectl describe pod <pod-name> -n nexent
```

### View Logs

```bash
kubectl logs -n nexent -l app=nexent-config
kubectl logs -n nexent -l app=nexent-web
kubectl logs -n nexent -l app=nexent-elasticsearch
```

### Restart Services

```bash
kubectl rollout restart deployment/nexent-config -n nexent
kubectl rollout restart deployment/nexent-runtime -n nexent
```

### Re-initialize Elasticsearch

If Elasticsearch initialization failed:

```bash
bash init-elasticsearch.sh
```

### Clean Up Stale PersistentVolumes

```bash
kubectl delete pv nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv
```

## 💡 Need Help

- Browse the [FAQ](./faq) for common install issues
- Drop questions in our [Discord community](https://discord.gg/tb5H3S3wyv)
- File bugs or feature ideas in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues)
