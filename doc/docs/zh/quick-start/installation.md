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
cd nexent/docker
```

> **💡 提示**: `deploy.sh` 会在 `docker/.env` 不存在时自动从 `.env.example` 复制一份。若无特殊需求，可直接部署；若需要配置语音模型（STT/TTS），请部署前或部署后修改 `docker/.env` 中的相关参数。

### 2. 部署选项

运行以下命令开始部署：

```bash
bash deploy.sh
```

执行此命令后，系统会通过 Bash TUI 选择部署参数。可使用方向键或 `j/k` 移动，空格切换多选项，回车确认，`b`/Backspace 返回上一步，`q` 退出。

**组件组合:**
- **infrastructure（必选）**: Elasticsearch、PostgreSQL、Redis、MinIO
- **application（默认选中，可取消）**: config、runtime、mcp、northbound、web
- **data-process（可选）**: 数据处理服务
- **supabase（可选）**: 启用用户、租户和认证能力
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
# 默认组件组合，development 端口策略，标准镜像源
bash deploy.sh --components infrastructure,application --port-policy development --image-source general

# 启用用户/租户能力、数据处理和终端工具
bash deploy.sh --components infrastructure,application,supabase,data-process,terminal

# 使用中国大陆镜像源
bash deploy.sh --image-source mainland

# 使用本地 latest 镜像
bash deploy.sh --image-source local-latest
```

部署成功后，非敏感部署选项会保存到 `docker/deploy.options`。下次交互部署时可选择复用本地配置或重新全量配置。


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

默认 `dataDir` 为 `./volumes`（可在 `.env` 中配置 `ROOT_DIR`）。

卸载由 `docker/uninstall.sh` 负责。默认交互询问是否删除持久化数据；也可使用 `--delete-volumes true|false`、`--remove-volumes`、`--keep-volumes`，或使用 `bash uninstall.sh delete-all` 删除容器和持久化数据。

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

部署时在脚本交互界面中选择 `monitoring` 组件即可启用 OpenTelemetry 监控。脚本会同步更新 `docker/.env` 中的 `ENABLE_TELEMETRY`、`MONITORING_PROVIDER` 和 `MONITORING_DASHBOARD_URL`，并启动 `docker/docker-compose-monitoring.yml` 中对应的观测组件。

```bash
cd nexent/docker
bash deploy.sh
```

如果本地已有 `docker/deploy.options`，脚本会询问是否复用本地配置。请选择重新配置/覆盖本地配置，然后在组件选择界面勾选 `monitoring`，再在 provider 选择界面手动选择 `grafana`、`phoenix`、`langfuse`、`langsmith`、`zipkin` 或 `otlp`。

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
cp docker/monitoring/monitoring.env.example docker/monitoring/monitoring.env
```

常用变量：

| 变量 | 说明 |
|------|------|
| `MONITORING_PROVIDER` | 默认监控 provider；部署脚本中手动选择 provider 后会同步更新 |
| `OTEL_COLLECTOR_HTTP_PORT` / `OTEL_COLLECTOR_GRPC_PORT` | Collector 对外暴露的 OTLP HTTP/gRPC 端口 |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | LangSmith 转发配置 |
| `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` | 本地 Langfuse 初始管理员账号 |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | 本地 Grafana 管理员账号 |

选择 `langsmith` provider 前，请先在 `docker/monitoring/monitoring.env` 中配置 `LANGSMITH_API_KEY`。如果只需要连接已有外部 Collector，也可以在 `docker/.env` 中调整 OTLP 目标地址：

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
bash deploy.sh --components infrastructure,application,supabase
```

Docker 部署在 `docker/.env` 中配置 OAuth：

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

### 北向接口配置 (NORTHBOUND_EXTERNAL_URL)

如果您需要使用以下功能，需要配置 `NORTHBOUND_EXTERNAL_URL` 环境变量：

1. **A2A 协议集成** - 第三方系统通过 A2A 协议调用 Nexent 智能体
2. **MCP 工具访问** - 使用第三方 MCP 工具访问 Nexent 文档文件等资源

**配置方法：**

在 `.env` 文件中设置公网可访问的 URL：

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
