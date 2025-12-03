# Nexent Development Guide

This guide provides comprehensive information for developers to understand and contribute to the Nexent project, covering architecture, technology stack, development environment setup, and best practices.

## 🏗️ Overall Architecture

```
nexent/
├── frontend/          # Frontend application (Next.js + TypeScript)
├── backend/           # Backend services (FastAPI + Python)
├── sdk/              # Python SDK
├── docker/           # Docker deployment configuration
├── make/             # Build scripts
├── test/             # Test code
└── assets/           # Static resources
```

## 🛠️ Technology Stack

### Frontend Tech Stack
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **UI Library**: React + Tailwind CSS
- **State Management**: React Hooks
- **Internationalization**: react-i18next
- **HTTP Client**: Fetch API

### Backend Tech Stack
- **Framework**: FastAPI
- **Language**: Python 3.10+
- **Database**: PostgreSQL + Redis + Elasticsearch
- **File Storage**: MinIO
- **Task Queue**: Celery + Ray
- **AI Framework**: smolagents
- **Vector Database**: Elasticsearch

### Deployment Tech Stack
- **Containerization**: Docker + Docker Compose
- **Reverse Proxy**: Nginx
- **Monitoring**: Built-in health checks
- **Logging**: Structured logging

## 🚀 Development Environment Setup

### Environment Requirements
- Python 3.10+
- Node.js 18+
- Docker & Docker Compose
- uv (Python package manager)
- pnpm (Node.js package manager)

### Infrastructure Deployment
Before starting backend development, you need to deploy infrastructure services. These services include databases, caching, file storage, and other core components.

```bash
# Execute in the docker directory of the project root directory
cd docker
./deploy.sh --mode infrastructure
```

::: info Important Notes
Infrastructure mode will start PostgreSQL, Redis, Elasticsearch, and MinIO services. The deployment script will automatically generate keys and environment variables needed for development and save them to the `.env` file in the root directory. Generated keys include MinIO access keys and Elasticsearch API keys. All service URLs will be configured as localhost addresses for convenient local development.
:::

### Backend Setup
```bash
# Execute in the backend directory of the project root directory
cd backend
uv sync --all-extras
uv pip install ../sdk
```

::: tip Notes
`--all-extras` will install all optional dependencies, including data processing, testing, and other modules. Then install the local SDK package.
:::

#### Using Domestic Mirror Sources (Optional)
If network access is slow, you can use domestic mirror sources to accelerate installation:

```bash
# Using Tsinghua University mirror source
uv sync --all-extras --default-index https://pypi.tuna.tsinghua.edu.cn/simple
uv pip install ../sdk --default-index https://pypi.tuna.tsinghua.edu.cn/simple

# Using Alibaba Cloud mirror source
uv sync --all-extras --default-index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --default-index https://mirrors.aliyun.com/pypi/simple/

# Using multiple mirror sources (recommended)
uv sync --all-extras --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
```

::: info Mirror Source Information
- **Tsinghua University Mirror**: `https://pypi.tuna.tsinghua.edu.cn/simple`
- **Alibaba Cloud Mirror**: `https://mirrors.aliyun.com/pypi/simple/`
- **USTC Mirror**: `https://pypi.mirrors.ustc.edu.cn/simple/`
- **Douban Mirror**: `https://pypi.douban.com/simple/`

It's recommended to use multiple mirror source configurations to improve download success rates.
:::

### Frontend Setup
```bash
# Execute in the frontend directory of the project root directory
cd frontend
pnpm install
pnpm dev
```

### Service Startup
Before starting services, you need to create and activate the virtual environment:

```bash
# Execute in the backend directory of the project root directory
cd backend
python -m venv .venv
source .venv/bin/activate  # Activate virtual environment
```

::: warning Important Notes
On Windows, you need to execute the `source .venv/Scripts/activate` command to activate the virtual environment.
:::

generate .env in the root directory
```bash
bash docker/generate_env.sh
```

Nexent includes three core backend services that need to be started separately:

```bash
# Execute in the project root directory, please follow this order:
source .env && python backend/mcp_service.py            # MCP service
source .env && python backend/data_process_service.py   # Data processing service
source .env && python backend/config_service.py         # Config service
source .env && python backend/runtime_service.py        # Runtime service
```

::: warning Important Notes
All services must be started from the project root directory. Each Python command should be preceded by `source .env` to load environment variables. Ensure infrastructure services (database, Redis, Elasticsearch, MinIO) are started and running properly.
:::

## 🔧 Development Module Guide

### 🎨 Frontend Development
- **Tech Stack**: Next.js 14 + TypeScript + React + Tailwind CSS
- **Core Features**: User interface, real-time chat, configuration management, internationalization
- **Details**: See [Frontend Overview](../frontend/overview.md)

### 🔧 Backend Development
- **Tech Stack**: FastAPI + Python 3.10+ + PostgreSQL + Redis + Elasticsearch
- **Core Features**: API services, agent management, data processing, vector search
- **Details**: See [Backend Overview](../backend/overview.md)

### 🤖 AI Agent Development
- **Framework**: Enterprise agent framework based on smolagents
- **Core Features**: Agent creation, tool integration, reasoning execution, multi-modal support
- **Custom Agents**: See [Agents](../sdk/core/agents)
- **System Prompts**: Located in `backend/prompts/`
- **Implementation Steps**: Create instance → Configure tools → Set prompts → Test run
- **Details**: See [Agents](../sdk/core/agents)

### 🛠️ Tool Development
- **MCP Tool System**: Based on Model Context Protocol
- **Development Flow**: Implement logic → Register tool → Restart service
- **Protocol Compliance**: Tool development must follow MCP protocol
- **Detailed Specification**: See [Tool Development Guide](../sdk/core/tools.md)

### 📦 SDK Development Kit
- **Features**: Complete interfaces for AI agents, model calling, tool integration
- **Modules**: Core agents, data processing, vector database
- **Details**: See [SDK Overview](../sdk/overview.md)

### 📊 Data Processing
- **File Processing**: Supports 20+ formats
- **Chunking Strategies**: basic, by_title, none
- **Streaming Processing**: Memory optimization for large files
- **Details**: See [Data Processing Guide](../sdk/data-process.md)

## 🏗️ Build & Deployment

### Docker Build
For detailed build instructions, see [Docker Build Guide](../deployment/docker-build.md)

## 📋 Development Best Practices & Important Notes

### Code Quality
1. **Test-Driven**: Write unit tests and integration tests
2. **Code Review**: Follow team coding standards
3. **Documentation**: Update related documentation timely
4. **Error Handling**: Comprehensive exception handling and logging

### Performance Optimization
1. **Async Processing**: Use async architecture for performance
2. **Caching Strategy**: Proper use of caching mechanisms
3. **Resource Management**: Pay attention to memory and connection pool management
4. **Monitoring & Debugging**: Use performance monitoring tools

### Security Considerations
1. **Input Validation**: Strictly validate all input parameters
2. **Access Control**: Implement appropriate access controls
3. **Sensitive Information**: Properly handle sensitive data like API keys
4. **Security Updates**: Regular dependency and security updates

### Important Development Notes
1. **Service Dependencies**: Ensure all services are started before testing
2. **Code Changes**: Restart related services after code modifications
3. **Development Mode**: Use debug mode in development environment
4. **Prompt Testing**: System prompts need thorough testing
5. **Environment Variables**: Ensure configuration in `.env` file is correct
6. **Infrastructure**: Ensure infrastructure services are running properly before development

## 💡 Getting Help

### Documentation Resources
- [Installation Guide](./installation.md) - Environment setup and deployment
- [FAQ](./faq) - Frequently asked questions
- [User Guide](../user-guide/home-page) - Nexent user guide

### Community Support
- [Discord Community](https://discord.gg/tb5H3S3wyv) - Real-time communication and support
- [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) - Issue reporting and feature requests