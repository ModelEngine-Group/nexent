# Docker Installation & Deployment

## Environment Setup

### 🎯 Prerequisites

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU**  | 4 cores | 8 cores |
| **RAM**  | 8 GiB | 16 GiB |
| **Disk** | 40 GiB | 100 GiB |
| **Architecture** | x86_64 / ARM64 | |
| **Software** | Docker Engine 18.09+ and Docker Compose v2 | A maintained Docker Engine release and Docker Compose v2 |

> **💡 Note**: The recommended configuration is suitable for environments that enable the complete application, data processing, and Docker sandboxes. Model services are usually deployed separately and are not included in the resource requirements above.

### Install Docker and Compose

| Deployment host | Installation steps |
| --- | --- |
| Linux server | Follow the official instructions for your distribution to configure the package repository, install Docker Engine, the CLI, and the Compose plugin, then start the Docker service. If Engine is already installed, you can add the Compose plugin separately. [Install Docker Engine](https://docs.docker.com/engine/install/) · [Install the Compose plugin](https://docs.docker.com/compose/install/linux/) |
| macOS or Windows development machine | Install and start Docker Desktop, which includes Docker Engine and Compose. On Windows, use Linux containers and run the deployment commands in a terminal with Bash. [Install Docker Desktop on macOS](https://docs.docker.com/desktop/setup/install/mac-install/) · [Install Docker Desktop on Windows](https://docs.docker.com/desktop/setup/install/windows-install/) |

Run these commands in the terminal and account you will use for deployment. If Docker is already installed, start here.

```bash
docker version
docker compose version
```

`docker version` should show both the `Client` and `Server` sections, and the second command should print the Compose version. If you see only client details and a connection error, check that the Docker service or Docker Desktop is running and that your account can access it. Once both checks pass, continue with either online or offline deployment.

## 🚀 Quick Start

- [Online Deployment](#online-deployment)
- [Offline Deployment](#offline-deployment)

### Online Deployment

#### 1. Download and Setup

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
```

Docker and Kubernetes share `deploy/env/.env`. The deployment script keeps existing values and adds any new variables from the template. If the file is missing, the installer uses the legacy `docker/.env` if available, or creates the file from `deploy/env/.env.example`. To set the administrator password or persistent data path before a fresh installation, copy the template to `deploy/env/.env` and edit the settings there.

#### 2. Deployment Options

Run the following command to start deployment:

```bash
bash deploy.sh docker
```

The installer prints the path to the deployment log when it starts. By default it writes to `logs/deploy/deploy-YYYYMMDD-HHMMSS.log` under the repository or offline package root. If deployment fails, open the file shown in the terminal to find the error from image loading, image pulls, or Compose startup. The installer saves the generated Elasticsearch API key in `deploy/env/.env` as `ELASTICSEARCH_API_KEY`.

The Bash menu prompts you for deployment options. Use the arrow keys or `j/k` to move, Space to toggle selections, Enter to confirm, `b` or Backspace to go back, and `q` to quit.

**Deployment components**

| Component | Selected by default | Purpose |
| --- | --- | --- |
| `infrastructure` | Required | Provides Elasticsearch, PostgreSQL, Redis, and MinIO. |
| `application` | Yes | Starts Web, Gateway, Management, Runtime, MCP, and Ops. Keep this selected to use the web interface, run agents, or inspect execution traces. |
| `data-process` | Yes | Starts the service that parses and imports files for knowledge bases. |
| `terminal` | No | Provides OpenSSH for the agent terminal tool. |
| `monitoring` | No | Sends telemetry to the selected OpenTelemetry backend. |

**Sandbox mode** defaults to the `lightweight` image. Choose `full` if your Skills require document processing, design, or frontend build tools. Runtime creates and reuses sandbox containers according to the execution policy.

**Port policy** defaults to `development`, which publishes database and internal service ports on the host for debugging. With `production`, these ports stay on the container network. The base application publishes Web, Gateway, and Ops on ports 3000, 5013, and 5016 by default.

**Image source** defaults to `general`, which uses the standard public registries. Choose `mainland` for mainland China mirrors or `local-latest` to reuse local Nexent application images.

Use `--defaults` to skip the configuration menu and override individual options as needed. Choose one of the following commands.

```bash
# Use saved deploy.options or built-in defaults without opening the TUI
bash deploy.sh docker --defaults

# Default components and development ports
bash deploy.sh docker --defaults --components infrastructure,application,data-process --port-policy development --image-source general

# Include the OpenSSH service
bash deploy.sh docker --defaults --components infrastructure,application,data-process,terminal

# Use a mainland registry
bash deploy.sh docker --defaults --image-source mainland

# Use local application images tagged latest
bash deploy.sh docker --defaults --image-source local-latest
```

#### HTTPS (Optional)

Docker serves the web interface over HTTP on port 3000 by default. When you enable HTTPS, Nginx accepts encrypted connections on port 3100 and forwards requests to Web. Set `NEXENT_WEB_PORT` in `deploy/env/.env` to change the HTTP port. With the `production` port policy, set `NEXENT_HTTPS_PORT` to change the HTTPS port.

The interactive installer prompts you to choose an HTTPS mode. To enable it non-interactively, use one of these commands.

```bash
# Self-signed certificate (recommended for internal deployments)
bash deploy.sh docker --defaults --https-mode self-signed

# Your own certificate (paths may also be preset via deploy/env/.env)
bash deploy.sh docker --defaults --https-mode custom --https-cert-file /path/to/server.pem --https-key-file /path/to/server.key
```

- **self-signed**: the installer generates a 99-year certificate with an unencrypted private key under `<ROOT_DIR>/nginx/ssl/` and reuses it on redeployment. SAN entries are auto-detected from the host network interfaces (loopback and Docker bridges excluded); preset `NEXENT_HTTPS_SAN` in `deploy/env/.env` to override (for example `NEXENT_HTTPS_SAN=10.0.0.5,example.com`). Browsers show an untrusted-certificate warning; import the certificate into your trust store to silence it.
- **custom**: point `NEXENT_HTTPS_CERT_FILE` and `NEXENT_HTTPS_KEY_FILE` at your PEM files. The installer validates the pair (PEM format, key/cert match, expiry) before deploying. Encrypted private keys are supported: provide the passphrase via `NEXENT_HTTPS_KEY_PASSPHRASE` or `--https-key-passphrase`; like other deployment credentials, it is stored in plain text in `deploy/env/.env`.
- If you use OAuth or CAS, set `OAUTH_CALLBACK_BASE_URL` or `CAS_CALLBACK_BASE_URL` to the address users open in their browsers, for example `https://nexent.example.com:3100`. If you configured a fixed address for shared conversations, also update `SHARE_BASE_URL`.

- Disabling HTTPS again (`--https-mode disabled`) removes the Nginx container; the certificate files are kept and can be reused later.

After a successful deployment, non-sensitive choices are saved to `deploy/docker/deploy.options`. `--defaults` reuses that file when it exists, otherwise it uses built-in defaults. The next interactive deployment can reuse the local config or run a full reconfiguration.

#### Administrator password for a fresh installation

Installing the full application creates the super administrator account `suadmin@nexent.com`. To set its password before the first installation, set `NEXENT_SUPER_ADMIN_PASSWORD` in `deploy/env/.env`. The default is `Nexent@123`. The installer displays the password in the terminal after it creates the account automatically. When you run an offline package with `--config`, it prompts you to enter and confirm the password and hides your input.

### Offline Deployment

When the target host cannot access public image registries, download a prebuilt offline deployment package from GitHub Actions:

1. Sign in to GitHub and open [Build Offline Deployment Package](https://github.com/ModelEngine-Group/nexent/actions/workflows/build-offline-package.yml).
2. Select a successful run for the required version and download the artifact matching the server architecture from **Artifacts** at the bottom of the run page.
3. Download `nexent-<version>-amd64.zip` for AMD64 or `nexent-<version>-arm64.zip` for ARM64.

GitHub Actions artifacts are retained for 30 days. If the required artifact has expired, ask a maintainer to rerun the workflow.

Copy the archive to the offline host. Replace the filename in the example with the file you downloaded, extract it, and run the installer.

```bash
unzip 'nexent-<version>-amd64.zip' -d nexent
cd nexent
bash deploy.sh --load-images docker
```

The offline package skips the configuration menu by default. Its `manifest.yaml` lists the components and images selected when the package was built. The official workflow includes images for infrastructure, the application, data processing, and the terminal tool. Use `--config` to enable the terminal tool or change the component selection. The images required by your selected components and sandbox mode must be in the package or already loaded on the server.

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

To push the packaged images to an internal registry accessible from the target environment, run the following command.

```bash
bash deploy.sh \
  --push-images \
  --image-registry-prefix registry.example.com/nexent \
  docker
```

When the prefix is omitted, the wrapper prompts for it. `push-images.sh` then prompts for the registry username and password before pushing.

### Access Your Installation

1. On the deployment host, open `http://localhost:3000`. From another device, use the host's domain name or IP address. If you enabled built-in HTTPS, the default URL is `https://<deployment-host>:3100`.
2. Sign in as `suadmin@nexent.com` with the password set during installation. In **Tenant Resources**, create a tenant and invite a tenant administrator.
3. Sign in as the tenant administrator to configure models and resources. See the [User Guide](../user-guide/home-page).

Authentication cookies have the `Secure` attribute by default. Use HTTPS when connecting from other devices, including through an external reverse proxy. If an isolated test environment can reach the remote host only over HTTP, set `NEXENT_AUTH_COOKIE_SECURE=false` in `deploy/env/.env` and redeploy with the same options. Set it back to `true` when you enable HTTPS.

On the deployment host, check the container status and the readiness of Gateway and Ops. These commands use the default ports.

```bash
docker ps -a --filter label=com.docker.compose.project=nexent
curl --fail http://localhost:5013/health/ready
curl --fail http://localhost:5016/health/ready
```

If Web opens but management API calls fail, run the Gateway image's built-in `curl` to check Management readiness from inside the container. This also works with the production port policy, where Management is reachable only on the container network.

```bash
docker exec nexent-gateway curl --fail --show-error --silent --noproxy '*' --max-time 5 http://nexent-config:5010/health/ready
```

For legacy account migration, administrator account issues, and data recovery, see the [migration and troubleshooting guide](https://github.com/ModelEngine-Group/nexent/blob/develop/deploy/sql/tools/supabase_to_postgres/README.md).

## 📦 Service Architecture

Nexent uses a microservice architecture deployed with Docker Compose.

**Application services**

| Service | Description | Default port |
| --- | --- | --- |
| nexent-web | Web interface. Browser requests reach the backend through Gateway. | 3000 |
| nexent-gateway | Common API entry point. Authenticates requests and forwards them to Management, Runtime, and Ops. | 5013 |
| nexent-config | Management service for configuration, resource management, and Northbound APIs | 5010 |
| nexent-runtime | Agent runtime API | 5014 |
| nexent-mcp | MCP management and tool service | 5011/5015 |
| nexent-ops | Operations metrics and historical trace queries | 5016 |

**Infrastructure services**

| Service | Description |
| --- | --- |
| nexent-postgresql | Relational database |
| nexent-elasticsearch | Search and indexing |
| nexent-minio | S3-compatible object storage |
| redis | Cache, distributed locks, and task message broker |

**Optional services**

| Service or component | Description |
| --- | --- |
| nexent-data-process | Data processing API (port 5012) and background processing jobs |
| nexent-openssh-server | SSH terminal for agents |
| monitoring | Installs the OpenTelemetry Collector and starts the monitoring services for the selected backend |

**On-demand execution environment**

| Component | Description |
| --- | --- |
| nexent-sandbox | Isolated environment that Runtime creates according to policy to run model-generated code and Skill scripts |

## 💾 Data Persistence

Docker deployments store database files, objects, and raw traces in host directories. The default root is `$HOME/nexent-data` for the user running the installer. Set `ROOT_DIR` in `deploy/env/.env` to use another location.

| Data | Default mount and location |
| --- | --- |
| PostgreSQL | Host directory `${ROOT_DIR}/postgresql/data` |
| Elasticsearch | Host directory `${ROOT_DIR}/elasticsearch` |
| Redis | Host directory `${ROOT_DIR}/redis` |
| MinIO | Host directory `${ROOT_DIR}/minio/data` |
| Conversation traces | Host directory `${ROOT_DIR}/trajectory`, mounted by default at `/mnt/nexent-data/trajectory` in Management, Runtime, and Ops |
| Service logs | Host directory `${ROOT_DIR}/logs` |
| Agent workspace | Docker named volume `nexent-agent-workspace`, configurable with `NEXENT_SANDBOX_WORKSPACE_VOLUME` |

### Uninstall Docker Deployment

Use the root uninstall entrypoint from the repository root:

```bash
# Stop and remove containers; keep persistent data unless you confirm deletion
bash uninstall.sh docker

# Non-interactive uninstall that keeps data
bash uninstall.sh docker --keep-volumes

# Remove volumes and deployment-managed data directories
bash uninstall.sh docker --delete-volumes true

# Remove containers, volumes, and deployment-managed data directories
bash uninstall.sh docker delete-all
```

Choose to keep the volumes if you plan to reuse the data. If you choose to delete the data, the script removes the database, object storage, Skill, and other service directories. The host retains `${ROOT_DIR}/trajectory` and `${ROOT_DIR}/logs`.

## 🔌 Port Mapping

The table shows common host port mappings under the `development` policy. The `production` policy publishes Web, Gateway, and Ops ports by default, plus the Nginx port when HTTPS is enabled.

| Service | Internal Port | External Port | Description |
|---------|---------------|---------------|-------------|
| Web Interface | 3000 | 3000 (`NEXENT_WEB_PORT`) | Main application access |
| HTTPS Entry | 3100 | 3100 | Optional encrypted entry via Nginx (when HTTPS is enabled) |
| Gateway API | 5013 | 5013 | Entry point for Web and Northbound APIs |
| Ops API | 5016 | 5016 | Operations and historical traces |
| Management API | 5010 | 5010 | Configuration and management service |
| Runtime API | 5014 | 5014 | Agent runtime service |
| MCP API | 5011/5015 | 5011/5015 | MCP management and tool service |
| Data Processing | 5012 | 5012 | Data processing API |
| PostgreSQL | 5432 | 5434 | Database connection |
| Elasticsearch | 9200 | 9210 | Search engine API |
| MinIO API | 9000 | 9010 | Object storage API |
| MinIO Console | 9001 | 9011 | Storage management UI |
| Redis | 6379 | 6379 | Cache service |
| SSH Server | 22 | 2222 | Terminal tool access |

For port forwarding when using a development container, see the [Dev Container Guide](../deployment/devcontainer).

## 🔧 Advanced Configuration

The Docker deployment template uses a system-scoped sandbox by default, allowing Runtime to reuse containers across runs. The Runtime service exchanges uploaded and generated files through a dedicated workspace volume. Artifacts that must be retained are synchronized to MinIO after a run.

Common settings are defined in `deploy/env/.env`:

| Variable | Default | Description |
|------|--------|------|
| `NEXENT_SANDBOX_DEFAULT_LEVEL` | `docker` | Isolation level: `local`, `docker`, or `wasm` |
| `NEXENT_SANDBOX_DEFAULT_SCOPE` | `system` | Container lifecycle: `session` or `system` |
| `NEXENT_SANDBOX_DOCKER_IMAGE` | `nexent/nexent-sandbox:latest` | Docker sandbox image |
| `NEXENT_SANDBOX_WORKSPACE_VOLUME` | `nexent-agent-workspace` | Docker volume shared by the Runtime service and sandboxes |
| `NEXENT_SANDBOX_MEMORY_LIMIT_MB` | `2048` | Sandbox memory limit in MiB |
| `NEXENT_SANDBOX_CPU_QUOTA` | `1.0` | Sandbox CPU quota |
| `NEXENT_SANDBOX_TIMEOUT_S` | `30` | Per-step execution timeout in seconds |
| `NEXENT_SANDBOX_NETWORK` | `disabled` | Whether sandbox network access is enabled |
| `NEXENT_SANDBOX_SHELL_POLICY` | `disabled` | Shell invocation policy: `disabled`, `restricted`, or `boxed` |
| `NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS` | `true` | Whether output files are automatically synchronized to MinIO |
| `AGENT_WORKSPACE_ROOT` | `/mnt/nexent/workdir` | Temporary file workspace for each run |

Do not change the isolation level to `local` in production. Redeploy the Runtime service after changing resource, network, or shell policies.

### Monitoring Configuration

The Operations Dashboard uses `OPS_MONITORING_TIMEZONE` to determine the date for daily statistics. For new installations, `deploy/env/.env.example` sets the timezone to `Asia/Shanghai`. Existing installations keep the timezone saved in `deploy/env/.env`.

#### View local traces in the Observability Center

When you deploy `application` with the default options, Runtime captures agent conversation traces and Ops serves historical queries. The default component selection is sufficient for the built-in Observability Center.

1. Confirm that `LOCAL_FILE_MONITORING_ENABLED=true` in `deploy/env/.env` (the default). The installer copies this setting to `deploy/env/monitoring.env` and sets `TRAJECTORY_READ_ENABLED=true` there to enable historical queries.
2. After deployment, run the following command to check the Ops container. A ready container reports `healthy`. By default, Config, Runtime, and Ops all mount the host's `${ROOT_DIR}/trajectory` at `/mnt/nexent-data/trajectory` and must be able to access the same files.

   ```bash
   docker inspect --format '{{.State.Health.Status}}' nexent-ops
   ```

3. Complete a turn in Agent Chat and copy the conversation ID at the top. Using an operations administrator or super administrator account with access to the page, search for the ID in the **Observability Center** and open the conversation details. See the [Observability Center guide](../user-guide/observability).

To stop capturing new conversations while keeping historical traces available during their retention period, set `LOCAL_FILE_MONITORING_ENABLED=false` in `deploy/env/.env`, keep `TRAJECTORY_READ_ENABLED=true` in `deploy/env/monitoring.env`, and run `bash deploy.sh docker --defaults` to apply the changes.

#### Export traces to a third-party platform

To also send telemetry to another platform, select `monitoring` in the deployment menu and choose a destination. Local capture has its own setting. The following command adds Phoenix to the default component set.

```bash
bash deploy.sh docker --components infrastructure,application,data-process,monitoring --monitoring-provider phoenix
```

| Destination | Access after deployment |
| --- | --- |
| `otlp` | Starts the OpenTelemetry Collector. Its debug exporter writes to the Collector log by default. |
| `phoenix` | Runs Phoenix locally. Open `http://localhost:6006` on the deployment host. |
| `langfuse` | Runs Langfuse locally. Open `http://localhost:3001` on the deployment host. |
| `langsmith` | Sends traces to hosted LangSmith. Before deployment, set `LANGSMITH_API_KEY` in `deploy/env/monitoring.env` and set `LANGSMITH_PROJECT` if needed. |

`MONITORING_DASHBOARD_URL` controls the third-party dashboard URL. `MONITORING_DASHBOARD_ALLOWED_ROLES` specifies which roles can see its link. Remote users must be able to reach the URL from their browsers. To change the Phoenix or Langfuse port, edit `PHOENIX_PORT` or `LANGFUSE_PORT` in `deploy/env/monitoring.env`, update the dashboard URL, and redeploy.

### OAuth Login Configuration

OAuth login uses local accounts in the application component. When enabling third-party login, set `OAUTH_CALLBACK_BASE_URL` to the browser-accessible Nexent Web URL.

```bash
bash deploy.sh docker --components infrastructure,application
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

CAS SSO uses local application accounts. Set `CAS_CALLBACK_BASE_URL` to the browser-accessible Nexent Web URL without a trailing `/`. `CAS_SERVER_URL` is the CAS Server root URL and should also not include a trailing `/`.

For Docker, configure CAS in `deploy/env/.env`:

```bash
CAS_ENABLED=true
CAS_SERVER_URL=http://localhost:8080/cas
# Optional internal CAS URL for backend containers. Leave empty to use CAS_SERVER_URL.
CAS_INTERNAL_SERVER_URL=
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
CAS_DEFAULT_ROLE=USER
CAS_TENANT_ATTRIBUTE=tenant_id
CAS_DEFAULT_TENANT_ID=tenant_id
CAS_ROLE_MAP_JSON='{"cas-admin":"ADMIN","cas-user":"USER"}'
CAS_SESSION_MAX_AGE_SECONDS=3600
LOCAL_SESSION_MAX_AGE_SECONDS=3600
CAS_HEARTBEAT_URL=
CAS_HEARTBEAT_INTERVAL_SECONDS=300
CAS_HEARTBEAT_COOKIE_NAME=
CAS_RENEW_BEFORE_SECONDS=300
CAS_RENEW_TIMEOUT_SECONDS=10
CAS_SYNTHETIC_EMAIL_DOMAIN=cas.local

# Empty means Nexent logout will not call the CAS Server logout endpoint.
# /logout is resolved against CAS_SERVER_URL.
CAS_LOGOUT_URL=/logout
CAS_SSL_VERIFY=true
CAS_CA_BUNDLE=
```

When CAS omits the role attribute selected by `CAS_ROLE_ATTRIBUTE`, returns it empty, or returns an unsupported role after mapping, Nexent uses `CAS_DEFAULT_ROLE`. Supported default roles are `SU`, `ADMIN`, `DEV`, and `USER`; invalid values fall back to `USER`.

When CAS omits the tenant attribute selected by `CAS_TENANT_ATTRIBUTE` or returns it empty, Nexent uses `CAS_DEFAULT_TENANT_ID`.

`CAS_HEARTBEAT_URL` enables a separate activity-driven heartbeat for CAS users. The first visible-page activity sends a GET immediately; later clicks, keyboard input, mouse movement, touch input, focus, or visibility changes send at most one request per `CAS_HEARTBEAT_INTERVAL_SECONDS` across browser tabs. If the configured Cookie is readable, Nexent sends `X-Auth-Token: <cookie-name>=<cookie-value>`; otherwise it sends the heartbeat without that header. The heartbeat endpoint must allow the Nexent origin, GET, OPTIONS, and `X-Auth-Token` through CORS. This heartbeat only keeps the authentication source active; the existing silent renewal continues to refresh the local Nexent session.

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

Add the following settings to `deploy/env/.env`. Replace the placeholders in angle brackets with the values for your installation.

```bash
CAS_ENABLED=true
CAS_SERVER_URL='https://<ModelEngine IP>:5443/SSOSvr'
CAS_VALIDATE_PATH=/p3/serviceValidate
CAS_CALLBACK_BASE_URL='http://<Nexent IP>:3000'
CAS_LOGIN_MODE=force
CAS_USER_ATTRIBUTE=userName
CAS_EMAIL_ATTRIBUTE=email
CAS_ROLE_ATTRIBUTE=userType
CAS_DEFAULT_ROLE=USER
CAS_TENANT_ATTRIBUTE=tenant_id
CAS_DEFAULT_TENANT_ID=tenant_id
CAS_ROLE_MAP_JSON='{"1":"ADMIN","3":"DEV"}'
CAS_SESSION_MAX_AGE_SECONDS=3600
LOCAL_SESSION_MAX_AGE_SECONDS=3600
CAS_HEARTBEAT_URL='https://<ModelEngine IP>:5443/<heartbeat-path>'
CAS_HEARTBEAT_INTERVAL_SECONDS=300
CAS_HEARTBEAT_COOKIE_NAME='<cookie-name>'
CAS_RENEW_BEFORE_SECONDS=300
CAS_RENEW_TIMEOUT_SECONDS=10
CAS_SYNTHETIC_EMAIL_DOMAIN=cas.local
CAS_LOGOUT_URL='/logout?service=http://<Nexent IP>:3000'
CAS_SSL_VERIFY=false
CAS_CA_BUNDLE=
```

Save the following JSON as `Nexent-10000001.json`, replacing `<Nexent IP>` with the actual address.

```json
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
```

From a terminal with access to the ModelEngine cluster, copy the registration file into the OMS container and set its owner.

```bash
kubectl cp Nexent-10000001.json model-engine/$(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}'):/opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
kubectl exec -i -n model-engine $(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}') -- chown tomcat:fusioncube /opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
```

### Northbound Interface Configuration (NORTHBOUND_EXTERNAL_URL)

Gateway serves the Northbound APIs on port `5013` by default. Nexent uses `NORTHBOUND_EXTERNAL_URL` to generate A2A agent addresses and external file links. The default is `http://localhost:5013/api`. If a third-party system connects from another host, set this variable in `deploy/env/.env` to a Gateway or reverse proxy address that system can reach. Keep the trailing `/api`, as in the following HTTPS example.

```dotenv
NORTHBOUND_EXTERNAL_URL=https://api.yourdomain.com/api
```

## 🤖 Official Agent Deployment

After Nexent is deployed, you can install official agents from the official agent resources included in the deployment package. Official agent deployment is decoupled from the Nexent platform deployment and does not run automatically when the platform starts.

### Prerequisites

Before deployment, make sure that:

1. Nexent has been deployed with Docker or Kubernetes;
2. The `nexent-config` service is running and database initialization is complete;
3. The deployment package contains `deploy/official-agents`;
4. Docker deployments use Git Bash or WSL to run the script; Kubernetes deployments use a terminal with access to the target cluster.

No additional environment variables are required, and users do not need to run Git commands, `docker cp`, or the synchronization API manually.

### Interactive Deployment

Run the following command from the Nexent repository root:

```bash
bash deploy/deploy-official-agents.sh
```

The script scans the actual first-level directories under `deploy/official-agents` and presents them as the available profiles. You can enter one profile, multiple profiles such as `2,3`, or `all` to install every profile. The script validates the directories and `agent.json` files. Invalid selections stop before any copy or synchronization operation.

For Docker deployments, the selected profiles are copied to `/mnt/nexent/official-agents/` in the `nexent-config` container and then synchronized to the official agent repository.

For Kubernetes deployments, run:

```bash
bash deploy/deploy-official-agents.sh --kubernetes
```

To specify a namespace:

```bash
bash deploy/deploy-official-agents.sh \
  --kubernetes \
  --namespace custom-namespace
```

### Using Official Agents After Deployment

After deployment, users can find the templates in the **Agent Repository** under the official agent list. When copying an official agent, follow the dialog to select models and choose whether to reuse or create the required knowledge bases, Skills, and MCP configurations.

The deployment stage only publishes templates. It does not create knowledge bases for every tenant. When an official agent includes a knowledge base, the target tenant must have an available embedding model when the agent is copied for the first time.

### Verification

For Docker deployments, inspect the copied resources with:

```bash
docker exec nexent-config find /mnt/nexent/official-agents -name agent.json -print
```

Then sign in to Nexent, open the **Agent Repository**, switch to the official agent list, and confirm that the selected profiles are available.

### Delete an Official Agent

Deleting an official template requires Super Administrator privileges:

1. Open **Resource Management**;
2. Open the **Agents** page;
3. Click **Manage Official Agents**;
4. Select the template and confirm deletion.

This removes the official repository listing, the source Agent in the system tenant, and the corresponding server-side Bundle files. Agent copies already created in regular tenants are not deleted.

## 💡 Need Help

- Browse the [FAQ](./faq) for common install issues
- Drop questions in our [Discord community](https://discord.gg/tb5H3S3wyv)
- File bugs or feature ideas in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues)

## 🔧 Build from Source

Want to build from source or add new features? Check the [Docker Build Guide](../deployment/docker-build) for step-by-step instructions.

For detailed setup instructions and customization options, see our [Developer Guide](../developer-guide/overview).
