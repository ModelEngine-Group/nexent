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
./deploy-helm.sh apply
```

执行此命令后，系统会提示您选择配置选项：

**版本选择:**
- **Speed version（轻量快速部署，默认）**: 快速启动核心功能，适合个人用户和小团队使用
- **Full version（完整功能版）**: 提供企业级租户管理和资源隔离等高级功能，包含 Supabase 认证服务

**镜像源选择:**
- **中国大陆**: 使用优化的区域镜像源，加快镜像拉取速度
- **通用**: 使用标准 Docker Hub 镜像源

**可选组件:**
- **终端工具**: 启用 openssh-server 供 AI 智能体执行 shell 命令

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
./deploy-helm.sh apply
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

**Supabase 服务（完整版独有）:**
| 服务 | 描述 |
|---------|-------------|
| nexent-supabase-kong | API 网关 |
| nexent-supabase-auth | 认证服务 |
| nexent-supabase-db | 数据库服务 |

**可选服务:**
| 服务 | 描述 |
|---------|-------------|
| nexent-openssh-server | AI 智能体 SSH 终端 |

## 🔌 端口映射

| 服务 | 内部端口 | NodePort | 描述 |
|---------|---------------|----------|-------------|
| Web 界面 | 3000 | 30000 | 主应用程序访问 |
| Northbound API | 5010 | 30013 | 北向 API 服务 |
| SSH 服务器 | 22 | 30022 | 终端工具访问 |

内部服务通信使用 Kubernetes 内部 DNS（例如 `http://nexent-config:5010`）。

## 💾 数据持久化

Nexent 使用 PersistentVolume 进行数据持久化：

| 数据类型 | PersistentVolume | 默认宿主机路径 |
|-----------|------------------|-------------------|
| Elasticsearch | nexent-elasticsearch-pv | `{dataDir}/elasticsearch` |
| PostgreSQL | nexent-postgresql-pv | `{dataDir}/postgresql` |
| Redis | nexent-redis-pv | `{dataDir}/redis` |
| MinIO | nexent-minio-pv | `{dataDir}/minio` |
| Supabase DB（完整版）| nexent-supabase-db-pv | `{dataDir}/supabase-db` |

默认 `dataDir` 为 `/var/lib/nexent-data`（可在 `values.yaml` 中配置）。

## 🔧 部署命令

```bash
# 交互式部署
./deploy-helm.sh apply

# 使用中国大陆镜像源部署
./deploy-helm.sh apply --is-mainland Y

# 部署完整版本（包含 Supabase）
./deploy-helm.sh apply --deployment-version full

# 仅清理 Helm 状态（修复卡住的发布）
./deploy-helm.sh clean

# 卸载但保留数据
./deploy-helm.sh delete

# 完全卸载包括所有数据
./deploy-helm.sh delete-all
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
