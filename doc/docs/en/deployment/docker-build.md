### 🏗️ Build and Push Images

```bash
# 🛠️ Create and use a new builder instance that supports multi-architecture builds
docker buildx create --name nexent_builder --use

# 🚀 build application for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent -f make/main/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent -f make/web/Dockerfile . --push

# 📊 build data_process for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-data-process -f make/data_process/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-data-process -f make/web/Dockerfile . --push

# 🌐 build web frontend for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-web -f make/web/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-web -f make/web/Dockerfile . --push

# 📚 build documentation for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-docs -f make/docs/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-docs -f make/docs/Dockerfile . --push

# 🔗 build MCP Server for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-mcp -f make/mcp/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-mcp -f make/mcp/Dockerfile . --push

# 💻 build Ubuntu Terminal for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-terminal -f make/terminal/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-terminal -f make/terminal/Dockerfile . --push
```

### 💻 Local Development Build

```bash
# 🚀 Build application image (current architecture only)
docker build --progress=plain -t nexent/nexent -f make/main/Dockerfile .

# 📊 Build data process image (current architecture only)
docker build --progress=plain -t nexent/nexent-data-process -f make/data_process/Dockerfile .

# 🌐 Build web frontend image (current architecture only)
docker build --progress=plain -t nexent/nexent-web -f make/web/Dockerfile .

# 📚 Build documentation image (current architecture only)
docker build --progress=plain -t nexent/nexent-docs -f make/docs/Dockerfile .

# 🔗 Build MCP Server image (current architecture only)
docker build --progress=plain -t nexent/nexent-mcp -f make/mcp/Dockerfile .

# 💻 Build OpenSSH Server image (current architecture only)
docker build --progress=plain -t nexent/nexent-ubuntu-terminal -f make/terminal/Dockerfile .
```

### 🧹 Clean up Docker resources

```bash
# 🧼 Clean up Docker build cache and unused resources
docker builder prune -f && docker system prune -f
```

### 🔧 Image Descriptions

#### Main Application Image (nexent/nexent)
- Contains backend API service
- Built from `make/main/Dockerfile`
- Provides core agent services

#### Data Processing Image (nexent/nexent-data-process)
- Contains data processing service
- Built from `make/data_process/Dockerfile`
- Handles document parsing and vectorization

#### Web Frontend Image (nexent/nexent-web)
- Contains Next.js frontend application
- Built from `make/web/Dockerfile`
- Provides user interface

#### Documentation Image (nexent/nexent-docs)
- Contains Vitepress documentation site
- Built from `make/docs/Dockerfile`
- Provides project documentation and API reference

#### MCP Server Image (nexent/nexent-mcp)
- Contains MCP (Model Context Protocol) proxy service
- Built from `make/mcp/Dockerfile`
- Provides MCP server functionality for AI model integration

##### Pre-installed Tools and Features
- **Python Environment**: Python 3.10 + pip
- **MCP Proxy**: mcp-proxy package for protocol handling
- **Node.js**: Node.js 20.17.0 with npm
- **Architecture Support**: linux/amd64, linux/arm64
- **Base Image**: python:3.10-slim

#### OpenSSH Server Image (nexent/nexent-ubuntu-terminal)
- Ubuntu 24.04-based SSH server container
- Built from `make/terminal/Dockerfile`
- Pre-installed with Conda, Python, Git and other development tools
- Supports SSH key authentication with username `linuxserver.io`
- Provides complete development environment

##### Pre-installed Tools and Features
- **Python Environment**: Python 3 + pip + virtualenv
- **Conda Management**: Miniconda3 environment management
- **Development Tools**: Git, Vim, Nano, Curl, Wget
- **Build Tools**: build-essential, Make
- **SSH Service**: Port 2222, root login and password authentication disabled
- **User Permissions**: `linuxserver.io` user has sudo privileges (no password required)
- **Timezone Setting**: Asia/Shanghai
- **Security Configuration**: SSH key authentication, 60-minute session timeout

### 🏷️ Tagging Strategy

Each image is pushed to two repositories:
- `nexent/*` - Main public image repository
- `ccr.ccs.tencentyun.com/nexent-hub/*` - Tencent Cloud image repository (China region acceleration)

All images include:
- `nexent/nexent` - Main application backend service
- `nexent/nexent-data-process` - Data processing service
- `nexent/nexent-web` - Next.js frontend application
- `nexent/nexent-docs` - Vitepress documentation site
- `nexent/nexent-mcp` - MCP server proxy service
- `nexent/nexent-ubuntu-terminal` - OpenSSH development server container

## 📚 Documentation Image Standalone Deployment

The documentation image can be built and run independently to serve nexent.tech/doc:

### Build Documentation Image

```bash
docker build -t nexent/nexent-docs -f make/docs/Dockerfile .
```

### Run Documentation Container

```bash
docker run -d --name nexent-docs -p 4173:4173 nexent/nexent-docs
```

### Check Container Status

```bash
docker ps
```

### View Container Logs

```bash
docker logs nexent-docs
```

### Stop and Remove Container

```bash
docker stop nexent-docs
```

```bash
docker rm nexent-docs
```

Notes:
- 🔧 Use `--platform linux/amd64,linux/arm64` to specify target architectures
- 📤 The `--push` flag automatically pushes the built images to Docker Hub
- 🔑 Make sure you are logged in to Docker Hub (`docker login`)
- ⚠️ If you encounter build errors, ensure Docker's buildx feature is enabled
- 🧹 Cleanup commands explanation:
  - `docker builder prune -f`: Cleans build cache
  - `docker system prune -f`: Cleans unused data (including dangling images, networks, etc.)
  - The `-f` flag forces execution without confirmation
- 🔧 The `--load` flag loads the built image into the local Docker images list
- ⚠️ `--load` can only be used with single architecture builds
- 📝 Use `docker images` to verify the images are loaded locally
- 📊 Use `--progress=plain` to see detailed build and push progress
- 📈 Use `--build-arg MIRROR=...` to set up a pip mirror to accelerate your build-up progress

## 🚀 Deployment Recommendations

After building is complete, you can use the docker/deploy.sh script for deployment, or directly start the services using docker-compose.

> When starting a test of locally built images, you need to change APP_VERSION="$(get_app_version)" to APP_VERSION="latest" in docker/deploy.sh, because the deployment will default to using the image corresponding to the current version.
