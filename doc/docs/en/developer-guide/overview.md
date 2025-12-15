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

## 🧱 Environment Preparation

All setup steps now live in the dedicated [Environment Preparation](./environment-setup) guide. It covers:

- Shared prerequisites for every contributor
- Full-stack Nexent setup (infrastructure, backend, frontend, runtime services)
- SDK-only installation workflows for developers who only need the Python package

Review that guide first, then return here for module-specific details.

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
- [Installation Guide](../quick-start/installation) - Environment setup and deployment
- [FAQ](../quick-start/faq) - Frequently asked questions
- [User Guide](../user-guide/home-page) - Nexent user guide

### Community Support
- [Discord Community](https://discord.gg/tb5H3S3wyv) - Real-time communication and support
- [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) - Issue reporting and feature requests