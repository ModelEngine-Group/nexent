# Northbound RESTful API — Conversation and Chat

Nexent platform provides a Northbound RESTful API, allowing external business systems to deeply integrate with the platform via HTTP protocol. This document focuses on **conversation and chat** related interfaces, helping you embed Agent capabilities into enterprise business systems for workflow automation.

## Overview

The conversation and chat API provides complete conversation lifecycle management capabilities:

| Capability | Description |
|-----------|-------------|
| **Start conversation** | Initiate conversation with specified Agent, supports streaming response and attachment upload |
| **Session management** | List conversations, query history, generate and update titles |
| **Stop conversation** | Interrupt ongoing streaming response |

> For other capabilities (such as API Key management, Agent discovery, knowledge base management, A2A protocol, etc.), see subsequent chapters or [API Overview](./overview).

## Authentication

All conversation and chat APIs require authentication using **Bearer Token** (API Key) mechanism.

### Getting API Key

1. Log in to Nexent platform
2. Navigate to "Personal Info" page
3. Click "Generate API Key"
4. Copy the generated Access Key

### Using API Key

Carry the `Authorization` field in the request header:

```http
Authorization: Bearer {access_key}
```

### Example Request

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "general-assistant",
    "query": "Hello, please introduce yourself"
  }'
```

### Response Format

Success response:

```json
{
  "message": "success",
  "requestId": "req-uuid-here",
  "data": { ... }
}
```

Error response:

```json
{
  "detail": "Error description"
}
```

## API List

| API | Method | Description |
|-----|--------|-------------|
| `/nb/v1/chat/attachments/upload` | POST | Upload conversation attachments |
| `/nb/v1/chat/run` | POST | Start conversation (streaming response) |
| `/nb/v1/chat/stop/{conversation_id}` | GET | Stop conversation |
| `/nb/v1/conversations` | GET | List all conversations for current user |
| `/nb/v1/conversations/{conversation_id}` | GET | Get conversation history |
| `/nb/v1/generate_title` | POST | Generate conversation title |
| `/nb/v1/conversations/{conversation_id}/title` | PUT | Update conversation title |

## Start Conversation

Start a conversation with an Agent, return streaming response (SSE).

```http
POST /nb/v1/chat/run
```

### Request Body

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_name` | string | Yes | Target Agent name |
| `query` | string | Yes | User input content |
| `conversation_id` | integer | No | Existing conversation ID; if not provided, create new conversation |
| `attachments` | array | No | Attachment list (S3 URLs or attachment metadata objects) |
| `model_id` | integer | No | Model ID (overrides Agent default model) |
| `metadata` | object | No | Runtime metadata (visible to Agent) |
| `meta_data` | object | No | Audit metadata (recorded only, not exposed to Agent) |
| `tool_params` | object | No | Tool parameter overrides |

### Request Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | Yes | `Bearer {access_key}` |
| `Content-Type` | Yes | `application/json` |
| `Idempotency-Key` | No | Idempotency key for preventing duplicate submissions |

### Request Examples

Basic conversation request:

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "general-assistant",
    "query": "Please help me analyze this sales data"
  }'
```

Conversation request with attachments:

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "data-analyst",
    "query": "Please analyze this sales report",
    "attachments": ["s3://nexent/attachments/user123/20260609_report.pdf"],
    "metadata": {"project_id": "P001", "manager": "Alice"},
    "meta_data": {"source": "crm", "ticket_id": "INC-1001"}
  }'
```

Request with tool parameter overrides:

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "common_sense_qa_assistant",
    "query": "Summarize this document",
    "attachments": ["s3://nexent/attachments/user123/doc.pdf"],
    "tool_params": {
      "agents": {
        "common_sense_qa_assistant": {
          "tools": {
            "analyze_text_file": {
              "chunk_size": 4000,
              "summary_only": true,
              "prompt": "Please provide a concise summary focusing on key points"
            },
            "knowledge_base_search": {
              "top_k": 10,
              "rerank": true,
              "rerank_model_name": "gte-rerank-v2",
              "index_names": ["nexent-docs", "faq-index"]
            }
          }
        }
      }
    }
  }'
```

### tool_params Structure

`tool_params` is used to override tool default parameters in a single request:

```json
{
  "agents": {
    "<agent_name>": {
      "tools": {
        "<tool_name>": {
          "<param_name>": "<param_value>"
        }
      }
    }
  }
}
```

Parameter merge rules:

- **Priority**: Request parameters > Database persisted parameters
- **Tool matching**: Match by `tool.name` first, then by `tool.class_name`
- **Unknown parameters**: Passing unknown parameter names returns `400 ValidationError`
- **Metadata fields**: Fields like `vdb_core`, `embedding_model` are automatically recalculated based on merged parameters

### Streaming Response

The API returns Server-Sent Events (SSE) stream, returning Agent responses in chunks:

```text
data: {"type":"text","content":"Analyzing data"}

data: {"type":"text","content":", please wait..."}

data: {"type":"done","conversation_id":123,"content":"Analysis complete"}
```

## Upload Conversation Attachments

Before calling `/nb/v1/chat/run`, upload attachments to get URLs that can be referenced in requests.

```http
POST /nb/v1/chat/attachments/upload
Content-Type: multipart/form-data
```

### Form Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | file | Yes | Files to upload (multiple supported) |

### Request Example

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/attachments/upload" \
  -H "Authorization: Bearer your-access-key-here" \
  -F "files=@report.pdf" \
  -F "files=@diagram.png"
```

### Response Example

```json
{
  "files": [
    {
      "filename": "report.pdf",
      "s3_url": "s3://nexent/attachments/user123/report.pdf",
      "size": 1024000
    },
    {
      "filename": "diagram.png",
      "s3_url": "s3://nexent/attachments/user123/diagram.png",
      "size": 524288
    }
  ]
}
```

Use the returned `s3_url` as the value of the `attachments` field in the `/nb/v1/chat/run` API.

## Stop Conversation

Terminate an ongoing conversation (streaming response).

```http
GET /nb/v1/chat/stop/{conversation_id}
```

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | integer | Conversation ID |

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `meta_data` | string | No | Metadata (JSON string) |

### Request Example

```bash
curl -X GET "https://your-nexent-domain.com/nb/v1/chat/stop/123" \
  -H "Authorization: Bearer your-access-key-here"
```

## Get Conversation History

Get all message history for a specified conversation.

```http
GET /nb/v1/conversations/{conversation_id}
```

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | integer | Conversation ID |

### Response Example

```json
{
  "conversation_id": 123,
  "title": "Sales Data Analysis",
  "messages": [
    {
      "role": "user",
      "content": "Please analyze this month's sales data",
      "timestamp": "2026-08-30T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "Based on your sales data, this month's sales increased 15% compared to last month...",
      "timestamp": "2026-08-30T10:00:05Z"
    }
  ]
}
```

## List Conversations

Get all conversation lists for the current user.

```http
GET /nb/v1/conversations
```

### Response Example

```json
{
  "conversations": [
    {
      "conversation_id": 123,
      "title": "Sales Data Analysis",
      "create_time": "2026-08-30T10:00:00Z",
      "update_time": "2026-08-30T10:30:00Z"
    },
    {
      "conversation_id": 124,
      "title": "Customer Profile Analysis",
      "create_time": "2026-08-30T14:00:00Z",
      "update_time": "2026-08-30T14:20:00Z"
    }
  ]
}
```

## Generate Conversation Title

Automatically generate a title based on the conversation's initial question and persist it.

```http
POST /nb/v1/generate_title
```

### Request Body

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | integer | Yes | Conversation ID |
| `question` | string | Yes | Initial question (used to generate title) |

### Request Example

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/generate_title" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": 123,
    "question": "Please help me analyze this quarter's sales performance by region and point out the top three regions"
  }'
```

### Response Example

```json
{
  "title": "Q3 Regional Sales Performance Analysis"
}
```

## Update Conversation Title

Manually update the conversation title.

```http
PUT /nb/v1/conversations/{conversation_id}/title
```

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | integer | Conversation ID |

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | string | Yes | New title |
| `meta_data` | string | No | Metadata (JSON string) |

### Request Headers

| Header | Description |
|--------|-------------|
| `Idempotency-Key` | Idempotency key (optional) for preventing duplicate submissions |

### Request Example

```bash
curl -X PUT "https://your-nexent-domain.com/nb/v1/conversations/123/title?title=Q3 Sales Analysis" \
  -H "Authorization: Bearer your-access-key-here"
```

## Error Codes

| HTTP Status Code | Description |
|------------------|-------------|
| `200 OK` | Request successful |
| `400 Bad Request` | Request parameter error (e.g., unknown tool parameter) |
| `401 Unauthorized` | Authentication failed or missing API Key |
| `403 Forbidden` | No permission to access the conversation or resource |
| `404 Not Found` | Conversation does not exist |
| `429 Too Many Requests` | Request rate limit exceeded |
| `500 Internal Server Error` | Server internal error |
| `502 Bad Gateway` | Upstream service unavailable |
| `504 Gateway Timeout` | Upstream service timeout |

## Complete Usage Examples

### Python Example: Conversation with Attachments

```python
import requests

BASE_URL = "https://your-nexent-domain.com"
API_KEY = "your-access-key-here"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 1. Upload attachments
upload_response = requests.post(
    f"{BASE_URL}/nb/v1/chat/attachments/upload",
    headers={"Authorization": f"Bearer {API_KEY}"},
    files={"files": open("sales-data.csv", "rb")}
)
upload_data = upload_response.json()
s3_url = upload_data["files"][0]["s3_url"]

# 2. Start conversation (streaming response)
with requests.post(
    f"{BASE_URL}/nb/v1/chat/run",
    headers=headers,
    json={
        "agent_name": "data-analyst",
        "query": "Analyze this sales data and find key trends",
        "attachments": [s3_url],
        "metadata": {"project_id": "Q3-REPORT"},
        "meta_data": {"source": "etl-pipeline", "batch_id": "B001"}
    },
    stream=True
) as response:
    for line in response.iter_lines():
        if line:
            print(line.decode("utf-8"))

# 3. Query conversation history
history_response = requests.get(
    f"{BASE_URL}/nb/v1/conversations/123",
    headers=headers
)
print(history_response.json())
```

### JavaScript Example: Initiate Streaming Conversation

```javascript
const BASE_URL = "https://your-nexent-domain.com";
const API_KEY = "your-access-key-here";

async function streamChat() {
  const response = await fetch(`${BASE_URL}/nb/v1/chat/run`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      agent_name: "general-assistant",
      query: "Please help me write a poem about autumn",
      conversation_id: 123  // Optional, creates new conversation if not provided
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    console.log(decoder.decode(value));
  }
}

streamChat();
```

## FAQ

### Q: How to get API Key?

On the Nexent platform's "Personal Info" page, click "Generate API Key" to get it.

### Q: Does the conversation API support streaming output?

Yes, `POST /nb/v1/chat/run` returns SSE (Server-Sent Events) streaming response, allowing real-time reception of Agent's partial outputs.

### Q: How to stop an ongoing conversation?

Call `GET /nb/v1/chat/stop/{conversation_id}` to terminate the conversation.

### Q: What happens with unknown parameters in tool_params?

If a parameter name not supported by the tool is passed in `tool_params`, it returns `400 Bad Request` error, prompting parameter validation failure.

### Q: Must attachments be uploaded first?

Yes, attachments need to be uploaded first via `/nb/v1/chat/attachments/upload` to get `s3_url`, which is then passed to the conversation API via the `attachments` field.

### Q: How to access in local development environment?

| Deployment Method | Path Prefix |
|------------------|--------------|
| Docker deployment | Replace with `http://localhost:5013/nb/v1` |
| Kubernetes deployment | Replace with `http://localhost:30013/nb/v1` |
| Production | Replace with actual server domain name or public IP |

### Q: How to upload multiple attachments?

In `multipart/form-data` requests, use multiple fields with the same name `files` to upload multiple files.

### Q: How long are conversation histories retained?

Conversation histories are retained by default indefinitely unless users actively delete them or the tenant has configured an expiration policy.

## Related Resources

- [API Overview](./overview) — Complete northbound API capability map
- [Agent Export](./agents-export) — Agent configuration export and publish
- [A2A Protocol Endpoints](./overview) — Agent-to-Agent communication standard
