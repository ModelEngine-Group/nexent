# Agent Publishing

Nexent supports publishing Agent to external callable services. After publishing, external business systems can integrate with Agents through standardized methods. This document introduces two publishing methods:

| Publishing Method | Description | Use Case |
|-------------------|-------------|----------|
| **Normal Publishing** | Publish and call Agent via Northbound RESTful API | Deep integration with business systems, workflow automation |
| **A2A Publishing** | Publish as A2A 1.0 compliant Agent | Cross-platform Agent collaboration, external system calls via A2A protocol |

## Method 1: Normal Publishing (Northbound RESTful API)

Normal publishing means publishing Agent to the platform, allowing external business systems to communicate with the Agent through Nexent's Northbound RESTful API, supporting streaming responses, attachment uploads, and session management.

### Publish Steps

1. Navigate to **Agent Development** page, create or edit Agent
2. Complete Agent configuration and save
3. Click the "Publish" button
4. Confirm default publishing (don't check A2A option)
5. Confirm publishing; after generating API Key, you can start calling

### Getting API Key

After successful publishing, you need to generate an API Key for callers:

1. Log in to Nexent platform
2. Navigate to **Personal Info** page
3. Click **Generate API Key**
4. Copy the generated Access Key

### Call Example

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "general-assistant",
    "query": "Hello, please introduce yourself"
  }'
```

### API Capabilities Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/nb/v1/chat/run` | POST | Start conversation (streaming response) |
| `/nb/v1/chat/stop/{conversation_id}` | GET | Stop conversation |
| `/nb/v1/chat/attachments/upload` | POST | Upload conversation attachments |
| `/nb/v1/conversations` | GET | List conversations |
| `/nb/v1/conversations/{conversation_id}` | GET | Get conversation history |
| `/nb/v1/generate_title` | POST | Generate conversation title |
| `/nb/v1/conversations/{conversation_id}/title` | PUT | Update conversation title |

> For complete API definitions, request/response examples, and error codes, see [Northbound API](./northbound-api).

### Local Development Notes

| Deployment | Path Prefix |
|------------|-------------|
| Docker deployment | Replace with `http://localhost:5013/nb/v1` |
| Kubernetes deployment | Replace with `http://localhost:30013/nb/v1` |
| Production | Replace with actual server domain name or public IP |

## Method 2: A2A Publishing

Expose a published Agent as an A2A service for external systems to discover and call via A2A 1.0 protocol.

### Publish Steps

1. Navigate to **Agent Development** page, create or edit Agent
2. Complete Agent configuration and save
3. Click the "Publish" button
4. Check **Publish as A2A Agent** in publish options
5. Confirm publish

### Getting Call Information

After successful publishing, the system displays A2A Agent call information:

| Info Item | Description |
|-----------|-------------|
| **Endpoint ID** | Unique identifier for A2A Agent |
| **Agent Card URL** | Agent discovery endpoint; external systems get Agent description via this address |
| **Protocol Version** | A2A protocol version, currently 1.0 |
| **REST Endpoint** | REST-style API endpoint |
| **JSON-RPC Endpoint** | JSON-RPC 2.0 protocol call endpoint |

### Call Examples

#### REST API

```bash
# Get Agent Card
GET /nb/a2a/{endpoint_id}/.well-known/agent-card.json

# Send synchronous message
POST /nb/a2a/{endpoint_id}/message:send
Content-Type: application/json

{
  "message": {
    "role": "user",
    "content": "Please help me analyze this sales data"
  }
}

# Send streaming message (SSE)
POST /nb/a2a/{endpoint_id}/message:stream
Content-Type: application/json

{
  "message": {
    "role": "user",
    "content": "Please help me analyze this sales data"
  }
}
```

#### JSON-RPC 2.0

```bash
POST /nb/a2a/{endpoint_id}/v1
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "SendMessage",
  "params": {
    "message": {
      "role": "user",
      "content": "Please help me analyze this sales data"
    }
  },
  "id": 1
}
```

### Local Development Notes

- **Docker deployment**: Replace path prefix `/nb/a2a` with `http://localhost:5013/nb/a2a`
- **Kubernetes deployment**: Replace path prefix `/nb/a2a` with `http://localhost:30013/nb/a2a`
- **Production**: Replace with actual server domain name or public IP address

## Authentication and Security

### Call Authentication

Both publishing methods require carrying authentication info in the request header:

```http
Authorization: Bearer {access_key}
```

The `access_key` is obtained through "Generate API Key" in **Personal Info** on the platform.

### Security Recommendations

1. **Protect API Key**: Don't hardcode in code; rotate regularly
2. **Limit access**: Only authorize trusted systems to access call endpoints
3. **Monitor logs**: Enable call log recording for auditing
4. **Data isolation**: Be careful not to send sensitive data to uncontrolled callers

## Version Management

### Publish Version

- Agents can publish multiple versions; each publish generates a new version
- Published versions cannot be modified, ensuring callers get consistent experience

### Version Update

1. Modify Agent configuration
2. Publish new version (select publishing method as needed)
3. External systems can get updates through the new Agent Card (A2A scenario)

### Agent Card Caching

- Agent Card information is cached (A2A scenario)
- Refresh interval is 1 hour
- If immediate update is needed, republish the Agent

## FAQ

### Q: Can normal publishing and A2A publishing be enabled simultaneously?

Yes. When publishing, you can both enable default Northbound RESTful API and check **Publish as A2A Agent**, supporting both calling methods.

### Q: A2A call returns 401 error

Confirm the request header contains a valid `Authorization` field and `access_key` is correct.

### Q: How to update a published A2A Agent?

Republish the Agent version; updated information will be exposed through the refreshed Agent Card.

### Q: Where are the detailed Northbound API parameters?

See [Northbound API](./northbound-api) for complete API parameters, request/response examples, and error codes.

## Related Resources

- [Publish as A2A Agent](../../user-guide/agent-development/a2a-publish) — Full guide for publishing and calling A2A agents
- [Northbound API](./northbound-api) — Northbound RESTful API detailed reference
- [Agent Configuration](../../user-guide/agent-development/agent-configuration) — Agent configuration details
