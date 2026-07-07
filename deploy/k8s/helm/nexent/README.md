# Nexent Helm Chart

This directory contains a Helm chart for deploying Nexent on Kubernetes.

## Prerequisites

- Kubernetes cluster (e.g., Minikube, K3s, Docker Desktop)
- Helm 3+
- kubectl configured with cluster access

## Quick Start

From the repository root, run the root deployment entrypoint:

```bash
bash deploy.sh k8s
```

## Commands

| Command | Description |
|---------|-------------|
| `bash deploy.sh k8s` | Deploy all K8s resources from the repository root |
| `bash uninstall.sh k8s` | Uninstall the Helm release from the repository root; prompts before deleting namespace or local data |
| `bash uninstall.sh k8s clean` | Clean Helm state only (fixes stuck releases) |
| `bash uninstall.sh k8s delete` | Uninstall the Helm release and delete the namespace |
| `bash uninstall.sh k8s delete-all` | Uninstall the Helm release, delete the namespace, and delete local PV data |

### Usage Examples

```bash
# Interactive deployment (will prompt for all options)
bash deploy.sh k8s

# Non-interactive deployment with the default component set
bash deploy.sh k8s --components infrastructure,application,data-process,supabase --port-policy development --image-source general

# Add terminal to the default component set
bash deploy.sh k8s --components infrastructure,application,data-process,supabase,terminal

# Use mainland China image sources
bash deploy.sh k8s --image-source mainland

# Use local latest Nexent images
bash deploy.sh k8s --image-source local-latest

# Use a specific StorageClass with the short alias
bash deploy.sh k8s --sc fast-storage

# Clean helm state (fixes stuck releases)
bash uninstall.sh k8s clean

# Uninstall but preserve data
bash uninstall.sh k8s

# Uninstall and keep local PV data without prompting
bash uninstall.sh k8s --keep-local-data --keep-namespace

# Delete namespace after uninstall
bash uninstall.sh k8s --delete-namespace true

# Delete local PV data after uninstall
bash uninstall.sh k8s --delete-local-data true

# Complete uninstall including namespace and local PV data
bash uninstall.sh k8s delete-all

# Complete uninstall but preserve local PV data
bash uninstall.sh k8s delete-all --keep-local-data
```

K8s deployments read runtime configuration from `deploy/env/.env`, the same file used by Docker. Existing `deploy/env/.env` is kept as-is. If it is missing, the deploy script first reuses `docker/.env`, then falls back to `deploy/env/.env.example`. Do not edit generated Helm values by hand; they are recreated from `deploy/env/.env` and deployment options.

When `--persistence-mode local` is used, Nexent renders static PVs with `hostPath` and `DirectoryOrCreate`; node affinity is not required. Shared workspace data uses `/var/lib/nexent`, shared skills use `/var/lib/nexent-data/skills`, and service data uses `/var/lib/nexent-data/nexent-*` by default.

## Deploy Options

| Option | Description | Values |
|--------|-------------|--------|
| `--components` | Comma-separated deployment components | `infrastructure`, `application`, `data-process`, `supabase`, `terminal`, `monitoring` |
| `--port-policy` | Host exposure policy | `development` or `production` |
| `--image-source` | Image reference source | `general`, `mainland`, or `local-latest` |
| `--registry-profile` | Legacy registry profile option | `general` or `mainland`; maps to `--image-source` |
| `--monitoring-provider` | Provider when `monitoring` is selected | `otlp`, `phoenix`, `langfuse`, `langsmith`, `grafana`, `zipkin` |
| `--use-local-config` | Reuse saved local deployment config | Flag |
| `--reconfigure` | Run interactive configuration using saved local config as defaults | Flag |
| `--config` | Open the interactive deployment configuration | Flag |
| `--is-mainland` | Legacy network location option | `Y` maps to `--image-source mainland`; `N` maps to `general` |
| `--version` | Application version | Version tag (auto-detected from `backend/consts/const.py` if not set) |
| `--deployment-version` | Legacy deployment version | `speed` maps to `infrastructure,application`; `full` adds `supabase` |
| `--persistence-mode` | Persistent volume mode | `local`, `dynamic`, or `existing`; default `local` |
| `--storage-class` | StorageClass for PV/PVC binding | StorageClass name; aliases `--storageclass`, `--storage-class-name`, `--sc` |
| `--local-path` | Base host path for local PVs except workspace | Path; default `/var/lib/nexent-data` |
| `--local-node-name` | Deprecated compatibility option | Ignored; local mode uses hostPath and does not require nodeAffinity |
| `--existing-claim-prefix` | Prefix for existing PVC names | Renders as `<prefix>-<component>` |

## Uninstall Options

| Option | Description | Values |
|--------|-------------|--------|
| `--delete-data` | Compatibility option for Helm-managed PV/PVC cleanup behavior | `true` or `false` |
| `--delete-volumes` | Alias for `--delete-data` | `true` or `false` |
| `--remove-volumes` | Alias for `--delete-data true` | Flag |
| `--keep-volumes` | Alias for `--delete-data false` | Flag |
| `--delete-local-data` | Delete local PV data under `/var/lib/nexent` and `/var/lib/nexent-data` after Helm uninstall | `true` or `false` |
| `--remove-local-data` | Alias for `--delete-local-data true` | Flag |
| `--keep-local-data` | Alias for `--delete-local-data false` | Flag |
| `--delete-namespace` | Delete the Kubernetes namespace after Helm uninstall | `true` or `false` |
| `--remove-namespace` | Alias for `--delete-namespace true` | Flag |
| `--keep-namespace` | Alias for `--delete-namespace false` | Flag |
| `--namespace` | Kubernetes namespace | Namespace name; default `nexent` |
| `--release` | Helm release name | Release name; default `nexent` |

## Offline Image Package

Use the repository-level offline package builder when the target Kubernetes environment cannot pull images directly:

```bash
bash deploy/offline/build_offline_package.sh \
  --target k8s \
  --version v2.2.1 \
  --platform amd64 \
  --components infrastructure,application,data-process,supabase \
  --image-source general \
  --compress true \
  --output-dir offline-package/k8s
```

Package contents include `images/*.tar`, `load-images.sh`, root `deploy.sh` and `uninstall.sh`, the filtered `deploy/` bundle for the selected target, `deploy/sql`, `manifest.yaml`, and `checksums.txt`. Local `deploy/env/.env`, `.env.generated`, and `deploy.options` are intentionally excluded. With `--compress true`, a `nexent-offline-<target>-<platform>-<version>.zip` archive is created next to the output directory.

On a target host with access to the cluster, load images before deployment:

```bash
cd offline-package/k8s
bash deploy.sh --load-images k8s \
  --version v2.2.1 \
  --components infrastructure,application,data-process,supabase \
  --image-source general
```

For multi-node clusters, run `load-images.sh` on every node that may schedule Nexent Pods, or push the loaded images to an internal registry and deploy with matching image references.

## Deployment Components

The deployment script uses Bash TUI menus when running interactively. It first shows a component multi-select menu, then single-select menus for port policy and image source. Use `b`/Backspace to return to the previous TUI step and `q` to quit. `infrastructure` is required and is added automatically if omitted; `application`, `data-process`, and `supabase` are selected by default and can be disabled for smaller deployments.

| Component | Services |
|-----------|----------|
| `infrastructure` | Elasticsearch, PostgreSQL, Redis, MinIO |
| `application` | config, runtime, mcp, northbound, web |
| `data-process` | nexent-data-process |
| `supabase` | Supabase Kong, GoTrue Auth, Supabase PostgreSQL, related initialization |
| `terminal` | OpenSSH terminal tool |
| `monitoring` | Optional monitoring chart; selecting it prompts for provider unless `--monitoring-provider` is passed |

`application` does not include `data-process`; it is a separate component even though it is selected by default. User and tenant features are enabled by selecting `supabase`; there is no separate user/tenant switch.

## Port Policy

| Policy | Kubernetes behavior |
|--------|---------------------|
| `development` | Uses NodePort for Web and selected debug/internal services |
| `production` | Keeps internal services as ClusterIP and exposes the Web and northbound entrypoints |

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

After successful deployment, non-sensitive deployment choices are saved to `deploy/k8s/deploy.options`. The next interactive run can reuse that config or reconfigure from scratch. Generated Helm values are runtime files and are ignored by git.

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

By default, `bash uninstall.sh k8s` removes the Helm release and preserves local PV data. It prompts before deleting the namespace or local PV contents. In non-interactive environments, both are preserved unless explicitly requested.

The following local PersistentVolumes can preserve data:

- `nexent-workspace-pv` - Shared user workspace mounted at `/mnt/nexent`
- `nexent-skills-pv` - Shared skills data mounted at `/mnt/nexent-data/skills`
- `nexent-elasticsearch-pv` - Search index data
- `nexent-postgresql-pv` - Relational database data
- `nexent-redis-pv` - Cache data
- `nexent-minio-pv` - Object storage data
- `nexent-supabase-db-pv` - Supabase database (full version only)
- Monitoring PVs such as Phoenix, Grafana, Tempo, and Langfuse data when monitoring is enabled

### Deleted Data

Use `--delete-local-data true` or `--remove-local-data` to delete known Nexent local PV data under `/var/lib/nexent`, `/var/lib/nexent-data/skills`, and `/var/lib/nexent-data/nexent-*`. `delete-all` deletes the namespace and local PV data by default; add `--keep-local-data` to preserve local volume contents.

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
| `global.dataDir` | Host path for persistent data | `/var/lib/nexent-data` |
| `global.sharedStorage.workspace.size` | Shared `/mnt/nexent` PVC size | `10Gi` |
| `global.sharedStorage.workspace.localPath` | Host path for shared workspace data | `/var/lib/nexent` |
| `global.sharedStorage.skills.size` | Shared `/mnt/nexent-data/skills` PVC size | `5Gi` |
| `global.sharedStorage.skills.localPath` | Host path for shared skills data | `/var/lib/nexent-data/skills` |
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
bash uninstall.sh k8s clean
bash deploy.sh k8s
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
bash deploy/k8s/init-elasticsearch.sh
```

### Clean Up Stale PersistentVolumes

Released PVs are automatically cleaned during deployment. To manually clean:

```bash
kubectl delete pv nexent-workspace-pv nexent-skills-pv nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv
```
