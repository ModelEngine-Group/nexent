### 🏗️ Build and Push Images

Recommended unified build entry:

```bash
# Run interactive selection, similar to the deploy scripts
bash build.sh

# Equivalent direct image builder
bash deploy/images/build.sh

# Build selected images with a fixed version tag
bash build.sh \
  --images main,web,mcp,data-process,terminal \
  --version v2.2.1 \
  --registry general \
  --platform linux/amd64,linux/arm64 \
  --push

# Build the same image set as latest
bash build.sh \
  --images main,web,mcp,data-process \
  --version latest \
  --registry general \
  --platform linux/amd64 \
  --load

# Build one or more explicit images when needed
bash build.sh --web --docs --version v2.2.1 --dry-run

# Build without Docker cache
bash build.sh --web --version v2.2.1 --no-cache
```

The root `build.sh` forwards image builds to `deploy/images/build.sh`. Use `bash build.sh --package ...` to forward to the offline package builder. When run in a terminal without arguments, `build.sh` prompts for images, image version (`latest` or root `VERSION`), and image source. The interactive defaults are images `main,web` and version `latest`. Use `--interactive` to force the same prompts.

`--platform` and `--no-cache` are command-line only. Omit `--platform` to build for the local architecture. The `mainland` web build also uses `--no-cache` automatically to avoid stale frontend dependency caches.

Variant options:
- `--dependency-variant cpu|gpu` controls data-process dependencies and defaults to `cpu`. `gpu` builds GPU/CUDA dependencies and uses the `-gpu` image-name suffix.
- `--terminal-variant slim|conda` controls the terminal image and defaults to `slim`. `conda` keeps Miniconda, `vim`, and the compiler toolchain and uses the `-conda` image-name suffix.

When building `data-process`, `deploy/images/build.sh` prepares `model-assets` automatically: it first uses an existing root `model-assets` directory, then tries `~/model-assets`, and otherwise clones the Hugging Face repository and runs `git lfs pull`. If you run `docker build` directly, prepare `model-assets` in the repository root first.

Image options:
- `--main` builds `nexent`
- `--web` builds `nexent-web`
- `--data-process` builds `nexent-data-process`
- `--mcp` builds `nexent-mcp`
- `--terminal` builds `nexent-ubuntu-terminal`
- `--docs` builds `nexent-docs`

```bash
# 🛠️ Create and use a new builder instance that supports multi-architecture builds
docker buildx create --name nexent_builder --use

# 🚀 build application for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent -f deploy/images/dockerfiles/main/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent -f deploy/images/dockerfiles/web/Dockerfile . --push

# 📊 build data_process for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-data-process -f deploy/images/dockerfiles/data-process/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-data-process -f deploy/images/dockerfiles/web/Dockerfile . --push

# 🌐 build web frontend for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-web -f deploy/images/dockerfiles/web/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-web -f deploy/images/dockerfiles/web/Dockerfile . --push

# 📚 build documentation for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile . --push

# 🔗 build MCP Server for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-mcp -f deploy/images/dockerfiles/mcp/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-mcp -f deploy/images/dockerfiles/mcp/Dockerfile . --push

# 💻 build Ubuntu Terminal for multiple architectures
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t nexent/nexent-terminal -f deploy/images/dockerfiles/terminal/Dockerfile . --push
docker buildx build --progress=plain --platform linux/amd64,linux/arm64 -t ccr.ccs.tencentyun.com/nexent-hub/nexent-terminal -f deploy/images/dockerfiles/terminal/Dockerfile . --push
```

### 💻 Local Development Build

```bash
# 🚀 Build application image (current architecture only)
docker build --progress=plain -t nexent/nexent -f deploy/images/dockerfiles/main/Dockerfile .

# 📊 Build data process image (current architecture only)
docker build --progress=plain -t nexent/nexent-data-process -f deploy/images/dockerfiles/data-process/Dockerfile .

# 📊 Build GPU data process image (current architecture only)
docker build --progress=plain -t nexent/nexent-data-process-gpu -f deploy/images/dockerfiles/data-process/Dockerfile --build-arg DATA_PROCESS_DEPENDENCY_VARIANT=gpu .

# 🌐 Build web frontend image (current architecture only)
docker build --progress=plain -t nexent/nexent-web -f deploy/images/dockerfiles/web/Dockerfile .

# 📚 Build documentation image (current architecture only)
docker build --progress=plain -t nexent/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile .

# 🔗 Build MCP Server image (current architecture only)
docker build --progress=plain -t nexent/nexent-mcp -f deploy/images/dockerfiles/mcp/Dockerfile .

# 💻 Build OpenSSH Server image (current architecture only)
docker build --progress=plain -t nexent/nexent-ubuntu-terminal -f deploy/images/dockerfiles/terminal/Dockerfile .

# 💻 Build OpenSSH Server image with Conda (current architecture only)
docker build --progress=plain -t nexent/nexent-ubuntu-terminal-conda -f deploy/images/dockerfiles/terminal/Dockerfile --build-arg TERMINAL_VARIANT=conda .
```

### 🧹 Clean up Docker resources

```bash
# 🧼 Clean up Docker build cache and unused resources
docker builder prune -f && docker system prune -f
```

### 🔧 Image Descriptions

#### Main Application Image (nexent/nexent)
- Contains backend API service
- Built from `deploy/images/dockerfiles/main/Dockerfile`
- Provides core agent services

#### Data Processing Image (nexent/nexent-data-process)
- Contains data processing service
- Built from `deploy/images/dockerfiles/data-process/Dockerfile`
- Handles document parsing and vectorization

#### Web Frontend Image (nexent/nexent-web)
- Contains Next.js frontend application
- Built from `deploy/images/dockerfiles/web/Dockerfile`
- Provides user interface

#### Documentation Image (nexent/nexent-docs)
- Contains Vitepress documentation site
- Built from `deploy/images/dockerfiles/docs/Dockerfile`
- Provides project documentation and API reference

#### MCP Server Image (nexent/nexent-mcp)
- Contains MCP (Model Context Protocol) proxy service
- Built from `deploy/images/dockerfiles/mcp/Dockerfile`
- Provides MCP server functionality for AI model integration

##### Pre-installed Tools and Features
- **Python Environment**: Python 3.11 + pip
- **MCP Proxy**: mcp-proxy package for protocol handling
- **Node.js**: Node.js 20.17.0 with npm
- **Architecture Support**: linux/amd64, linux/arm64
- **Base Image**: python:3.11-slim

#### OpenSSH Server Image (nexent/nexent-ubuntu-terminal)
- Ubuntu 24.04-based SSH server container
- Built from `deploy/images/dockerfiles/terminal/Dockerfile`
- Defaults to OpenSSH, Python, pip, venv, Git, Curl, and Wget
- `TERMINAL_VARIANT=conda` also installs Miniconda, Vim, and the compiler toolchain
- Runs as root and allows root login with password authentication

##### Pre-installed Tools and Features
- **Python Environment**: Python 3 + pip + venv
- **Conda Management**: Miniconda3 is included only in the `conda` variant
- **Development Tools**: Git, Curl, Wget; the `conda` variant also includes Vim and build-essential
- **SSH Service**: Container port 22, root login and password authentication enabled

### 🏷️ Tagging Strategy

Repository selection depends on `--registry` and `--push`:
- `--registry general` builds or pushes `nexent/*`.
- `--registry mainland --push` pushes to `ccr.ccs.tencentyun.com/nexent-hub/*` for mainland China acceleration.
- `--registry mainland` without `--push` still builds local `nexent/*` tags while using mainland build mirrors.

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
docker build -t nexent/nexent-docs -f deploy/images/dockerfiles/docs/Dockerfile .
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

After building is complete, you can deploy local images from the repository root:

```bash
bash deploy.sh docker --image-source local-latest
```

> `local-latest` uses local `latest` Nexent application images and avoids pulling those images again. You do not need to modify `deploy/docker/deploy.sh`.

### Package Local Images for Offline Deployment

After building local `latest` images, package them with the offline builder:

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

When `--version latest` or `--image-source local-latest` is used, the builder expects local Nexent application images and skips pulling those `latest` tags. The package can then be moved to another host and deployed with:

```bash
cd offline-package/docker-local
bash deploy.sh --load-images docker \
  --version latest \
  --components infrastructure,application,data-process,supabase \
  --image-source local-latest
```

By default, an offline package uses saved configuration or built-in defaults and creates the initial super administrator with `NEXENT_SUPER_ADMIN_PASSWORD` (default `Nexent@123`), displaying the effective password in the terminal after successful creation. When `bash deploy.sh --config ...` opens the interactive configuration and the account does not yet exist, deployment also prompts for and confirms the super administrator password. This input is neither written to the configuration file nor displayed in the terminal.

To push the packaged images to an internal registry during offline deployment, replace `--load-images` with `--push-images --image-registry-prefix registry.example.com/nexent`. If the prefix is omitted, the wrapper prompts for it before `push-images.sh` asks for the registry username and password. The deployment config will use the same registry prefix for Docker Compose image references.
