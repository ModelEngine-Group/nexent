# Nexent Development Guide

This guide helps developers quickly understand Nexent's code structure, service boundaries, and local development workflow. Nexent is a zero-code agent platform that also provides a standalone Python SDK. Before making a change, identify whether it belongs to the frontend, backend services, or SDK, then choose the corresponding debugging and testing workflow.

## 🏗️ Overall Architecture

```text
nexent/
├── frontend/          # Web application (Next.js + TypeScript)
├── backend/           # HTTP APIs and business services (FastAPI + Python)
├── sdk/nexent/        # Agent runtime framework and data-processing capabilities
├── deploy/            # Docker, Kubernetes, and database deployment configuration
├── doc/               # VitePress documentation site
├── test/              # Backend and SDK tests
└── assets/            # Project static assets
```

A typical request crosses the following boundaries:

1. The frontend calls a FastAPI endpoint.
2. `backend/apps/` parses the request and delegates business processing to `backend/services/`.
3. The service layer reads databases, object storage, or configuration and passes runtime parameters to `sdk/nexent/`.
4. The SDK handles model calls, tool execution, agent collaboration, and sandbox workspaces, then returns results to the frontend as a regular response or streaming events.

Backend exceptions follow the same boundary: the service layer raises domain exceptions, and the API layer maps them to the appropriate HTTP status codes. Do not place database operations or business orchestration directly in endpoint functions when adding business logic.

## 🛠️ Technology Stack

### Frontend Technology Stack

- **Framework**: Next.js 15 (App Router)
- **Language**: TypeScript
- **UI**: React, Tailwind CSS, Ant Design
- **Chat UI**: Assistant UI
- **State Management**: React Hooks, Zustand, TanStack Query
- **Internationalization**: i18next
- **Package Manager**: npm

### Backend Technology Stack

- **Framework**: FastAPI
- **Language**: Python 3.11+
- **Database and Cache**: PostgreSQL, Redis
- **Retrieval and Vector Storage**: Elasticsearch
- **File Storage**: MinIO
- **Background Tasks**: Celery, Ray
- **Agent Framework**: Nexent SDK, smolagents
- **Runtime Isolation**: System-scoped sandboxes enabled by default, with an independent workspace for each run

### Deployment Technology Stack

- **Containerization**: Docker, Docker Compose
- **Cluster Deployment**: Kubernetes, Helm
- **Reverse Proxy**: Nginx
- **Observability**: OpenTelemetry and optional monitoring backends
- **Logging and Health Checks**: Structured logs and service health checks

## 🧱 Environment Preparation

Environment setup has moved to the dedicated [Environment Preparation](./environment-setup) guide, which covers:

- Common dependencies and prerequisites
- Full-stack Nexent setup, including infrastructure, backend, frontend, and service startup
- SDK-only installation

Complete the environment setup first, then return here and choose the module you want to develop.

## 🔧 Development Module Guide

### 🎨 Frontend Development

- **Directory**: `frontend/`
- **Core Functions**: Page interaction, agent configuration, real-time chat, resource management, and internationalization
- **Quality Checks**: Run `pnpm run check-all` to perform type checking, linting, formatting checks, and a build
- **Details**: See [Frontend Overview](../frontend/overview)

### 🔧 Backend Development

- **Directory**: `backend/`
- **API Layer**: `backend/apps/` handles request parsing, authentication, and HTTP error mapping
- **Service Layer**: `backend/services/` orchestrates business logic and raises domain exceptions
- **Configuration Entry Point**: Environment variables are read centrally in `backend/consts/const.py`; other modules import configuration from that file
- **Details**: See [Backend Overview](../backend/overview)

### 🤖 AI Agent Development

- **Directory**: `sdk/nexent/core/agents/`
- **Core Functions**: Agent execution, tool invocation, multi-agent collaboration, memory, streaming output, and sandbox workspaces
- **Configuration**: Backend services read platform configuration and pass it to the SDK as parameters; the SDK does not read deployment environment variables directly
- **System Prompts**: Located in `backend/prompts/`
- **Details**: See [Agent Module](../sdk/core/agents)

### 🛠️ Tool Development

- **Built-in Tools**: Registered in platform services and invoked by agents according to their configuration
- **MCP Tools**: Supports remote MCP services, containerized MCP services, and OpenAPI conversion
- **Skills**: Can include instructions, scripts, and resource files; scripts run in the runtime sandbox
- **Details**: See [Tool Development Guide](../sdk/core/tools)

### 📦 SDK Development Kit

- **Directory**: `sdk/nexent/`
- **Functions**: Provides agent, model, tool, memory, data-processing, and observability interfaces
- **Use Cases**: Can be used as the Nexent platform runtime or integrated independently as a Python package
- **Details**: See [SDK Overview](../sdk/overview)

### 📊 Data Processing

- **File Processing**: Parses common document, spreadsheet, presentation, and text formats
- **Chunking Strategies**: Supports `basic`, `by_title`, and `none`
- **Processing Flow**: A dedicated data-processing service handles file parsing, chunking, vectorization, and Elasticsearch indexing
- **Details**: See [Data Processing Guide](../sdk/data-process)

## 🏗️ Build and Deployment

### Docker Build

See the [Docker Build Guide](../deployment/docker-build) for detailed instructions. Deployment configuration is located under `deploy/`. Changes to Compose files must remain compatible with the project's declared minimum Docker Engine version.

## 📋 Development Best Practices and Important Notes

### Code Quality

1. **Keep Changes in Scope**: Place API handling, business logic, and SDK capabilities in their respective layers without duplicating implementations.
2. **Add Tests**: The backend and SDK use pytest. Defect fixes should cover at least the corresponding regression scenario.
3. **Check the Frontend**: Run type, formatting, lint, and build checks before submitting changes.
4. **Synchronize Documentation**: When user-visible behavior, configuration, or deployment changes, update both the Chinese and English documentation.

### Performance Optimization

1. **Prefer Asynchronous I/O**: Avoid long-running blocking operations in request-processing paths.
2. **Control Context Size**: Set reasonable limits for model output, message history, and tool results.
3. **Use Background Tasks**: Run time-consuming work such as document processing and memory consolidation through task queues.
4. **Release Resources**: Close connections and clean up temporary files and sandbox workspaces correctly.

### Security Considerations

1. **Validate Inputs**: Validate parameters, file types, and sizes at the HTTP boundary.
2. **Enforce Authorization**: The service layer must also check tenant, user-group, and resource permissions instead of relying only on hidden frontend entry points.
3. **Protect Sensitive Information**: Do not expose passwords or tokens in logs, Metadata, prompts, or tool output.
4. **Isolate Execution**: Use the platform sandbox and workspace capabilities when executing scripts or processing untrusted files.

### Important Development Notes

1. **Environment Variables**: Add environment-variable reads only in `backend/consts/const.py`.
2. **SDK Boundary**: The SDK receives configuration through function parameters and must not read environment variables directly.
3. **Database Migrations**: SQL files already merged into the target branch are immutable. Add database changes in a new versioned migration file.
4. **Service Dependencies**: Make sure PostgreSQL, Redis, Elasticsearch, and MinIO are ready before running application services.
5. **Sandbox Dependency**: System-scoped sandboxes are enabled by default. Make sure Docker is available when debugging tools or Skill scripts locally.
6. **Code Changes**: Restart the relevant services after modifying code, and write code comments and docstrings in English.
7. **Development Mode**: Use debugging mode in development environments.
8. **Prompt Testing**: Test system prompts thoroughly.
9. **Infrastructure**: Make sure infrastructure services are running before development.

## 💡 Getting Help

### Documentation Resources

- [Installation and Deployment](../quick-start/installation) - Environment setup and deployment
- [FAQ](../quick-start/faq) - Answers to common questions
- [User Guide](../user-guide/home-page) - Nexent usage guide

### Community Support

- [Discord Community](https://discord.gg/tb5H3S3wyv) - Real-time discussion and support
- [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) - Bug reports and feature requests
