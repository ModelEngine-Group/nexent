# Docker 构建指南

这个文档介绍如何构建和推送 Nexent 的 Docker 镜像。

## 🏗️ 构建和推送镜像

推荐使用统一构建入口：

```bash
# 类似部署脚本，进入交互式选择
bash build.sh

# 按镜像构建指定版本
bash build.sh \
  --images main,web,mcp,data-process,terminal \
  --version v2.2.1 \
  --registry general \
  --platform linux/amd64,linux/arm64 \
  --push

# 按同一镜像集合构建 latest 镜像
bash build.sh \
  --images main,web,mcp,data-process \
  --version latest \
  --registry general \
  --platform linux/amd64 \
  --load

# 需要时也可以只构建一个或多个指定镜像
bash build.sh --web --docs --version v2.2.1 --dry-run

# 跳过 Docker 构建缓存
bash build.sh --web --version v2.2.1 --no-cache
```

根目录 `build.sh` 会把镜像构建转发到 `deploy/images/build.sh`。使用 `bash build.sh --package ...` 可以转发到离线包构建脚本。在终端无参数运行 `build.sh` 时，会依次选择镜像、镜像版本（`latest` 或根 `VERSION`）和镜像源。交互式默认选择 `main,web` 和 `latest`。也可以用 `--interactive` 强制进入同样的选择流程。

`--platform` 和 `--no-cache` 仅支持命令行传入。不传 `--platform` 时不会添加该参数，默认按本地架构构建。`mainland` 的 web 镜像构建也会自动使用 `--no-cache`，避免前端依赖缓存过期。

变体选项：
- `--dependency-variant cpu|gpu` 控制数据处理依赖，默认 `cpu`。`gpu` 会构建带 GPU/CUDA 依赖的镜像，并使用 `-gpu` 镜像名后缀。
- `--terminal-variant slim|conda` 控制终端镜像，默认 `slim`。`conda` 会保留 Miniconda、`vim` 和编译工具链，并使用 `-conda` 镜像名后缀。

构建 `data-process` 时，`deploy/images/build.sh` 会自动准备 `model-assets`：优先使用仓库根目录已有的 `model-assets`，其次复用 `~/model-assets`，否则从 Hugging Face 仓库拉取并执行 `git lfs pull`。如果直接执行 `docker build`，需要先在仓库根目录准备好 `model-assets`。

镜像选项：
- `--main` 构建 `nexent`
- `--web` 构建 `nexent-web`
- `--data-process` 构建 `nexent-data-process`
- `--mcp` 构建 `nexent-mcp`
- `--terminal` 构建 `nexent-ubuntu-terminal`
- `--docs` 构建 `nexent-docs`

```bash
# 🛠️ 创建并使用支持多架构构建的新构建器实例
docker buildx create --name nexent_builder --use

# 🚀 为多个架构构建应用程序
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent -f deploy/images/dockerfiles/main/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent -f deploy/images/dockerfiles/web/Dockerfile . --push

# 📊 为多个架构构建数据处理服务
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-data-process -f deploy/images/dockerfiles/data-process/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-data-process -f deploy/images/dockerfiles/web/Dockerfile . --push

# 🌐 为多个架构构建前端
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-web -f deploy/images/dockerfiles/web/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-web -f deploy/images/dockerfiles/web/Dockerfile . --push

# 📚 为多个架构构建文档
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile . --push

# 🔗 为多个架构构建 MCP Server
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-mcp -f deploy/images/dockerfiles/mcp/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-mcp -f deploy/images/dockerfiles/mcp/Dockerfile . --push

# 💻 为多个架构构建 Ubuntu Terminal
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-terminal -f deploy/images/dockerfiles/terminal/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-terminal -f deploy/images/dockerfiles/terminal/Dockerfile . --push
```

## 💻 本地开发构建

```bash
# 🚀 构建应用程序镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent -f deploy/images/dockerfiles/main/Dockerfile .

# 📊 构建数据处理镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-data-process -f deploy/images/dockerfiles/data-process/Dockerfile .

# 📊 构建 GPU 数据处理镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-data-process-gpu -f deploy/images/dockerfiles/data-process/Dockerfile --build-arg DATA_PROCESS_DEPENDENCY_VARIANT=gpu .

# 🌐 构建前端镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-web -f deploy/images/dockerfiles/web/Dockerfile .

# 📚 构建文档镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile .

# 🔗 构建 MCP Server 镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-mcp -f deploy/images/dockerfiles/mcp/Dockerfile .

# 💻 构建 OpenSSH Server 镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-ubuntu-terminal -f deploy/images/dockerfiles/terminal/Dockerfile .

# 💻 构建带 Conda 的 OpenSSH Server 镜像（仅当前架构）
docker build --progress=plain -t nexent/nexent-ubuntu-terminal-conda -f deploy/images/dockerfiles/terminal/Dockerfile --build-arg TERMINAL_VARIANT=conda .
```

## 🔧 镜像说明

### 主应用镜像 (nexent/nexent)
- 包含后端 API 服务
- 基于 `deploy/images/dockerfiles/main/Dockerfile` 构建
- 提供核心的智能体服务

### 数据处理镜像 (nexent/nexent-data-process)
- 包含数据处理服务
- 基于 `deploy/images/dockerfiles/data-process/Dockerfile` 构建
- 处理文档解析和向量化

### 前端镜像 (nexent/nexent-web)
- 包含 Next.js 前端应用
- 基于 `deploy/images/dockerfiles/web/Dockerfile` 构建
- 提供用户界面

### 文档镜像 (nexent/nexent-docs)
- 包含 Vitepress 文档站点
- 基于 `deploy/images/dockerfiles/docs/Dockerfile` 构建
- 提供项目文档和 API 参考

### MCP Server 镜像 (nexent/nexent-mcp)
- 包含 MCP (Model Context Protocol) 代理服务
- 基于 `deploy/images/dockerfiles/mcp/Dockerfile` 构建
- 为 AI 模型集成提供 MCP 服务器功能

#### 预装工具和特性
- **Python 环境**: Python 3.11 + pip
- **MCP Proxy**: mcp-proxy 包用于协议处理
- **Node.js**: Node.js 20.17.0 包含 npm
- **架构支持**: linux/amd64, linux/arm64
- **基础镜像**: python:3.11-slim

### OpenSSH Server 镜像 (nexent/nexent-ubuntu-terminal)
- 基于 Ubuntu 24.04 的 SSH 服务器容器
- 基于 `deploy/images/dockerfiles/terminal/Dockerfile` 构建
- 默认预装 OpenSSH、Python、pip、venv、Git、Curl、Wget
- `TERMINAL_VARIANT=conda` 额外预装 Miniconda、Vim 和编译工具链
- 以 root 用户运行，支持 root 登录和密码认证

#### 预装工具和特性
- **Python 环境**: Python 3 + pip + venv
- **Conda 管理**: 仅 `conda` 变体包含 Miniconda3
- **开发工具**: Git、Curl、Wget；`conda` 变体额外包含 Vim 和 build-essential
- **SSH 服务**: 容器端口 22，允许 root 登录和密码认证

## 🏷️ 标签策略

镜像仓库由 `--registry` 和 `--push` 决定：
- `--registry general` 构建或推送 `nexent/*`。
- `--registry mainland --push` 推送到 `ccr.ccs.tencentyun.com/nexent-hub/*`，用于中国大陆加速。
- `--registry mainland` 但不带 `--push` 时，仍构建本地 `nexent/*` tag，同时使用大陆构建镜像源。

所有镜像包括：
- `nexent/nexent` - 主应用后端服务
- `nexent/nexent-data-process` - 数据处理服务
- `nexent/nexent-web` - Next.js 前端应用
- `nexent/nexent-docs` - Vitepress 文档站点
- `nexent/nexent-mcp` - MCP 服务器代理服务
- `nexent/nexent-ubuntu-terminal` - OpenSSH 开发服务器容器

## 📚 文档镜像独立部署

文档镜像可以独立构建和运行，用于为 nexent.tech/doc 提供服务：

### 构建文档镜像

```bash
docker build -t nexent/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile .
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

## 🚀 部署建议

构建完成后，可以进入 `docker` 目录使用部署脚本启动本地镜像：

```bash
bash deploy.sh docker --image-source local-latest
```

> `local-latest` 会使用本地 `latest` Nexent 应用镜像并避免重新拉取这些镜像，无需修改 `deploy/docker/deploy.sh`。

### 构建离线部署包

在联网机器上，可从仓库根目录构建包含 Docker 和 Kubernetes 资源的离线部署包：

```bash
bash build.sh --package \
  --target all \
  --version v2.2.1 \
  --platform amd64 \
  --components infrastructure,application,data-process,supabase \
  --image-source general \
  --compress true \
  --output-dir offline-package
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--target` | 生成 `docker`、`k8s` 或 `all` 部署资源 |
| `--version` | 要拉取并打包的 Nexent 镜像版本 |
| `--platform` | 目标服务器架构：`amd64` 或 `arm64` |
| `--components` | 部署组件，同时决定需要打包的镜像 |
| `--image-source` | `general`、`mainland` 或 `local-latest` |
| `--include-source` | 是否加入项目源码，默认 `false` |
| `--compress` | 是否生成 zip 压缩包，默认 `false` |
| `--output-dir` | 未压缩离线包的输出目录 |

如需打包本地构建的 `latest` 应用镜像：

```bash
bash build.sh --package \
  --target docker \
  --version latest \
  --platform amd64 \
  --components infrastructure,application,data-process,supabase \
  --image-source local-latest \
  --compress true \
  --output-dir offline-package/docker-local
```

`local-latest` 会复用本地 Nexent 应用镜像，不会再次拉取这些 `latest` 镜像。构建脚本会生成镜像 tar、部署资源、`manifest.yaml` 和 `checksums.txt`，且不会复制本机的 `deploy/env/.env`、`deploy/env/monitoring.env` 或 `deploy.options`。

启用 `--compress true` 后，会在输出目录旁生成 `nexent-offline-<target>-<platform>-<version>.zip`。也可以手动运行 GitHub Actions 中的 [Build Offline Deployment Package](https://github.com/ModelEngine-Group/nexent/actions/workflows/build-offline-package.yml)，工作流会为 AMD64 和 ARM64 分别生成可下载的 `nexent-<version>-<platform>.zip`，默认保留 30 天。

离线包的获取和安装方法参见：

- [Docker 安装部署中的离线部署](../quick-start/installation#离线部署)
- [Kubernetes 安装部署中的离线部署](../quick-start/kubernetes-installation#离线部署)
