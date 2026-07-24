# Docker Installation & Deployment

## 🎯 Prerequisites

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU**  | 4 cores | 8 cores |
| **RAM**  | 8 GiB | 16 GiB |
| **Disk** | 40 GiB | 100 GiB |
| **Architecture** | x86_64 / ARM64 | |
| **Software** | Docker & Docker Compose installed | Docker 24+, Docker Compose v2+ |

> **💡 Note**: The recommended configuration of **8 cores and 16 GiB RAM** provides good performance for production workloads.

## 🚀 Quick Start

- [Online Deployment](#online-deployment)
- [Offline Deployment](#offline-deployment)

### Online Deployment

#### 1. Download and Setup

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
```

> **Tip**: Docker and Kubernetes use `deploy/env/.env`. Before every deployment, the scripts keep all existing values, comments, and old variables, then append variables newly introduced by the current `deploy/env/.env.example`. If `.env` does not exist, they first reuse legacy `docker/.env`, then fall back to the current template. A readable `.env.example` is required. If you need to configure voice models (STT/TTS), update the related values in `deploy/env/.env` before or after deployment.

#### 2. Deployment Options

Run the following command to start deployment:

```bash
bash deploy.sh docker
```

After running the command, the script opens Bash TUI menus for deployment options. Use arrow keys or `j/k` to move, Space to toggle multi-select items, Enter to confirm, `b`/Backspace to go back, and `q` to quit.

**Deployment Components:**
- **infrastructure (required)**: Elasticsearch, PostgreSQL, Redis, MinIO
- **application (selected by default, optional)**: config, runtime, mcp, northbound, web
- **data-process (selected by default, optional)**: data processing service
- **supabase (selected by default, optional)**: enables user, tenant, and authentication features
- **terminal (optional)**: enables the OpenSSH terminal tool
- **monitoring (optional)**: enables observability components and then prompts for a provider

**Port Policy:**
- **development (default)**: publishes debug and internal service ports for local troubleshooting
- **production**: publishes only production entry ports

**Image Source:**
- **general (default)**: uses standard public registries
- **mainland**: uses mainland China mirrors
- **local-latest**: uses local `latest` Nexent images and avoids pulling Nexent application images

You can also pass options directly:

```bash
# Use saved deploy.options or built-in defaults without opening the TUI
bash deploy.sh docker --defaults

# Default component set, development port policy, standard image source
bash deploy.sh docker --components infrastructure,application,data-process,supabase --port-policy development --image-source general

# Add the terminal tool to the default component set
bash deploy.sh docker --components infrastructure,application,data-process,supabase,terminal

# Use mainland China image sources
bash deploy.sh docker --image-source mainland

# Use local latest images
bash deploy.sh docker --image-source local-latest
```

After a successful deployment, non-sensitive choices are saved to `deploy/docker/deploy.options`. `--defaults` reuses that file when it exists, otherwise it uses built-in defaults. The next interactive deployment can reuse the local config or run a full reconfiguration.

#### ⚠️ Important Notes

1️⃣ **When deploying v1.8.0 or later for the first time**, Nexent creates the `suadmin@nexent.com` super administrator account with the default password `Nexent@123`, without prompting, and displays it in the terminal after successful creation. Override it before the first deployment with `NEXENT_SUPER_ADMIN_PASSWORD` in `deploy/env/.env`; non-interactive creation displays the effective password. As an exception, an offline package launched with `--config` prompts for and confirms the password, and that input takes precedence without being displayed.

> This account is used for permission management only and cannot develop agents or create knowledge bases. Log in with this account and complete: Access tenant resources → Create tenant → Create tenant administrator, then log in with the tenant administrator account to use all features. For role permissions, see [User Management](../user-guide/user-management).

2️⃣ To recreate the `suadmin` account, follow these steps:

```bash
# Step 1: Delete su account record in supabase container
docker exec -it supabase-db-mini bash
psql -U postgres
select id, email from auth.users;
# Get the user_id of suadmin@nexent.com account
delete from auth.users where id = 'your_user_id';
delete from auth.identities where user_id = 'your_user_id';

# Step 2: Delete su account record in nexent database
docker exec -it nexent-postgresql bash
psql -U root -d nexent
delete from nexent.user_tenant_t where user_id = 'your_user_id';

# Step 3: Redeploy; non-interactive mode uses the configured or default password
```

### Offline Deployment

When the target host cannot access public image registries, download a prebuilt offline deployment package from GitHub Actions:

1. Sign in to GitHub and open [Build Offline Deployment Package](https://github.com/ModelEngine-Group/nexent/actions/workflows/build-offline-package.yml).
2. Select a successful run for the required version and download the artifact matching the server architecture from **Artifacts** at the bottom of the run page.
3. Download `nexent-<version>-amd64.zip` for AMD64 or `nexent-<version>-arm64.zip` for ARM64.

GitHub Actions artifacts are retained for 30 days. If the required artifact has expired, ask a maintainer to rerun the workflow.

Copy the downloaded archive to the offline host and extract it. The downloaded artifact contains the package files directly, with no nested archive:

```bash
unzip nexent-v2.2.1-amd64.zip -d nexent
cd nexent
bash deploy.sh --load-images docker
```

The offline package installs all Nexent components by default. Add `--config` to reselect components, port policy, image source, or monitoring provider:

```bash
bash deploy.sh --load-images --config docker
```

If the host still has a previously deployed offline package, use `--reuse-from` to reuse its environment configuration and deployment options:

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  docker
```

The specified directory must be the root of an extracted previous package and contain `deploy/env/.env`. This option imports the old `.env`, preserves its values, and immediately appends variables newly introduced by the current package's `.env.example`. It also reuses `monitoring.env` and Docker `deploy.options` when present; the new scripts regenerate Docker-derived configuration. `--reuse-from` can be combined with `--config`, `--defaults`, or `--push-images`.

When `suadmin@nexent.com` is created for the first time, non-interactive deployment uses `NEXENT_SUPER_ADMIN_PASSWORD`, which defaults to `Nexent@123`, and displays the effective password after successful creation. Offline deployment with `--config` prompts for and confirms the password; that input is neither persisted nor displayed.

To push the packaged images to an internal registry accessible to the target environment:

```bash
bash deploy.sh \
  --push-images \
  --image-registry-prefix registry.example.com/nexent \
  docker
```

When the prefix is omitted, the wrapper prompts for it. `push-images.sh` then prompts for the registry username and password before pushing.

### Access Your Installation

When deployment completes successfully:
1. Open **http://localhost:3000** in your browser
2. Log in with the super administrator account
3. Access tenant resources → Create tenant and tenant administrator
4. Log in with the tenant administrator account
5. Refer to the [User Guide](../user-guide/home-page) to develop agents


## 🏗️ Service Architecture

Nexent uses a microservices architecture deployed via Docker Compose.

**Application Services:**
| Service | Description | Default Port |
|---------|-------------|--------------|
| nexent | Backend service | 5010 |
| nexent-web | Web frontend | 3000 |
| nexent-data-process | Data processing service | 5012 |
| nexent-northbound | Northbound API service | 5013 |

**Infrastructure Services:**
| Service | Description |
|---------|-------------|
| nexent-postgresql | Relational database |
| nexent-elasticsearch | Search and indexing engine |
| nexent-minio | S3-compatible object storage |
| redis | Caching layer |

**Supabase Services (when `supabase` is selected):**
| Service | Description |
|---------|-------------|
| supabase-kong | API Gateway |
| supabase-auth | Authentication service |
| supabase-db-mini | Database service |

**Optional Services:**
| Service | Description |
|---------|-------------|
| nexent-openssh-server | SSH terminal for AI agents |
| nexent-monitoring | Optional observability stack |

Internal services communicate using the Docker internal network.

## 💾 Data Persistence

Nexent uses Docker volumes for data persistence:

| Data Type | Volume Name | Default Host Path |
|-----------|------------------|-------------------|
| PostgreSQL | nexent-postgresql-data | `{dataDir}/postgresql` |
| Elasticsearch | nexent-elasticsearch-data | `{dataDir}/elasticsearch` |
| Redis | nexent-redis-data | `{dataDir}/redis` |
| MinIO | nexent-minio-data | `{dataDir}/minio` |
| Supabase DB (when `supabase` is selected) | nexent-supabase-db-data | `{dataDir}/supabase-db` |

Default `dataDir` is `./volumes` (configurable via `ROOT_DIR` in `deploy/env/.env`).

### Uninstall Docker Deployment

Use the root uninstall entrypoint from the repository root:

```bash
# Stop and remove containers; keep persistent data unless you confirm deletion
bash uninstall.sh docker

# Non-interactive uninstall that keeps data
bash uninstall.sh docker --keep-volumes

# Delete Docker volumes and Nexent data under ROOT_DIR
bash uninstall.sh docker --delete-volumes true

# Full cleanup: containers plus persistent data
bash uninstall.sh docker delete-all
```

The Docker uninstall script reads `deploy/env/.env` to resolve `ROOT_DIR` and removes Compose resources. Data deletion removes service directories such as `postgresql`, `elasticsearch`, `redis`, `minio`, `volumes`, `openssh-server`, `scripts`, and `skills`; keep volumes when you plan to redeploy with existing data.

## 🔌 Port Mapping

| Service | Internal Port | External Port | Description |
|---------|---------------|---------------|-------------|
| Web Interface | 3000 | 3000 | Main application access |
| Backend API | 5010 | 5010 | Backend service |
| Data Processing | 5012 | 5012 | Data processing API |
| Northbound API | 5013 | 5013 | Northbound interface service (A2A/MCP integration) |
| PostgreSQL | 5432 | 5434 | Database connection |
| Elasticsearch | 9200 | 9210 | Search engine API |
| MinIO API | 9000 | 9010 | Object storage API |
| MinIO Console | 9001 | 9011 | Storage management UI |
| Redis | 6379 | 6379 | Cache service |
| SSH Server | 22 | 2222 | Terminal tool access |

For complete port mapping details, see our [Dev Container Guide](../deployment/devcontainer.md#port-mapping).

## 🔧 Advanced Configuration

### Monitoring Configuration

Select the `monitoring` component in the deployment script UI to enable OpenTelemetry monitoring. The script synchronizes `ENABLE_TELEMETRY`, `MONITORING_PROVIDER`, `MONITORING_DASHBOARD_URL`, OTLP endpoints, and provider defaults in `deploy/env/monitoring.env`, then starts the matching observability services from `deploy/docker/compose/docker-compose-monitoring.yml`. The frontend monitoring entry is visible in speed mode when a dashboard URL is configured; in standard mode, only the super administrator can see it.

```bash
cd nexent
bash deploy.sh docker
```

If `deploy/docker/deploy.options` already exists, the script asks whether to reuse local configuration. Choose to reconfigure/overwrite local configuration, then select `monitoring` in the component menu and manually choose `grafana`, `phoenix`, `langfuse`, `langsmith`, `zipkin`, or `otlp` in the provider menu.

Supported providers:

| Provider | Purpose | Default URL |
|----------|---------|-------------|
| `otlp` | OpenTelemetry Collector only, useful for forwarding to an external platform | No dashboard |
| `phoenix` | Local Phoenix trace analysis | `http://localhost:6006` |
| `langfuse` | Local Langfuse observability stack | `http://localhost:3001` |
| `langsmith` | Forwarding to hosted LangSmith | `https://smith.langchain.com/` |
| `grafana` | Local Grafana + Tempo | `http://localhost:3002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1` |
| `zipkin` | Local Zipkin | `http://localhost:9411` |

To change ports, image versions, or local Langfuse bootstrap credentials, copy and edit the monitoring environment file first:

```bash
cp deploy/env/monitoring.env.example deploy/env/monitoring.env
```

Common variables:

| Variable | Description |
|----------|-------------|
| `MONITORING_PROVIDER` | Default monitoring provider; updated when you choose a provider in the deployment script |
| `OTEL_COLLECTOR_HTTP_PORT` / `OTEL_COLLECTOR_GRPC_PORT` | Published OTLP HTTP/gRPC ports |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | LangSmith forwarding configuration |
| `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` | Local Langfuse bootstrap admin |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | Local Grafana admin |

Before choosing the `langsmith` provider, configure `LANGSMITH_API_KEY` in `deploy/env/monitoring.env`. If you only need to connect to an existing external Collector, adjust the OTLP target in `deploy/env/monitoring.env`:

```bash
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
MONITORING_DASHBOARD_URL=
```

> **Production note**: Replace default passwords, secrets, and the Langfuse `ENCRYPTION_KEY`. Restrict dashboard and Collector access with a reverse proxy or firewall.

### OAuth Login Configuration

OAuth login requires the `supabase` component. When enabling third-party login, deploy `supabase` and set `OAUTH_CALLBACK_BASE_URL` to the browser-accessible Nexent Web URL.

```bash
bash deploy.sh docker --components infrastructure,application,supabase
```

For Docker, configure OAuth in `deploy/env/.env`:

```bash
# Web entry URL. The full callback path is generated as:
# {OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=<provider>
OAUTH_CALLBACK_BASE_URL=http://localhost:3000

# GitHub OAuth
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=

# GDE OAuth
GDE_URL=
GDE_OAUTH_CLIENT_ID=
GDE_OAUTH_CLIENT_SECRET=

# Link App OAuth
LINK_APP_URL=
LINK_APP_OAUTH_CLIENT_ID=
LINK_APP_OAUTH_CLIENT_SECRET=

# WeChat OAuth
ENABLE_WECHAT_OAUTH=false
WECHAT_OAUTH_APP_ID=
WECHAT_OAUTH_APP_SECRET=

# TLS verification when contacting OAuth providers
OAUTH_SSL_VERIFY=true
OAUTH_CA_BUNDLE=

# disabled: hide OAuth login entries and disable automatic redirects
# button: show configured OAuth providers as login buttons
# force: redirect automatically when exactly one provider is configured
OAUTH_LOGIN_MODE=button
```

Provider enablement rules:

| Provider | Required variables | Callback URL |
|----------|--------------------|--------------|
| GitHub | `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `GDE_URL`, `GDE_OAUTH_CLIENT_ID`, `GDE_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| Link App | `LINK_APP_URL`, `LINK_APP_OAUTH_CLIENT_ID`, `LINK_APP_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=link_app` |
| WeChat | `ENABLE_WECHAT_OAUTH=true`, `WECHAT_OAUTH_APP_ID`, `WECHAT_OAUTH_APP_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

For local Docker, a GitHub callback example is `http://localhost:3000/api/user/oauth/callback?provider=github`. In production, use a public HTTPS domain such as `https://nexent.example.com/api/user/oauth/callback?provider=github` and register the exact same URL in the OAuth provider console.

`OAUTH_LOGIN_MODE` supports `disabled`, `button`, and `force`, and defaults to `button`. In `force` mode, unauthenticated users are redirected when exactly one provider is enabled. OAuth is disabled when no provider is available, while multiple providers fall back to login buttons. CAS `force` mode takes precedence when both are configured.

### CAS Login Configuration

CAS SSO does not require the `supabase` component. Set `CAS_CALLBACK_BASE_URL` to the browser-accessible Nexent Web URL without a trailing `/`. `CAS_SERVER_URL` is the CAS Server root URL and should also not include a trailing `/`.

For Docker, configure CAS in `deploy/env/.env`:

```bash
CAS_ENABLED=true
CAS_SERVER_URL=http://localhost:8080/cas
CAS_VALIDATE_PATH=/p3/serviceValidate
CAS_CALLBACK_BASE_URL=http://localhost:3000

# disabled: disable the CAS login entry and automatic redirects
# button: show CAS as an optional login button
# force: redirect unauthenticated Nexent users to CAS automatically
CAS_LOGIN_MODE=force

# Empty means use <cas:user>; set userName to read <cas:attributes><cas:userName>
CAS_USER_ATTRIBUTE=
CAS_EMAIL_ATTRIBUTE=email
CAS_ROLE_ATTRIBUTE=role
CAS_TENANT_ATTRIBUTE=tenant_id
CAS_ROLE_MAP_JSON={"cas-admin":"ADMIN","cas-user":"USER"}
CAS_SESSION_MAX_AGE_SECONDS=3600
LOCAL_SESSION_MAX_AGE_SECONDS=3600
CAS_RENEW_BEFORE_SECONDS=300
CAS_RENEW_TIMEOUT_SECONDS=10
CAS_SYNTHETIC_EMAIL_DOMAIN=cas.local

# Empty means Nexent logout will not call the CAS Server logout endpoint.
# /logout is resolved against CAS_SERVER_URL.
CAS_LOGOUT_URL=/logout
CAS_SSL_VERIFY=true
CAS_CA_BUNDLE=
```

Common CAS URLs:

| Purpose | URL |
|---------|-----|
| Nexent login entry | `{CAS_CALLBACK_BASE_URL}/api/user/cas/login?redirect=/` |
| CAS service callback | `{CAS_CALLBACK_BASE_URL}/api/user/cas/callback` |
| CAS silent renewal callback | `{CAS_CALLBACK_BASE_URL}/api/user/cas/renew_callback` |
| CAS single logout callback | `POST {CAS_CALLBACK_BASE_URL}/api/user/cas/logout_callback` |

For Apereo CAS JSON Service Registry, create a service registration file such as `Nexent-10001.json` in the service registry directory configured by your CAS deployment. The `id` must be globally unique. This is a local Docker example:

```json
{
  "@class": "org.apereo.cas.services.RegexRegisteredService",
  "serviceId": "http://localhost:3000.*",
  "name": "Nexent CAS Client",
  "id": 10001,
  "description": "Nexent CAS SSO client",
  "evaluationOrder": 1,
  "logoutType": "BACK_CHANNEL",
  "logoutUrl": "http://localhost:3000/api/user/cas/logout_callback"
}
```

In production, keep `CAS_SSL_VERIFY=true`; for self-signed certificates, prefer `CAS_CA_BUNDLE` and only use `CAS_SSL_VERIFY=false` for local testing.

#### CAS Integration with ModelEngine

When integrating with ModelEngine through the CAS protocol, deploy Nexent with the following configuration:

```bash
CAS_ENABLED=true
CAS_SERVER_URL=https://<ModelEngine IP>:5443/SSOSvr
CAS_VALIDATE_PATH=/p3/serviceValidate
CAS_CALLBACK_BASE_URL=http://<Nexent IP>:3000
CAS_LOGIN_MODE=force
CAS_USER_ATTRIBUTE=userName
CAS_EMAIL_ATTRIBUTE=email
CAS_ROLE_ATTRIBUTE=userType
CAS_TENANT_ATTRIBUTE=tenant_id
CAS_ROLE_MAP_JSON={"1":"ADMIN","3":"DEV"}
CAS_SESSION_MAX_AGE_SECONDS=3600
LOCAL_SESSION_MAX_AGE_SECONDS=3600
CAS_RENEW_BEFORE_SECONDS=300
CAS_RENEW_TIMEOUT_SECONDS=10
CAS_SYNTHETIC_EMAIL_DOMAIN=cas.local
CAS_LOGOUT_URL=/logout?service=http://<Nexent IP>:3000
CAS_SSL_VERIFY=false
CAS_CA_BUNDLE=
```

You also need to add a CAS client service registration file in the OMS container. Use the following steps as a reference:

```bash
# Create the registration file, paste the JSON content into it, and save it.
vim Nexent-10000001.json
{
  "@class": "org.apereo.cas.services.CasRegisteredService",
  "serviceId": "http://<Nexent IP>:3000.*",
  "name": "Nexent CAS Client",
  "id": 1000001,
  "description": "Nexent CAS SSO client",
  "evaluationOrder": 1,
  "logoutType": "BACK_CHANNEL",
  "logoutUrl": "http://<Nexent IP>:3000/api/user/cas/logout_callback"
}

# Run the following command to copy the registration file into the container.
kubectl cp Nexent-10000001.json model-engine/$(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}'):/opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
kubectl exec -i -n model-engine $(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}') -- chown tomcat:fusioncube /opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
```

### Northbound Interface Configuration (NORTHBOUND_EXTERNAL_URL)

If you need to use any of the following features, configure the `NORTHBOUND_EXTERNAL_URL` environment variable:

1. **A2A Protocol Integration** - Third-party systems calling Nexent agents via A2A protocol
2. **MCP Tool Access** - Using MCP protocol to access Nexent resources like documents

**Configuration:**

Set the publicly accessible URL in your `deploy/env/.env` file:

```bash
# Format: protocol://host:port/api
# Local development (default):
NORTHBOUND_EXTERNAL_URL=http://localhost:5013/api

# Production - use your public IP or domain:
NORTHBOUND_EXTERNAL_URL=http://your-public-ip:5013/api
# or
NORTHBOUND_EXTERNAL_URL=https://api.yourdomain.com/api
```

> **Important**: The URL must include the `/api` suffix because the Northbound service uses FastAPI's `root_path="/api"` configuration.

## 💡 Need Help

- Browse the [FAQ](./faq) for common install issues
- Drop questions in our [Discord community](https://discord.gg/tb5H3S3wyv)
- File bugs or feature ideas in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues)

## 🔧 Build from Source

Want to build from source or add new features? Check the [Docker Build Guide](../deployment/docker-build) for step-by-step instructions.

For detailed setup instructions and customization options, see our [Developer Guide](../developer-guide/overview).
