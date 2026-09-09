# Backend API Reference

## 🔗 Access API Docs

The backend API reference is maintained in Apifox. Please visit the live documentation here:

[Nexent API](https://8icfxll43r.apifox.cn)

## Northbound Open API (/nb/v1)

Open interfaces for third-party systems, authenticated with `Authorization: Bearer <access_key>` (API Key), supporting multi-replica deployment (service port 5013):

| Endpoint | Description |
|------|------|
| `/nb/v1/chat/run` | Agent conversation (POST, supports streaming; with `/nb/v1/chat/stop/{conversation_id}` and `/nb/v1/chat/attachments/upload`) |
| `/nb/v1/knowledge/*` | Knowledge base query and management |
| `/nb/v1/models` | Model list query |
| `/nb/v1/generate_title` | Conversation title generation |
| `/nb/v1/api-users/batch` | Batch API user management |
| `/nb/a2a/{endpoint_id}/.well-known/agent-card.json` | A2A Agent Card discovery |
| `/nb/a2a/{endpoint_id}/v1` | A2A JSON-RPC 2.0 (SendMessage / SendStreamingMessage / GetTask) |

For internal management APIs (A2A, MCP, skills, evaluation, automation tasks, etc.), refer to the Apifox documentation above.
