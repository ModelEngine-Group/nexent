# Nexent Helm Chart

This directory contains a Helm chart for deploying Nexent on Kubernetes.

## Prerequisites

- Kubernetes cluster (e.g., Minikube, K3s, Docker Desktop)
- Helm 3+
- kubectl configured with cluster access

## Quick Start

Navigate to the `k8s/helm` directory and run the deployment script:

```bash
cd k8s/helm
./deploy-helm.sh apply
```

## Commands

| Command | Description |
|---------|-------------|
| `apply` | Clean helm state and deploy all K8s resources |
| `clean` | Clean helm state only (fixes stuck releases) |
| `delete` | Delete resources but **PRESERVE** data (PVC/PV) |
| `delete-all` | Delete ALL resources including data |

### Usage Examples

```bash
# Interactive deployment (will prompt for all options)
./deploy-helm.sh apply

# Deploy with mainland China image sources
./deploy-helm.sh apply --is-mainland Y

# Deploy with general image sources
./deploy-helm.sh apply --is-mainland N

# Deploy full version with Supabase
./deploy-helm.sh apply --deployment-version full

# Non-interactive deployment with all options
./deploy-helm.sh apply --is-mainland N --deployment-version speed

# Clean helm state (fixes stuck releases)
./deploy-helm.sh clean

# Uninstall but preserve data
./deploy-helm.sh delete

# Complete uninstall including all data
./deploy-helm.sh delete-all
```

## Command Line Options

| Option | Description | Values |
|--------|-------------|--------|
| `--is-mainland` | Server network location | `Y` (mainland China) or `N` (general) |
| `--version` | Application version | Version tag (auto-detected from `backend/consts/const.py` if not set) |
| `--deployment-version` | Deployment version | `speed` (default, no Supabase) or `full` (includes Supabase) |

## Deployment Versions

### Speed Version (Default)

Lightweight deployment with essential features:

- Backend services (config, runtime, mcp, northbound)
- Web frontend
- Data process service
- Infrastructure: Elasticsearch, PostgreSQL, Redis, MinIO
- MCP Docker container
- Terminal tool (OpenSSH, optional)

### Full Version

Full-featured deployment with all capabilities:

- All Speed version components
- Supabase authentication (Kong API Gateway, GoTrue Auth, PostgreSQL)

## Deployment Workflow

The `apply` command performs the following steps:

1. **Select deployment version** - Choose between speed or full deployment
2. **Select image source** - Choose mainland China or general image sources
3. **Update image tags** - Configure values.yaml with selected image repositories
4. **Generate MinIO credentials** - Create access key and secret key for object storage
5. **Generate Supabase secrets** - Create JWT and other secrets (full version only)
6. **Configure Terminal tool** - Optionally enable OpenSSH server for AI shell commands
7. **Clean stale PersistentVolumes** - Remove any released PVs before deployment
8. **Deploy Helm chart** - Install/upgrade the release with all resources
9. **Initialize Elasticsearch** - Wait for ES pod and create API key
10. **Restart backend services** - Reload services with new ES configuration
11. **Create super admin user** - Initialize admin account (full version only)
12. **Pull MCP image** - Download MCP Docker image to local host

## Image Sources

The deployment script automatically selects image sources based on your network location:

- **Mainland China** (`--is-mainland Y`): Uses `.env.mainland` with optimized regional mirrors
- **General** (`--is-mainland N`): Uses `.env.general` with standard Docker Hub registries

## Accessing the Application

After successful deployment:

| Service | Default Address |
|---------|-----------------|
| Web Application | http://localhost:30000 |
| SSH Terminal | localhost:30022 (if enabled) |

## Data Persistence

### Preserved Data (with `delete`)

The following PersistentVolumes preserve data when using `delete`:

- `nexent-elasticsearch-pv` - Search index data
- `nexent-postgresql-pv` - Relational database data
- `nexent-redis-pv` - Cache data
- `nexent-minio-pv` - Object storage data
- `nexent-supabase-db-pv` - Supabase database (full version only)

### Deleted Data (with `delete-all`)

Using `delete-all` removes all PVCs, PVs, and the namespace, permanently deleting all data.

## Services

### Application Services

| Service | Description | Replicas |
|---------|-------------|----------|
| nexent-config | Configuration service | 1 |
| nexent-runtime | Runtime service | 1 |
| nexent-mcp | MCP container service | 1 |
| nexent-northbound | Northbound API service | 1 |
| nexent-web | Web frontend | 1 |
| nexent-data-process | Data processing service | 1 |

### Infrastructure Services

| Service | Description |
|---------|-------------|
| nexent-elasticsearch | Search and indexing engine |
| nexent-postgresql | Relational database |
| nexent-redis | Caching layer |
| nexent-minio | S3-compatible object storage |

### Supabase Services (Full Version Only)

| Service | Description |
|---------|-------------|
| nexent-supabase-kong | API Gateway |
| nexent-supabase-auth | Authentication service |
| nexent-supabase-db | Database service |

### Optional Services

| Service | Description | Enabled By |
|---------|-------------|------------|
| nexent-openssh-server | SSH terminal for AI agents | `--set services.openssh.enabled=true` |

## Configuration

### Customizing via values.yaml

Edit `nexent/values.yaml` or pass values via command line:

```bash
helm upgrade --install nexent nexent \
  --set images.backend.tag=v1.0.0 \
  --set global.dataDir=/custom/path
```

### Key Configuration Parameters

#### Global Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.namespace` | Kubernetes namespace | `nexent` |
| `global.dataDir` | Host path for persistent data | `/data/nexent` |
| `deploymentVersion` | Deployment version | `speed` |

#### Images

| Parameter | Description |
|-----------|-------------|
| `images.backend.repository` | Backend image repository |
| `images.backend.tag` | Backend image tag |
| `images.web.repository` | Web image repository |
| `images.web.tag` | Web image tag |
| `images.dataProcess.repository` | Data process image repository |
| `images.dataProcess.tag` | Data process image tag |
| `images.elasticsearch.repository` | Elasticsearch image |
| `images.postgresql.repository` | PostgreSQL image |
| `images.redis.repository` | Redis image |
| `images.minio.repository` | MinIO image |
| `images.mcp.repository` | MCP container image |

#### Secrets

| Parameter | Description |
|-----------|-------------|
| `secrets.ssh.username` | SSH username (for Terminal tool) |
| `secrets.ssh.password` | SSH password (for Terminal tool) |
| `secrets.supabase.jwtSecret` | Supabase JWT secret |
| `secrets.supabase.secretKeyBase` | Supabase secret key base |
| `secrets.supabase.anonKey` | Supabase anonymous key |
| `secrets.supabase.serviceRoleKey` | Supabase service role key |

#### MinIO

| Parameter | Description |
|-----------|-------------|
| `minio.accessKey` | MinIO access key |
| `minio.secretKey` | MinIO secret key |

## Troubleshooting

### Helm Release Stuck

If you see "Release does not exist" errors:

```bash
./deploy-helm.sh clean
./deploy-helm.sh apply
```

### Pods Not Starting

Check pod status:

```bash
kubectl get pods -n nexent
kubectl describe pod <pod-name> -n nexent
```

### View Logs

```bash
kubectl logs -n nexent -l app=nexent-backend
kubectl logs -n nexent -l app=nexent-elasticsearch
```

### Elasticsearch Initialization Failed

Re-run the initialization script:

```bash
cd k8s/helm
bash init-elasticsearch.sh
```

### Clean Up Stale PersistentVolumes

Released PVs are automatically cleaned during deployment. To manually clean:

```bash
kubectl delete pv nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv
```
