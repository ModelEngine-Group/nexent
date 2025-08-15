# Docker 构建指南

这个文档介绍如何构建和推送 Nexent 的 Docker 镜像。

## 🏗️ 构建和推送镜像

```bash
# 🛠️ 创建并使用支持多架构构建的新构建器实例
docker buildx create --name nexent_builder --use

# 🚀 为多个架构构建应用程序
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent -f make/main/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent -f make/web/Dockerfile . --push

# 📊 为多个架构构建数据处理服务
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-data-process -f make/data_process/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-data-process -f make/web/Dockerfile . --push

# 🌐 为多个架构构建前端
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-web -f make/web/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-web -f make/web/Dockerfile . --push

# 📚 为多个架构构建文档
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-docs -f make/docs/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-docs -f make/docs/Dockerfile . --push

# 💻 为多个架构构建 Ubuntu Terminal
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-terminal -f make/terminal/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-terminal -f make/terminal/Dockerfile . --push
```

## 💻 本地开发构建

```bash
# 🚀 构建应用程序镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent -f make/main/Dockerfile .

# 📊 构建数据处理镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-data-process -f make/data_process/Dockerfile .

# 🌐 构建前端镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-web -f make/web/Dockerfile .

# 📚 构建文档镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-docs -f make/docs/Dockerfile .

# 💻 构建 OpenSSH Server 镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-ubuntu-terminal -f make/terminal/Dockerfile .
```

## 🔧 镜像说明

### 主应用镜像 (nexent/nexent)
- 包含后端 API 服务
- 基于 `make/main/Dockerfile` 构建
- 提供核心的智能体服务

### 数据处理镜像 (nexent/nexent-data-process)
- 包含数据处理服务
- 基于 `make/data_process/Dockerfile` 构建
- 处理文档解析和向量化

### 前端镜像 (nexent/nexent-web)
- 包含 Next.js 前端应用
- 基于 `make/web/Dockerfile` 构建
- 提供用户界面

### 文档镜像 (nexent/nexent-docs)
- 包含 Vitepress 文档站点
- 基于 `make/docs/Dockerfile` 构建
- 提供项目文档和 API 参考

### OpenSSH Server 镜像 (nexent/nexent-ubuntu-terminal)
- 基于 Ubuntu 24.04 的 SSH 服务器容器
- 基于 `make/terminal/Dockerfile` 构建
- 预装 Conda、Python、Git 等开发工具
- 支持 SSH 密钥认证，用户名为 `linuxserver.io`
- 提供完整的开发环境

#### 预装工具和特性
- **Python 环境**: Python 3 + pip + virtualenv
- **Conda 管理**: Miniconda3 环境管理
- **开发工具**: Git、Vim、Nano、Curl、Wget
- **构建工具**: build-essential、Make
- **SSH 服务**: 端口 2222，禁用 root 登录和密码认证
- **用户权限**: `linuxserver.io` 用户具有 sudo 权限（无需密码）
- **时区设置**: Asia/Shanghai
- **安全配置**: SSH 密钥认证，会话超时 60 分钟

## 🏷️ 标签策略

每个镜像都会推送到两个仓库：
- `nexent/*` - 主要的公共镜像仓库
- `ccr.ccs.tencentyun.com/nexent-hub/*` - 腾讯云镜像仓库（中国地区加速）

所有镜像包括：
- `nexent/nexent` - 主应用后端服务
- `nexent/nexent-data-process` - 数据处理服务  
- `nexent/nexent-web` - Next.js 前端应用
- `nexent/nexent-docs` - Vitepress 文档站点
- `nexent/nexent-ubuntu-terminal` - OpenSSH 开发服务器容器

## 📚 文档镜像独立部署

文档镜像可以独立构建和运行，用于为 nexent.tech/doc 提供服务：

### 构建文档镜像

```bash
docker build -t nexent/nexent-docs -f make/docs/Dockerfile .
```

### 运行文档容器

```bash
docker run -d --name nexent-docs -p 4173:4173 nexent/nexent-docs
```

### 查看容器状态

```bash
docker ps
```

### 查看容器日志

```bash
docker logs nexent-docs
```

### 停止和删除容器

```bash
docker stop nexent-docs
```

```bash
docker rm nexent-docs
```

##  部署建议

构建完成后，可以使用 `docker/deploy.sh` 脚本进行部署，或者直接使用 `docker-compose` 启动服务。