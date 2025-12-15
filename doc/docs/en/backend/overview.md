# Backend Architecture Overview

Nexent's backend is built with FastAPI and Python, providing a robust and scalable API platform for AI agent services.

## Technology Stack

- **Framework**: FastAPI
- **Language**: Python 3.10+
- **Database**: PostgreSQL + Redis + Elasticsearch
- **File Storage**: MinIO
- **Task Queue**: Celery + Ray
- **AI Framework**: smolagents
- **Vector Database**: Elasticsearch

## Directory Structure

```
backend/
├── apps/                         # API application layer
│   ├── base_app.py              # FastAPI main application
│   ├── agent_app.py             # Agent-related APIs
│   ├── conversation_management_app.py # Conversation management APIs
│   ├── file_management_app.py   # File management APIs
│   ├── knowledge_app.py         # Knowledge base APIs
│   ├── model_managment_app.py   # Model management APIs
│   ├── config_sync_app.py       # Configuration sync APIs
│   └── voice_app.py             # Voice-related APIs
├── services/                     # Business service layer
│   ├── agent_service.py         # Agent business logic
│   ├── conversation_management_service.py # Conversation management
│   ├── vectordatabase_service.py # Search engine service
│   ├── model_health_service.py  # Model health checks
│   ├── prompt_service.py        # Prompt service
│   └── tenant_config_service.py # Tenant configuration service
├── database/                     # Data access layer
│   ├── client.py                # Database connections
│   ├── db_models.py             # Database models
│   ├── agent_db.py              # Agent data operations
│   ├── conversation_db.py       # Conversation data operations
│   ├── knowledge_db.py          # Knowledge base data operations
│   └── tenant_config_db.py      # Tenant configuration data operations
├── agents/                       # Agent core logic
│   ├── agent_run_manager.py     # Agent execution manager
│   ├── create_agent_info.py     # Agent information creation
│   └── default_agents/          # Default agent configurations
├── data_process/                 # Data processing module
│   ├── app.py                   # Data processing application
│   ├── config.py                # Data processing configuration
│   ├── tasks.py                 # Data processing tasks
│   ├── worker.py                # Data processing worker
│   └── utils.py                 # Data processing utilities
├── utils/                        # Utility classes
│   ├── auth_utils.py            # Authentication utilities
│   ├── config_utils.py          # Configuration utilities
│   ├── file_management_utils.py # File management utilities
│   ├── logging_utils.py         # Logging utilities
│   └── thread_utils.py          # Thread utilities
├── consts/                       # Constants definition
│   ├── const.py                 # System constants
│   └── model.py                 # Data models
├── prompts/                      # Prompt templates
│   ├── knowledge_summary_agent.yaml # Knowledge base summary agent
│   ├── manager_system_prompt_template.yaml # Manager system prompt
│   └── utils/                   # Prompt utilities
├── sql/                         # SQL scripts
├── assets/                      # Backend resource files
├── config_service.py            # Config service entry point
├── runtime_service.py           # Runtime service entry point
├── data_process_service.py      # Data processing service entry point
└── requirements.txt             # Python dependencies
```

## Architecture Responsibilities

### **Application Layer (apps)**
- API route definitions
- Request parameter validation
- Response formatting
- Authentication and authorization

### **Service Layer (services)**
- Core business logic implementation
- Data processing and transformation
- External service integration
- Business rule enforcement

### **Data Layer (database)**
- Database operations and ORM models
- Data access interfaces
- Transaction management
- Data consistency and integrity

### **Agent Layer (agents)**
- AI agent core logic and execution
- Tool calling and integration
- Reasoning and decision making
- Agent lifecycle management

### **Utility Layer (utils)**
- Common utility functions
- Configuration management
- Logging and monitoring
- Thread and process management

## Core Services

### Agent Management
- Agent creation and configuration
- Execution lifecycle management
- Tool integration and calling
- Performance monitoring

### Conversation Management
- Message handling and storage
- Context management
- History tracking
- Multi-tenant support

### Knowledge Base
- Document processing and indexing
- Vector search and retrieval
- Content summarization
- Knowledge graph construction

### File Management
- Multi-format file processing
- MinIO storage integration
- Batch processing capabilities
- Metadata extraction

### Model Integration
- Multiple model provider support
- Health monitoring and failover
- Load balancing and caching
- Performance optimization

## Data Flow Architecture

### 1. User Request Flow
```
User Input → Frontend Validation → API Call → Backend Routing → Business Service → Data Access → Database
```

### 2. AI Agent Execution Flow
```
User Message → Agent Creation → Tool Calling → Model Inference → Streaming Response → Result Storage
```

### 3. Knowledge Base File Processing Flow
```
File Upload → Temporary Storage → Data Processing → Vectorization → Knowledge Base Storage → Index Update
```

### 4. Real-time File Processing Flow
```
File Upload → Temporary Storage → Data Processing → Agent → Response
```

## Deployment Architecture

### Container Services
- **nexent**: Backend service (port 5010)
- **nexent-data-process**: Data processing service (port 5012)
- **nexent-postgresql**: Database (port 5434)
- **nexent-elasticsearch**: Search engine (port 9210)
- **nexent-minio**: Object storage (port 9010)
- **redis**: Cache service (port 6379)

### Optional Services
- **nexent-openssh-server**: SSH server for Terminal tool (port 2222)

## Development Setup

### Environment Setup
```bash
cd backend
uv sync && uv pip install -e ../sdk
```

### Service Startup
```bash
python backend/data_process_service.py   # Data processing service
python backend/config_service.py         # Config service
python backend/runtime_service.py        # Runtime service
python backend/mcp_service.py            # MCP service
```

## Performance and Scalability

### Async Architecture
- Based on asyncio for high-performance async processing
- Thread-safe concurrent processing mechanisms
- Optimized for distributed task queues

### Caching Strategy
- Multi-layer caching for improved response speed
- Redis for session and temporary data
- Elasticsearch for search result caching

### Load Balancing
- Intelligent concurrent limiting
- Resource pool management
- Auto-scaling capabilities

For detailed backend development guidelines, see the [Developer Guide](../developer-guide/overview).