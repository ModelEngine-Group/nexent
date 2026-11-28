# Kubernetes Installation & Deployment

## Environment Setup

### 🎯 Prerequisites

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU**  | 4 cores | 8 cores |
| **RAM**  | 16 GiB | 64 GiB |
| **Disk** | 100 GiB | 200 GiB |
| **Architecture** | x86_64 / ARM64 | Images matching the node architecture |
| **Software** | Kubernetes 1.24+, Helm 3+, Bash 4+, and kubectl configured for cluster access | Kubernetes 1.28+ |

> **💡 Note**: The recommended configuration is suitable for a complete deployment. Actual resource requirements also depend on the replica count, knowledge-base size, and number of concurrent agents. Set requests and limits in production according to load-test results.

### Prepare a Kubernetes cluster

- **Existing cluster.** Get a kubeconfig with the permissions needed to deploy Nexent from your cluster administrator or cloud provider. Configure it on the deployment host.
- **Local single-node trial.** Choose a driver for your operating system, install minikube, and start a cluster. If the node runs in a VM, allocate the CPU, memory, and disk space listed above. [Official minikube getting started guide](https://minikube.sigs.k8s.io/docs/start/)
- **Self-managed Linux cluster.** Prepare a CRI-compatible container runtime such as containerd on each node and install kubeadm and kubelet. Initialize the control plane, install a Pod network plugin, and join worker nodes as needed. [Install kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/) · [Create a cluster with kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/)

### Install management tools and verify the environment

On the host where you will run the Nexent deployment script, use Bash 4 or later and install versions of kubectl and Helm compatible with your cluster. Use kubectl to access the cluster and Helm to install the Nexent charts. [Official Kubernetes tools installation guide](https://kubernetes.io/docs/tasks/tools/) · [Official Helm installation guide](https://helm.sh/docs/intro/install/)

```bash
bash --version
kubectl version --client
helm version --short
kubectl config current-context
kubectl cluster-info
kubectl get nodes
kubectl get storageclass
```

Confirm that the current context points to the intended cluster, the API server is reachable, and the nodes that will run Nexent report `Ready`. A fresh installation dynamically provisions volumes through the cluster's default StorageClass. Shared storage needs `ReadWriteMany` (RWX) access. If the cluster has no suitable default, pass `--storage-class <storage-class-name>`. For a single-node test, you can use `--persistence-mode local`. See [Data Persistence](#data-persistence) for other storage options.

## 🚀 Quick Start

- [Online Deployment](#online-deployment)
- [Offline Deployment](#offline-deployment)

### Online Deployment

#### 1. Clone and Navigate

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
```

For a new multi-node cluster, choose storage that supports reads and writes from different nodes. Local trace capture is enabled by default. To use it across nodes, copy `deploy/env/.env.example` to a new `deploy/env/.env` and set `TRAJECTORY_STORAGE_MODE=shared_directory` before the first startup. For storage requirements and a three-replica installation, see [Deploy Multiple Runtime Replicas](#deploy-multiple-runtime-replicas).

#### 2. Deployment

Run the deployment script:

```bash
bash deploy.sh k8s
```

The script installs two Helm releases in the `nexent` namespace. It installs `nexent-infrastructure` first, waits for Elasticsearch, PostgreSQL, Redis, and MinIO to become ready, and initializes the Elasticsearch API key. It then deploys the `nexent` application release. On first installation, a bootstrap Job runs database migrations and initializes system agents before the application services start. The deployment account needs permission to manage workloads and Jobs in the namespace and run `kubectl exec` in the PostgreSQL and Elasticsearch Pods. Choose the release scope for your deployment.

```bash
bash deploy.sh k8s --release-scope all
bash deploy.sh k8s --release-scope infrastructure
bash deploy.sh k8s --release-scope nexent
```

Deploying only `nexent` requires the infrastructure release and all four of its services to be ready. Before uninstalling infrastructure on its own, uninstall the `nexent` application release. If a legacy single `nexent` release still owns infrastructure resources, the script stops. The two-release layout requires a fresh installation.

The script opens an interactive Bash menu. Use the arrow keys or `j/k` to move, Space to toggle items, Enter to confirm, `b` or Backspace to return to the previous step, and `q` to quit.

**Deployment components**

| Option | Default | What it deploys |
| --- | --- | --- |
| `infrastructure` | Required | Elasticsearch, PostgreSQL, Redis, and MinIO |
| `application` | Selected | Gateway, Management, Runtime, MCP, Web, and Ops |
| `data-process` | Selected | Data processing service |
| `terminal` | Optional | OpenSSH terminal |
| `monitoring` | Optional | Exports telemetry to the selected provider |

The `application` component also prepares the agent sandbox image configuration. Runtime uses a shared workspace for uploads and generated files and syncs artifacts that need to be retained to MinIO.

**Port policy**

The default `development` policy exposes Web, Gateway, Ops, and selected internal services through NodePorts for debugging. The `production` policy uses ClusterIP for internal services such as Management, Runtime, and infrastructure. Web, Gateway, and Ops still have NodePorts. The port mapping table below lists the defaults.

**Image source**

The default, `general`, uses standard public registries. Use `mainland` for mainland China mirrors. With `local-latest`, Nexent uses local application images tagged `latest`. Without a private registry prefix, the pull policy is `Never`. Import the images on every node that might run the application Pods.

Docker and Kubernetes share `deploy/env/.env`. Before each deployment, the script preserves existing values, comments, and legacy variables and appends new variables from `deploy/env/.env.example`. If `.env` is missing, the script first looks for the legacy `docker/.env`, then falls back to the current template. The installer requires a readable `.env.example`.

Run `bash deploy.sh k8s --defaults` to skip the interactive menu. The script reads component, storage, and other settings from `deploy/k8s/deploy.options` and uses built-in defaults for missing options. The application version comes from `VERSION` in the current repository or deployment package. Use `--version` to override it. The script ignores application versions saved in older options files.

#### ⚠️ Important Notes

1️⃣ **When deploying v1.8.0 or later for the first time**, Nexent creates the `suadmin@nexent.com` super administrator account with the default password `Nexent@123`, without prompting, and displays it in the terminal after successful creation. Override it before the first deployment with `NEXENT_SUPER_ADMIN_PASSWORD` in `deploy/env/.env`; non-interactive creation displays the effective password. An offline package launched with `--config` instead prompts for and confirms the password, and that input takes precedence without being displayed.

2️⃣ For historical account upgrades, administrator failures and data recovery, use the [consolidated migration runbook](https://github.com/ModelEngine-Group/nexent/blob/develop/deploy/sql/tools/supabase_to_postgres/README.md). Preserve the original account ID and tenant ownership; recover consistent data as described there.

### Offline Deployment

When the target cluster cannot access public image registries, download a prebuilt offline deployment package from GitHub Actions:

1. Sign in to GitHub and open [Build Offline Deployment Package](https://github.com/ModelEngine-Group/nexent/actions/workflows/build-offline-package.yml).
2. Select a successful run for the required version and download `nexent-<version>-<platform>.zip` matching the cluster node architecture from **Artifacts**.
3. Copy the archive to a management host that can access the target cluster and extract it. Workflow artifacts are retained for 30 days; if one has expired, ask a maintainer to rerun the workflow.

Replace the example filename with the package you downloaded, then extract it and enter the deployment directory.

```bash
unzip 'nexent-<version>-amd64.zip' -d nexent
cd nexent
```

A single-node cluster backed by the Docker container runtime can load and deploy the images directly:

```bash
bash deploy.sh --load-images k8s
```

If the management host still has a previously deployed offline package, use `--reuse-from` to reuse its environment configuration and Kubernetes deployment options:

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  k8s
```

The directory must be the root of the extracted previous package and contain `deploy/env/.env`. The script preserves the old environment values, appends new variables from the current template, and reuses existing `monitoring.env` and Kubernetes deployment options. When reusing settings, run the command from the new package directory. Check that the application version shown in the terminal matches the packaged images. You can combine `--reuse-from` with `--config`, `--defaults`, or `--push-images`.

For other single-node and multi-node clusters, push images to an internal registry accessible to the cluster, or import them with the container runtime's tooling on every node that may run Nexent Pods:

```bash
bash deploy.sh \
  --push-images \
  --image-registry-prefix registry.example.com/nexent \
  k8s
```

The offline package lists its components and images in `manifest.yaml`. The entry point reuses saved options or built-in defaults. Add `--config` to choose different settings. Before enabling an optional component, confirm that the cluster can pull its images or that the nodes already have them.

### Access Your Installation

Check the releases, workloads, and assigned NodePorts from the deployment host. After a default installation, both Helm releases should show `deployed`, and the `READY` column should show the desired number of replicas for each application you selected.

```bash
helm list -n nexent
kubectl get deployments,svc -n nexent
```

The default Web address is `http://<node-address>:30000`. For a temporary local check, run the following command and open `http://localhost:3000` on the same machine.

```bash
kubectl -n nexent port-forward svc/nexent-web 3000:3000
```

**Use HTTPS to sign in from another machine.** Web sets the `Secure` attribute on session cookies by default, so a browser connecting to a remote node over HTTP may not retain the session. Use the domain for your existing HTTPS endpoint, or enable the built-in Nginx proxy at deployment time. Its default HTTPS NodePort is `31000`. To use an existing certificate, replace the paths below with the PEM certificate and private key on the deployment host. Then open `https://<domain-on-certificate>:31000`.

```bash
bash deploy.sh k8s --defaults --https-mode custom \
  --https-cert-file /path/to/fullchain.pem --https-key-file /path/to/private.key
```

Sign in as `suadmin@nexent.com` with the password set during the first deployment. Under **Tenant Resources**, create a tenant and its administrator. Sign in as the tenant administrator to configure models or agents. See the [User Guide](../user-guide/home-page).

## 🏗️ Service Architecture

Helm charts deploy the following Nexent services.

**Application Services**

| Service | Description | Default Port |
|---------|-------------|--------------|
| nexent-config | Configuration and management API | 5010 |
| nexent-runtime | Agent runtime API | 5014 |
| nexent-mcp | MCP management and tool service | 5011 |
| nexent-gateway | Entry point for the northbound API and Web requests | 5013 |
| nexent-ops | Operations API for runtime metrics and historical traces | 5016 |
| nexent-web | Web frontend | 3000 |
| nexent-data-process | Data processing service | 5012 |

**Infrastructure Services**

| Service | Description |
|---------|-------------|
| nexent-elasticsearch | Search and indexing engine |
| nexent-postgresql | Relational database |
| nexent-redis | Cache, distributed locks, and task message broker |
| nexent-minio | S3-compatible object storage |

**Optional Services**

| Service | Description |
|---------|-------------|
| nexent-openssh-server | SSH terminal for AI agents |
| nexent-otel-collector | OpenTelemetry Collector, deployed when `monitoring` is enabled |
| nexent-nginx | Reverse proxy, deployed when built-in HTTPS is enabled |

## 🔌 Port Mapping

| Service | Internal Port | NodePort | Description |
|---------|---------------|----------|-------------|
| Web Interface | 3000 | 30000 | Main application access |
| HTTPS endpoint | 3000 | 31000 | Nginx accepts TLS connections when built-in HTTPS is enabled |
| Gateway | 5013 | 30013 | Northbound API |
| Ops | 5016 | 30016 | Operations service |
| SSH Server | 22 | 30022 | Available when the terminal component is enabled |

For internal service communication, services use Kubernetes internal DNS (e.g., `http://nexent-config:5010`).

## Data Persistence

Run the deployment command from the repository root and choose the mode that matches your storage.

| Available storage | Deployment command and behavior |
| --- | --- |
| Default StorageClass supports RWX | Run `bash deploy.sh k8s --defaults`. A fresh installation uses `dynamic`, and Kubernetes provisions a volume for each claim. |
| A specific StorageClass supports dynamic provisioning | Run `bash deploy.sh k8s --defaults --persistence-mode dynamic --storage-class my-rwx-storage`. Replace the example name with your storage class. |
| Host directories on a single node | Run `bash deploy.sh k8s --defaults --persistence-mode local`. The chart creates static PVs backed by `hostPath`. |
| The required PVCs already exist | Run `bash deploy.sh k8s --defaults --persistence-mode existing`. Check that the claim names and access modes match the deployment configuration. |

On subsequent deployments, an explicit `--persistence-mode` overrides the mode saved in `deploy/k8s/deploy.options`. Keep the original storage settings for existing deployments so services continue to use the same data. When you use Helm directly to upgrade a release backed by static volumes, retain its `local` settings.

The following paths are the defaults for `local` mode.

| Data Type | PersistentVolume | Default Host Path |
|-----------|------------------|-------------------|
| Elasticsearch | nexent-elasticsearch-pv | `/var/lib/nexent-data/nexent-elasticsearch` |
| PostgreSQL | nexent-postgresql-pv | `/var/lib/nexent-data/nexent-postgresql` |
| Redis | nexent-redis-pv | `/var/lib/nexent-data/nexent-redis` |
| MinIO | nexent-minio-pv | `/var/lib/nexent-data/nexent-minio` |
| Shared workspace | nexent-workspace-pv | `/var/lib/nexent` |
| Shared skills | nexent-skills-pv | `/var/lib/nexent-data/skills` |
| Memory plugins | nexent-memory-plugins-pv | `/var/lib/nexent-data/memory-provider-plugins` |
| Service logs | nexent-logs-pv | `/var/lib/nexent-data/logs` |
| Local traces | nexent-trajectory-pv | `/var/lib/nexent-data/trajectory` |
| Web project configuration | nexent-project-config-pv | `/var/lib/nexent-data/project-config` |

By default, `nexent-workspace` requests 10 GiB of `ReadWriteMany` storage. Application services use it to exchange inputs and outputs during a run. On multi-node clusters, check that Pods on different nodes can read and write the same files.

### Deploy Multiple Runtime Replicas

Runtime starts with one replica. To handle more concurrent work, set a fixed count with `--runtime-replicas`. This example installs three replicas on a new cluster. Replace `my-rwx-storage` with a StorageClass that supports shared reads and writes across nodes. Before the first startup, set the trace storage mode if you plan to capture local traces across nodes. See [Monitoring Configuration](#monitoring-configuration).

```bash
bash deploy.sh k8s --defaults --runtime-replicas 3 \
  --persistence-mode dynamic --storage-class my-rwx-storage
kubectl -n nexent rollout status deployment/nexent-runtime
kubectl -n nexent get deployment nexent-runtime
```

For multiple replicas, use a dynamic StorageClass that supports RWX or pre-create shared PVCs and use `existing` mode. You can omit `--storage-class` if the default StorageClass supports RWX. The deployment account must be able to read the five PVCs below and their bound PVs. The script checks that both the claims and volumes are `Bound`, include `ReadWriteMany`, and use the `Filesystem` volume mode. It rejects PVs with `spec.local`.

| Shared data | Default PVCs |
| --- | --- |
| Workspace, skills, logs | `nexent-workspace`, `nexent-skills`, `nexent-logs` |
| Memory plugins, traces | `nexent-memory-plugins`, `nexent-trajectory` |

To change the replica count on an existing installation, keep its storage settings and run `bash deploy.sh k8s --defaults --release-scope nexent --runtime-replicas 3` during a maintenance window with no active tasks. The standard deployment pauses the application Pods, runs bootstrap, and starts the configured replicas. Runtime uses the `Recreate` strategy and may be briefly unavailable. Set the count to `1` to return to one replica.

For a healthy, initialized application where only the replica count is changing, you can add `--direct-upgrade` to the same command to skip the application-wide pause and bootstrap Job. Use the standard deployment flow for a first installation, a paused application, reinitialization of system agents, or an upgrade with incompatible database changes.

### Use Kubernetes SYSTEM Sandboxes

The Runtime replica count and sandbox provider are independent settings. The default provider is `docker`. To use Kubernetes Pods for SYSTEM sandbox tasks, first verify that the cluster CNI blocks traffic denied by NetworkPolicy and that the nodes can pull the sandbox image.

Set `sandboxProvider` to `kubernetes` in the existing `global` section of `deploy/k8s/helm/nexent/values.yaml`. Once you have verified the network policy, set `sandboxNetworkPolicyVerified` to `true` and run the deployment script. Use shared RWX storage for the workspace. For single-node development with a local workspace, you can explicitly set `global.sandboxSingleNodeDevelopment: true`. Multiple Runtime replicas still require the storage described above.

Each Runtime Pod creates its own sandbox Pod the first time it executes a task that needs a SYSTEM sandbox. After running an agent that uses the sandbox, list the Pods it created.

```bash
kubectl -n nexent get pods -l nexent.ai/sandbox=system
```

### Uninstall Kubernetes Deployment

Run `bash uninstall.sh k8s` from the repository root to remove the application release followed by the infrastructure release. In interactive mode, the script asks whether to delete dynamic PVCs and defaults to keeping them. The following command keeps dynamic PVCs, the namespace, and local data.

```bash
bash uninstall.sh k8s --delete-pvc false --keep-namespace --keep-local-data
```

Add `--release-scope nexent` to remove only the application. To remove only infrastructure, confirm that the application release has been uninstalled, then use `--release-scope infrastructure`.

| Resource | Option and effect |
| --- | --- |
| Dynamic PVCs to keep | The default, `--delete-pvc false`, retains dynamic PVCs for the selected releases and keeps their namespace, even with `delete` or `delete-all`. If an older release manifest lacks the PVC retention policy, the script stops. First upgrade that release with the current chart and its original storage settings, then uninstall. |
| Dynamic PVCs to delete | `bash uninstall.sh k8s --delete-pvc true --keep-namespace` deletes the dynamic PVCs belonging to the selected releases. The bound PV's reclaim policy determines what happens to the underlying data. A `Delete` policy may delete the data as well. |
| Local hostPath data | With `local` storage, `--delete-local-data true` removes host directories managed by the deployment script. Use `--keep-local-data` to keep them. By default, `delete-all` requests deletion of the namespace and local data. |

Use `--keep-namespace` explicitly to retain pre-created PVCs or other resources in the same namespace. The compatibility options `--delete-data` and `--delete-volumes` control cleanup after a failed Helm uninstall. Use `--delete-pvc` to control dynamic PVC deletion.

## 🔧 Deployment Commands

```bash
# Deploy with interactive prompts
bash deploy.sh k8s

# Upgrade only infrastructure or only the application release
bash deploy.sh k8s --release-scope infrastructure
bash deploy.sh k8s --release-scope nexent

# Non-interactive deployment with the default component set
bash deploy.sh k8s --defaults --components infrastructure,application,data-process --port-policy development --image-source general

# Add the terminal tool to the default component set
bash deploy.sh k8s --components infrastructure,application,data-process,terminal

# Deploy with mainland China image sources
bash deploy.sh k8s --image-source mainland

# Use local latest images
bash deploy.sh k8s --image-source local-latest

# Select a StorageClass using the --sc alias
bash deploy.sh k8s --persistence-mode dynamic --sc fast-storage
```

## 🔧 Advanced Configuration

### Use an Uploaded MCP Image

To upload a custom MCP image through the UI, first push the image to a registry that the cluster can reach, or preload it on every node that may run MCP Pods. In `deploy/env/.env`, set `ENABLE_UPLOAD_IMAGE=true` and use `NEXENT_MCP_KUBERNETES_PRELOADED_IMAGES` to map the SHA-256 of the original tar file to its image reference. After redeployment, the Config service uses the mapping when it creates an MCP Pod. For an example, see [Uploading an image on Kubernetes](../user-guide/resource-repository/mcp-repository#uploading-an-image-on-kubernetes).

### Monitoring Configuration

#### View Local Traces in the Observability Center

The installer enables local trace capture when you deploy the `application` component. It reads `LOCAL_FILE_MONITORING_ENABLED` from `deploy/env/.env` (default `true`) and writes `TRAJECTORY_READ_ENABLED=true` to `deploy/env/monitoring.env` when capture is enabled. The default component selection includes everything needed for the built-in Observability Center.

1. Check that Runtime and Ops are ready and that the trajectory PVC is `Bound`. The default namespace is `nexent`.

   ```bash
   kubectl -n nexent get deployment nexent-runtime nexent-ops
   kubectl -n nexent get pvc nexent-trajectory
   ```

2. Verify that Config, Runtime, and Ops mount the same trace storage. The default container path is `/mnt/nexent-data/trajectory`. For a multi-node deployment, set `TRAJECTORY_STORAGE_MODE=shared_directory` in `deploy/env/.env` before the first capture. Use a shared filesystem that supports cross-node file locking and atomic replacement. An existing trace directory checks the storage mode registered when it was created. Plan for data migration when moving from a single node.
3. Complete a conversation turn with an agent and copy its conversation ID. With an operations or super administrator account that can access the **Observability Center**, look up the ID and open the call timeline for that turn. See the [Observability Center guide](../user-guide/observability).

To stop capturing new conversations while keeping existing traces available, set `LOCAL_FILE_MONITORING_ENABLED=false` in `deploy/env/.env`, keep `TRAJECTORY_READ_ENABLED=true` in `deploy/env/monitoring.env`, and redeploy with the original options. If you manage the Helm release directly, use `global.monitoring.localFileEnabled: false` and `global.monitoring.trajectoryReadEnabled: true`.

#### Export Traces to a Third-Party Platform

To also send traces to a third-party platform, add the `monitoring` component and choose a provider. The script generates the Helm configuration and installs the Collector. Local capture retains its own setting. The following example adds Phoenix to the default components.

```bash
bash deploy.sh k8s --components infrastructure,application,data-process,monitoring --monitoring-provider phoenix
```

| Provider | Where to access the data |
| --- | --- |
| `otlp` | Starts the OpenTelemetry Collector. Its default debug exporter writes to the Collector logs. |
| `phoenix` | Deploys Phoenix. Open the dashboard on port `30006` of a reachable node. |
| `langfuse` | Deploys Langfuse. Open the dashboard on port `30001` of a reachable node. |
| `langsmith` | Sends traces to hosted LangSmith. Set `LANGSMITH_API_KEY` in `deploy/env/monitoring.env` before deployment and optionally set the project with `LANGSMITH_PROJECT`. |

To change the dashboard NodePort, set `K8S_PHOENIX_NODE_PORT` or `K8S_LANGFUSE_NODE_PORT` in `deploy/env/monitoring.env`. For remote access, set `MONITORING_DASHBOARD_URL` to an address the user's browser can reach. For Langfuse, also check `K8S_LANGFUSE_NEXTAUTH_URL`. After deployment, inspect the Collector logs with `kubectl -n nexent logs deployment/nexent-otel-collector`.

### OAuth Login Configuration

OAuth login uses local Nexent accounts. When using the installer, enter the provider credentials in `deploy/env/.env` and set the callback base URL to the Web address users can reach from their browsers. This example configures GitHub login.

```dotenv
OAUTH_CALLBACK_BASE_URL=https://nexent.example.com
GITHUB_OAUTH_CLIENT_ID=your_github_client_id
GITHUB_OAUTH_CLIENT_SECRET=your_github_client_secret
OAUTH_LOGIN_MODE=button
```

Save the file and redeploy the application with its original options. If you manage the Helm release directly, use the corresponding values below.

| Value | Environment variable | Description |
|-------|----------------------|-------------|
| `nexent-common.config.oauth.callbackBaseUrl` | `OAUTH_CALLBACK_BASE_URL` | Web entry URL; the callback path is appended automatically |
| `nexent-common.config.oauth.githubClientId` | `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth Client ID |
| `nexent-common.config.oauth.githubClientSecret` | `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth Client Secret |
| `nexent-common.config.oauth.gdeUrl` | `GDE_URL` | GDE OAuth service URL |
| `nexent-common.config.oauth.gdeClientId` | `GDE_OAUTH_CLIENT_ID` | GDE OAuth Client ID |
| `nexent-common.config.oauth.gdeClientSecret` | `GDE_OAUTH_CLIENT_SECRET` | GDE OAuth Client Secret |
| `nexent-common.config.oauth.enableWechat` | `ENABLE_WECHAT_OAUTH` | Enables WeChat OAuth |
| `nexent-common.config.oauth.wechatClientId` | `WECHAT_OAUTH_APP_ID` | WeChat App ID |
| `nexent-common.config.oauth.wechatClientSecret` | `WECHAT_OAUTH_APP_SECRET` | WeChat App Secret |
| `nexent-common.config.oauth.sslVerify` | `OAUTH_SSL_VERIFY` | Whether to verify provider TLS certificates |
| `nexent-common.config.oauth.caBundle` | `OAUTH_CA_BUNDLE` | Custom CA bundle path |
| `nexent-common.config.oauth.loginMode` | `OAUTH_LOGIN_MODE` | `disabled`, `button`, or `force` |

`loginMode` defaults to `button`. In `force` mode, OAuth is disabled when no provider is available, while multiple providers fall back to login buttons. CAS `force` mode takes precedence over OAuth auto login.

Provider callback URLs:

| Provider | Callback URL |
|----------|--------------|
| GitHub | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| WeChat | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

For local NodePort, a GitHub callback example is `http://localhost:30000/api/user/oauth/callback?provider=github`. In production, use a public HTTPS domain and register the exact same URL in the OAuth provider console.

### CAS Login Configuration

CAS single sign-on uses local Nexent accounts. When using the installer, enter the CAS server address and the browser-accessible Nexent Web address in `deploy/env/.env`. Omit the trailing `/` from both URLs.

```dotenv
CAS_ENABLED=true
CAS_SERVER_URL=https://cas.example.com/cas
CAS_CALLBACK_BASE_URL=https://nexent.example.com
CAS_LOGIN_MODE=force
CAS_LOGOUT_URL=/logout
```

Save the file and redeploy the application with its original options. If you manage the Helm release directly, use the corresponding values below.

| Value | Environment variable | Description |
|-------|----------------------|-------------|
| `nexent-common.config.cas.enabled` | `CAS_ENABLED` | Enables CAS |
| `nexent-common.config.cas.serverUrl` | `CAS_SERVER_URL` | CAS Server root URL |
| `nexent-common.config.cas.validatePath` | `CAS_VALIDATE_PATH` | serviceValidate path, default `/p3/serviceValidate` |
| `nexent-common.config.cas.callbackBaseUrl` | `CAS_CALLBACK_BASE_URL` | Web entry URL; CAS callback paths are appended automatically |
| `nexent-common.config.cas.loginMode` | `CAS_LOGIN_MODE` | `disabled`, `button`, or `force` |
| `nexent-common.config.cas.userAttribute` | `CAS_USER_ATTRIBUTE` | User identifier attribute. Empty means use `<cas:user>` |
| `nexent-common.config.cas.emailAttribute` | `CAS_EMAIL_ATTRIBUTE` | Email attribute |
| `nexent-common.config.cas.roleAttribute` | `CAS_ROLE_ATTRIBUTE` | Role attribute |
| `nexent-common.config.cas.defaultRole` | `CAS_DEFAULT_ROLE` | Default Nexent role when the CAS role is missing, empty, or unsupported; default `USER` |
| `nexent-common.config.cas.tenantAttribute` | `CAS_TENANT_ATTRIBUTE` | Tenant attribute |
| `nexent-common.config.cas.defaultTenantId` | `CAS_DEFAULT_TENANT_ID` | Default tenant when CAS omits the tenant attribute or returns it empty |
| `nexent-common.config.cas.roleMapJson` | `CAS_ROLE_MAP_JSON` | JSON mapping from CAS roles to Nexent roles |
| `nexent-common.config.cas.sessionMaxAgeSeconds` | `CAS_SESSION_MAX_AGE_SECONDS` | Maximum local CAS session lifetime |
| `nexent-common.config.cas.localSessionMaxAgeSeconds` | `LOCAL_SESSION_MAX_AGE_SECONDS` | Nexent local session lifetime |
| `nexent-common.config.cas.heartbeatUrl` | `CAS_HEARTBEAT_URL` | Activity-driven CAS Server heartbeat GET URL; empty disables heartbeat |
| `nexent-common.config.cas.heartbeatIntervalSeconds` | `CAS_HEARTBEAT_INTERVAL_SECONDS` | Minimum heartbeat interval for active CAS users, default 300 seconds |
| `nexent-common.config.cas.heartbeatCookieName` | `CAS_HEARTBEAT_COOKIE_NAME` | Readable browser Cookie copied to the `X-Auth-Token` heartbeat header |
| `nexent-common.config.cas.renewBeforeSeconds` | `CAS_RENEW_BEFORE_SECONDS` | Trigger silent renewal within this many seconds before expiry |
| `nexent-common.config.cas.renewTimeoutSeconds` | `CAS_RENEW_TIMEOUT_SECONDS` | Silent renewal timeout |
| `nexent-common.config.cas.syntheticEmailDomain` | `CAS_SYNTHETIC_EMAIL_DOMAIN` | Domain used when CAS does not return an email |
| `nexent-common.config.cas.logoutUrl` | `CAS_LOGOUT_URL` | CAS logout URL. Empty means Nexent logout will not call the CAS Server logout endpoint |
| `nexent-common.config.cas.sslVerify` | `CAS_SSL_VERIFY` | Whether to verify CAS Server TLS certificates |
| `nexent-common.config.cas.caBundle` | `CAS_CA_BUNDLE` | Custom CA bundle path |

CAS heartbeat runs only for CAS users with a valid local session and visible-page activity. The first activity sends a GET immediately, then browser tabs share the configured minimum interval. A readable configured Cookie is sent as `X-Auth-Token: <cookie-name>=<cookie-value>`; if it cannot be read, the request is sent without the header. Because the browser calls the heartbeat URL directly, the endpoint must allow the Nexent origin, GET, OPTIONS, and `X-Auth-Token` through CORS. Heartbeat failures do not log the user out or refresh the local JWT.

Common CAS URLs:

| Purpose | URL |
|---------|-----|
| Nexent login entry | `{CAS_CALLBACK_BASE_URL}/api/user/cas/login?redirect=/` |
| CAS service callback | `{CAS_CALLBACK_BASE_URL}/api/user/cas/callback` |
| CAS silent renewal callback | `{CAS_CALLBACK_BASE_URL}/api/user/cas/renew_callback` |
| CAS single logout callback | `POST {CAS_CALLBACK_BASE_URL}/api/user/cas/logout_callback` |

For Apereo CAS JSON Service Registry, create a service registration file such as `Nexent-10001.json` in the service registry directory configured by your CAS deployment. The `id` must be globally unique. This is a local NodePort example:

```json
{
  "@class": "org.apereo.cas.services.RegexRegisteredService",
  "serviceId": "http://localhost:30000.*",
  "name": "Nexent CAS Client",
  "id": 10001,
  "description": "Nexent CAS SSO client",
  "evaluationOrder": 1,
  "logoutType": "BACK_CHANNEL",
  "logoutUrl": "http://localhost:30000/api/user/cas/logout_callback"
}
```

In production, keep `CAS_SSL_VERIFY=true`; for self-signed certificates, prefer `CAS_CA_BUNDLE` and only use `CAS_SSL_VERIFY=false` for local testing.

#### CAS Integration with ModelEngine

When integrating with ModelEngine through the CAS protocol, use a values file to configure Nexent. This avoids complex command-line escaping for `CAS_ROLE_MAP_JSON`.

Create `cas-modelengine-values.yaml`:

```yaml
nexent-common:
  config:
    cas:
      enabled: true
      serverUrl: "https://<ModelEngine IP>:5443/SSOSvr"
      validatePath: "/p3/serviceValidate"
      callbackBaseUrl: "http://<Nexent IP>:30000"
      loginMode: "force"
      userAttribute: "userName"
      emailAttribute: "email"
      roleAttribute: "userType"
      defaultRole: "USER"
      tenantAttribute: "tenant_id"
      defaultTenantId: "tenant_id"
      roleMapJson: '{"1":"ADMIN","3":"DEV"}'
      sessionMaxAgeSeconds: 3600
      localSessionMaxAgeSeconds: 3600
      heartbeatUrl: "https://<ModelEngine IP>:5443/<heartbeat-path>"
      heartbeatIntervalSeconds: 300
      heartbeatCookieName: "<cookie-name>"
      renewBeforeSeconds: 300
      renewTimeoutSeconds: 10
      syntheticEmailDomain: "cas.local"
      logoutUrl: "/logout?service=http://<Nexent IP>:30000"
      sslVerify: false
      caBundle: ""
```

You also need to add a CAS client service registration file in the OMS container. Use the following steps as a reference:

```bash
# Create the registration file, paste the JSON content into it, and save it.
vim Nexent-10000001.json
{
  "@class": "org.apereo.cas.services.CasRegisteredService",
  "serviceId": "http://<Nexent IP>:30000.*",
  "name": "Nexent CAS Client",
  "id": 1000001,
  "description": "Nexent CAS SSO client",
  "evaluationOrder": 1,
  "logoutType": "BACK_CHANNEL",
  "logoutUrl": "http://<Nexent IP>:30000/api/user/cas/logout_callback"
}

# Run the following command to copy the registration file into the container.
kubectl cp Nexent-10000001.json model-engine/$(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}'):/opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
kubectl exec -i -n model-engine $(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}') -- chown tomcat:fusioncube /opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
```

## 🔍 Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n nexent
kubectl describe pod <pod-name> -n nexent
```

### View Logs

The installer prints the current stage and the path to the deployment log. It writes Helm output, Pod readiness checks, and available bootstrap Job output to `logs/deploy/deploy-YYYYMMDD-HHMMSS.log` under the deployment directory. If deployment fails, use the exit code and log path shown in the terminal to locate the failed step. To investigate a running service, check the logs for its Pods.

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

### Elasticsearch Initialization Failed

Check the Elasticsearch Pod status and logs. After fixing any storage, resource, or permission errors, rerun the application deployment from the repository root. The script checks Elasticsearch again, prepares the API key, and resumes initialization.

```bash
bash deploy.sh k8s --defaults --release-scope nexent
```

### Pods Waiting for Storage

If a Pod stays `Pending`, check the PVCs and Pod events. With default dynamic provisioning, verify that the cluster has a suitable default StorageClass or that you passed an RWX-capable class with `--storage-class`. Check available capacity and volume binding. For multiple Runtime replicas, confirm that all five shared volumes are bound.

```bash
kubectl -n nexent get pvc
kubectl -n nexent get events --sort-by=.lastTimestamp
```

## 💡 Need Help

- Browse the [FAQ](./faq) for common install issues
- Drop questions in our [Discord community](https://discord.gg/tb5H3S3wyv)
- File bugs or feature ideas in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues)
