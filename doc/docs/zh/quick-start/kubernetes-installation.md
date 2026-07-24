# Kubernetes 安装部署

## 🎯 系统要求

| 资源 | 最低要求 | 推荐配置 |
|----------|---------|-------------|
| **CPU**  | 4 核 | 8 核 |
| **内存**  | 16 GiB | 64 GiB |
| **磁盘** | 100 GiB | 200 GiB |
| **架构** | x86_64 / ARM64 |
| **软件** | Kubernetes 1.24+, Helm 3+, kubectl 已配置 | Kubernetes 1.28+ |

> **💡 注意**：推荐的 **8 核 64 GiB 内存** 配置可确保生产环境下的最佳性能。

## 🚀 快速开始

### 1. 准备 Kubernetes 集群

确保 Kubernetes 集群正常运行，且 kubectl 已配置好集群访问权限：

```bash
kubectl cluster-info
kubectl get nodes
```

### 2. 克隆并进入目录

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
```

### 3. 部署

运行部署脚本：

```bash
bash deploy.sh k8s
```

执行此命令后，系统会通过 Bash TUI 选择配置选项。可使用方向键或 `j/k` 移动，空格切换多选项，回车确认，`b`/Backspace 返回上一步，`q` 退出。

**组件组合:**
- **infrastructure（必选）**: Elasticsearch、PostgreSQL、Redis、MinIO
- **application（默认选中，可取消）**: config、runtime、mcp、northbound、web
- **data-process（默认选中，可选）**: 数据处理服务
- **supabase（默认选中，可选）**: 启用用户、租户和认证能力
- **terminal（可选）**: 启用 OpenSSH 终端工具
- **monitoring（可选）**: 启用观测组件，选择后会继续选择 provider

**端口策略:**
- **development（默认）**: 使用 NodePort 暴露 Web 和调试/内部服务
- **production**: 内部服务使用 ClusterIP，仅暴露生产入口

**镜像来源:**
- **general（默认）**: 使用标准公开镜像仓库
- **mainland**: 使用中国大陆镜像源
- **local-latest**: 使用本地 `latest` 镜像，并将 Nexent 应用镜像的拉取策略设为本地优先

Kubernetes 使用与 Docker 相同的 `deploy/env/.env`。已有 `deploy/env/.env` 会原样保留；如果不存在，部署脚本会优先复用 `docker/.env`，再回退到 `deploy/env/.env.example`。

使用 `bash deploy.sh k8s --defaults` 可跳过 TUI，并复用已保存的 `deploy.options` 或内置默认值。

部署成功后，非敏感部署选项会保存到 `deploy/k8s/deploy.options`。下次交互部署时可选择复用本地配置或重新全量配置。

### ⚠️ 重要提示

1️⃣ **首次部署 v1.8.0 及以上版本时**，部署过程中系统会提示您设置 `suadmin` 超级管理员账号的密码。该账号为系统最高权限账户，请输入您想要的密码并**妥善保存**——密码创建后无法再次找回。

2️⃣ 忘记记录 `suadmin` 账号密码？请按照以下步骤操作：

```bash
# Step 1: 在 Supabase 数据库中删除 su 账号记录
kubectl exec -it -n nexent deploy/nexent-supabase-db -- psql -U postgres -c \
  "SELECT id, email FROM auth.users WHERE email='suadmin@nexent.com';"
# 获取 user_id 后执行删除
kubectl exec -it -n nexent deploy/nexent-supabase-db -- psql -U postgres -c \
  "DELETE FROM auth.identities WHERE user_id='your_user_id';"
kubectl exec -it -n nexent deploy/nexent-supabase-db -- psql -U postgres -c \
  "DELETE FROM auth.users WHERE id='your_user_id';"

# Step 2: 在 nexent 数据库中删除 su 账号记录
kubectl exec -it -n nexent deploy/nexent-postgresql -- psql -U root -d nexent -c \
  "DELETE FROM nexent.user_tenant_t WHERE user_id='your_user_id';"

# Step 3: 重新部署并记录 su 账号密码
bash deploy.sh k8s
```

### 4. 访问您的安装

部署成功完成后：

| 服务 | 默认地址 |
|---------|-----------------|
| Web 应用 | http://localhost:30000 |
| SSH 终端 | localhost:30022（已启用时） |

访问步骤：
1. 在浏览器中打开 **http://localhost:30000**
2. 登录超级管理员账号
3. 访问租户资源 → 创建租户及租户管理员
4. 登录租户管理员账号
5. 参考 [用户指南](../user-guide/home-page) 进行智能体的开发

## 🏗️ 服务架构

Nexent 采用微服务架构，通过 Helm Chart 进行部署：

**应用服务:**
| 服务 | 描述 | 默认端口 |
|---------|-------------|--------------|
| nexent-config | 配置服务 | 5010 |
| nexent-runtime | 运行时服务 | 5014 |
| nexent-mcp | MCP 容器服务 | 5011 |
| nexent-northbound | 北向 API 服务 | 5013 |
| nexent-web | Web 前端 | 3000 |
| nexent-data-process | 数据处理服务 | 5012 |

**基础设施服务:**
| 服务 | 描述 |
|---------|-------------|
| nexent-elasticsearch | 搜索引擎和索引服务 |
| nexent-postgresql | 关系型数据库 |
| nexent-redis | 缓存层 |
| nexent-minio | S3 兼容对象存储 |

**Supabase 服务（选择 `supabase` 组件时）:**
| 服务 | 描述 |
|---------|-------------|
| nexent-supabase-kong | API 网关 |
| nexent-supabase-auth | 认证服务 |
| nexent-supabase-db | 数据库服务 |

**可选服务:**
| 服务 | 描述 |
|---------|-------------|
| nexent-openssh-server | AI 智能体 SSH 终端 |
| nexent-monitoring | 可选观测组件 |

## 🔌 端口映射

| 服务 | 内部端口 | NodePort | 描述 |
|---------|---------------|----------|-------------|
| Web 界面 | 3000 | 30000 | 主应用程序访问 |
| Northbound API | 5013 | 30013 | 北向 API 服务 |
| SSH 服务器 | 22 | 30022 | 终端工具访问 |

内部服务通信使用 Kubernetes 内部 DNS（例如 `http://nexent-config:5010`）。

## 💾 数据持久化

Nexent 使用 PersistentVolume 进行数据持久化：

| 数据类型 | PersistentVolume | 默认宿主机路径 |
|-----------|------------------|-------------------|
| Elasticsearch | nexent-elasticsearch-pv | `/var/lib/nexent-data/nexent-elasticsearch` |
| PostgreSQL | nexent-postgresql-pv | `/var/lib/nexent-data/nexent-postgresql` |
| Redis | nexent-redis-pv | `/var/lib/nexent-data/nexent-redis` |
| MinIO | nexent-minio-pv | `/var/lib/nexent-data/nexent-minio` |
| Supabase DB（选择 supabase 时）| nexent-supabase-db-pv | `/var/lib/nexent-data/nexent-supabase-db` |
| 共享工作区 | nexent-workspace-pv | `/var/lib/nexent` |
| 共享技能目录 | nexent-skills-pv | `/var/lib/nexent-data/skills` |

卸载 Helm release 默认不会删除本地 hostPath 数据。可使用 `bash uninstall.sh k8s --delete-local-data true` 删除 `/var/lib/nexent`、`/var/lib/nexent-data/skills` 和 `/var/lib/nexent-data/nexent-*` 下的 Nexent 本地卷内容，使用 `--keep-local-data` 显式保留。

### 卸载 Kubernetes 部署

请在仓库根目录使用统一卸载入口：

```bash
# 删除 Helm release；交互模式会询问是否删除 namespace 和本地数据
bash uninstall.sh k8s

# 仅清理 Helm release 状态，适合修复卡住的发布
bash uninstall.sh k8s clean

# 删除 Helm release 和 namespace，但保留本地 hostPath 数据
bash uninstall.sh k8s delete --keep-local-data

# 卸载后删除已知本地 hostPath 数据
bash uninstall.sh k8s --delete-local-data true

# 完整清理：Helm release、namespace 和本地 hostPath 数据都会删除
bash uninstall.sh k8s delete-all
```

`--delete-data` 和 `--delete-volumes` 是兼容 Helm 管理资源的参数；本地盘数据请使用 `--delete-local-data` 或 `--keep-local-data` 控制。`delete-all --keep-local-data` 会删除 namespace，但保留本地卷内容。

### 离线镜像包

可在仓库根目录构建 Kubernetes 离线包：

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

包内包含镜像 tar、`load-images.sh`、`push-images.sh`、根目录部署/卸载入口、Kubernetes Helm 资源、SQL 文件、`deploy/env/.env.example`、`deploy/env/monitoring.env.example`、`manifest.yaml` 和 `checksums.txt`，不会包含本地 `deploy/env/.env`、`deploy/env/monitoring.env` 或生成的 Helm values。使用 `--compress true` 时，会在输出目录的父目录生成 `nexent-offline-<target>-<platform>-<version>.zip`。

在目标机器上部署时，包根目录的 `deploy.sh` 会优先复用已保存的 `deploy.options`，否则使用内置默认值，默认不进入 TUI。添加 `--config` 可进入交互式配置界面。如果离线包构建时使用了自定义版本、组件、端口策略或镜像源，请在部署时传入相同选项，或使用 `--config` 交互选择。如果是单节点、Docker 作为容器运行时的集群，可以直接加载并部署：

```bash
cd offline-package
bash deploy.sh --load-images k8s
```

多节点集群需要在每个可能运行 Nexent Pod 的节点上加载镜像，或将镜像推送到集群可访问的内部镜像仓库，再使用匹配的镜像参数部署：

```bash
bash deploy.sh --push-images --image-registry-prefix registry.example.com/nexent k8s
```

启用 `--push-images` 且未传前缀时，`deploy.sh` 会先询问镜像仓库前缀；随后 `push-images.sh` 在推送前询问仓库账号和密码。

## 🔧 部署命令

```bash
# 交互式部署
bash deploy.sh k8s

# 非交互式部署默认组件
bash deploy.sh k8s --components infrastructure,application,data-process,supabase --port-policy development --image-source general

# 启用用户/租户能力、数据处理和终端工具
bash deploy.sh k8s --components infrastructure,application,data-process,supabase,terminal

# 使用中国大陆镜像源部署
bash deploy.sh k8s --image-source mainland

# 使用本地 latest 镜像
bash deploy.sh k8s --image-source local-latest

# 使用 --sc 简写指定 StorageClass
bash deploy.sh k8s --sc fast-storage

# 仅清理 Helm 状态（修复卡住的发布）
bash uninstall.sh k8s clean

# 卸载，默认保留本地数据；交互确认是否删除 namespace 和本地数据
bash uninstall.sh k8s

# 卸载并删除 namespace
bash uninstall.sh k8s --delete-namespace true

# 卸载并删除本地 hostPath 数据
bash uninstall.sh k8s --delete-local-data true

# 完全卸载，包括 namespace 和本地 hostPath 数据
bash uninstall.sh k8s delete-all

# 完全卸载但保留本地 hostPath 数据
bash uninstall.sh k8s delete-all --keep-local-data
```

## 🔧 高级配置

### 监控配置

Kubernetes 部署通过脚本交互界面中的 `monitoring` 组件启用监控。部署脚本会在 `deploy/env/monitoring.env` 中同步 provider 配置，生成 `global.monitoring.*` 和 `nexent-monitoring.*` 运行时 Helm values，并启用 `nexent-monitoring` 子 Chart。

```bash
cd nexent
bash deploy.sh k8s
```

如果本地已有 `deploy/k8s/deploy.options`，脚本会询问是否复用本地配置。请选择重新配置/覆盖本地配置，然后在组件选择界面勾选 `monitoring`，再在 provider 选择界面手动选择 `grafana`、`phoenix`、`langfuse`、`langsmith`、`zipkin` 或 `otlp`。

支持的 provider：

| Provider | 用途 | 默认访问地址 |
|----------|------|--------------|
| `otlp` | 仅启动 OpenTelemetry Collector，适合转发到外部平台 | 无 Dashboard |
| `phoenix` | 本地 Phoenix 追踪分析 | `http://localhost:30006` |
| `langfuse` | 本地 Langfuse 观测栈 | `http://localhost:30001` |
| `langsmith` | 转发到托管 LangSmith | `https://smith.langchain.com/` |
| `grafana` | 本地 Grafana + Tempo | `http://localhost:30002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1` |
| `zipkin` | 本地 Zipkin | `http://localhost:30011` |

选择 `langsmith` provider 前，请先在 `deploy/env/monitoring.env` 中配置 `LANGSMITH_API_KEY`，必要时配置 `LANGSMITH_PROJECT`。如需修改本地 Grafana、Langfuse 或各 Dashboard 的端口，请调整 `deploy/env/monitoring.env` 中对应的 `K8S_*_NODE_PORT` 或服务变量，再通过部署脚本重新配置并手动选择 `monitoring`。

常用生成的 Helm values：

| Values | 说明 |
|--------|------|
| `global.monitoring.enabled` | 是否让 Nexent 后端开启 OpenTelemetry 上报 |
| `global.monitoring.provider` | 后端 provider 标识：`otlp`、`phoenix`、`langfuse`、`langsmith`、`grafana`、`zipkin` |
| `global.monitoring.otlpEndpoint` | 后端 OTLP HTTP 上报地址，默认 `http://nexent-otel-collector:4318` |
| `global.monitoring.dashboardUrl` | 前端监控入口地址，留空则隐藏入口；speed 模式下可见，标准模式下仅超级管理员可见 |
| `global.monitoring.traceContentMode` | Trace 内容采集模式：`summary`、`metrics`、`full` |
| `nexent-monitoring.<provider>.service.nodePort` | 调整各 Dashboard 的 NodePort |
| `nexent-monitoring.langfuse.init.*` | 本地 Langfuse 初始组织、项目和管理员账号 |
| `nexent-monitoring.grafana.adminUser` / `adminPassword` | 本地 Grafana 管理员账号 |

常用 `deploy/env/monitoring.env` 变量：

| 变量 | 说明 |
|------|------|
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | LangSmith 转发配置 |
| `K8S_PHOENIX_NODE_PORT` / `K8S_LANGFUSE_NODE_PORT` / `K8S_GRAFANA_NODE_PORT` / `K8S_ZIPKIN_NODE_PORT` | 本地 Dashboard 的 NodePort 覆盖值 |
| `K8S_LANGFUSE_NEXTAUTH_URL` | K8s Langfuse 栈使用的浏览器可访问地址 |

查看监控组件状态：

```bash
kubectl get pods -n nexent | grep -E 'otel|phoenix|grafana|tempo|zipkin|langfuse'
kubectl get svc -n nexent | grep -E 'otel|phoenix|grafana|zipkin|langfuse'
```

> **生产建议**：请替换默认密码、密钥和 Langfuse `encryptionKey`，并将 Dashboard Service 改为 ClusterIP 或通过受控 Ingress 暴露。

### OAuth 登录配置

OAuth 登录依赖 `supabase` 组件。启用第三方登录时，请同时部署 `supabase`，并将 `config.oauth.callbackBaseUrl` 设置为浏览器可访问的 Nexent Web 地址。

```bash
bash deploy.sh k8s --components infrastructure,application,supabase
```

Kubernetes 部署通过 `nexent-common` 的 `config.oauth.*` values 写入后端环境变量：

```bash
helm upgrade --install nexent nexent \
  --namespace nexent --create-namespace \
  --set global.deploymentComponents.supabase=true \
  --set nexent-supabase-kong.enabled=true \
  --set nexent-supabase-auth.enabled=true \
  --set nexent-supabase-db.enabled=true \
  --set nexent-common.config.oauth.callbackBaseUrl=https://nexent.example.com \
  --set nexent-common.config.oauth.githubClientId=your_github_client_id \
  --set nexent-common.config.oauth.githubClientSecret=your_github_client_secret \
  --set nexent-common.config.oauth.loginMode=force
```

可配置的 OAuth values：

| Values | 对应环境变量 | 说明 |
|--------|--------------|------|
| `nexent-common.config.oauth.callbackBaseUrl` | `OAUTH_CALLBACK_BASE_URL` | Web 入口地址，回调路径会自动拼接 |
| `nexent-common.config.oauth.githubClientId` | `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth Client ID |
| `nexent-common.config.oauth.githubClientSecret` | `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth Client Secret |
| `nexent-common.config.oauth.gdeUrl` | `GDE_URL` | GDE OAuth 服务地址 |
| `nexent-common.config.oauth.gdeClientId` | `GDE_OAUTH_CLIENT_ID` | GDE OAuth Client ID |
| `nexent-common.config.oauth.gdeClientSecret` | `GDE_OAUTH_CLIENT_SECRET` | GDE OAuth Client Secret |
| `nexent-common.config.oauth.enableWechat` | `ENABLE_WECHAT_OAUTH` | 是否启用 WeChat OAuth |
| `nexent-common.config.oauth.wechatClientId` | `WECHAT_OAUTH_APP_ID` | WeChat App ID |
| `nexent-common.config.oauth.wechatClientSecret` | `WECHAT_OAUTH_APP_SECRET` | WeChat App Secret |
| `nexent-common.config.oauth.sslVerify` | `OAUTH_SSL_VERIFY` | 访问 OAuth provider 时是否校验证书 |
| `nexent-common.config.oauth.caBundle` | `OAUTH_CA_BUNDLE` | 自定义 CA bundle 路径 |
| `nexent-common.config.oauth.loginMode` | `OAUTH_LOGIN_MODE` | `disabled`、`button` 或 `force` |

`loginMode` 默认为 `button`。`force` 模式下，没有可用 Provider 时禁用 OAuth，同时启用多个 Provider 时回退到登录按钮；CAS `force` 模式优先于 OAuth 自动登录。

Provider 回调地址：

| Provider | 回调地址 |
|----------|----------|
| GitHub | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| WeChat | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

本地 NodePort 默认回调示例为 `http://localhost:30000/api/user/oauth/callback?provider=github`。生产环境应改为公网 HTTPS 域名，并在 OAuth provider 控制台中登记相同地址。

### CAS 登录配置

CAS SSO 不依赖 `supabase`。启用 CAS 时，请将 `nexent-common.config.cas.callbackBaseUrl` 设置为浏览器可访问的 Nexent Web 地址，且不要带结尾 `/`。`nexent-common.config.cas.serverUrl` 是 CAS Server 根地址，也不要带结尾 `/`。

Kubernetes 部署通过 `nexent-common` 的 `config.cas.*` values 写入后端环境变量：

```bash
helm upgrade --install nexent nexent \
  --namespace nexent --create-namespace \
  --set nexent-common.config.cas.enabled=true \
  --set nexent-common.config.cas.serverUrl=https://cas.example.com/cas \
  --set nexent-common.config.cas.callbackBaseUrl=https://nexent.example.com \
  --set nexent-common.config.cas.loginMode=force \
  --set nexent-common.config.cas.logoutUrl=/logout
```

可配置的 CAS values：

| Values | 对应环境变量 | 说明 |
|--------|--------------|------|
| `nexent-common.config.cas.enabled` | `CAS_ENABLED` | 是否启用 CAS |
| `nexent-common.config.cas.serverUrl` | `CAS_SERVER_URL` | CAS Server 根地址 |
| `nexent-common.config.cas.validatePath` | `CAS_VALIDATE_PATH` | serviceValidate 路径，默认 `/p3/serviceValidate` |
| `nexent-common.config.cas.callbackBaseUrl` | `CAS_CALLBACK_BASE_URL` | Web 入口地址，CAS 回调路径会自动拼接 |
| `nexent-common.config.cas.loginMode` | `CAS_LOGIN_MODE` | `disabled`、`button` 或 `force` |
| `nexent-common.config.cas.userAttribute` | `CAS_USER_ATTRIBUTE` | 用户标识属性。为空时使用 `<cas:user>` |
| `nexent-common.config.cas.emailAttribute` | `CAS_EMAIL_ATTRIBUTE` | 邮箱属性 |
| `nexent-common.config.cas.roleAttribute` | `CAS_ROLE_ATTRIBUTE` | 角色属性 |
| `nexent-common.config.cas.tenantAttribute` | `CAS_TENANT_ATTRIBUTE` | 租户属性 |
| `nexent-common.config.cas.defaultTenantId` | `CAS_DEFAULT_TENANT_ID` | CAS 未返回租户属性或属性为空时使用的默认租户 |
| `nexent-common.config.cas.roleMapJson` | `CAS_ROLE_MAP_JSON` | CAS 角色到 Nexent 角色的 JSON 映射 |
| `nexent-common.config.cas.sessionMaxAgeSeconds` | `CAS_SESSION_MAX_AGE_SECONDS` | CAS 本地会话最长有效期 |
| `nexent-common.config.cas.localSessionMaxAgeSeconds` | `LOCAL_SESSION_MAX_AGE_SECONDS` | Nexent 本地会话有效期 |
| `nexent-common.config.cas.heartbeatUrl` | `CAS_HEARTBEAT_URL` | 用户活动触发的 CAS Server 心跳 GET 地址；为空时禁用 |
| `nexent-common.config.cas.heartbeatIntervalSeconds` | `CAS_HEARTBEAT_INTERVAL_SECONDS` | CAS 活跃用户最小心跳间隔，默认 300 秒 |
| `nexent-common.config.cas.heartbeatCookieName` | `CAS_HEARTBEAT_COOKIE_NAME` | 复制到心跳 `X-Auth-Token` Header 的前端可读 Cookie 名称 |
| `nexent-common.config.cas.renewBeforeSeconds` | `CAS_RENEW_BEFORE_SECONDS` | 距离过期多少秒内触发无感续期 |
| `nexent-common.config.cas.renewTimeoutSeconds` | `CAS_RENEW_TIMEOUT_SECONDS` | 无感续期等待超时时间 |
| `nexent-common.config.cas.syntheticEmailDomain` | `CAS_SYNTHETIC_EMAIL_DOMAIN` | CAS 未返回邮箱时生成邮箱使用的域名 |
| `nexent-common.config.cas.logoutUrl` | `CAS_LOGOUT_URL` | CAS 登出地址。为空时 Nexent 主动退出不调用 CAS Server 登出接口 |
| `nexent-common.config.cas.sslVerify` | `CAS_SSL_VERIFY` | 访问 CAS Server 时是否校验证书 |
| `nexent-common.config.cas.caBundle` | `CAS_CA_BUNDLE` | 自定义 CA bundle 路径 |

CAS 心跳仅在 CAS 用户本地会话有效、页面可见且发生用户活动时运行。首次活动立即发送 GET，之后所有浏览器标签页共享配置的最小间隔。配置的 Cookie 可读取时，请求携带 `X-Auth-Token: <cookie-name>=<cookie-value>`；读取不到时仍发送请求但不带该 Header。由于浏览器直接访问心跳地址，认证源必须通过 CORS 允许 Nexent Origin、GET、OPTIONS 和 `X-Auth-Token`。心跳失败不会退出用户，也不会刷新本地 JWT。

常用 CAS 地址：

| 用途 | 地址 |
|------|------|
| Nexent 登录入口 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/login?redirect=/` |
| CAS service 回调 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/callback` |
| CAS 无感续期回调 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/renew_callback` |
| CAS 单点登出回调 | `POST {CAS_CALLBACK_BASE_URL}/api/user/cas/logout_callback` |

Apereo CAS 使用 JSON Service Registry 时，可以新增一个服务注册文件，例如 `Nexent-10001.json`。文件需要放到 CAS 部署配置的 service registry 目录中，`id` 必须全局唯一。本地 NodePort 示例：

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

生产环境建议保持 `CAS_SSL_VERIFY=true`；自签名证书优先配置 `CAS_CA_BUNDLE`，仅本地验证时再临时设置 `CAS_SSL_VERIFY=false`。

#### CAS 对接 ModelEngine

当使用 CAS 协议对接 ModelEngine 时，建议通过 values 文件配置 Nexent，避免 `CAS_ROLE_MAP_JSON` 在命令行中转义复杂。

创建 `cas-modelengine-values.yaml`：

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

同时，需要进入 OMS 容器添加 CAS client 的注册配置文件，参考如下步骤：

```bash
# 创建注册配置文件，将 JSON 部分输入文件并保存
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

# 执行如下命令，将配置文件拷贝到容器中
kubectl cp Nexent-10000001.json model-engine/$(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}'):/opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
kubectl exec -i -n model-engine $(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}') -- chown tomcat:fusioncube /opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
```

## 🔍 故障排查

### 查看 Pod 状态

```bash
kubectl get pods -n nexent
kubectl describe pod <pod-name> -n nexent
```

### 查看日志

```bash
kubectl logs -n nexent -l app=nexent-config
kubectl logs -n nexent -l app=nexent-web
kubectl logs -n nexent -l app=nexent-elasticsearch
```

### 重启服务

```bash
kubectl rollout restart deployment/nexent-config -n nexent
kubectl rollout restart deployment/nexent-runtime -n nexent
```

### 重新初始化 Elasticsearch

如果 Elasticsearch 初始化失败：

```bash
bash init-elasticsearch.sh
```

### 清理过期的 PersistentVolume

```bash
kubectl delete pv nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv
```

## 💡 需要帮助

- 浏览 [常见问题](./faq) 了解常见安装问题
- 在我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 提问
- 在 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 中提交错误报告或功能建议
