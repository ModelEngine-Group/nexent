# Software Architecture

Nexent separates the web frontend, configuration management, agent runtime, MCP, northbound APIs, and data processing into independent services. These services collaborate through well-defined APIs and use PostgreSQL, Elasticsearch, Redis, and MinIO to store different types of data. The project provides both Docker Compose and Kubernetes deployment options.

![Software Architecture Diagram](../../assets/architecture_zh.png)

## 🏗️ Overall Architecture Design

Nexent's software architecture follows layered design principles, structured into the following core layers from top to bottom:

### 🌐 Frontend Layer
- **Technology Stack**: Next.js + React + TypeScript
- **Functions**: Agent generation and configuration, chat interaction, resource management, and multimodal file uploads
- **Features**: Responsive design, SSE streaming results, WebSocket voice communication, and internationalization (i18n)

### 🔌 API Gateway Layer
The backend consists of multiple FastAPI-based API services:

| Service | Port | Description |
|---------|------|-------------|
| **nexent-config** | 5010 | Configuration API: agents, conversations, models, knowledge bases, memory, permissions, and resources |
| **nexent-runtime** | 5014 | Runtime API: agent execution, sandbox coordination, and streaming responses |
| **nexent-mcp** | 5011/5015 | MCP API and FastMCP service: MCP configuration, tool discovery, and container management |
| **nexent-northbound** | 5013 | Northbound API: external calls, conversation management, and A2A interfaces |
| **nexent-data-process** | 5012 | Data processing API: document parsing, chunking, vectorization, and indexing |

### 🧠 Business Logic Layer
The backend implements a clean layered architecture:

#### App Layer (`backend/apps/`)
- **Purpose**: HTTP boundary layer - parse/validate inputs, call services, map errors to HTTP
- **Key Modules**:
  - `agent_app.py` - Agent CRUD, version management, streaming execution
  - `conversation_management_app.py` - Multi-turn dialogue, history tracking
  - `api_key_app.py` / `quota_app.py` - API key and capacity management
  - `model_managment_app.py` - Model configuration, health checks
  - `skill_app.py` - Skill creation and management
  - `knowledge_summary_app.py` - Knowledge base operations
  - `remote_mcp_app.py` - Remote MCP tool management
  - `a2a_client_app.py` / `a2a_server_app.py` - A2A protocol support

#### Service Layer (`backend/services/`)
- **Purpose**: Core business logic orchestration, coordinate repositories/SDKs
- **Key Modules**:
  - `agent_service.py` - Agent lifecycle, configuration, and runtime request orchestration
  - `runtime_proxy_service.py` - Forward chat and debugging requests to the Runtime service
  - `agent_version_service.py` - Version publishing, rollback, comparison
  - `model_management_service.py` / `model_gateway_service.py` - Model management and unified adaptation
  - `memory_config_service.py` - Memory configuration, context building
  - `conversation_management_service.py` - Session management, history persistence
  - `skill_service.py` - Skill generation, template processing
  - `nl2agent_service.py` - Natural-language agent generation conversations and draft management
  - `data_process_service.py` - Document processing pipeline
  - `mcp_container_service.py` - MCP container lifecycle management
  - `remote_mcp_service.py` - Remote MCP server integration
  - `a2a_client_service.py` / `a2a_server_service.py` - A2A agent communication
  - `redis_service.py` - Caching, distributed locks, session storage

#### Agent Core (`backend/agents/`)
- **Purpose**: Agent execution framework built on SmolAgents
- **Key Components**:
  - `agent_run_manager.py` - Agent run lifecycle, workspace management, and streaming coordination
  - `create_agent_info.py` - Agent configuration, tool, and sandbox environment builder
  - `preprocess_manager.py` - Document preprocessing orchestration
  - `skill_creation_agent.py` - LLM-powered skill generation

### 📊 Data Layer
Distributed data storage architecture with multiple specialized databases:

#### 🗄️ Structured Data Storage
- **PostgreSQL** (port 5434): Primary relational database
  - User and tenant management (`user_tenant_db.py`)
  - Agent configuration and versions (`agent_db.py`, `agent_version_db.py`)
  - Tool definitions and instances (`tool_db.py`)
  - Conversation history (`conversation_db.py`)
  - Group and permission management (`group_db.py`, `role_permission_db.py`)
  - Memory configuration (`memory_config_db.py`)
  - Skill definitions (`skill_db.py`)
- **Features**: ACID transactions, relation integrity, multi-tenancy support

#### 🔍 Vector Search & Full-Text Search
- **Elasticsearch** (port 9210): Vector and full-text search engine
  - Knowledge base storage (`knowledge_db.py`)
  - Vector similarity search, hybrid search
  - Semantic chunking and indexing
- **Features**: Scalable search, relevance ranking, large-scale optimization

#### 💾 Cache Layer
- **Redis** (port 6379): High-performance in-memory database
  - Session caching
  - Temporary data storage
  - Distributed locks (`redis_service.py`)
  - Celery task broker for async jobs
- **Features**: Sub-millisecond latency, persistence with AOF

#### 📁 Object Storage
- **MinIO** (port 9010/9011): Distributed object storage
  - File uploads and attachments (`attachment_db.py`)
  - Document storage for knowledge base
  - Preview files and sandbox-generated artifacts
- **Features**: S3-compatible API, large file handling

The agent runtime also uses a separate workspace for the inputs and outputs of each run. Docker deployments share the workspace through the `nexent-agent-workspace` volume, while Kubernetes deployments use the `nexent-workspace` PVC. Artifacts that must be retained are synchronized to MinIO after a run, and the backend cleans up temporary working directories.

## 🔧 Core Service Architecture

### 🤖 Agent Services
```
Agent Framework (SmolAgents-based):
├── Agent Creation & Configuration
│   ├── NL2Agent requirement clarification and configuration generation
│   ├── Tool and Skill recommendation, installation, and binding
│   ├── Sub-agent relationship management
│   └── Version control and publishing
├── Agent Execution Engine
│   ├── Streaming response (SSE)
│   ├── Tool calling and orchestration
│   ├── Multi-model and multimodal input
│   └── Memory context building
├── Isolated Execution & File Processing
│   ├── Docker or other code sandbox levels
│   ├── Session or system lifecycle scope
│   ├── Isolated Skill script execution
│   └── Runtime workspace and MinIO artifact synchronization
├── Version Management
│   ├── Publishing and rollback
│   ├── Version comparison
│   └── A2A agent card registration
└── Lifecycle Management
    ├── Run registration and tracking
    ├── Stop and cleanup
    └── Preprocessing coordination
```

### 📈 Data Processing Services
```
Distributed Data Processing Pipeline:
├── Document Ingestion
│   ├── Multi-format support (20+ formats)
│   ├── PDF parsing with OCR
│   └── Table structure extraction
├── Chunking & Processing
│   ├── Semantic chunking algorithms
│   ├── Batch processing with Celery
│   └── Ray distributed computing
├── Vectorization & Indexing
│   ├── Embedding generation
│   ├── Elasticsearch indexing
│   └── Incremental updates
└── Preview Generation
    ├── PDF to preview conversion
    └── Image thumbnail generation
```

### 🌐 MCP Ecosystem
```
Model Context Protocol Integration:
├── Local MCP Service
│   ├── Stable built-in tools
│   └── Docker-based tool containers
├── Remote MCP Service
│   ├── Dynamic remote MCP server proxy
│   └── Outer API tool integration
├── MCP Container Management
│   ├── Container lifecycle (Docker)
│   ├── Log aggregation
│   └── Resource monitoring
└── FastMCP Server
    ├── Tool registration and discovery
    └── Standardized tool interfaces
```

### 🔄 A2A Protocol Support
```
Agent-to-Agent Communication:
├── A2A Client
│   ├── Agent card discovery
│   ├── Task submission and streaming
│   └── Response handling
├── A2A Server
│   ├── Agent card registration
│   ├── Task processing
│   └── Message streaming
└── Agent Adapter
    ├── Nexent ↔ A2A protocol translation
    └── Skill execution coordination
```

## 🚀 Distributed Architecture Features

### ⚡ Asynchronous Processing Architecture
- **Foundation**: asyncio-based high-performance async processing
- **Task Queue**: Celery + Redis for distributed task execution
- **Computing Framework**: Ray for distributed computing in data processing
- **Stream Processing**: Server-Sent Events (SSE) for real-time streaming
- **Concurrency Control**: Thread-safe concurrent processing mechanisms

### 🔄 Microservices Design
```
Service Decomposition Strategy:
├── nexent-config (5010)
│   └── Agent CRUD, configuration, user management
├── nexent-runtime (5014)
│   └── Agent execution, sandbox coordination, file artifacts, and streaming responses
├── nexent-mcp (5011/5015)
│   └── MCP tool protocol, container management
├── nexent-northbound (5013)
│   └── External APIs, A2A protocol, partner integration
├── nexent-data-process (5012)
│   └── Document processing, vectorization, Celery workers
├── nexent-web (3000)
│   └── Frontend Next.js application
├── nexent-sandbox (created according to the runtime strategy)
│   └── Isolated execution of model-generated code and Skill scripts
└── Optional Services
    ├── nexent-redis (6379) - Caching and message broker
    ├── nexent-elasticsearch (9210) - Vector search
    ├── nexent-postgresql (5434) - Relational data
    └── nexent-minio (9010) - Object storage
```

### 🌍 Containerized Deployment
```
Docker Compose Orchestration:
├── Application Services Containerization
├── Sandbox images and independent workspace volumes
├── Database Service Isolation
├── Network Layer Security (bridge network)
├── Volume Mounting for Data Persistence
├── Health Checks and Auto-restart
└── Corresponding Kubernetes Helm deployment option
```

## 🔐 Security and Scalability

### 🛡️ Security Architecture
- **Authentication**: Local accounts, OAuth, CAS, and northbound API keys
- **Authorization**: Role-based access control (RBAC) and user-group permissions
- **Data Security**: Tenant data isolation with sensitive configuration managed by backend services
- **Runtime Isolation**: Deployments use Docker sandboxes by default and restrict network access, shell access, CPU, memory, and per-step execution time

### 📈 Scalability Design
- **Service Scaling**: Configuration, runtime, northbound, and data-processing services can be deployed independently
- **Resource Control**: Compute resources can be configured separately for sandboxes and data-processing services
- **Storage Scaling**: MinIO stores objects, while Elasticsearch stores retrieval indexes
- **Caching and Tasks**: Redis provides caching, locks, and the Celery message broker

### 🔧 Modular Architecture
- **Loose Coupling**: Low inter-service dependencies, standardized interfaces
- **Plugin Architecture**: Hot-swappable tools and models
- **Configuration Management**: Environment-based configuration, dynamic updates
- **Single Source of Truth**: Environment variables centralized in `backend/consts/const.py`

## 🔄 System Data Flow

### 📥 User Request Flow
```
User Input → Web Frontend → nexent-config or nexent-northbound
    → App Layer Validation → Service Layer Orchestration
    → Data Access (Database Layer) → PostgreSQL/Elasticsearch/Redis/MinIO
```

### 🤖 Agent Execution Flow
```
User Message → nexent-config / nexent-northbound
    → Runtime Proxy → nexent-runtime
    → Memory and Metadata Context Build → Tool and Sandbox Execution
    → Model Inference → SSE Streaming Response
    → File Artifact Synchronization → Final Conversation Persistence
```

### 📚 Knowledge Base Processing Flow
```
File Upload → nexent-config → nexent-data-process
    → Document Parsing → Chunking → Vectorization
    → Elasticsearch Index → Search Ready
```

### ⚡ Real-time Processing Flow
```
Real-time Input → Streaming Endpoint → Async Processing
    → SSE Stream → Frontend Display
```

## 🎯 Architecture Advantages

### 🏢 Enterprise-grade Features
- **Deployability**: Service decomposition, health checks, and automatic restart
- **High Performance**: Async processing, Redis caching, vector search optimization
- **Concurrent Processing**: Asynchronous APIs, task queues, and an independent Runtime service
- **Monitoring Friendly**: OpenTelemetry observability, Grafana Tempo tracing, structured logging

### 🔧 Developer Friendly
- **Modular Development**: Clean layered architecture (App → Service → Database)
- **Standardized Interfaces**: Unified API design with FastAPI
- **Flexible Configuration**: Environment-based configuration, hot-reload
- **Easy Testing**: Comprehensive test suites, dependency injection

### 🌱 Ecosystem Compatibility
- **MCP Standard**: Full Model Context Protocol implementation
- **A2A Protocol**: Agent-to-agent communication support
- **Open Source Ecosystem**: Integration with SmolAgents, FastMCP, LangChain
- **Cloud Native**: Docker Compose and Kubernetes deployment support
- **Multi-model Support**: Compatible with mainstream AI model providers

---

This architecture separates configuration management, agent execution, and data processing, allowing deployment scenarios to select components as needed while providing clear boundaries for tool extensibility, runtime isolation, and external-system integration.
