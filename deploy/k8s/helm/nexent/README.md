# Nexent Kubernetes Helm Charts

Kubernetes deployment uses two independent releases with disjoint resource ownership:

- `nexent-infrastructure`: Elasticsearch, PostgreSQL, Redis, MinIO, infrastructure credentials, and PostgreSQL bootstrap SQL.
- `nexent`: Config, Runtime, MCP, Northbound, Web, Data Process, Terminal, Monitoring, and application-owned shared resources.

Fresh installations are supported. If the deployment script detects a legacy `nexent` release that still owns infrastructure resources, it stops instead of attempting an in-place migration.

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
| `bash deploy.sh k8s` | Deploy infrastructure, initialize Elasticsearch, then deploy Nexent |
| `bash deploy.sh k8s --release-scope infrastructure` | Install or upgrade infrastructure only |
| `bash deploy.sh k8s --release-scope nexent` | Verify infrastructure and install or upgrade Nexent only |
| `bash uninstall.sh k8s` | Uninstall Nexent first, then infrastructure |
| `bash uninstall.sh k8s --release-scope nexent` | Uninstall the application release only |
| `bash uninstall.sh k8s --release-scope infrastructure` | Uninstall infrastructure only when Nexent is absent |
| `bash uninstall.sh k8s clean` | Clean Helm state only (fixes stuck releases) |
| `bash uninstall.sh k8s delete` | Uninstall the Helm release and delete the namespace |
| `bash uninstall.sh k8s delete-all` | Uninstall the Helm release, delete the namespace, and delete local PV data |

### Usage Examples

```bash
# Interactive deployment (will prompt for all options)
bash deploy.sh k8s

# Upgrade infrastructure and application in dependency order
bash deploy.sh k8s --release-scope all

# Operate either release independently
bash deploy.sh k8s --release-scope infrastructure
bash deploy.sh k8s --release-scope nexent

# Non-interactive deployment with dynamic RWX storage
bash deploy.sh k8s --defaults \
  --persistence-mode dynamic \
  --storage-class <rwx-storage-class>

# Non-interactive deployment with pre-created claims
bash deploy.sh k8s --defaults \
  --persistence-mode existing \
  --existing-claim-prefix <claim-prefix>

# Add terminal to the default component set
bash deploy.sh k8s --components infrastructure,application,data-process,terminal

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

K8s deployments read runtime configuration from `deploy/env/.env`, the same file used by Docker. Before every deployment, existing values, comments, ordering, and old-only variables are preserved while assignments newly introduced by the current `deploy/env/.env.example` are appended. If `.env` is missing, the deploy script first reuses legacy `docker/.env`, then falls back to the current template. A readable template is required before deployment starts. Do not edit generated Helm values by hand; they are recreated from the merged `deploy/env/.env` and deployment options.

Config, Runtime, MCP, Northbound, and Data Process load every variable declared in `.env` through the backend-only `nexent-env` Secret, including newly added variables without a Helm mapping. Config and Runtime additionally load `deploy/env/monitoring.env` through `nexent-monitoring-env`. These scopes match the production Docker Compose configuration. Web and infrastructure do not reference either complete env Secret; they keep their service-specific environment configuration.

Internal MCP authentication uses `NEXENT_MCP_INTERNAL_TOKEN`. The deployment script carries an existing `TOKEN` assignment forward when the new key is missing. For direct Helm upgrades, move any existing `nexent-common.config.voiceService.token` override to `nexent-common.secrets.mcpInternalToken`. When `NEXENT_MCP_INTERNAL_TOKEN` is present in the deployment environment file, it takes precedence over the Helm value.

Environment precedence, from lowest to highest, is the existing ConfigMap, `.env`, `monitoring.env` where applicable, finalized deployment credentials, and explicit container environment settings. Kubernetes mode, namespace, SQL startup/checksum, selected MCP/sandbox images, and sandbox execution level remain deployment-controlled. Env files use the existing trusted Bash-compatible syntax: empty strings, quoting, JSON, substitutions, and multiline strings are preserved. Only variables assigned in the file are emitted; unrelated exported host variables are excluded.

Application Secret values are rendered after credentials are finalized and written atomically with mode `0600`. The chart exposes `nexent-common.envFiles.rootData` and `monitoringData` as Base64-encoded string mappings; both default to `{}` so direct Helm rendering works without generated env files. Editing `.env` takes effect on the next deployment, when the environment checksum replaces backend Pods. Fresh Secret maps also remove deleted variables. Generated values contain sensitive configuration and must stay outside Git and shared logs.

Ordinary backend configuration is injected through these file Secrets instead of being copied field by field into generated common values. The common ConfigMap and Chart values remain the fallback for omitted keys and direct Helm use. The runtime renderer retains timezone and Web's Northbound URL/upload limit, plus Redis URL and part-processor count because they also supply the runtime-state Redis fallback and derived worker concurrency. Deployment overrides, finalized credentials and infrastructure configuration keep their dedicated rendering paths.

When `--persistence-mode local` is used, Nexent renders static PVs with `hostPath` and `DirectoryOrCreate`; the chart does not pin these workloads to a node. Use this mode only on a single-node cluster so the Runtime and its maintenance Job see the same workspace. On multiple nodes, use `dynamic` or `existing` with actual shared RWX storage. Shared workspace data uses `/var/lib/nexent`, shared skills use `/var/lib/nexent-data/skills`, Web project configuration uses `/var/lib/nexent-data/project-config`, and service data uses `/var/lib/nexent-data/nexent-*` by default.

Config, Runtime, and Northbound use `/health/live` startup probes, while Web probes `/`, before their liveness and readiness probes become active. Each service waits 30 seconds before its first startup check; the following probe budget is five minutes (`periodSeconds: 5`, `failureThreshold: 60`) so cold starts and Python imports do not trigger a premature liveness restart. Operators can override each delay independently, for example with `--set nexent-runtime.probes.startup.initialDelaySeconds=60`.

Config and Data Process remain single-replica workloads. Runtime also defaults to one replica and retains the Kubernetes `Recreate` strategy. Web keeps its existing scaling controls, but project-configuration write consistency is supported only for the default single replica.

### Kubernetes SYSTEM Sandbox

Set `global.sandboxProvider: kubernetes` in this chart's `values.yaml` and deploy with the project script. Kubernetes SYSTEM creates one sandbox Pod per Runtime Pod on first use. Existing Agent sandbox policies at the `docker` level select the Kubernetes provider when this setting is enabled. Runtime replicas keep the normal offline maintenance sequence.

Set `global.sandboxNetworkPolicyVerified: true` after verifying that the cluster's CNI enforces the sandbox NetworkPolicy. Use shared RWX workspace storage, or set `global.sandboxSingleNodeDevelopment: true` for a single-node development cluster. The sandbox image configured for Nexent must be available to Kubernetes when the first Agent run needs it.

### Runtime Maintenance

Use `bash deploy.sh k8s` (or `--release-scope nexent`) to deploy or upgrade Runtime. The script holds a PostgreSQL session lock while it stops old business Pods, runs system bootstrap, and submits the Runtime maintenance Job. The Job uses the Management image configured for `nexent-config` and settles interrupted AgentOS executions in the maintenance transaction. The script activates the release after verifying the paused batch and its committed completion marker. Each Runtime Pod checks the same marker and renews only its own execution leases.

Before bootstrap, the script waits for each existing business Deployment to report zero replicas for its current generation and for its Pods to disappear. The maintenance Job independently checks both conditions for Runtime; an empty Pod list by itself does not confirm that the controller has applied the scale-to-zero request.

Reserve the database, Redis keyspace, and workspace for one Nexent application release. The script needs permission to exec into the PostgreSQL Deployment and manage the release's maintenance Job and namespaced RBAC. If bootstrap or maintenance fails, leave workloads paused and inspect the Jobs and their logs. To retry a failed Runtime maintenance Job after resolving the underlying problem, rerun the same application deployment settings and add `--release-scope nexent --retry-runtime-maintenance <UUID>` using the batch UUID from the failure. Keep the original target replica count and do not rotate credentials during the retry. Only the matching paused release can retry the batch, and only its failed Job is replaced. Do not activate Runtime using standalone `helm upgrade` or `kubectl scale`; those commands bypass the maintenance window. Runtime file logs are under `/mnt/nexent-data/logs/<pod-name>` inside its container.

If the maintenance Job succeeded but the final pre-activation check could not verify the PostgreSQL lock, the completion record alone does not authorize activation. Confirm that the release is still paused and no other deployment is in progress, address the connection failure, then rerun the normal application deployment with the same settings and without `--retry-runtime-maintenance`. This acquires a new lock and starts a new maintenance batch; the retry flag is only for failed Jobs.

Before pausing the release, the script also checks for unfinished bootstrap or maintenance Jobs and their Pods from an earlier attempt. A Job can still start work even if it has no Pod yet. If the check fails, inspect the reported Job or Pod and wait until the old work has stopped before rerunning deployment. The script does not delete the reported resource automatically. If the deployment lock is lost while synchronizing official skills, the script does not signal the bootstrap Job to start SQL.

### Fixed Runtime Replicas

To change the fixed Runtime count on an application release already using shared storage, edit `nexent-runtime.replicaCount` in this chart's `values.yaml` and run the deployment script in a maintenance window:

```bash
bash deploy.sh k8s --release-scope nexent --defaults
```

You can also set the count explicitly for a deployment:

```bash
bash deploy.sh k8s --release-scope nexent --defaults --runtime-replicas 3 \
  --persistence-mode dynamic --storage-class my-rwx-storage
```

An explicit `--runtime-replicas` takes precedence. Without it, a changed count in `values.yaml` takes precedence over the saved `runtimeReplicas` in `deploy/k8s/deploy.options`. Subsequent deployments reuse the saved count while the chart value is unchanged. For older saved options, the script treats `1` as the previous chart value. Use the release's current persistence settings. To roll back, set the count to `1` and deploy during a maintenance window. Each invocation stops business workloads while it runs bootstrap and maintenance. Changing the count does not migrate data or claims. No HPA or KEDA controller is created.

More than one Runtime replica requires `dynamic` with an explicit RWX-capable StorageClass, or `existing` with precreated PVCs. The deployment identity needs read access to the Runtime PVCs and their bound PVs. Before starting bootstrap writes, the script requires the workspace, skills, memory-plugin, logs, and trajectory volumes to be `Bound` with `ReadWriteMany` access and `Filesystem` volume mode. PVs with `spec.local` remain unsupported. A `hostPath` PV that meets these checks can be used for single-node deployments. For multi-node deployments, verify cross-node reads and writes on the backing storage. With existing storage, the workspace, skills, and logs claim names honor `--existing-claim-prefix`. The memory-plugin and trajectory claims use `nexent-memory-plugins` and `nexent-trajectory`.

Budget threads, database and Redis connections, object storage, and downstream model traffic for the total number of Runtime processes.

## Deploy Options

| Option | Description | Values |
|--------|-------------|--------|
| `--release-scope` | Helm release scope | `all` (default), `infrastructure`, or `nexent` |
| `--components` | Comma-separated deployment components | `infrastructure`, `application`, `data-process`, `terminal`, `monitoring` |
| `--port-policy` | Host exposure policy | `development` or `production` |
| `--image-source` | Image reference source | `general`, `mainland`, or `local-latest` |
| `--registry-profile` | Legacy registry profile option | `general` or `mainland`; maps to `--image-source` |
| `--monitoring-provider` | Remote provider when `monitoring` is selected | `otlp`, `phoenix`, `langfuse`, `langsmith` |
| `--use-local-config` | Reuse saved local deployment config | Flag |
| `--reconfigure` | Run interactive configuration using saved local config as defaults | Flag |
| `--config` | Open the interactive deployment configuration | Flag |
| `--is-mainland` | Legacy network location option | `Y` maps to `--image-source mainland`; `N` maps to `general` |
| `--version` | Application version | Version tag (auto-detected from `backend/contracts/constants/environment.py` if not set) |
| `--deployment-version` | Legacy deployment version | Both versions use `infrastructure,application`; `full` enables local authentication |
| `--persistence-mode` | Persistent volume mode | `local`, `dynamic`, or `existing`; default `local` |
| `--runtime-replicas` | Explicit override of the fixed Runtime replica count after offline maintenance | Positive integer |
| `--retry-runtime-maintenance` | Retry a paused Runtime maintenance batch | Batch UUID; use with `--release-scope nexent` |
| `--storage-class` | StorageClass for PV/PVC binding | StorageClass name; aliases `--storageclass`, `--storage-class-name`, `--sc` |
| `--local-path` | Base host path for local PVs except workspace | Path; default `/var/lib/nexent-data` |
| `--local-node-name` | Deprecated compatibility option | Ignored; local mode uses hostPath and does not require nodeAffinity |
| `--existing-claim-prefix` | Prefix for existing PVC names | Renders as `<prefix>-<component>` |

## Uninstall Options

| Option | Description | Values |
|--------|-------------|--------|
| `--release-scope` | Helm release scope; infrastructure-only removal is dependency protected | `all` (default), `infrastructure`, or `nexent` |
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

## Offline Image Package

Use the repository-level offline package builder when the target Kubernetes environment cannot pull images directly:

```bash
bash deploy/offline/build_offline_package.sh \
  --target k8s \
  --version v2.2.1 \
  --platform amd64 \
  --components infrastructure,application,data-process \
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
  --components infrastructure,application,data-process \
  --image-source general
```

For multi-node clusters, run `load-images.sh` on every node that may schedule Nexent Pods, or push the loaded images to an internal registry and deploy with matching image references.

## Deployment Components

The deployment script uses Bash TUI menus when running interactively. It first shows a component multi-select menu, then single-select menus for port policy and image source. Use `b`/Backspace to return to the previous TUI step and `q` to quit. `infrastructure` is required and is added automatically if omitted; `application` and `data-process` are selected by default and can be disabled for smaller deployments.

| Component | Services |
|-----------|----------|
| `infrastructure` | Elasticsearch, PostgreSQL, Redis, MinIO |
| `application` | config, runtime, mcp, northbound, web |
| `data-process` | nexent-data-process |
| `terminal` | OpenSSH terminal tool |
| `monitoring` | Optional monitoring chart; selecting it prompts for provider unless `--monitoring-provider` is passed |

`application` does not include `data-process`; it is a separate component even though it is selected by default. User and tenant features use the existing PostgreSQL service; full mode enables authentication independently of optional components.

## Port Policy

| Policy | Kubernetes behavior |
|--------|---------------------|
| `development` | Uses NodePort for Web and selected debug/internal services |
| `production` | Keeps internal services as ClusterIP and exposes the Web and northbound entrypoints |

## Deployment Workflow

The `apply` command performs the following steps:

1. **Select deployment components** - TUI multi-select or `--components`
2. **Select port policy and image source** - TUI/config/CLI arguments
3. **Render release-specific values** - Images, storage, SQL, and infrastructure Secret values
4. **Deploy infrastructure** - Install or upgrade `nexent-infrastructure` exactly once
5. **Wait for infrastructure** - Require Elasticsearch, PostgreSQL, Redis, and MinIO to be Ready
6. **Initialize Elasticsearch** - Validate or create the API key without patching Kubernetes resources
7. **Render application Secret values** - Put the API key only in the application-side Secret
8. **Deploy Nexent** - Install or upgrade `nexent` exactly once
9. **Wait for selected workloads** - Verify all selected application Deployments
10. **Synchronize official skills** - Verify and copy the bundled archives to the shared workspace PVC
11. **Create super admin user** - Initialize the admin account after local account migrations complete

If infrastructure readiness or Elasticsearch initialization fails, the infrastructure release is retained for retry and the Nexent release is not installed or upgraded.

### Independent Helm commands

The deployment script is the recommended entrypoint because it generates credentials and enforces dependency ordering. For operators that manage values externally, the two releases can be upgraded independently:

```bash
helm dependency update deploy/k8s/helm/nexent-infrastructure
helm upgrade --install nexent-infrastructure deploy/k8s/helm/nexent-infrastructure \
  --namespace nexent --create-namespace \
  -f /path/to/infrastructure-values.yaml

# Wait for all four infrastructure Deployments, then initialize the ES API key
bash deploy/k8s/init-elasticsearch.sh

helm dependency update deploy/k8s/helm/nexent
helm upgrade --install nexent deploy/k8s/helm/nexent \
  --namespace nexent \
  -f /path/to/application-values-with-es-api-key.yaml
```

The two values files must contain the same PostgreSQL and MinIO credentials. `ELASTICSEARCH_API_KEY` belongs only in the application values. Do not install both charts under one release name. Official skill archives are synchronized to the workspace PVC only by `deploy/k8s/deploy.sh`; direct Helm installations must initialize `/mnt/nexent/official-skills-zip` separately.

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
| Phoenix | http://localhost:30006 |

## Data Persistence

### Preserved Data

By default, `bash uninstall.sh k8s` removes the Helm release and preserves local PV data. It prompts before deleting the namespace or local PV contents. In non-interactive environments, both are preserved unless explicitly requested.

The following local PersistentVolumes can preserve data:

- `nexent-workspace-pv` - Shared user workspace mounted at `/mnt/nexent`
- `nexent-skills-pv` - Shared skills data mounted at `/mnt/nexent-data/skills`
- `nexent-project-config-pv` - Web names, localized customization, and logos mounted at `/mnt/nexent-data/project-config`
- `nexent-elasticsearch-pv` - Search index data
- `nexent-postgresql-pv` - Relational database data
- `nexent-redis-pv` - Cache data
- `nexent-minio-pv` - Object storage data
- `nexent-trajectory-pv` - Local trajectory archives
- Monitoring PVs such as Phoenix and Langfuse data when those providers are selected

### Deleted Data

Use `--delete-local-data true` or `--remove-local-data` to delete known Nexent local PV data under `/var/lib/nexent`, `/var/lib/nexent-data/skills`, `/var/lib/nexent-data/project-config`, and `/var/lib/nexent-data/nexent-*`. `delete-all` deletes the namespace and local PV data by default; add `--keep-local-data` to preserve local volume contents.

## Services

### Application Services

| Service | Description | Replicas |
|---------|-------------|----------|
| nexent-config | Configuration service | 1 |
| nexent-runtime | Runtime service | 1 |
| nexent-mcp | MCP container service | 1 |
| nexent-gateway | Northbound API service | 1 |
| nexent-web | Web frontend | 1 |
| nexent-data-process | Data processing service | 1 |

### Infrastructure Services

| Service | Description |
|---------|-------------|
| nexent-elasticsearch | Search and indexing engine |
| nexent-postgresql | Relational database |
| nexent-redis | Caching layer |
| nexent-minio | S3-compatible object storage |

### Optional Services

| Service | Description | Enabled By |
|---------|-------------|------------|
| nexent-openssh-server | SSH terminal for AI agents | `--set services.openssh.enabled=true` |
| nexent-monitoring | OpenTelemetry Collector and optional observability backend | `--set nexent-monitoring.enabled=true` |

### Monitoring

Docker and Kubernetes application deployments capture traces to the persistent
`/mnt/nexent-data/trajectory` directory by default. Set
`LOCAL_FILE_MONITORING_ENABLED=false` in `deploy/env/.env` and rerun the deployment
script to stop new local capture. Existing local traces remain available in
the observability center. For direct Helm deployments, use
`--set global.monitoring.localFileEnabled=false` to turn off local capture and
`--set global.monitoring.trajectoryReadEnabled=true` to keep historical reads.

To export new traces to a third-party provider, include the `monitoring`
component and select a provider in the deployment script. Local capture keeps its
own setting. With both enabled, Runtime records full traces locally and applies
the existing remote sampling and content settings to the third-party export.
Omit the `monitoring` component to turn off remote export.

If a saved deployment profile used the former `local_file` option, the script
loads it with remote export off and uses `LOCAL_FILE_MONITORING_ENABLED` for
local capture. For direct Helm upgrades from `global.monitoring.provider=local_file`,
set `global.monitoring.provider=otlp`, `global.monitoring.enabled=false`,
`nexent-monitoring.enabled=false`, and `global.monitoring.localFileEnabled=true`.

```bash
bash deploy.sh docker --components infrastructure,application,data-process,monitoring --monitoring-provider phoenix
bash deploy.sh k8s --components infrastructure,application,data-process,monitoring --monitoring-provider phoenix
```

The optional monitoring chart supports `otlp` for the Collector with its debug
exporter, `phoenix`, `langfuse`, and `langsmith`. For direct Helm deployments,
enable `nexent-monitoring` and select a provider. LangSmith also requires an API key.

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
| `global.sharedStorage.trajectory.size` | Trajectory PVC size | `50Gi` |
| `global.sharedStorage.trajectory.localPath` | Host path for trajectory archives | `/var/lib/nexent-data/trajectory` |
| `global.sharedStorage.trajectory.existingClaim` | Existing trajectory PVC in existing-storage mode | `nexent-trajectory` |
| `global.monitoring.trajectoryRootDir` | Runtime mount and trajectory directory | `/mnt/nexent-data/trajectory` |
| `global.sharedStorage.projectConfig.size` | Web project configuration PVC size | `1Gi` |
| `global.sharedStorage.projectConfig.localPath` | Host path for Web project configuration | `/var/lib/nexent-data/project-config` |
| `global.sharedStorage.projectConfig.existingClaim` | Existing project configuration PVC | `nexent-project-config` |
| `nexent-web.config.fileUploadSizeLimit` | File upload limit synchronized into persisted locale configuration at Web startup | `10` |
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
kubectl delete pv nexent-workspace-pv nexent-skills-pv nexent-project-config-pv nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv
```

Local authentication requires `nexent-common.secrets.jwtSecret`. The deploy script generates or reuses it. [Migration runbook](../../../sql/tools/supabase_to_postgres/README.md) covers historical credentials and cutover.
