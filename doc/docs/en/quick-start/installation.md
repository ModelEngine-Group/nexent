# Installation & Deployment

## 🎯 Prerequisites

| Resource | Minimum |
|----------|---------|
| **CPU**  | 2 cores |
| **RAM**  | 6 GiB   |
| **Architecture** | x86_64 / ARM64 |
| **Software** | Docker & Docker Compose installed |

## 🚀 Quick Start

### 1. Download and Setup

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/docker
cp .env.example .env # Configure environment variables
```

 
Note on ModelEngine configuration:
- `MODEL_ENGINE_ENABLED` (default `false`) — set to `true` to enable ModelEngine integration.
- `MODEL_ENGINE_HOST` — base URL for your ModelEngine deployment (only used when `MODEL_ENGINE_ENABLED=true`).

### 2. Deployment Options

Run the following command to start deployment:

```bash
bash deploy.sh
```

After executing this command, the system will provide two different versions for you to choose from:

**Version Selection:**
- **Speed version (Lightweight & Fast Deployment, Default)**: Quick startup of core features, suitable for individual users and small teams
- **Full version (Complete Feature Edition)**: Provides enterprise-level tenant management and resource isolation features, but takes longer to install, suitable for enterprise users

**Deployment Modes:**
- **Development mode (default)**: Exposes all service ports for debugging
- **Infrastructure mode**: Only starts infrastructure services
- **Production mode**: Only exposes port 3000 for security

**Optional Components:**
- **Terminal Tool**: Enables openssh-server for AI agent shell command execution
- **Regional optimization**: Mainland China users can use optimized image sources

### 3. Access Your Installation

When deployment completes successfully:
1. Open **http://localhost:3000** in your browser
2. Refer to the [User Guide](../user-guide/home-page) to develop agents


## 🏗️ Service Architecture

Nexent uses a microservices architecture with the following core services:

**Core Services:**
- `nexent`: Backend service (port 5010)
- `nexent-web`: Frontend interface (port 3000)
- `nexent-data-process`: Data processing service (port 5012)

**Infrastructure Services:**
- `nexent-postgresql`: Database (port 5434)
- `nexent-elasticsearch`: Search engine (port 9210)
- `nexent-minio`: Object storage (port 9010, console 9011)
- `redis`: Cache service (port 6379)

**Optional Services:**
- `nexent-openssh-server`: SSH server for Terminal tool (port 2222)

## 🔌 Port Mapping

| Service | Internal Port | External Port | Description |
|---------|---------------|---------------|-------------|
| Web Interface | 3000 | 3000 | Main application access |
| Backend API | 5010 | 5010 | Backend service |
| Data Processing | 5012 | 5012 | Data processing API |
| PostgreSQL | 5432 | 5434 | Database connection |
| Elasticsearch | 9200 | 9210 | Search engine API |
| MinIO API | 9000 | 9010 | Object storage API |
| MinIO Console | 9001 | 9011 | Storage management UI |
| Redis | 6379 | 6379 | Cache service |
| SSH Server | 22 | 2222 | Terminal tool access |

For complete port mapping details, see our [Dev Container Guide](../deployment/devcontainer.md#port-mapping).

## 💡 Need Help

- Browse the [FAQ](./faq) for common install issues
- Drop questions in our [Discord community](https://discord.gg/tb5H3S3wyv)
- File bugs or feature ideas in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues)

## 🔧 Build from Source

Want to build from source or add new features? Check the [Docker Build Guide](../deployment/docker-build) for step-by-step instructions.

For detailed setup instructions and customization options, see our [Developer Guide](../developer-guide/overview).
