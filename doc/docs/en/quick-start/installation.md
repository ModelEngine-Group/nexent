# Docker Installation & Deployment

## 🎯 Prerequisites

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU**  | 4 cores | 8 cores |
| **RAM**  | 8 GiB | 16 GiB |
| **Disk** | 40 GiB | 100 GiB |
| **Architecture** | x86_64 / ARM64 | |
| **Software** | Docker & Docker Compose installed | Docker 24+, Docker Compose v2+ |

> **💡 Note**: The recommended configuration of **8 cores and 16 GiB RAM** provides good performance for production workloads.

## 🚀 Quick Start

### 1. Download and Setup

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/docker
cp .env.example .env # Configure environment variables
```

> **💡 Tip**: If there are no special requirements, you can directly use `.env.example` for deployment without making any changes. If you need to configure voice models (STT/TTS), you will need to set the relevant parameters in `.env`. We will work on making this configuration available through the frontend soon—stay tuned.

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

#### ⚠️ Important Notes

1️⃣ **When deploying v1.8.0 or later for the first time**, please pay special attention to the `suadmin` super administrator account information output in the Docker logs. This account has the highest system privileges, and the password is only displayed upon first generation. It cannot be viewed again later, so please be sure to save it securely.

> This account is used for permission management only and cannot develop agents or create knowledge bases. Log in with this account and complete: Access tenant resources → Create tenant → Create tenant administrator, then log in with the tenant administrator account to use all features. For role permissions, see [User Management](../user-guide/user-management).

2️⃣ Forgot to note the `suadmin` account password? Follow these steps:

```bash
# Step 1: Delete su account record in supabase container
docker exec -it supabase-db-mini bash
psql -U postgres
select id, email from auth.users;
# Get the user_id of suadmin@nexent.com account
delete from auth.users where id = 'your_user_id';
delete from auth.identities where user_id = 'your_user_id';

# Step 2: Delete su account record in nexent database
docker exec -it nexent-postgresql bash
psql -U root -d nexent
delete from nexent.user_tenant_t where user_id = 'your_user_id';

# Step 3: Redeploy and record the su account password
```

### 3. Access Your Installation

When deployment completes successfully:
1. Open **http://localhost:3000** in your browser
2. Log in with the super administrator account
3. Access tenant resources → Create tenant and tenant administrator
4. Log in with the tenant administrator account
5. Refer to the [User Guide](../user-guide/home-page) to develop agents


## 🏗️ Service Architecture

Nexent uses a microservices architecture deployed via Docker Compose.

**Application Services:**
| Service | Description | Default Port |
|---------|-------------|--------------|
| nexent | Backend service | 5010 |
| nexent-web | Web frontend | 3000 |
| nexent-data-process | Data processing service | 5012 |
| nexent-northbound | Northbound API service | 5013 |

**Infrastructure Services:**
| Service | Description |
|---------|-------------|
| nexent-postgresql | Relational database |
| nexent-elasticsearch | Search and indexing engine |
| nexent-minio | S3-compatible object storage |
| redis | Caching layer |

**Supabase Services (Full Version Only):**
| Service | Description |
|---------|-------------|
| supabase-kong | API Gateway |
| supabase-auth | Authentication service |
| supabase-db-mini | Database service |

**Optional Services:**
| Service | Description |
|---------|-------------|
| nexent-openssh-server | SSH terminal for AI agents |

Internal services communicate using the Docker internal network.

## 💾 Data Persistence

Nexent uses Docker volumes for data persistence:

| Data Type | Volume Name | Default Host Path |
|-----------|------------------|-------------------|
| PostgreSQL | nexent-postgresql-data | `{dataDir}/postgresql` |
| Elasticsearch | nexent-elasticsearch-data | `{dataDir}/elasticsearch` |
| Redis | nexent-redis-data | `{dataDir}/redis` |
| MinIO | nexent-minio-data | `{dataDir}/minio` |
| Supabase DB (Full) | nexent-supabase-db-data | `{dataDir}/supabase-db` |

Default `dataDir` is `./volumes` (configurable via `ROOT_DIR` in `.env`).

## 🔌 Port Mapping

| Service | Internal Port | External Port | Description |
|---------|---------------|---------------|-------------|
| Web Interface | 3000 | 3000 | Main application access |
| Backend API | 5010 | 5010 | Backend service |
| Data Processing | 5012 | 5012 | Data processing API |
| Northbound API | 5013 | 5013 | Northbound interface service (A2A/MCP integration) |
| PostgreSQL | 5432 | 5434 | Database connection |
| Elasticsearch | 9200 | 9210 | Search engine API |
| MinIO API | 9000 | 9010 | Object storage API |
| MinIO Console | 9001 | 9011 | Storage management UI |
| Redis | 6379 | 6379 | Cache service |
| SSH Server | 22 | 2222 | Terminal tool access |

For complete port mapping details, see our [Dev Container Guide](../deployment/devcontainer.md#port-mapping).

## 🔧 Advanced Configuration

### Northbound Interface Configuration (NORTHBOUND_EXTERNAL_URL)

If you need to use any of the following features, configure the `NORTHBOUND_EXTERNAL_URL` environment variable:

1. **A2A Protocol Integration** - Third-party systems calling Nexent agents via A2A protocol
2. **MCP Tool Access** - Using MCP protocol to access Nexent resources like documents

**Configuration:**

Set the publicly accessible URL in your `.env` file:

```bash
# Format: protocol://host:port/api
# Local development (default):
NORTHBOUND_EXTERNAL_URL=http://localhost:5013/api

# Production - use your public IP or domain:
NORTHBOUND_EXTERNAL_URL=http://your-public-ip:5013/api
# or
NORTHBOUND_EXTERNAL_URL=https://api.yourdomain.com/api
```

> **Important**: The URL must include the `/api` suffix because the Northbound service uses FastAPI's `root_path="/api"` configuration.

## 💡 Need Help

- Browse the [FAQ](./faq) for common install issues
- Drop questions in our [Discord community](https://discord.gg/tb5H3S3wyv)
- File bugs or feature ideas in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues)

## 🔧 Build from Source

Want to build from source or add new features? Check the [Docker Build Guide](../deployment/docker-build) for step-by-step instructions.

For detailed setup instructions and customization options, see our [Developer Guide](../developer-guide/overview).