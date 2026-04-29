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
cp .env.example .env # 复制环境变量配置文件
```

> **💡 提示**: 若无特殊需求，您可直接使用 `.env.example` 进行部署，无需进行任何修改。若您需要配置语音模型（STT/TTS），则需要在 `.env` 中配置相关参数。我们会尽快将此部分配置前端化，敬请期待。

### 2. 部署选项

运行以下命令开始部署：

```bash
bash deploy.sh
```

执行此命令后，系统会提供两个不同的版本供您选择：

**版本选择:**
- **Speed version（轻量快速部署，默认）**: 快速启动核心功能，适合个人用户和小团队使用
- **Full version（完整功能版）**: 提供企业级租户管理和资源隔离等高级功能，但安装时间略长，适合企业用户

**部署模式:**
- **开发模式 (默认)**: 暴露所有服务端口以便调试
- **基础设施模式**: 仅启动基础设施服务
- **生产模式**: 为安全起见仅暴露端口 3000

**可选组件:**
- **终端工具**: 启用 openssh-server 供 AI 智能体执行 shell 命令
- **区域优化**: 中国大陆用户可使用优化的镜像源


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

**Supabase 服务（完整版独有）:**
| 服务 | 描述 |
|---------|-------------|
| supabase-kong | API 网关 |
| supabase-auth | 认证服务 |
| supabase-db-mini | 数据库服务 |

**可选服务:**
| 服务 | 描述 |
|---------|-------------|
| nexent-openssh-server | AI 智能体 SSH 终端 |

## 💾 数据持久化

Nexent 使用 Docker volumes 进行数据持久化：

| 数据类型 | Volume 名称 | 默认宿主机路径 |
|-----------|------------------|-------------------|
| PostgreSQL | nexent-postgresql-data | `{dataDir}/postgresql` |
| Elasticsearch | nexent-elasticsearch-data | `{dataDir}/elasticsearch` |
| Redis | nexent-redis-data | `{dataDir}/redis` |
| MinIO | nexent-minio-data | `{dataDir}/minio` |
| Supabase DB（完整版）| nexent-supabase-db-data | `{dataDir}/supabase-db` |

默认 `dataDir` 为 `./volumes`（可在 `.env` 中配置 `ROOT_DIR`）。

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