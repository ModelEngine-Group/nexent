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
cd nexent
```

### 3. Deployment

Run the deployment script:

```bash
bash deploy.sh k8s
```

After running the command, the script opens Bash TUI menus for configuration. Use arrow keys or `j/k` to move, Space to toggle multi-select items, Enter to confirm, `b`/Backspace to go back, and `q` to quit.

**Deployment Components:**
- **infrastructure (required)**: Elasticsearch, PostgreSQL, Redis, MinIO
- **application (selected by default, optional)**: config, runtime, mcp, northbound, web
- **data-process (selected by default, optional)**: data processing service
- **supabase (selected by default, optional)**: enables user, tenant, and authentication features
- **terminal (optional)**: enables the OpenSSH terminal tool
- **monitoring (optional)**: enables observability components and then prompts for a provider

**Port Policy:**
- **development (default)**: uses NodePort for Web and selected debug/internal services
- **production**: keeps internal services as ClusterIP and exposes only production entrypoints

**Image Source:**
- **general (default)**: uses standard public registries
- **mainland**: uses mainland China mirrors
- **local-latest**: uses local `latest` images and local-friendly pull policies for Nexent application images

Kubernetes uses the same `deploy/env/.env` file as Docker. Existing `deploy/env/.env` is kept as-is. If it does not exist, the deploy scripts first reuse `docker/.env`, then fall back to `deploy/env/.env.example`.

After a successful deployment, non-sensitive choices are saved to `deploy/k8s/deploy.options`. The next interactive deployment can reuse the local config or run a full reconfiguration.

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
bash deploy.sh k8s
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

**Supabase Services (when `supabase` is selected):**
| Service | Description |
|---------|-------------|
| nexent-supabase-kong | API Gateway |
| nexent-supabase-auth | Authentication service |
| nexent-supabase-db | Database service |

**Optional Services:**
| Service | Description |
|---------|-------------|
| nexent-openssh-server | SSH terminal for AI agents |
| nexent-monitoring | Optional observability stack |

## 🔌 Port Mapping

| Service | Internal Port | NodePort | Description |
|---------|---------------|----------|-------------|
| Web Interface | 3000 | 30000 | Main application access |
| Northbound API | 5013 | 30013 | Northbound API service |
| SSH Server | 22 | 30022 | Terminal tool access |

For internal service communication, services use Kubernetes internal DNS (e.g., `http://nexent-config:5010`).

## 💾 Data Persistence

Nexent uses PersistentVolumes for data persistence:

| Data Type | PersistentVolume | Default Host Path |
|-----------|------------------|-------------------|
| Elasticsearch | nexent-elasticsearch-pv | `/var/lib/nexent-data/nexent-elasticsearch` |
| PostgreSQL | nexent-postgresql-pv | `/var/lib/nexent-data/nexent-postgresql` |
| Redis | nexent-redis-pv | `/var/lib/nexent-data/nexent-redis` |
| MinIO | nexent-minio-pv | `/var/lib/nexent-data/nexent-minio` |
| Supabase DB (when `supabase` is selected) | nexent-supabase-db-pv | `/var/lib/nexent-data/nexent-supabase-db` |
| Shared workspace | nexent-workspace-pv | `/var/lib/nexent` |
| Shared skills | nexent-skills-pv | `/var/lib/nexent-data/skills` |

Helm uninstall does not delete local hostPath data by default. Use `bash deploy/k8s/uninstall.sh --delete-local-data true` or `bash uninstall.sh k8s --delete-local-data true` to delete known Nexent local volume contents under `/var/lib/nexent`, `/var/lib/nexent-data/skills`, and `/var/lib/nexent-data/nexent-*`; use `--keep-local-data` to preserve them explicitly.

### Uninstall Kubernetes Deployment

Use the root uninstall entrypoint from the repository root:

```bash
# Remove Helm release; prompts before deleting namespace or local data in interactive shells
bash uninstall.sh k8s

# Clean only Helm release state, useful for stuck releases
bash uninstall.sh k8s clean

# Remove Helm release and namespace, but keep local hostPath data
bash uninstall.sh k8s delete --keep-local-data

# Delete known local hostPath data after uninstall
bash uninstall.sh k8s --delete-local-data true

# Full cleanup: Helm release, namespace, and local hostPath data
bash uninstall.sh k8s delete-all
```

`--delete-data` and `--delete-volumes` are compatibility options for Helm-managed resources. For local disks, use `--delete-local-data` or `--keep-local-data`; `delete-all --keep-local-data` removes the namespace while preserving local volume contents.

### Offline Image Package

Build a Kubernetes offline package from the repository root:

```bash
bash deploy/offline/build_offline_package.sh \
  --target k8s \
  --version v2.2.1 \
  --platform amd64 \
  --components infrastructure,application,data-process,supabase \
  --image-source general \
  --compress true \
  --output-dir offline-package
```

The package includes image tar files, `load-images.sh`, root deploy/uninstall entrypoints, Kubernetes Helm assets, SQL files, `deploy/env/.env.example`, `deploy/env/monitoring.env.example`, `manifest.yaml`, and `checksums.txt`. It does not include local `deploy/env/.env`, `deploy/env/monitoring.env`, or generated Helm values. With `--compress true`, a `nexent-offline-<target>-<platform>-<version>.zip` archive is created next to the output directory. On a single-node Docker-backed cluster, you can load and deploy directly:

```bash
cd offline-package
bash deploy.sh --load-images k8s
```

For multi-node clusters, load the images on every node that may run Nexent Pods, or push the loaded images to an internal registry and deploy with matching image settings.

## 🔧 Deployment Commands

```bash
# Deploy with interactive prompts
bash deploy.sh k8s

# Non-interactive deployment with the default component set
bash deploy.sh k8s --components infrastructure,application,data-process,supabase --port-policy development --image-source general

# Add the terminal tool to the default component set
bash deploy.sh k8s --components infrastructure,application,data-process,supabase,terminal

# Deploy with mainland China image sources
bash deploy.sh k8s --image-source mainland

# Use local latest images
bash deploy.sh k8s --image-source local-latest

# Clean helm state only (fixes stuck releases)
bash uninstall.sh k8s clean

# Uninstall; local data is preserved by default, with interactive prompts for namespace and local data deletion
bash uninstall.sh k8s

# Uninstall and delete the namespace
bash uninstall.sh k8s --delete-namespace true

# Uninstall and delete local hostPath data
bash uninstall.sh k8s --delete-local-data true

# Complete uninstall including namespace and local hostPath data
bash uninstall.sh k8s delete-all

# Complete uninstall but preserve local hostPath data
bash uninstall.sh k8s delete-all --keep-local-data
```

## 🔧 Advanced Configuration

### Monitoring Configuration

Kubernetes deployments enable monitoring through the `monitoring` component in the deployment script UI. The deployment script synchronizes provider settings in `deploy/env/monitoring.env`, renders runtime Helm values for `global.monitoring.*` and `nexent-monitoring.*`, and enables the `nexent-monitoring` subchart.

```bash
cd nexent
bash deploy.sh k8s
```

If `deploy/k8s/deploy.options` already exists, the script asks whether to reuse local configuration. Choose to reconfigure/overwrite local configuration, then select `monitoring` in the component menu and manually choose `grafana`, `phoenix`, `langfuse`, `langsmith`, `zipkin`, or `otlp` in the provider menu.

Supported providers:

| Provider | Purpose | Default URL |
|----------|---------|-------------|
| `otlp` | OpenTelemetry Collector only, useful for forwarding to an external platform | No dashboard |
| `phoenix` | Local Phoenix trace analysis | `http://localhost:30006` |
| `langfuse` | Local Langfuse observability stack | `http://localhost:30001` |
| `langsmith` | Forwarding to hosted LangSmith | `https://smith.langchain.com/` |
| `grafana` | Local Grafana + Tempo | `http://localhost:30002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1` |
| `zipkin` | Local Zipkin | `http://localhost:30011` |

Before choosing the `langsmith` provider, configure `LANGSMITH_API_KEY` and optionally `LANGSMITH_PROJECT` in `deploy/env/monitoring.env`. To change local Grafana, Langfuse, or dashboard ports, adjust the related `K8S_*_NODE_PORT` or service variables in `deploy/env/monitoring.env`, then re-run the deployment script, choose to reconfigure, and manually select `monitoring`.

Common generated Helm values:

| Value | Description |
|-------|-------------|
| `global.monitoring.enabled` | Enables OpenTelemetry export in the Nexent backend |
| `global.monitoring.provider` | Backend provider label: `otlp`, `phoenix`, `langfuse`, `langsmith`, `grafana`, `zipkin` |
| `global.monitoring.otlpEndpoint` | Backend OTLP HTTP endpoint, default `http://nexent-otel-collector:4318` |
| `global.monitoring.dashboardUrl` | Frontend monitoring entry URL; leave empty to hide the entry |
| `global.monitoring.traceContentMode` | Trace content capture mode: `summary`, `metrics`, or `full` |
| `nexent-monitoring.<provider>.service.nodePort` | NodePort override for provider dashboards |
| `nexent-monitoring.langfuse.init.*` | Local Langfuse bootstrap organization, project, and admin account |
| `nexent-monitoring.grafana.adminUser` / `adminPassword` | Local Grafana admin credentials |

Common `deploy/env/monitoring.env` variables:

| Variable | Description |
|----------|-------------|
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | LangSmith forwarding configuration |
| `K8S_PHOENIX_NODE_PORT` / `K8S_LANGFUSE_NODE_PORT` / `K8S_GRAFANA_NODE_PORT` / `K8S_ZIPKIN_NODE_PORT` | NodePort overrides for local dashboards |
| `K8S_LANGFUSE_NEXTAUTH_URL` | Browser-accessible Langfuse URL used by the K8s Langfuse stack |

Check monitoring status:

```bash
kubectl get pods -n nexent | grep -E 'otel|phoenix|grafana|tempo|zipkin|langfuse'
kubectl get svc -n nexent | grep -E 'otel|phoenix|grafana|zipkin|langfuse'
```

> **Production note**: Replace default passwords, secrets, and the Langfuse `encryptionKey`. Prefer ClusterIP services or a controlled Ingress for dashboards.

### OAuth Login Configuration

OAuth login requires the `supabase` component. When enabling third-party login, deploy `supabase` and set `config.oauth.callbackBaseUrl` to the browser-accessible Nexent Web URL.

```bash
bash deploy.sh k8s --components infrastructure,application,supabase
```

Kubernetes writes OAuth settings into backend environment variables through `nexent-common` `config.oauth.*` values:

```bash
helm upgrade --install nexent nexent \
  --namespace nexent --create-namespace \
  --set global.deploymentComponents.supabase=true \
  --set nexent-supabase-kong.enabled=true \
  --set nexent-supabase-auth.enabled=true \
  --set nexent-supabase-db.enabled=true \
  --set nexent-common.config.oauth.callbackBaseUrl=https://nexent.example.com \
  --set nexent-common.config.oauth.githubClientId=your_github_client_id \
  --set nexent-common.config.oauth.githubClientSecret=your_github_client_secret
```

Configurable OAuth values:

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

Provider callback URLs:

| Provider | Callback URL |
|----------|--------------|
| GitHub | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| WeChat | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

For local NodePort, a GitHub callback example is `http://localhost:30000/api/user/oauth/callback?provider=github`. In production, use a public HTTPS domain and register the exact same URL in the OAuth provider console.

### CAS Login Configuration

CAS SSO does not require the `supabase` component. Set `nexent-common.config.cas.callbackBaseUrl` to the browser-accessible Nexent Web URL without a trailing `/`. `nexent-common.config.cas.serverUrl` is the CAS Server root URL and should also not include a trailing `/`.

Kubernetes writes CAS settings into backend environment variables through `nexent-common` `config.cas.*` values:

```bash
helm upgrade --install nexent nexent \
  --namespace nexent --create-namespace \
  --set nexent-common.config.cas.enabled=true \
  --set nexent-common.config.cas.serverUrl=https://cas.example.com/cas \
  --set nexent-common.config.cas.callbackBaseUrl=https://nexent.example.com \
  --set nexent-common.config.cas.loginMode=force \
  --set nexent-common.config.cas.logoutUrl=/logout
```

Configurable CAS values:

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
| `nexent-common.config.cas.tenantAttribute` | `CAS_TENANT_ATTRIBUTE` | Tenant attribute |
| `nexent-common.config.cas.roleMapJson` | `CAS_ROLE_MAP_JSON` | JSON mapping from CAS roles to Nexent roles |
| `nexent-common.config.cas.sessionMaxAgeSeconds` | `CAS_SESSION_MAX_AGE_SECONDS` | Maximum local CAS session lifetime |
| `nexent-common.config.cas.localSessionMaxAgeSeconds` | `LOCAL_SESSION_MAX_AGE_SECONDS` | Nexent local session lifetime |
| `nexent-common.config.cas.renewBeforeSeconds` | `CAS_RENEW_BEFORE_SECONDS` | Trigger silent renewal within this many seconds before expiry |
| `nexent-common.config.cas.renewTimeoutSeconds` | `CAS_RENEW_TIMEOUT_SECONDS` | Silent renewal timeout |
| `nexent-common.config.cas.syntheticEmailDomain` | `CAS_SYNTHETIC_EMAIL_DOMAIN` | Domain used when CAS does not return an email |
| `nexent-common.config.cas.logoutUrl` | `CAS_LOGOUT_URL` | CAS logout URL. Empty means Nexent logout will not call the CAS Server logout endpoint |
| `nexent-common.config.cas.sslVerify` | `CAS_SSL_VERIFY` | Whether to verify CAS Server TLS certificates |
| `nexent-common.config.cas.caBundle` | `CAS_CA_BUNDLE` | Custom CA bundle path |

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
      tenantAttribute: "tenant_id"
      roleMapJson: '{"1":"ADMIN","3":"DEV"}'
      sessionMaxAgeSeconds: 3600
      localSessionMaxAgeSeconds: 3600
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
