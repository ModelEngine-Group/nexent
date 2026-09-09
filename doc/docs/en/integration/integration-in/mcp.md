# MCP Service Integration

MCP (Model Context Protocol) is the standard communication protocol for AI tools. Nexent platform supports integrating tool services conforming to MCP specifications, greatly extending the capabilities of your Agents.

## Integration Methods Overview

Nexent supports multiple MCP service integration methods:

| Method | Use Case | Prerequisites |
|--------|----------|---------------|
| **Remote URL** | Independently deployed MCP services (HTTP/SSE) | Service URL is accessible |
| **Container** | MCP services running in containers | Docker environment or image |
| **API-to-MCP** | Convert REST API to MCP tools | OpenAPI specification document |

## Method 1: Remote URL Integration

Suitable for independently deployed MCP services, such as MCP services provided by ModelScope.

### Steps

1. Navigate to **MCP Repository** → **My MCP** page
2. Click "Add MCP Service"
3. Select integration type as "Remote"
4. Fill in service configuration:

| Config Item | Description | Example |
|-------------|-------------|---------|
| **Service Name** | Display name for the MCP service | `modelscope-github` |
| **Service URL** | HTTP/SSE endpoint address of the MCP service | `https://api.modelscope.cn/mcp/sse` |
| **Authorization Token** | Authentication token (if needed) | `Bearer xxx` |
| **Custom Headers** | Additional HTTP headers (JSON format) | `{"X-API-Key": "xxx"}` |

5. Click "Connectivity Test" to confirm the service is accessible
6. Click "Save" to complete the addition

### Example: Integrate ModelScope GitHub MCP

ModelScope provides rich MCP services. Here's how to integrate the GitHub MCP:

1. Visit [ModelScope MCP Market](https://modelscope.cn/mcp) to find GitHub MCP
2. Get the service SSE endpoint address
3. Fill in configuration in Nexent:

```json
{
  "name": "modelscope-github",
  "url": "https://api.modelscope.cn/mcp/servers/github",
  "headers": {}
}
```

4. After passing the test, you can use it

## Method 2: Container Integration

Suitable for MCP services running as Docker containers, such as services deployed via npx.

### Steps

1. Navigate to **MCP Repository** → **My MCP** page
2. Click "Add MCP Service"
3. Select integration type as "Container"
4. Fill in container configuration JSON:

```json
{
  "mcpServers": {
    "service-name": {
      "command": "npx",
      "args": ["-y", "@modelScope/mcp-server-package@version"]
    }
  }
}
```

5. Fill in container port number
6. Click "Save", and the system will automatically start the container and configure it

### Port Explanation

- **Docker/Kubernetes deployment**: Container port is automatically allocated by the system
- **Local deployment**: Use recommended port or manually specify an available port

## Method 3: API-to-MCP

This is a powerful feature provided by Nexent that can quickly convert existing REST APIs into MCP tools without writing MCP Server code.

### Use Cases

- Enterprise already has REST API interfaces and wants to quickly give Agents the ability to call them
- Third-party services provide HTTP APIs but have no MCP adapter
- Rapid prototyping that needs to quickly expose API capabilities to Agents

### Steps

1. Navigate to **Agent Development** → **MCP Configuration**
2. Select integration type as "API to MCP"
3. Fill in configuration:

| Config Item | Description | Example |
|-------------|-------------|---------|
| **Service Name** | Display name for MCP service | `company-crm-api` |
| **OpenAPI JSON** | JSON content of OpenAPI 3.x specification | (Paste JSON) |
| **Base Service URL** | Base address of the API service | `https://api.example.com` |

4. Click "Add" to complete conversion

### OpenAPI Specification Support

The conversion feature supports the following OpenAPI 3.x features:

- HTTP methods: GET/POST/PUT/DELETE
- Path, Query, and Header parameters
- Request Body (JSON format)
- Authentication info (Bearer Token, API Key, etc.)

### Example: Convert Internal Ticket System to MCP

Suppose you have a ticket system with the following OpenAPI definition:

```json
{
  "openapi": "3.0.0",
  "info": {"title": "Ticket System", "version": "1.0.0"},
  "paths": {
    "/tickets": {
      "get": {
        "summary": "Get ticket list",
        "parameters": [
          {"name": "status", "in": "query", "schema": {"type": "string"}}
        ]
      },
      "post": {
        "summary": "Create ticket",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "title": {"type": "string"},
                  "description": {"type": "string"}
                }
              }
            }
          }
        }
      }
    }
  }
}
```

After conversion to MCP, Agents can call these interfaces through natural language, such as "Query all pending tickets".

## Managing Integrated MCP Services

### Viewing Service Status

Each service card displays the following status:

| Status | Description |
|--------|-------------|
| **Enabled** | Whether the service is enabled; disabled tools won't appear in Agent tool selection |
| **Under Review** | Application pending admin review |
| **Published** | Shared in repository with same tenant |
| **Rejected** | Publication application not approved |

### Common Operations

- **Edit**: Modify service configuration
- **Connectivity Test**: Test service connection status
- **Apply to Publish**: Share service with same tenant members
- **Delete**: Remove service (container services will clean up containers simultaneously)

## Using MCP Tools in Agents

### Assigning to Agents

1. Navigate to **Agent Development** page
2. In "Select Agent's Tools", switch to **MCP** tab
3. Find the added MCP service and expand to view tool list
4. Select needed tools and configure necessary parameters
5. Save Agent configuration

### Tool Testing

When assigning tools, you can click the "Test" button on the tool card to verify functionality:

1. Fill in test parameters
2. Click "Execute Test"
3. View returned results

## Best Practices

### Security Recommendations

1. **Protect authentication info**: Use the platform's key management feature, avoid storing Tokens in plain text in configuration
2. **Principle of least privilege**: Only apply for minimum permissions required by the service
3. **Regular rotation**: Regularly change API Keys and other authentication info

### Performance Recommendations

1. **Service availability**: Ensure MCP services are stable and reliable to avoid slowing down Agent responses
2. **Timeout settings**: Set reasonable timeout for time-consuming operations
3. **Error handling**: Use tool testing to discover and handle issues in advance

### Maintenance Recommendations

1. **Version management**: Follow MCP service updates and upgrade to stable versions in a timely manner
2. **Log monitoring**: Monitor service call logs and handle anomalies promptly
3. **Dependency management**: Record service dependencies for troubleshooting

## FAQ

### Q: What to do if MCP service connection fails?

1. Check if the service URL is accessible
2. Confirm network connectivity and firewall configuration
3. Verify authentication info is correct
4. Check if the service is running normally

### Q: What authentication methods does API-to-MCP support?

Currently supported:
- Bearer Token
- API Key (Query/Header)
- Basic Auth

### Q: How to develop my own MCP service?

See [MCP Tool Development](../../backend/tools/mcp) documentation.

## Related Resources

- [MCP Repository](../../user-guide/resource-repository/mcp-repository) — Browse, install, and manage MCP services
- [Agent Configuration](../../user-guide/agent-development/agent-configuration) — Use MCP tools in Agents
- [MCP Tool Development](../../backend/tools/mcp) — Develop custom MCP services
- [MCP Ecosystem](../../mcp-ecosystem/overview) — Learn more about MCP ecosystem
