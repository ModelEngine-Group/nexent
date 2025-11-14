# Hierarchical Proxy Architecture Documentation

## System Architecture Flowchart

```mermaid
graph TD
    A["Frontend Requests"] --> B["Main Service (FastAPI)<br/>(Port: 5010)"]
    
    B --> B1["Web API Management Layer<br/>(/api/mcp/*)"]
    B1 --> B2["/api/mcp/tools/<br/>(Get Tool Information)"]
    B1 --> B3["/api/mcp/add<br/>(Add MCP Server)"]
    B1 --> B4["/api/mcp/<br/>(Delete MCP Server)"]
    B1 --> B5["/api/mcp/list<br/>(List MCP Servers)"]
    B1 --> B6["/api/mcp/recover<br/>(Recover MCP Servers)"]
    
    B --> C["MCP Service (FastMCP)<br/>(Port: 5011)"]
    
    C --> C1["Local Service Layer"]
    C --> C2["Remote Proxy Layer"]
    C --> C3["MCP Protocol API Layer"]
    
    C1 --> C11["local_mcp_service<br/>(Stable Mount)"]
    
    C2 --> C21["RemoteProxyManager<br/>(Dynamic Management)"]
    C21 --> C22["Remote Proxy 1"]
    C21 --> C23["Remote Proxy 2"]
    C21 --> C24["Remote Proxy n..."]
    
    C3 --> C31["/healthcheck<br/>(Connectivity Check)"]
    C3 --> C32["/list-remote-proxies<br/>(List Proxies)"]
    C3 --> C33["/add-remote-proxies<br/>(Add Proxies)"]
    C3 --> C34["/remote-proxies<br/>(Delete Proxies)"]
    
    C22 --> D1["Remote MCP Service 1<br/>(SSE/HTTP)"]
    C23 --> D2["Remote MCP Service 2<br/>(SSE/HTTP)"]
    C24 --> D3["Remote MCP Service n<br/>(SSE/HTTP)"]
    
    style A fill:#e1f5fe
    style B fill:#f3e5f5
    style C fill:#e8f5e8
    style B1 fill:#fff3e0
    style C1 fill:#e8f5e8
    style C2 fill:#fff3e0
    style C3 fill:#fce4ec
```

## Architecture Overview

This system implements a **dual-service proxy architecture** consisting of two independent services:

### 1. Main Service (FastAPI) - Port 5010
- **Purpose**: Provides web management interface and RESTful API, serving as the single entry point for frontend
- **Features**: User-oriented management with authentication, multi-tenant support, and proxy calls to MCP service
- **Startup File**: `main_service.py`

### 2. MCP Service (FastMCP) - Port 5011  
- **Purpose**: Provides MCP protocol services and proxy management (internal service)
- **Features**: MCP protocol standard, supports local services and remote proxies, primarily called by main service
- **Startup File**: `nexent_mcp_service.py`

**Important Note**: Frontend clients only directly access the main service (5010). All MCP-related operations are completed by the main service proxying calls to the MCP service (5011).

## Core Features

### 1. Local Service Stability
- `local_mcp_service` and other local services maintain stable operation
- Adding, removing, or updating remote proxies does not affect local services

### 2. Dynamic Remote Proxy Management
- Supports dynamic addition, removal, and updating of remote MCP service proxies
- Each remote proxy is managed as an independent service
- Supports multiple transport methods (SSE, HTTP)

### 3. Dual-Layer API Interface

#### Main Service API (Port 5010) - External Management Layer
**Interfaces directly accessed by frontend clients**, providing user-oriented management features with authentication and multi-tenant support:

**Get Remote MCP Server Tool Information**
```http
GET /api/mcp/tools/?service_name={name}&mcp_url={url}
Authorization: Bearer {token}
```

**Add Remote MCP Server**
```http
POST /api/mcp/add?mcp_url={url}&service_name={name}
Authorization: Bearer {token}
```

**Delete Remote MCP Server**
```http
DELETE /api/mcp/?service_name={name}&mcp_url={url}
Authorization: Bearer {token}
```

**Get Remote MCP Server List**
```http
GET /api/mcp/list
Authorization: Bearer {token}
```

**Recover Remote MCP Servers**
```http
GET /api/mcp/recover
Authorization: Bearer {token}
```

#### MCP Service API (Port 5011) - Internal Protocol Layer
**Internal interfaces primarily called by main service**, also available for external MCP clients:

**Connectivity Check**
```http
GET /healthcheck?mcp_url={url}
```
Quickly checks if remote MCP service is reachable, returns simple connection status.

**List All Remote Proxies**
```http
GET /list-remote-proxies
```

**Add Remote Proxy**
```http
POST /add-remote-proxies
Content-Type: application/json

{
    "service_name": "my_service",
    "mcp_url": "http://localhost:5012/sse", 
    "transport": "sse"
}
```

**Delete Remote Proxy**
```http
DELETE /remote-proxies?service_name={service_name}
```

## Usage

### 1. Starting Services

**Start Main Service**
```bash
cd backend
python edit_time_service.py
python runtime_service.py
```
Service will start at `http://localhost:5010`.

**Start MCP Service**
```bash
cd backend
python nexent_mcp_service.py
```
Service will start at `http://localhost:5011`.

### 2. Using APIs

#### Recommended Method: Managing MCP Servers via Main Service
**Frontend clients should use this method**, featuring complete authentication and permission management:

```bash
# Add remote MCP server
curl -X POST "http://localhost:5010/api/mcp/add?mcp_url=http://external-server:5012/sse&service_name=external_service" \
  -H "Authorization: Bearer {your_token}"

# Get MCP server list
curl -H "Authorization: Bearer {your_token}" \
  "http://localhost:5010/api/mcp/list"
```

#### Internal Debugging: Direct Access to MCP Service (Optional)
**For debugging or external MCP client direct integration only**:

```bash
# Test remote service connection
curl "http://localhost:5011/healthcheck?mcp_url=http://external-server:5012/sse"

# Add remote proxy
curl -X POST http://localhost:5011/add-remote-proxies \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "external_service",
    "mcp_url": "http://external-server:5012/sse",
    "transport": "sse"
  }'
```

## Code Structure

### Main Service Components (main_service.py)
- **FastAPI Application**: Provides Web API and management interface
- **Multi-tenant Support**: Multi-tenant management based on authentication
- **Router Management**: Contains routers for multiple functional modules

### MCP Service Components (nexent_mcp_service.py)

#### RemoteProxyManager Class
Responsible for managing the lifecycle of all remote proxies:
- `add_remote_proxy()`: Add new remote proxy
- `remove_remote_proxy()`: Remove specified remote proxy  
- `update_remote_proxy()`: Update existing remote proxy
- `list_remote_proxies()`: List all remote proxy configurations
- `_validate_remote_service()`: Validate remote service connection

#### MCP Protocol Endpoints
- `/healthcheck`: Connectivity check endpoint
- `/list-remote-proxies`: List all remote proxy endpoint
- `/add-remote-proxies`: Add remote proxy endpoint
- `/remote-proxies`: Delete specific proxy endpoint

### Remote MCP Management (remote_mcp_app.py)
- **Authentication Integration**: Integrated with main service authentication system
- **Data Persistence**: Supports database storage and recovery
- **Service Discovery**: Tool information acquisition and management

## Service Dependencies

```mermaid
graph LR
    A["Frontend Client"] --> B["Main Service :5010<br/>(FastAPI)"]
    B --> C["MCP Service :5011<br/>(FastMCP)"]
    B --> D["Database<br/>(Users/Tenants/Config)"]
    C --> E["Local MCP Service"]
    C --> F["Remote MCP Proxy"]
    
    G["External MCP Client"] -.-> C
    
    style A fill:#e1f5fe
    style B fill:#f3e5f5
    style C fill:#e8f5e8
    style G fill:#fff3e0
```

## Interface Sequence Diagrams

### 1. Get Remote MCP Tool Information (GET /api/mcp/tools/)

```mermaid
sequenceDiagram
    participant C as Frontend Client
    participant M as Main Service(5010)
    participant T as Tool Config Service
    participant R as Remote MCP Service

    C->>M: GET /api/mcp/tools/?service_name=xxx&mcp_url=xxx
    Note over C,M: Authorization: Bearer token (optional)
    
    M->>T: get_tool_from_remote_mcp_server(service_name, mcp_url)
    T->>R: Direct connection to remote MCP service for tool list
    R-->>T: Return tool information
    T-->>M: Tool information list
    
    M-->>C: JSON response {tools: [...], status: "success"}
    
    Note over M,C: Returns 400 status code on error
    Note over T,R: Note: This interface accesses remote MCP directly, not through local MCP service(5011)
```

### 2. Add Remote MCP Server (POST /api/mcp/add)

```mermaid
sequenceDiagram
    participant C as Frontend Client
    participant M as Main Service(5010)
    participant A as Auth System
    participant S as MCP Service Management
    participant DB as Database
    participant MCP as MCP Service(5011)
    participant R as Remote MCP Service

    C->>M: POST /api/mcp/add?mcp_url=xxx&service_name=xxx
    Note over C,M: Authorization: Bearer token
    
    M->>A: get_current_user_id(authorization)
    A-->>M: user_id, tenant_id
    
    M->>S: add_remote_mcp_server_list(tenant_id, user_id, mcp_url, service_name)
    
    S->>DB: Check if service name already exists
    DB-->>S: Check result
    
    alt Service name already exists
        S-->>M: JSONResponse (409 - Service name already exists)
        M-->>C: Error response (409)
    else Service name available
        S->>S: add_remote_proxy()
        S->>MCP: POST /add-remote-proxies
        MCP->>MCP: Validate remote MCP service connection
        MCP->>R: Connectivity test
        R-->>MCP: Connection response
        
        alt MCP connection successful
            MCP->>MCP: Create and mount remote proxy
            MCP-->>S: 200 - Successfully added proxy
            S->>DB: Save MCP server configuration
            DB-->>S: Save result
            S-->>M: Success result
            M-->>C: JSON response {message: "Successfully added", status: "success"}
        else MCP connection failed
            MCP-->>S: Error response (503/409/400)
            S-->>M: Error result/JSONResponse
            M-->>C: Error response (400/409/503)
        end
    end
```

### 3. Delete Remote MCP Server (DELETE /api/mcp/)

```mermaid
sequenceDiagram
    participant C as Frontend Client
    participant M as Main Service(5010)
    participant A as Auth System
    participant S as MCP Service Management
    participant DB as Database
    participant MCP as MCP Service(5011)

    C->>M: DELETE /api/mcp/?service_name=xxx&mcp_url=xxx
    Note over C,M: Authorization: Bearer token
    
    M->>A: get_current_user_id(authorization)
    A-->>M: user_id, tenant_id
    
    M->>S: delete_remote_mcp_server_list(tenant_id, user_id, mcp_url, service_name)
    
    S->>DB: Find and delete MCP server configuration
    DB-->>S: Delete result
    
    alt Database deletion failed
        S-->>M: JSONResponse (400 - server not record)
        M-->>C: Error response (400)
    else Database deletion successful
        S->>MCP: DELETE /remote-proxies?service_name=xxx
        MCP->>MCP: Unmount remote proxy service
        
        alt MCP deletion successful
            MCP-->>S: 200 - Successfully removed
            S-->>M: Success result
            M-->>C: JSON response {message: "Successfully deleted", status: "success"}
        else MCP deletion failed
            MCP-->>S: 404/400 - Deletion failed
            S-->>M: Error result/JSONResponse
            M-->>C: Error response (400/404)
        end
    end
```

### 4. Get Remote MCP Server List (GET /api/mcp/list)

```mermaid
sequenceDiagram
    participant C as Frontend Client
    participant M as Main Service(5010)
    participant A as Auth System
    participant S as MCP Service Management
    participant DB as Database

    C->>M: GET /api/mcp/list
    Note over C,M: Authorization: Bearer token
    
    M->>A: get_current_user_id(authorization)
    A-->>M: user_id, tenant_id
    
    M->>S: get_remote_mcp_server_list(tenant_id)
    S->>DB: Query tenant's MCP server list
    DB-->>S: Server list data
    S-->>M: remote_mcp_server_list
    
    M-->>C: JSON response {remote_mcp_server_list: [...], status: "success"}
    
    Note over M,C: Returns 400 status code on error
```

### 5. Recover Remote MCP Servers (GET /api/mcp/recover)

```mermaid
sequenceDiagram
    participant C as Frontend Client
    participant M as Main Service(5010)
    participant A as Auth System
    participant S as MCP Service Management
    participant DB as Database
    participant MCP as MCP Service(5011)
    participant R as Remote MCP Service

    C->>M: GET /api/mcp/recover
    Note over C,M: Authorization: Bearer token
    
    M->>A: get_current_user_id(authorization)
    A-->>M: user_id, tenant_id
    
    M->>S: recover_remote_mcp_server(tenant_id)
    
    S->>DB: Query all tenant's MCP server configurations
    DB-->>S: Server list in database (record_set)
    
    S->>MCP: GET /list-remote-proxies
    MCP-->>S: Current proxy list in MCP service (remote_set)
    
    S->>S: Calculate difference (record_set - remote_set)
    
    loop For each missing MCP server
        S->>S: add_remote_proxy(mcp_name, mcp_url)
        S->>MCP: POST /add-remote-proxies
        MCP->>R: Connect to remote MCP service
        R-->>MCP: Connection response
        
        alt Addition successful
            MCP-->>S: 200 - Successfully added
        else Addition failed
            MCP-->>S: Error response
            S-->>M: Error result/JSONResponse
            M-->>C: Error response (400)
            Note over S,M: If any server recovery fails, entire operation fails
        end
    end
    
    S-->>M: Success result
    M-->>C: JSON response {message: "Successfully recovered", status: "success"}
```

## Sequence Diagram Explanation

### Interface Classification

#### 1. Direct Remote MCP Access Interfaces
- **GET /api/mcp/tools/**: Directly accesses remote MCP through tool configuration service for tool information
- Feature: Does not go through local MCP service (5011), directly connects to external MCP service

#### 2. Local MCP Service Interaction Interfaces  
- **POST /api/mcp/add**: Validates connection and adds proxy through MCP service
- **DELETE /api/mcp/**: Removes proxy through MCP service
- **GET /api/mcp/recover**: Recovers proxy connections through MCP service
- Feature: Requires interaction with local MCP service (5011), involves proxy lifecycle management

#### 3. Database-Only Interfaces
- **GET /api/mcp/list**: Directly queries database for server list
- Feature: Simplest flow, only involves database queries

### Common Flow Characteristics
1. **Authentication Flow**: Except for tool query interface, other interfaces require Bearer token authentication, obtaining user and tenant information through `get_current_user_id()`
2. **Multi-tenant Isolation**: All operations are isolated based on `tenant_id`, ensuring data security
3. **Error Handling**: Unified exception handling mechanism, returning standardized JSON error responses
4. **Proxy Architecture**: Main service acts as proxy, coordinating calls to various backend services

### Key Interaction Points
- **Authentication System**: Validates user identity and permissions
- **Database**: Stores and manages MCP server configuration information
- **MCP Service (5011)**: Handles MCP protocol interaction and proxy management
- **Tool Configuration Service**: Handles tool information acquisition
- **Remote MCP Service**: External MCP service providers

### Operation Sequence Importance
- **Add Operations**: First validate MCP connection, save to database only after success (ensures data consistency)
- **Delete Operations**: First delete database records, then remove MCP proxy (prevents data residue)
- **Recovery Operations**: Compare database and MCP service differences, supplement missing proxies

## Error Handling

- Validates remote service connection before adding proxies
- Provides detailed error information and status codes
- Supports graceful service unloading and reloading
- Dual-layer error handling: management layer and protocol layer

## Performance Optimization

- Proxy services are loaded on demand
- Supports concurrent operations
- Minimizes impact on existing services
- Loosely coupled service design

## Security Features

- **Authentication & Authorization**: Main service supports Bearer token authentication
- **Multi-tenant Isolation**: Isolated management of MCP servers for different tenants
- **Connection Validation**: Performs connectivity verification before adding remote services 