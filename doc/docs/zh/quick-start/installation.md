# 基于 Docker 安装部署

## 环境准备

### 🎯 系统要求

| 资源 | 最低要求 | 推荐配置 |
|----------|---------|-------------|
| **CPU**  | 4 核 | 8 核 |
| **内存**  | 8 GiB | 16 GiB |
| **磁盘** | 40 GiB | 100 GiB |
| **架构** | x86_64 / ARM64 | |
| **软件** | Docker Engine 18.09+、Docker Compose v2 | 使用仍受维护的 Docker Engine 和 Compose v2 |

> **💡 注意**：推荐配置适合启用完整应用、数据处理和 Docker 沙箱的环境。模型服务通常独立部署，不计入上表资源。

### 安装 Docker 和 Compose

| 部署主机 | 安装方法 |
| --- | --- |
| Linux 服务器 | 按发行版的官方步骤配置软件仓库，安装 Docker Engine、命令行工具和 Compose 插件，然后启动 Docker 服务。已有 Engine 的主机可单独补装 Compose 插件。[安装 Docker Engine](https://docs.docker.com/engine/install/) · [安装 Compose 插件](https://docs.docker.com/compose/install/linux/) |
| macOS 或 Windows 开发机 | 安装并启动 Docker Desktop，它自带 Docker Engine 和 Compose。Windows 上使用 Linux 容器，并在可运行 Bash 的终端执行后续部署命令。[在 macOS 上安装 Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) · [在 Windows 上安装 Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) |

用准备执行部署的账号，在同一终端运行以下命令。已有 Docker 环境可以直接从这里开始检查。

```bash
docker version
docker compose version
```

`docker version` 应同时显示 `Client` 和 `Server` 信息，第二条命令应输出 Compose 版本。如果只看到客户端信息并提示连接失败，先确认 Docker 服务或 Docker Desktop 已启动，并检查当前账号能否访问 Docker。检查通过后，在线和离线部署均可继续。

## 🚀 快速开始

- [在线部署](#在线部署)
- [离线部署](#离线部署)

### 在线部署

#### 1. 下载和设置

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
```

Docker 和 Kubernetes 共用 `deploy/env/.env`。部署脚本会保留已有值，补充模板中新增的变量。如果该文件不存在，脚本优先复用旧版 `docker/.env`，否则从 `deploy/env/.env.example` 创建。全新安装需要预设管理员密码或持久化目录时，可先将模板复制为 `deploy/env/.env`，再编辑所需设置。

#### 2. 部署选项

运行以下命令开始部署：

```bash
bash deploy.sh docker
```

安装开始时，终端会显示本次部署日志的路径。日志默认保存在仓库或离线包根目录的 `logs/deploy/deploy-YYYYMMDD-HHMMSS.log`。如果部署失败，打开终端提示的文件，查看镜像加载、拉取或 Compose 启动阶段的具体报错。安装器生成的 Elasticsearch API Key 保存在 `deploy/env/.env` 的 `ELASTICSEARCH_API_KEY` 中。

执行此命令后，系统会通过 Bash TUI 选择部署参数。可使用方向键或 `j/k` 移动，空格切换多选项，回车确认，`b`/Backspace 返回上一步，`q` 退出。

**组件组合**

| 组件 | 默认选择 | 用途 |
| --- | --- | --- |
| `infrastructure` | 必选 | 提供 Elasticsearch、PostgreSQL、Redis 和 MinIO。 |
| `application` | 是 | 启动 Web、Gateway、Management、Runtime、MCP 和 Ops 服务。需要访问网页、运行智能体或查看运行轨迹时，保留此项。 |
| `data-process` | 是 | 启动数据处理服务，供知识库解析、导入文件使用。 |
| `terminal` | 否 | 为智能体的终端工具提供 OpenSSH 服务。 |
| `monitoring` | 否 | 将遥测数据发送到所选 OpenTelemetry 后端。 |

**沙箱模式**默认选用轻量镜像（`lightweight`）。如果 Skill 依赖文档处理、设计或前端构建工具，可选择 `full` 镜像。Runtime 根据执行策略创建和复用沙箱容器。

**端口策略**默认为 `development`，会向宿主机发布数据库和内部服务的调试端口。`production` 收起这些端口，基础应用仍发布 Web、Gateway 和 Ops，默认分别为 3000、5013 和 5016。

**镜像来源**默认为 `general`（标准公开仓库）。也可以选 `mainland`（中国大陆镜像源），或用 `local-latest` 复用本地已有的 Nexent 应用镜像。

要跳过配置菜单，可使用 `--defaults` 并按需覆盖选项。以下命令分别演示不同的安装方式，选择其中一条执行即可。

```bash
# 使用已保存的 deploy.options 或内置默认值，不进入 TUI
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

#### HTTPS（可选）

Docker 默认通过 HTTP 的 3000 端口提供 Web 页面。启用 HTTPS 后，随部署安装的 Nginx 通过 3100 端口提供加密访问，并将请求转发给 Web。HTTP 入口可通过 `deploy/env/.env` 中的 `NEXENT_WEB_PORT` 调整。使用 `production` 端口策略时，HTTPS 入口也可通过 `NEXENT_HTTPS_PORT` 调整。

可交互启用（安装器只询问一个问题：HTTPS 模式），也可非交互启用：

```bash
# 自签证书（内网部署推荐）
bash deploy.sh docker --defaults --https-mode self-signed

# 使用自己的证书（路径也可以预先写入 deploy/env/.env）
bash deploy.sh docker --defaults --https-mode custom --https-cert-file /path/to/server.pem --https-key-file /path/to/server.key
```

- **self-signed**：安装器生成 99 年有效期的自签证书（私钥不加密），保存在 `<ROOT_DIR>/nginx/ssl/`，重复部署时自动复用。SAN 条目从部署主机网卡自动探测（排除回环与 Docker 网桥）；如需指定，在 `deploy/env/.env` 预填 `NEXENT_HTTPS_SAN`（例如 `NEXENT_HTTPS_SAN=10.0.0.5,example.com`）。浏览器会提示证书不受信任，将证书导入系统信任链后即可消除。
- **custom**：通过 `NEXENT_HTTPS_CERT_FILE` 与 `NEXENT_HTTPS_KEY_FILE` 指定 PEM 证书与私钥。安装器在部署前校验证书对（PEM 格式、证书与私钥匹配、有效期）。支持加密私钥：通过 `NEXENT_HTTPS_KEY_PASSPHRASE` 或 `--https-key-passphrase` 提供密码；与其他部署凭证一致，密码以明文保存在 `deploy/env/.env` 中。
- 使用 OAuth 或 CAS 登录时，请把对应的 `OAUTH_CALLBACK_BASE_URL` 或 `CAS_CALLBACK_BASE_URL` 设为浏览器实际使用的地址，例如 `https://nexent.example.com:3100`。如已配置固定的对话分享地址，也请更新 `SHARE_BASE_URL`。
- 再次禁用 HTTPS（`--https-mode disabled`）后，Nginx 容器会被移除；证书文件会保留，之后可重新启用。

部署成功后，非敏感部署选项会保存到 `deploy/docker/deploy.options`。`--defaults` 会优先复用该文件；文件不存在时使用内置默认值。下次交互部署时可选择复用本地配置或重新全量配置。


#### 首次安装的管理员密码

安装完整应用时，系统会创建超级管理员 `suadmin@nexent.com`。首次安装前可在 `deploy/env/.env` 中设置 `NEXENT_SUPER_ADMIN_PASSWORD`，默认值为 `Nexent@123`。脚本自动创建账号后，会在终端显示此次使用的密码。使用离线包并显式指定 `--config` 时，按提示输入并确认密码，终端会隐藏输入内容。

### 离线部署

目标服务器无法访问公网镜像仓库时，可从 GitHub Actions 获取已经打包好的离线部署包：

1. 登录 GitHub，打开 [Build Offline Deployment Package](https://github.com/ModelEngine-Group/nexent/actions/workflows/build-offline-package.yml)。
2. 选择目标版本对应的成功运行记录，在页面底部的 **Artifacts** 中下载与服务器架构匹配的压缩包。
3. `amd64` 服务器下载 `nexent-<version>-amd64.zip`，ARM64 服务器下载 `nexent-<version>-arm64.zip`。

GitHub Actions 构建产物默认保留 30 天。如果目标版本的产物已过期，请联系维护者重新运行工作流。

下载后，将压缩包复制到离线服务器。把下例中的文件名替换为实际下载的文件名，再解压并运行安装脚本。

```bash
unzip 'nexent-<version>-amd64.zip' -d nexent
cd nexent
bash deploy.sh --load-images docker
```

离线包默认跳过配置菜单。包内 `manifest.yaml` 列出了打包时选定的组件和镜像。官方工作流包含基础设施、应用、数据处理和终端工具镜像。需要启用终端工具或重新选择组件时，可以添加 `--config`。离线环境所选组件及沙箱模式所需的镜像须已包含在包内或预先导入服务器。

```bash
bash deploy.sh --load-images --config docker
```

如果服务器上保留了此前已部署的离线包，可通过 `--reuse-from` 复用其中的环境配置和部署选项：

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  docker
```

指定目录必须是已解压的旧部署包根目录，并包含 `deploy/env/.env`。该参数会导入旧 `.env`、保留其已有值，并立即追加当前包 `.env.example` 新增的变量。存在 `monitoring.env` 和 Docker `deploy.options` 时也会复用；Docker 派生配置由新版本脚本重新生成。`--reuse-from` 可与 `--config`、`--defaults` 或 `--push-images` 组合使用。

如果需要先将镜像推送到目标环境可访问的内部仓库：

```bash
bash deploy.sh \
  --push-images \
  --image-registry-prefix registry.example.com/nexent \
  docker
```

未传入仓库前缀时，脚本会先询问前缀；随后 `push-images.sh` 会在推送前询问仓库用户名和密码。

### 访问您的安装

1. 在安装主机上打开 `http://localhost:3000`。从其他设备访问时，使用部署主机的域名或 IP。若已启用内置 HTTPS，默认地址为 `https://<部署主机>:3100`。
2. 使用超级管理员 `suadmin@nexent.com` 及首次安装时的密码登录。在 **租户资源** 中创建租户并邀请租户管理员。
3. 使用租户管理员账号登录，按需配置模型和资源。具体操作见[用户指南](../user-guide/home-page)。

认证 Cookie 默认带有 `Secure` 属性。从其他设备访问时请优先使用 HTTPS，包括由外部反向代理提供的 HTTPS。如果隔离测试环境只能通过远程主机的 HTTP 地址访问，在 `deploy/env/.env` 中设置 `NEXENT_AUTH_COOKIE_SECURE=false` 后，使用原部署选项重新部署。启用 HTTPS 时应设回 `true`。

可在部署主机查看容器状态和 Gateway、Ops 的就绪情况。以下命令使用默认端口。

```bash
docker ps -a --filter label=com.docker.compose.project=nexent
curl --fail http://localhost:5013/health/ready
curl --fail http://localhost:5016/health/ready
```

如果 Web 已经打开，但调用管理接口失败，可以用 Gateway 镜像自带的 `curl` 从容器内检查 Management 是否就绪。以下命令也适用于仅在容器网络内提供 Management 服务的生产端口策略。

```bash
docker exec nexent-gateway curl --fail --show-error --silent --noproxy '*' --max-time 5 http://nexent-config:5010/health/ready
```

历史账号迁移、管理员账号异常和数据恢复请参阅[统一迁移与排障手册](https://github.com/ModelEngine-Group/nexent/blob/develop/deploy/sql/tools/supabase_to_postgres/README.md)。


## 📦 服务架构

Nexent 采用微服务架构，通过 Docker Compose 进行部署。

**应用服务**

| 服务 | 描述 | 默认端口 |
|---------|-------------|--------------|
| nexent-web | Web 界面，浏览器请求通过 Gateway 访问后端 | 3000 |
| nexent-gateway | 统一 API 入口，负责身份校验并向 Management、Runtime 和 Ops 转发请求 | 5013 |
| nexent-config | Management 服务，负责配置、资源管理和北向业务 API | 5010 |
| nexent-runtime | 智能体运行时 API | 5014 |
| nexent-mcp | MCP 管理与工具服务 | 5011/5015 |
| nexent-ops | 运维指标和历史轨迹查询 | 5016 |

**基础设施服务**

| 服务 | 描述 |
|---------|-------------|
| nexent-postgresql | 关系型数据库 |
| nexent-elasticsearch | 搜索引擎和索引服务 |
| nexent-minio | S3 兼容对象存储 |
| redis | 缓存、分布式锁和任务消息代理 |

**可选服务**

| 服务或组件 | 描述 |
|---------|-------------|
| nexent-data-process | 数据处理 API（5012 端口）和后台处理任务 |
| nexent-openssh-server | AI 智能体 SSH 终端 |
| monitoring | 安装 OpenTelemetry Collector，并按所选后端启动对应的监控服务 |

**按需执行环境**

| 组件 | 描述 |
|---------|-------------|
| nexent-sandbox | Runtime 按策略创建的隔离执行环境，用于运行模型生成的代码和 Skill 脚本 |

## 💾 数据持久化

Docker 部署将数据库、对象存储和原始轨迹保存到宿主机目录。默认根目录是运行部署脚本的用户的 `$HOME/nexent-data`，可以在 `deploy/env/.env` 中通过 `ROOT_DIR` 指定其他位置。

| 数据 | 默认挂载方式和位置 |
| --- | --- |
| PostgreSQL | 宿主机目录 `${ROOT_DIR}/postgresql/data` |
| Elasticsearch | 宿主机目录 `${ROOT_DIR}/elasticsearch` |
| Redis | 宿主机目录 `${ROOT_DIR}/redis` |
| MinIO | 宿主机目录 `${ROOT_DIR}/minio/data` |
| 会话轨迹 | 宿主机目录 `${ROOT_DIR}/trajectory`，默认挂载到容器内的 `/mnt/nexent-data/trajectory`，供 Management、Runtime 和 Ops 共用 |
| 服务日志 | 宿主机目录 `${ROOT_DIR}/logs` |
| 智能体运行工作区 | Docker 命名卷 `nexent-agent-workspace`，通过 `NEXENT_SANDBOX_WORKSPACE_VOLUME` 指定 |

### 卸载 Docker 部署

请在仓库根目录使用统一卸载入口：

```bash
# 停止并删除容器；是否删除持久化数据由交互确认
bash uninstall.sh docker

# 非交互卸载并保留数据
bash uninstall.sh docker --keep-volumes

# Remove volumes and deployment-managed data directories
bash uninstall.sh docker --delete-volumes true

# Remove containers, volumes, and deployment-managed data directories
bash uninstall.sh docker delete-all
```

如果后续需要复用已有数据，请选择保留 volumes。选择删除数据时，脚本会移除数据库、对象存储、Skill 等服务目录。`${ROOT_DIR}/trajectory` 和 `${ROOT_DIR}/logs` 会留在宿主机上。

## 🔌 端口映射

下表列出 `development` 策略下常用的宿主机映射。`production` 策略默认发布 Web、Gateway 和 Ops 端口，启用 HTTPS 后还会发布 Nginx 端口。

| 服务 | 内部端口 | 外部端口 | 描述 |
|---------|---------------|---------------|-------------|
| Web 界面 | 3000 | 3000（`NEXENT_WEB_PORT`） | 主应用程序访问 |
| HTTPS 入口 | 3100 | 3100 | 可选，启用 HTTPS 后的加密访问入口（Nginx） |
| Gateway API | 5013 | 5013 | Web 和北向 API 的统一入口 |
| Ops API | 5016 | 5016 | 运维与历史轨迹服务 |
| Management API | 5010 | 5010 | 配置与管理服务 |
| Runtime API | 5014 | 5014 | 智能体运行时服务 |
| MCP API | 5011/5015 | 5011/5015 | MCP 管理与工具服务 |
| 数据处理 | 5012 | 5012 | 数据处理 API |
| PostgreSQL | 5432 | 5434 | 数据库连接 |
| Elasticsearch | 9200 | 9210 | 搜索引擎 API |
| MinIO API | 9000 | 9010 | 对象存储 API |
| MinIO 控制台 | 9001 | 9011 | 存储管理 UI |
| Redis | 6379 | 6379 | 缓存服务 |
| SSH 服务器 | 22 | 2222 | 终端工具访问 |

使用开发容器时，端口转发方式见[开发容器指南](../deployment/devcontainer)。

## 🔧 高级配置

Docker 部署模板默认使用系统级沙箱，可在多次运行之间复用容器。Runtime 通过独立工作区卷交换上传文件和生成文件，运行结束后将需要保留的产物同步到 MinIO。

常用配置位于 `deploy/env/.env`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXENT_SANDBOX_DEFAULT_LEVEL` | `docker` | 隔离级别，可选 `local`、`docker`、`wasm` |
| `NEXENT_SANDBOX_DEFAULT_SCOPE` | `system` | 容器生命周期，可选 `session` 或 `system` |
| `NEXENT_SANDBOX_DOCKER_IMAGE` | `nexent/nexent-sandbox:latest` | Docker 沙箱镜像 |
| `NEXENT_SANDBOX_WORKSPACE_VOLUME` | `nexent-agent-workspace` | Runtime 与沙箱共享的 Docker 卷 |
| `NEXENT_SANDBOX_MEMORY_LIMIT_MB` | `2048` | 沙箱内存上限，单位为 MiB |
| `NEXENT_SANDBOX_CPU_QUOTA` | `1.0` | 沙箱 CPU 配额 |
| `NEXENT_SANDBOX_TIMEOUT_S` | `30` | 单步执行超时，单位为秒 |
| `NEXENT_SANDBOX_NETWORK` | `disabled` | 是否允许沙箱访问网络 |
| `NEXENT_SANDBOX_SHELL_POLICY` | `disabled` | Shell 调用策略，可选 `disabled`、`restricted`、`boxed` |
| `NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS` | `true` | 是否自动将输出文件同步到 MinIO |
| `AGENT_WORKSPACE_ROOT` | `/mnt/nexent/workdir` | 每次运行的临时文件工作区 |

生产环境不建议将隔离级别改为 `local`。调整资源、网络或 Shell 策略后，需要重新部署 Runtime。

### 监控配置

运维看板按 `OPS_MONITORING_TIMEZONE` 划分统计日期。新安装使用的 `deploy/env/.env.example` 默认配置为 `Asia/Shanghai`。已有部署沿用 `deploy/env/.env` 中保存的时区。

#### 在可观测中心查看本地轨迹

按默认选项部署 `application` 后，Runtime 会采集智能体会话的执行轨迹，Ops 提供历史查询。只使用 Nexent 自带的可观测中心时，保留默认组件选择即可。

1. 在 `deploy/env/.env` 中确认 `LOCAL_FILE_MONITORING_ENABLED=true`（默认值）。部署脚本会在 `deploy/env/monitoring.env` 中同步采集开关，并写入 `TRAJECTORY_READ_ENABLED=true` 以启用历史查询。
2. 部署完成后，运行以下命令检查 Ops 容器，正常时输出 `healthy`。默认配置将宿主机的 `${ROOT_DIR}/trajectory` 挂载到 Config、Runtime 和 Ops 容器内的 `/mnt/nexent-data/trajectory`，三个服务需要访问同一份文件。

   ```bash
   docker inspect --format '{{.State.Health.Status}}' nexent-ops
   ```

3. 在智能体对话中完成一轮问答，复制顶部的会话 ID。使用有页面权限的运维管理员或超级管理员账号，在 **可观测中心** 搜索该 ID 并打开会话详情。操作示例见[可观测中心](../user-guide/observability)。

如需停止采集新对话并继续查看保留期内的历史轨迹，在 `deploy/env/.env` 中设置 `LOCAL_FILE_MONITORING_ENABLED=false`，在 `deploy/env/monitoring.env` 中保留 `TRAJECTORY_READ_ENABLED=true`，然后执行 `bash deploy.sh docker --defaults` 使配置生效。

#### 向第三方平台导出轨迹

需要同时向其他平台上报时，在部署菜单中额外勾选 `monitoring` 并选择目标。本地采集开关独立生效。例如，以下命令在默认应用组件的基础上部署 Phoenix。

```bash
bash deploy.sh docker --components infrastructure,application,data-process,monitoring --monitoring-provider phoenix
```

| 目标 | 部署后的访问方式 |
| --- | --- |
| `otlp` | 启动 OpenTelemetry Collector，默认通过调试导出器输出到 Collector 日志。 |
| `phoenix` | 启动本地 Phoenix，在部署主机访问 `http://localhost:6006`。 |
| `langfuse` | 启动本地 Langfuse，在部署主机访问 `http://localhost:3001`。 |
| `langsmith` | 将轨迹发送到托管的 LangSmith，部署前在 `deploy/env/monitoring.env` 中填写 `LANGSMITH_API_KEY`，并按需设置 `LANGSMITH_PROJECT`。 |

第三方面板的地址和可见角色分别由 `MONITORING_DASHBOARD_URL` 和 `MONITORING_DASHBOARD_ALLOWED_ROLES` 控制。远程用户需要能从浏览器访问该地址。若需调整 Phoenix 或 Langfuse 的端口，编辑 `deploy/env/monitoring.env` 中的 `PHOENIX_PORT` 或 `LANGFUSE_PORT`，同步修改面板地址并重新部署。

### OAuth 登录配置

OAuth 登录使用 application 中的本地账号。启用第三方登录时，请将 `OAUTH_CALLBACK_BASE_URL` 设置为浏览器可访问的 Nexent Web 地址。

```bash
bash deploy.sh docker --components infrastructure,application
```

Docker 部署在 `deploy/env/.env` 中配置 OAuth：

```bash
# Web 入口地址。回调完整路径会自动拼接为：
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

# 访问 OAuth provider 时的 TLS 校验
OAUTH_SSL_VERIFY=true
OAUTH_CA_BUNDLE=

# disabled: 隐藏 OAuth 登录入口并禁用自动跳转
# button: 显示已配置的 OAuth 登录按钮
# force: 恰好配置一个 Provider 时，未登录用户自动跳转
OAUTH_LOGIN_MODE=button
```

Provider 启用规则：

| Provider | 必填变量 | 回调地址 |
|----------|----------|----------|
| GitHub | `GITHUB_OAUTH_CLIENT_ID`、`GITHUB_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `GDE_URL`、`GDE_OAUTH_CLIENT_ID`、`GDE_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| Link App | `LINK_APP_URL`、`LINK_APP_OAUTH_CLIENT_ID`、`LINK_APP_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=link_app` |
| WeChat | `ENABLE_WECHAT_OAUTH=true`、`WECHAT_OAUTH_APP_ID`、`WECHAT_OAUTH_APP_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

本地默认回调示例为 `http://localhost:3000/api/user/oauth/callback?provider=github`。生产环境应改为公网 HTTPS 域名，例如 `https://nexent.example.com/api/user/oauth/callback?provider=github`，并在 OAuth provider 控制台中登记相同地址。

`OAUTH_LOGIN_MODE` 支持 `disabled`、`button`、`force`，默认为 `button`。`force` 模式下，恰好有一个 Provider 满足启用条件时，未登录访问 Nexent 会直接跳转到该 Provider；没有可用 Provider 时禁用 OAuth，多个 Provider 时回退到登录按钮。若同时配置了 CAS `force` 模式，CAS 优先。

### CAS 登录配置

CAS SSO 使用本地账号。启用 CAS 时，请将 `CAS_CALLBACK_BASE_URL` 设置为浏览器可访问的 Nexent Web 地址，且不要带结尾 `/`。`CAS_SERVER_URL` 是 CAS Server 根地址，也不要带结尾 `/`。

Docker 部署在 `deploy/env/.env` 中配置 CAS：

```bash
CAS_ENABLED=true
CAS_SERVER_URL=http://localhost:8080/cas
# 可选：后端容器访问 CAS 的内部地址；为空时复用 CAS_SERVER_URL。
CAS_INTERNAL_SERVER_URL=
CAS_VALIDATE_PATH=/p3/serviceValidate
CAS_CALLBACK_BASE_URL=http://localhost:3000

# disabled: 禁用 CAS 登录入口和自动跳转
# button: 在登录页显示 CAS 登录按钮
# force: 未登录访问 Nexent 时自动跳转到 CAS
CAS_LOGIN_MODE=force

# 为空时使用 <cas:user>；填写 userName 时从 <cas:attributes><cas:userName> 取用户标识
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

# 为空时 Nexent 主动退出不会调用 CAS Server 登出接口。
# 可配置为 /logout，系统会基于 CAS_SERVER_URL 拼接。
CAS_LOGOUT_URL=/logout
CAS_SSL_VERIFY=true
CAS_CA_BUNDLE=
```

CAS 未返回 `CAS_ROLE_ATTRIBUTE` 指定的角色属性、属性为空或映射后的角色不受支持时，使用 `CAS_DEFAULT_ROLE`。支持的默认角色为 `SU`、`ADMIN`、`DEV` 和 `USER`；配置无效时回退到 `USER`。

CAS 未返回 `CAS_TENANT_ATTRIBUTE` 指定的租户属性或属性为空时，使用 `CAS_DEFAULT_TENANT_ID`。

`CAS_HEARTBEAT_URL` 用于启用独立的 CAS 用户活动心跳。页面可见时，首次用户活动立即发送 GET；之后点击、键盘、鼠标、触摸、窗口聚焦或页面可见性变化在所有浏览器标签页中每 `CAS_HEARTBEAT_INTERVAL_SECONDS` 最多发送一次。若配置的 Cookie 可被前端读取，请求会携带 `X-Auth-Token: <cookie-name>=<cookie-value>`；读取不到时仍发送心跳，但不带该 Header。由于浏览器直接访问心跳地址，认证源必须通过 CORS 允许 Nexent Origin、GET、OPTIONS 和 `X-Auth-Token`。心跳只保活认证源会话，现有无感续期仍负责刷新 Nexent 本地会话。

常用 CAS 地址：

| 用途 | 地址 |
|------|------|
| Nexent 登录入口 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/login?redirect=/` |
| CAS service 回调 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/callback` |
| CAS 无感续期回调 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/renew_callback` |
| CAS 单点登出回调 | `POST {CAS_CALLBACK_BASE_URL}/api/user/cas/logout_callback` |

Apereo CAS 使用 JSON Service Registry 时，可以新增一个服务注册文件，例如 `Nexent-10001.json`。文件需要放到 CAS 部署配置的 service registry 目录中，`id` 必须全局唯一。下面是本地 Docker 示例：

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

生产环境建议保持 `CAS_SSL_VERIFY=true`；自签名证书优先配置 `CAS_CA_BUNDLE`，仅本地验证时再临时设置 `CAS_SSL_VERIFY=false`。

#### CAS 对接 ModelEngine

在 `deploy/env/.env` 中填写以下配置，将尖括号及其中的文字替换为实际值。

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

将以下 JSON 保存为 `Nexent-10000001.json`，并把其中的 `<Nexent IP>` 替换为实际地址。

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

然后在管理 ModelEngine 集群的终端，将注册文件复制到 OMS 容器并设置属主。

```bash
kubectl cp Nexent-10000001.json model-engine/$(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}'):/opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
kubectl exec -i -n model-engine $(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}') -- chown tomcat:fusioncube /opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
```

### 北向接口配置 (NORTHBOUND_EXTERNAL_URL)

Gateway 提供北向接口，默认端口为 `5013`。Nexent 使用 `NORTHBOUND_EXTERNAL_URL` 生成 A2A 智能体地址和对外文件链接，默认值为 `http://localhost:5013/api`。第三方系统从其他主机调用时，请在 `deploy/env/.env` 中填写对方能访问的 Gateway 或反向代理地址，保留末尾的 `/api`。以下示例使用 HTTPS 域名。

```dotenv
NORTHBOUND_EXTERNAL_URL=https://api.yourdomain.com/api
```

## 🤖 官方智能体部署

Nexent 主平台安装完成后，可以从部署包中的官方智能体资源目录安装指定行业的官方智能体。官方智能体部署与 Nexent 主平台部署解耦，不会在平台启动时自动安装。

### 部署前提

执行前请确认：

1. Nexent 已完成 Docker 或 Kubernetes 部署；
2. `nexent-config` 服务已启动并完成数据库初始化；
3. 部署包中存在 `deploy/official-agents` 目录；
4. Docker 环境使用 Git Bash 或 WSL 执行脚本；Kubernetes 环境使用能够访问目标集群的终端执行脚本。

官方智能体资源不需要额外配置环境变量，也不需要用户手工执行 Git、`docker cp` 或同步接口。

### 交互式部署

在 Nexent 仓库根目录执行：

```bash
bash deploy/deploy-official-agents.sh
```

脚本会扫描 `deploy/official-agents` 下实际存在的一级目录，并将这些目录作为可选 Profile 显示。可以输入单个 Profile、多个 Profile（例如 `2,3`），或输入 `all` 安装全部 Profile。脚本会校验目录和 `agent.json`，选择无效时不会执行复制或同步。

Docker 部署时，脚本会将选中的 Profile 复制到 `nexent-config` 容器的 `/mnt/nexent/official-agents/`，然后同步到官方智能体仓库。

Kubernetes 环境执行：

```bash
bash deploy/deploy-official-agents.sh --kubernetes
```

如需指定命名空间：

```bash
bash deploy/deploy-official-agents.sh \
  --kubernetes \
  --namespace custom-namespace
```

### 部署后的使用方式

部署完成后，用户可以在 **智能体仓库** 的官方列表中复制智能体。复制时可以根据页面提示选择模型，并选择复用或创建知识库、Skill 和 MCP 配置。

官方智能体部署阶段只发布模板，不会为所有租户自动创建知识库。包含知识库的官方智能体在首次复制时，要求目标租户配置可用的向量模型。

### 部署验证

Docker 环境可以查看已复制的资源：

```bash
docker exec nexent-config find /mnt/nexent/official-agents -name agent.json -print
```

登录 Nexent 后，打开 **智能体仓库**，切换到官方智能体列表，确认所选 Profile 中的模板已经出现。

### 删除官方智能体

删除官方模板需要超级管理员权限：

1. 进入 **资源管理**；
2. 打开 **智能体** 页面；
3. 点击 **管理官方智能体**；
4. 选择需要删除的官方模板并确认。

删除操作会删除官方智能体仓库条目、system 租户中的官方源 Agent 和服务器上的对应 Bundle 文件；已经复制到普通租户中的 Agent 副本不会被删除。

## 💡 需要帮助

- 浏览 [常见问题](./faq) 了解常见安装问题
- 在我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 提问
- 在 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 中提交错误报告或功能建议

## 🔧 从源码构建

想要从源码构建或添加新功能？查看 [Docker 构建指南](../deployment/docker-build) 获取详细说明。

有关详细的安装说明和自定义选项，请查看我们的 [开发者指南](../developer-guide/overview)。
