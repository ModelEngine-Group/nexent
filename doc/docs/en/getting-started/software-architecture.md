# Software Architecture

Nexent adopts a modern distributed microservices architecture designed to provide a high-performance, scalable AI agent platform. The entire system is containerized with Docker and supports cloud-native and enterprise-grade deployment scenarios.

![Software Architecture Diagram](../../assets/architecture_zh.png)

## 🏗️ Overall Architecture Design

Nexent's software architecture follows layered design principles, structured into the following core layers from top to bottom:

### 🌐 Frontend Layer
- **Technology Stack**: Next.js + React + TypeScript
- **Functions**: User interface, agent interaction, multimodal input processing
- **Features**: Responsive design, real-time WebSocket communication, internationalization (i18n)

### 🔌 API Gateway Layer
Distributed API services built on FastAPI:

| Service | Port | Description |
|---------|------|-------------|
| **nexent-config** | 5010 | Main API service - agent CRUD, configuration management |
| **nexent-runtime** | 5014 | Runtime service - agent execution, streaming responses |
| **nexent-mcp** | 5011/5015 | MCP service - tool protocol management, FastMCP server |
| **nexent-northbound** | 5013 | External API service - A2A protocol, partner integrations |
| **nexent-data-process** | 5012 | Data processing service - document parsing, vectorization |

### 🧠 Business Logic Layer
The backend implements a clean layered architecture:

#### App Layer (`backend/apps/`)
- **Purpose**: HTTP boundary layer - parse/validate inputs, call services, map errors to HTTP
- **Key Modules**:
  - `agent_app.py` - Agent CRUD, version management, streaming execution
  - `conversation_management_app.py` - Multi-turn dialogue, history tracking
  - `model_managment_app.py` - Model configuration, health checks
  - `skill_app.py` - Skill creation and management
  - `knowledge_summary_app.py` - Knowledge base operations
  - `remote_mcp_app.py` - Remote MCP tool management
  - `a2a_client_app.py` / `a2a_server_app.py` - A2A protocol support

#### Service Layer (`backend/services/`)
- **Purpose**: Core business logic orchestration, coordinate repositories/SDKs
- **Key Modules**:
  - `agent_service.py` - Agent lifecycle, execution orchestration, memory management
  - `agent_version_service.py` - Version publishing, rollback, comparison
  - `model_management_service.py` - Multi-model support, load balancing
  - `memory_config_service.py` - Memory configuration, context building
  - `conversation_management_service.py` - Session management, history persistence
  - `skill_service.py` - Skill generation, template processing
  - `data_process_service.py` - Document processing pipeline
  - `mcp_container_service.py` - MCP container lifecycle management
  - `remote_mcp_service.py` - Remote MCP server integration
  - `a2a_client_service.py` / `a2a_server_service.py` - A2A agent communication
  - `redis_service.py` - Caching, distributed locks, session storage

#### Agent Core (`backend/agents/`)
- **Purpose**: Agent execution framework built on SmolAgents
- **Key Components**:
  - `agent_run_manager.py` - Agent run lifecycle, streaming coordination
  - `create_agent_info.py` - Agent configuration builder, tool integration
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
  - Preview generation and temporary files
- **Features**: S3-compatible API, large file handling

## 🔧 Core Service Architecture

### 🤖 Agent Services
```
Agent Framework (SmolAgents-based):
├── Agent Creation & Configuration
│   ├── Name/display name generation (LLM-powered)
│   ├── Tool integration and selection
│   ├── Sub-agent relationship management
│   └── Version control and publishing
├── Agent Execution Engine
│   ├── Streaming response (SSE)
│   ├── Tool calling and orchestration
│   ├── Multi-model support (LLM + Business logic)
│   └── Memory context building
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
│   └── Agent execution, streaming responses
├── nexent-mcp (5011/5015)
│   └── MCP tool protocol, container management
├── nexent-northbound (5013)
│   └── External APIs, A2A protocol, partner integration
├── nexent-data-process (5012)
│   └── Document processing, vectorization, Celery workers
├── nexent-web (3000)
│   └── Frontend Next.js application
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
├── Database Service Isolation
├── Network Layer Security (bridge network)
├── Volume Mounting for Data Persistence
├── Health Checks and Auto-restart
└── Kubernetes Support (IS_DEPLOYED_BY_KUBERNETES)
```

## 🔐 Security and Scalability

### 🛡️ Security Architecture
- **Authentication**: Multi-tenant support, user permission management
- **Authorization**: Role-based access control (RBAC), group-based permissions
- **Data Security**: Tenant data isolation, secure transmission (HTTPS)
- **Network Security**: Service间安全通信, Docker network isolation

### 📈 Scalability Design
- **Horizontal Scaling**: Independent microservice scaling, load balancing
- **Vertical Scaling**: Resource pool management, intelligent scheduling
- **Storage Scaling**: Distributed storage (MinIO), data sharding (Elasticsearch)
- **Cache Scaling**: Redis clustering for session and data caching

### 🔧 Modular Architecture
- **Loose Coupling**: Low inter-service dependencies, standardized interfaces
- **Plugin Architecture**: Hot-swappable tools and models
- **Configuration Management**: Environment-based configuration, dynamic updates
- **Single Source of Truth**: Environment variables centralized in `backend/consts/const.py`

## 🔄 Data Flow Architecture

### 📥 User Request Flow
```
User Input → Frontend Validation → API Gateway (nexent-config)
    → Route Distribution → Business Service (Service Layer)
    → Data Access (Database Layer) → PostgreSQL/Elasticsearch/Redis/MinIO
```

### 🤖 Agent Execution Flow
```
User Message → nexent-runtime → Agent Service
    → Memory Context Build → Tool Resolution
    → Model Inference (Streaming) → SSE Response
    → Conversation Save → History Storage
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
- **High Availability**: Multi-service redundancy, health checks, auto-restart
- **High Performance**: Async processing, Redis caching, vector search optimization
- **High Concurrency**: Distributed architecture, load balancing
- **Monitoring Friendly**: Prometheus metrics, Jaeger tracing, structured logging

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

This architectural design ensures that Nexent can provide a stable, scalable AI agent service platform while maintaining high performance. Whether for individual users or enterprise-level deployments, it delivers excellent user experience and technical assurance.
