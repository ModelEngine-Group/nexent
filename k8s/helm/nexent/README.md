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
./deploy.sh
```

## Commands

| Command | Description |
|---------|-------------|
| `./deploy.sh` | Deploy all K8s resources |
| `./uninstall.sh` | Uninstall the Helm release; prompts before deleting namespace or local data |
| `./uninstall.sh clean` | Clean Helm state only (fixes stuck releases) |
| `./uninstall.sh delete` | Uninstall the Helm release and delete the namespace |
| `./uninstall.sh delete-all` | Uninstall the Helm release, delete the namespace, and delete local hostPath data |

### Usage Examples

```bash
# Interactive deployment (will prompt for all options)
./deploy.sh

# Non-interactive deployment with the default component set
./deploy.sh --components infrastructure,application --port-policy development --image-source general

# Enable Supabase, data processing, and terminal
./deploy.sh --components infrastructure,application,supabase,data-process,terminal

# Use mainland China image sources
./deploy.sh --image-source mainland

# Use local latest Nexent images
./deploy.sh --image-source local-latest

# Clean helm state (fixes stuck releases)
./uninstall.sh clean

# Uninstall but preserve data
./uninstall.sh

# Uninstall and keep local hostPath data without prompting
./uninstall.sh --keep-local-data --keep-namespace

# Delete namespace after uninstall
./uninstall.sh --delete-namespace true

# Delete local hostPath data after uninstall
./uninstall.sh --delete-local-data true

# Complete uninstall including namespace and local hostPath data
./uninstall.sh delete-all

# Complete uninstall but preserve local hostPath data
./uninstall.sh delete-all --keep-local-data
```

## Deploy Options

| Option | Description | Values |
|--------|-------------|--------|
| `--components` | Comma-separated deployment components | `infrastructure`, `application`, `data-process`, `supabase`, `terminal`, `monitoring` |
| `--port-policy` | Host exposure policy | `development` or `production` |
| `--image-source` | Image reference source | `general`, `mainland`, or `local-latest` |
| `--registry-profile` | Legacy registry profile option | `general` or `mainland`; maps to `--image-source` |
| `--monitoring-provider` | Provider when `monitoring` is selected | `otlp`, `phoenix`, `langfuse`, `langsmith`, `grafana`, `zipkin` |
| `--use-local-config` | Reuse saved local deployment config | Flag |
| `--reconfigure` | Ignore saved local config and run full configuration | Flag |
| `--config` | Deployment config path | YAML file |
| `--is-mainland` | Legacy network location option | `Y` maps to `--image-source mainland`; `N` maps to `general` |
| `--version` | Application version | Version tag (auto-detected from `backend/consts/const.py` if not set) |
| `--deployment-version` | Legacy deployment version | `speed` maps to `infrastructure,application`; `full` adds `supabase` |

## Uninstall Options

| Option | Description | Values |
|--------|-------------|--------|
| `--delete-data` | Compatibility option for Helm-managed PV/PVC cleanup behavior | `true` or `false` |
| `--delete-volumes` | Alias for `--delete-data` | `true` or `false` |
| `--remove-volumes` | Alias for `--delete-data true` | Flag |
| `--keep-volumes` | Alias for `--delete-data false` | Flag |
| `--delete-local-data` | Delete local hostPath data under `/var/lib/nexent-data` after Helm uninstall | `true` or `false` |
| `--remove-local-data` | Alias for `--delete-local-data true` | Flag |
| `--keep-local-data` | Alias for `--delete-local-data false` | Flag |
| `--delete-namespace` | Delete the Kubernetes namespace after Helm uninstall | `true` or `false` |
| `--remove-namespace` | Alias for `--delete-namespace true` | Flag |
| `--keep-namespace` | Alias for `--delete-namespace false` | Flag |
| `--namespace` | Kubernetes namespace | Namespace name; default `nexent` |
| `--release` | Helm release name | Release name; default `nexent` |

## Deployment Components

The deployment script uses Bash TUI menus when running interactively. It first shows a component multi-select menu, then single-select menus for port policy and image source. Use `b`/Backspace to return to the previous TUI step and `q` to quit. `infrastructure` is required and is added automatically if omitted; `application` is selected by default but can be disabled.

| Component | Services |
|-----------|----------|
| `infrastructure` | Elasticsearch, PostgreSQL, Redis, MinIO |
| `application` | config, runtime, mcp, northbound, web |
| `data-process` | nexent-data-process |
| `supabase` | Supabase Kong, GoTrue Auth, Supabase PostgreSQL, related initialization |
| `terminal` | OpenSSH terminal tool |
| `monitoring` | Optional monitoring chart; selecting it prompts for provider unless `--monitoring-provider` is passed |

`application` does not include `data-process`. User and tenant features are enabled by selecting `supabase`; there is no separate user/tenant switch.

## Port Policy

| Policy | Kubernetes behavior |
|--------|---------------------|
| `development` | Uses NodePort for Web and selected debug/internal services |
| `production` | Keeps internal services as ClusterIP and exposes the Web entrypoint |

## Deployment Workflow

The `apply` command performs the following steps:

1. **Select deployment components** - TUI multi-select or `--components`
2. **Select port policy and image source** - TUI/config/CLI arguments
3. **Render generated values** - Runtime-only Helm values for components, ports, and images
4. **Generate MinIO credentials** - Create access key and secret key for object storage
5. **Generate Supabase secrets** - Only when the `supabase` component is selected
6. **Configure Terminal tool** - Only when the `terminal` component is selected
7. **Clean stale PersistentVolumes** - Remove any released PVs before deployment
8. **Deploy Helm chart** - Install/upgrade the release with all resources
9. **Initialize Elasticsearch** - Wait for ES pod and create API key
10. **Restart backend services** - Reload services with new ES configuration
11. **Create super admin user** - Initialize admin account (full version only)
12. **Pull MCP image** - Download MCP Docker image to local host

## Image Sources And Local Config

Image source is independent from components and ports:

- `general`: uses standard public registry images and `--version`.
- `mainland`: uses mainland China registry mirror images and `--version`.
- `local-latest`: uses local `latest` Nexent images and sets local-friendly pull policy.

After successful deployment, non-sensitive deployment choices are saved to `k8s/helm/deploy.options`. The next interactive run can reuse that config or reconfigure from scratch. Generated Helm values are runtime files and are ignored by git.

## Accessing the Application

After successful deployment:

| Service | Default Address |
|---------|-----------------|
| Web Application | http://localhost:30000 |
| SSH Terminal | localhost:30022 (if enabled) |
| Langfuse | http://localhost:30001 |
| Grafana | http://localhost:30002 |
| Phoenix | http://localhost:30006 |
| Zipkin | http://localhost:30011 |

## Data Persistence

### Preserved Data

By default, `./uninstall.sh` removes the Helm release and preserves local hostPath data. It prompts before deleting the namespace or hostPath contents. In non-interactive environments, both are preserved unless explicitly requested.

The following local hostPath-backed PersistentVolumes can preserve data:

- `nexent-elasticsearch-pv` - Search index data
- `nexent-postgresql-pv` - Relational database data
- `nexent-redis-pv` - Cache data
- `nexent-minio-pv` - Object storage data
- `nexent-supabase-db-pv` - Supabase database (full version only)
- Monitoring PVs such as Phoenix, Grafana, Tempo, and Langfuse data when monitoring is enabled

### Deleted Data

Use `--delete-local-data true` or `--remove-local-data` to delete known Nexent hostPath data under `/var/lib/nexent-data/nexent-*`. `delete-all` deletes the namespace and local hostPath data by default; add `--keep-local-data` to preserve local volume contents.

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
| nexent-monitoring | OpenTelemetry Collector and optional observability backend | `--set nexent-monitoring.enabled=true` |

### Monitoring

The Helm chart includes an optional monitoring stack that mirrors the Docker
monitoring deployment. The collector is always installed when
`nexent-monitoring.enabled=true`; the backend stack is selected by
`global.monitoring.provider`.

Supported providers:

- `otlp` / `collector` - Collector only, debug exporter
- `phoenix` - Collector + local Phoenix
- `grafana` - Collector + Tempo + Grafana
- `zipkin` - Collector + local Zipkin
- `langfuse` - Collector + self-hosted Langfuse stack
- `langsmith` - Collector forwarding to hosted LangSmith

Example:

```bash
helm upgrade --install nexent nexent \
  --set nexent-monitoring.enabled=true \
  --set global.monitoring.enabled=true \
  --set global.monitoring.provider=grafana \
  --set 'global.monitoring.dashboardUrl=http://localhost:30002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1'
```

For LangSmith, also provide an API key:

```bash
helm upgrade --install nexent nexent \
  --set nexent-monitoring.enabled=true \
  --set global.monitoring.enabled=true \
  --set global.monitoring.provider=langsmith \
  --set global.monitoring.langsmithApiKey=lsv2_xxx
```

The monitoring subchart passes `global.monitoring.langsmithApiKey`,
`global.monitoring.langsmithProject`, and the LangSmith OTLP trace endpoint to
the Collector. If needed, override them directly with
`nexent-monitoring.collector.env.*`.

The backend receives OTLP settings through the shared `nexent-config`
ConfigMap, with `OTEL_EXPORTER_OTLP_ENDPOINT` defaulting to
`http://nexent-otel-collector:4318`. The frontend monitoring entry uses
`global.monitoring.dashboardUrl`; leave it empty to hide the entry.
Monitoring UI Services default to NodePort and can be overridden with
`nexent-monitoring.<provider>.service.type` and
`nexent-monitoring.<provider>.service.nodePort`.

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
./uninstall.sh clean
./deploy.sh
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
