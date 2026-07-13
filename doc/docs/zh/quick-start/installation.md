# 基于 Docker 安装部署

## 🎯 系统要求

| 资源 | 最低要求 | 推荐配置 |
|----------|---------|-------------|
| **CPU**  | 4 核 | 8 核 |
| **内存**  | 8 GiB | 16 GiB |
| **磁盘** | 40 GiB | 100 GiB |
| **架构** | x86_64 / ARM64 | |
| **软件** | 已安装 Docker 和 Docker Compose | Docker 24+, Docker Compose v2+ |

> **💡 注意**：推荐的 **8 核 16 GiB 内存** 配置可确保生产环境下的良好性能。

## 🚀 快速开始

### 1. 下载和设置

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
```

> **💡 提示**: `deploy.sh` 使用 `deploy/env/.env` 作为运行配置。已有 `deploy/env/.env` 会原样保留；如果不存在，会优先复用 `docker/.env`，再回退到 `deploy/env/.env.example`。若需要配置语音模型（STT/TTS），请部署前或部署后修改 `deploy/env/.env` 中的相关参数。

### 2. 部署选项

运行以下命令开始部署：

```bash
bash deploy.sh docker
```

执行此命令后，系统会通过 Bash TUI 选择部署参数。可使用方向键或 `j/k` 移动，空格切换多选项，回车确认，`b`/Backspace 返回上一步，`q` 退出。

**组件组合:**
- **infrastructure（必选）**: Elasticsearch、PostgreSQL、Redis、MinIO
- **application（默认选中，可取消）**: config、runtime、mcp、northbound、web
- **data-process（默认选中，可选）**: 数据处理服务
- **supabase（默认选中，可选）**: 启用用户、租户和认证能力
- **terminal（可选）**: 启用 OpenSSH 终端工具
- **monitoring（可选）**: 启用观测组件，选择后会继续选择 provider

**端口策略:**
- **development（默认）**: 暴露调试和内部服务端口，便于本地排查
- **production**: 仅发布生产入口端口

**镜像来源:**
- **general（默认）**: 使用标准公开镜像仓库
- **mainland**: 使用中国大陆镜像源
- **local-latest**: 使用本地 `latest` 镜像，避免拉取 Nexent 应用镜像

您也可以通过参数跳过交互：

```bash
# 使用已保存的 deploy.options 或内置默认值，不进入 TUI
bash deploy.sh docker --defaults

# 默认组件组合，development 端口策略，标准镜像源
bash deploy.sh docker --components infrastructure,application,data-process,supabase --port-policy development --image-source general

# 启用用户/租户能力、数据处理和终端工具
bash deploy.sh docker --components infrastructure,application,data-process,supabase,terminal

# 使用中国大陆镜像源
bash deploy.sh docker --image-source mainland

# 使用本地 latest 镜像
bash deploy.sh docker --image-source local-latest
```

部署成功后，非敏感部署选项会保存到 `deploy/docker/deploy.options`。`--defaults` 会优先复用该文件；文件不存在时使用内置默认值。下次交互部署时可选择复用本地配置或重新全量配置。


#### ⚠️ 重要提示

1️⃣ **首次部署 v1.8.0 及以上版本时**，需特别留意 Docker 日志中输出的 `suadmin` 超级管理员账号信息。该账号为系统最高权限账户，密码仅在首次生成时显示，后续无法再次查看，请务必妥善保存。
> 该账号仅用于权限管理，无权开发智能体或创建知识库。请登录该账号，依次完成：访问租户资源→创建租户→创建租户管理员，然后使用租户管理员账号登录,即可使用全部功能。角色权限详情参见 [用户管理](../user-guide/user-management)

2️⃣ 忘记留意 `suadmin` 账号密码？请按照以下步骤操作：
```bash
# Step1: 在supabase容器中删除su账号记录
docker exec -it supabase-db-mini bash
psql -U postgres
select id, email from auth.users;
# 获取 suadmin@nexent.com 账号的 user_id
delete from auth.users where id = 'your_user_id';
delete from auth.identities where user_id = 'your_user_id';

# Step 2: 在 nexent 数据库中删除 su 账号记录
docker exec -it nexent-postgresql bash
psql -U root -d nexent
delete from nexent.user_tenant_t where user_id = 'your_user_id';

# Step 3: 重新部署并记录 su 账号密码
```
### 3. 访问您的安装

部署成功完成后：
1. 在浏览器中打开 **http://localhost:3000**
2. 登录超级管理员账号
3. 访问租户资源 → 创建租户及租户管理员
4. 登录租户管理员账号
5. 参考 [用户指南](../user-guide/home-page) 进行智能体的开发


## 📦 服务架构

Nexent 采用微服务架构，通过 Docker Compose 进行部署。

**应用服务:**
| 服务 | 描述 | 默认端口 |
|---------|-------------|--------------|
| nexent | 后端服务 | 5010 |
| nexent-web | Web 前端 | 3000 |
| nexent-data-process | 数据处理服务 | 5012 |
| nexent-northbound | 北向 API 服务 | 5013 |

**基础设施服务:**
| 服务 | 描述 |
|---------|-------------|
| nexent-postgresql | 关系型数据库 |
| nexent-elasticsearch | 搜索引擎和索引服务 |
| nexent-minio | S3 兼容对象存储 |
| redis | 缓存层 |

**Supabase 服务（选择 `supabase` 组件时）:**
| 服务 | 描述 |
|---------|-------------|
| supabase-kong | API 网关 |
| supabase-auth | 认证服务 |
| supabase-db-mini | 数据库服务 |

**可选服务:**
| 服务 | 描述 |
|---------|-------------|
| nexent-openssh-server | AI 智能体 SSH 终端 |
| nexent-monitoring | 可选观测组件 |

## 💾 数据持久化

Nexent 使用 Docker volumes 进行数据持久化：

| 数据类型 | Volume 名称 | 默认宿主机路径 |
|-----------|------------------|-------------------|
| PostgreSQL | nexent-postgresql-data | `{dataDir}/postgresql` |
| Elasticsearch | nexent-elasticsearch-data | `{dataDir}/elasticsearch` |
| Redis | nexent-redis-data | `{dataDir}/redis` |
| MinIO | nexent-minio-data | `{dataDir}/minio` |
| Supabase DB（选择 supabase 时）| nexent-supabase-db-data | `{dataDir}/supabase-db` |

默认 `dataDir` 为 `./volumes`（可在 `deploy/env/.env` 中配置 `ROOT_DIR`）。

### 卸载 Docker 部署

请在仓库根目录使用统一卸载入口：

```bash
# 停止并删除容器；是否删除持久化数据由交互确认
bash uninstall.sh docker

# 非交互卸载并保留数据
bash uninstall.sh docker --keep-volumes

# 删除 Docker volumes 和 ROOT_DIR 下的 Nexent 数据
bash uninstall.sh docker --delete-volumes true

# 完整清理：容器和持久化数据都会删除
bash uninstall.sh docker delete-all
```

Docker 卸载脚本会读取 `deploy/env/.env` 中的 `ROOT_DIR` 并清理 Compose 资源。删除数据时会移除 `postgresql`、`elasticsearch`、`redis`、`minio`、`volumes`、`openssh-server`、`scripts`、`skills` 等服务目录；如果后续要复用已有数据，请选择保留 volumes。

### 离线镜像包

需要把镜像和部署脚本搬到离线机器时，可使用 `deploy/offline/build_offline_package.sh`：

```bash
bash deploy/offline/build_offline_package.sh \
  --target docker \
  --version v2.2.1 \
  --platform amd64 \
  --components infrastructure,application,data-process,supabase \
  --image-source general \
  --compress true \
  --output-dir offline-package
```

包目录会包含 `images/*.tar`、`load-images.sh`、`push-images.sh`、`deploy.sh`、`uninstall.sh`、`manifest.yaml`、`checksums.txt`、`deploy/env/.env.example`、`deploy/env/monitoring.env.example` 和 `deploy/sql`，不会包含本地 `deploy/env/.env`、`deploy/env/monitoring.env` 或 `deploy.options`。使用 `--compress true` 时，会在输出目录的父目录生成 `nexent-offline-<target>-<platform>-<version>.zip`。

在目标机器上部署时，包根目录的 `deploy.sh` 会优先复用已保存的 `deploy.options`，否则使用内置默认值，默认不进入 TUI。添加 `--config` 可进入交互式配置界面。如果离线包构建时使用了自定义版本、组件、端口策略或镜像源，请在部署时传入相同选项，或使用 `--config` 交互选择：

```bash
cd offline-package
bash deploy.sh --load-images docker
```

如果需要先推送到内部镜像仓库并使用该前缀部署：

```bash
bash deploy.sh --push-images --image-registry-prefix registry.example.com/nexent docker
```

启用 `--push-images` 且未传前缀时，`deploy.sh` 会先询问镜像仓库前缀；随后 `push-images.sh` 在推送前询问仓库账号和密码。

## 🔌 端口映射

| 服务 | 内部端口 | 外部端口 | 描述 |
|---------|---------------|---------------|-------------|
| Web 界面 | 3000 | 3000 | 主应用程序访问 |
| 后端 API | 5010 | 5010 | 后端服务 |
| 数据处理 | 5012 | 5012 | 数据处理 API |
| 北向 API | 5013 | 5013 | 北向接口服务 (A2A/MCP 集成) |
| PostgreSQL | 5432 | 5434 | 数据库连接 |
| Elasticsearch | 9200 | 9210 | 搜索引擎 API |
| MinIO API | 9000 | 9010 | 对象存储 API |
| MinIO 控制台 | 9001 | 9011 | 存储管理 UI |
| Redis | 6379 | 6379 | 缓存服务 |
| SSH 服务器 | 22 | 2222 | 终端工具访问 |

有关完整的端口映射详细信息，请参阅我们的 [开发容器指南](../deployment/devcontainer.md#port-mapping)。

## 🔧 高级配置

### 监控配置

部署时在脚本交互界面中选择 `monitoring` 组件即可启用 OpenTelemetry 监控。脚本会在 `deploy/env/monitoring.env` 中同步更新 `ENABLE_TELEMETRY`、`MONITORING_PROVIDER`、`MONITORING_DASHBOARD_URL`、OTLP endpoint 和 provider 默认值，并启动 `deploy/docker/compose/docker-compose-monitoring.yml` 中对应的观测组件。前端监控入口在 speed 模式下配置 dashboard URL 后可见；标准模式下仅超级管理员可见。

```bash
cd nexent
bash deploy.sh docker
```

如果本地已有 `deploy/docker/deploy.options`，脚本会询问是否复用本地配置。请选择重新配置/覆盖本地配置，然后在组件选择界面勾选 `monitoring`，再在 provider 选择界面手动选择 `grafana`、`phoenix`、`langfuse`、`langsmith`、`zipkin` 或 `otlp`。

支持的 provider：

| Provider | 用途 | 默认访问地址 |
|----------|------|--------------|
| `otlp` | 仅启动 OpenTelemetry Collector，适合转发到外部平台 | 无 Dashboard |
| `phoenix` | 本地 Phoenix 追踪分析 | `http://localhost:6006` |
| `langfuse` | 本地 Langfuse 观测栈 | `http://localhost:3001` |
| `langsmith` | 转发到托管 LangSmith | `https://smith.langchain.com/` |
| `grafana` | 本地 Grafana + Tempo | `http://localhost:3002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1` |
| `zipkin` | 本地 Zipkin | `http://localhost:9411` |

如需调整端口、镜像版本或 Langfuse 初始账号，请先复制并编辑监控环境变量：

```bash
cp deploy/env/monitoring.env.example deploy/env/monitoring.env
```

常用变量：

| 变量 | 说明 |
|------|------|
| `MONITORING_PROVIDER` | 默认监控 provider；部署脚本中手动选择 provider 后会同步更新 |
| `OTEL_COLLECTOR_HTTP_PORT` / `OTEL_COLLECTOR_GRPC_PORT` | Collector 对外暴露的 OTLP HTTP/gRPC 端口 |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | LangSmith 转发配置 |
| `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` | 本地 Langfuse 初始管理员账号 |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | 本地 Grafana 管理员账号 |

选择 `langsmith` provider 前，请先在 `deploy/env/monitoring.env` 中配置 `LANGSMITH_API_KEY`。如果只需要连接已有外部 Collector，也可以在 `deploy/env/monitoring.env` 中调整 OTLP 目标地址：

```bash
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
MONITORING_DASHBOARD_URL=
```

> **生产建议**：请替换示例中的默认密码、密钥和 Langfuse `ENCRYPTION_KEY`，并通过反向代理或防火墙限制 Dashboard、Collector 端口的访问范围。

### OAuth 登录配置

OAuth 登录依赖 `supabase` 组件。启用第三方登录时，请同时部署 `supabase`，并将 `OAUTH_CALLBACK_BASE_URL` 设置为浏览器可访问的 Nexent Web 地址。

```bash
bash deploy.sh docker --components infrastructure,application,supabase
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
```

Provider 启用规则：

| Provider | 必填变量 | 回调地址 |
|----------|----------|----------|
| GitHub | `GITHUB_OAUTH_CLIENT_ID`、`GITHUB_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `GDE_URL`、`GDE_OAUTH_CLIENT_ID`、`GDE_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| Link App | `LINK_APP_URL`、`LINK_APP_OAUTH_CLIENT_ID`、`LINK_APP_OAUTH_CLIENT_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=link_app` |
| WeChat | `ENABLE_WECHAT_OAUTH=true`、`WECHAT_OAUTH_APP_ID`、`WECHAT_OAUTH_APP_SECRET` | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

本地默认回调示例为 `http://localhost:3000/api/user/oauth/callback?provider=github`。生产环境应改为公网 HTTPS 域名，例如 `https://nexent.example.com/api/user/oauth/callback?provider=github`，并在 OAuth provider 控制台中登记相同地址。

### CAS 登录配置

CAS SSO 不依赖 `supabase`。启用 CAS 时，请将 `CAS_CALLBACK_BASE_URL` 设置为浏览器可访问的 Nexent Web 地址，且不要带结尾 `/`。`CAS_SERVER_URL` 是 CAS Server 根地址，也不要带结尾 `/`。

Docker 部署在 `deploy/env/.env` 中配置 CAS：

```bash
CAS_ENABLED=true
CAS_SERVER_URL=http://localhost:8080/cas
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
CAS_TENANT_ATTRIBUTE=tenant_id
CAS_ROLE_MAP_JSON={"cas-admin":"ADMIN","cas-user":"USER"}
CAS_SESSION_MAX_AGE_SECONDS=3600
LOCAL_SESSION_MAX_AGE_SECONDS=3600
CAS_RENEW_BEFORE_SECONDS=300
CAS_RENEW_INTERVAL_SECONDS=300
CAS_RENEW_TIMEOUT_SECONDS=10
CAS_SYNTHETIC_EMAIL_DOMAIN=cas.local

# 为空时 Nexent 主动退出不会调用 CAS Server 登出接口。
# 可配置为 /logout，系统会基于 CAS_SERVER_URL 拼接。
CAS_LOGOUT_URL=/logout
CAS_SSL_VERIFY=true
CAS_CA_BUNDLE=
```

CAS 续期仅在用户近期有点击、键盘、鼠标、触摸、窗口聚焦或页面可见性变化时触发。`CAS_RENEW_INTERVAL_SECONDS` 控制活跃用户访问 CAS Server 的最小间隔；无操作或页面隐藏时不会保活。`CAS_RENEW_BEFORE_SECONDS` 仍用于会话临近过期时的补偿续期。建议将本地会话时长和续期间隔都设置得短于认证源的空闲过期时间。

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

#### CAS对接ModelEngine
当使用CAS协议对接ModelEngine时，可以使用如下配置部署Nexent：
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
CAS_RENEW_INTERVAL_SECONDS=300
CAS_RENEW_TIMEOUT_SECONDS=10
CAS_SYNTHETIC_EMAIL_DOMAIN=cas.local
CAS_LOGOUT_URL=/logout?service=http://<Nexent IP>:3000
CAS_SSL_VERIFY=false
CAS_CA_BUNDLE=
```

同时，需要进入oms容器添加cas client的注册配置文件，参考如下步骤：
```bash
# 创建注册配置文件，将json部分输入文件并保存
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

# 执行如下命令，将配置文件拷贝到容器中
kubectl cp Nexent-10000001.json model-engine/$(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}'):/opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
kubectl exec -i -n model-engine $(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}') -- chown tomcat:fusioncube /opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
```

### 北向接口配置 (NORTHBOUND_EXTERNAL_URL)

如果您需要使用以下功能，需要配置 `NORTHBOUND_EXTERNAL_URL` 环境变量：

1. **A2A 协议集成** - 第三方系统通过 A2A 协议调用 Nexent 智能体
2. **MCP 工具访问** - 使用第三方 MCP 工具访问 Nexent 文档文件等资源

**配置方法：**

在 `deploy/env/.env` 文件中设置公网可访问的 URL：

```bash
# 格式：协议://主机:端口/api
# 本地开发（默认）:
NORTHBOUND_EXTERNAL_URL=http://localhost:5013/api

# 生产环境 - 使用您的公网 IP 或域名:
NORTHBOUND_EXTERNAL_URL=http://your-public-ip:5013/api
# 或
NORTHBOUND_EXTERNAL_URL=https://api.yourdomain.com/api
```

> **重要**: URL 必须包含 `/api` 后缀，因为 Northbound 服务使用 FastAPI 的 `root_path="/api"` 配置。

## 💡 需要帮助

- 浏览 [常见问题](./faq) 了解常见安装问题
- 在我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 提问
- 在 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 中提交错误报告或功能建议

## 🔧 从源码构建

想要从源码构建或添加新功能？查看 [Docker 构建指南](../deployment/docker-build) 获取详细说明。

有关详细的安装说明和自定义选项，请查看我们的 [开发者指南](../developer-guide/overview)。
