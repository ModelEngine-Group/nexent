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
cd nexent/k8s/helm
```

### 3. 部署

运行部署脚本：

```bash
./deploy.sh
```

执行此命令后，系统会通过 Bash TUI 选择配置选项。可使用方向键或 `j/k` 移动，空格切换多选项，回车确认，`b`/Backspace 返回上一步，`q` 退出。

**组件组合:**
- **infrastructure（必选）**: Elasticsearch、PostgreSQL、Redis、MinIO
- **application（默认选中，可取消）**: config、runtime、mcp、northbound、web
- **data-process（可选）**: 数据处理服务
- **supabase（可选）**: 启用用户、租户和认证能力
- **terminal（可选）**: 启用 OpenSSH 终端工具
- **monitoring（可选）**: 启用观测组件，选择后会继续选择 provider

**端口策略:**
- **development（默认）**: 使用 NodePort 暴露 Web 和调试/内部服务
- **production**: 内部服务使用 ClusterIP，仅暴露生产入口

**镜像来源:**
- **general（默认）**: 使用标准公开镜像仓库
- **mainland**: 使用中国大陆镜像源
- **local-latest**: 使用本地 `latest` 镜像，并将 Nexent 应用镜像的拉取策略设为本地优先

部署成功后，非敏感部署选项会保存到 `k8s/helm/deploy.options`。下次交互部署时可选择复用本地配置或重新全量配置。

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
./deploy.sh
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

卸载 Helm release 默认不会删除本地 hostPath 数据。可使用 `./uninstall.sh --delete-local-data true` 删除 `/var/lib/nexent-data/nexent-*` 下的 Nexent 本地卷内容，使用 `--keep-local-data` 显式保留。

## 🔧 部署命令

```bash
# 交互式部署
./deploy.sh

# 非交互式部署默认组件
./deploy.sh --components infrastructure,application --port-policy development --image-source general

# 启用用户/租户能力、数据处理和终端工具
./deploy.sh --components infrastructure,application,supabase,data-process,terminal

# 使用中国大陆镜像源部署
./deploy.sh --image-source mainland

# 使用本地 latest 镜像
./deploy.sh --image-source local-latest

# 仅清理 Helm 状态（修复卡住的发布）
./uninstall.sh clean

# 卸载，默认保留本地数据；交互确认是否删除 namespace 和本地数据
./uninstall.sh

# 卸载并删除 namespace
./uninstall.sh --delete-namespace true

# 卸载并删除本地 hostPath 数据
./uninstall.sh --delete-local-data true

# 完全卸载，包括 namespace 和本地 hostPath 数据
./uninstall.sh delete-all

# 完全卸载但保留本地 hostPath 数据
./uninstall.sh delete-all --keep-local-data
```

## 🔧 高级配置

### 监控配置

Kubernetes 部署通过脚本交互界面中的 `monitoring` 组件启用监控。部署脚本会生成运行时 Helm values，设置 `global.monitoring.enabled`、`global.monitoring.provider`、`global.monitoring.dashboardUrl`，并启用 `nexent-monitoring` 子 Chart。

```bash
cd nexent/k8s/helm
./deploy.sh
```

如果本地已有 `k8s/helm/deploy.options`，脚本会询问是否复用本地配置。请选择重新配置/覆盖本地配置，然后在组件选择界面勾选 `monitoring`，再在 provider 选择界面手动选择 `grafana`、`phoenix`、`langfuse`、`langsmith`、`zipkin` 或 `otlp`。

支持的 provider：

| Provider | 用途 | 默认访问地址 |
|----------|------|--------------|
| `otlp` | 仅启动 OpenTelemetry Collector，适合转发到外部平台 | 无 Dashboard |
| `phoenix` | 本地 Phoenix 追踪分析 | `http://localhost:30006` |
| `langfuse` | 本地 Langfuse 观测栈 | `http://localhost:30001` |
| `langsmith` | 转发到托管 LangSmith | `https://smith.langchain.com/` |
| `grafana` | 本地 Grafana + Tempo | `http://localhost:30002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1` |
| `zipkin` | 本地 Zipkin | `http://localhost:30011` |

选择 `langsmith` provider 前，请先在 `k8s/helm/nexent/values.yaml` 中配置 `global.monitoring.langsmithApiKey` 和 `global.monitoring.langsmithProject`。如需修改本地 Grafana、Langfuse 或各 Dashboard 的端口，也建议先在 values 文件中调整，再通过部署脚本重新配置并手动选择 `monitoring`。

常用 Helm values：

| Values | 说明 |
|--------|------|
| `global.monitoring.enabled` | 是否让 Nexent 后端开启 OpenTelemetry 上报 |
| `global.monitoring.provider` | 后端 provider 标识：`otlp`、`phoenix`、`langfuse`、`langsmith`、`grafana`、`zipkin` |
| `global.monitoring.otlpEndpoint` | 后端 OTLP HTTP 上报地址，默认 `http://nexent-otel-collector:4318` |
| `global.monitoring.dashboardUrl` | 前端监控入口地址，留空则隐藏入口 |
| `global.monitoring.traceContentMode` | Trace 内容采集模式：`summary`、`metrics`、`full` |
| `nexent-monitoring.<provider>.service.nodePort` | 调整各 Dashboard 的 NodePort |
| `nexent-monitoring.langfuse.init.*` | 本地 Langfuse 初始组织、项目和管理员账号 |
| `nexent-monitoring.grafana.adminUser` / `adminPassword` | 本地 Grafana 管理员账号 |

查看监控组件状态：

```bash
kubectl get pods -n nexent | grep -E 'otel|phoenix|grafana|tempo|zipkin|langfuse'
kubectl get svc -n nexent | grep -E 'otel|phoenix|grafana|zipkin|langfuse'
```

> **生产建议**：请替换默认密码、密钥和 Langfuse `encryptionKey`，并将 Dashboard Service 改为 ClusterIP 或通过受控 Ingress 暴露。

### OAuth 登录配置

OAuth 登录依赖 `supabase` 组件。启用第三方登录时，请同时部署 `supabase`，并将 `config.oauth.callbackBaseUrl` 设置为浏览器可访问的 Nexent Web 地址。

```bash
./deploy.sh --components infrastructure,application,supabase
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
  --set nexent-common.config.oauth.githubClientSecret=your_github_client_secret
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

Provider 回调地址：

| Provider | 回调地址 |
|----------|----------|
| GitHub | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| WeChat | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

本地 NodePort 默认回调示例为 `http://localhost:30000/api/user/oauth/callback?provider=github`。生产环境应改为公网 HTTPS 域名，并在 OAuth provider 控制台中登记相同地址。

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
