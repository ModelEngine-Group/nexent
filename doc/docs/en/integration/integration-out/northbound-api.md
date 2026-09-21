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
| `enable_hitl` | boolean | No | Enable human interaction; defaults to `false` |
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
data: {"type":"model_output_thinking","content":"Analyzing data","unit_index":1}

data: {"type":"model_output_thinking","content":", please wait...","unit_index":1}

data: {"type":"final_answer","content":"Analysis complete","unit_index":2}
```

## Human-in-the-loop (HITL)

The gateway entry point is `POST /api/nb/v1/chat/run`. Other paths in this document omit the shared `/api` gateway prefix; use your deployment's root path when connecting directly. All HITL endpoints use `Authorization: Bearer {access_key}`. The API key determines the user and tenant; callers cannot supply either identity.

### Start and discover capabilities

```bash
curl -N 'https://your-nexent-domain.com/api/nb/v1/chat/run' \
  -H "Authorization: Bearer ${NEXENT_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"agent_name":"general-assistant","query":"Help me prepare a notice","enable_hitl":true}'
```

`enable_hitl` defaults to `false`. Check `GET /nb/v1/chat/human-interactions/capabilities` first: its `data` includes `enabled`, `accept_new_runs`, `tool_approval_enabled`, executor mode and form limits. When HITL is disabled or new runs are being drained, chat starts follow the existing ordinary execution path. Opting in does not force a clarification card for every query.

The runtime creates a `run_id` for this conversation. A pending interaction puts it into `WAITING_HUMAN`; an accepted decision moves it to `READY` so the existing worker or scheduler can continue the same run. The northbound service forwards requests using an internal JWT and reuses runtime persistence, ownership checks, version checks and idempotency.

### SSE contract

The envelope remains `data: {"type": ..., "content": ...}`. **The card event type is `human_interaction`.** Its `content` is a JSON object, not a serialized JSON string.

| `type` | Content and purpose |
|---|---|
| `conversation_created` | Object containing the newly created `conversation_id` |
| `human_run` | Run status; snapshots also include `conversation_id`, `event_seq`, and pending `requests` |
| `human_interaction` | A pending input or approval card |
| `human_decision` | Accepted decision: `run_id`, `request_id`, `status` |
| `human_execution` | Tool execution slot and status |
| `model_output_thinking`, `final_answer`, `token_count`, etc. | Existing runtime output, forwarded unchanged |

The card's `content.kind` selects its behavior:

| `kind` | `decision` | Input |
|---|---|---|
| `CLARIFICATION` | `answer` | `answers` for structured forms; `text` for legacy single-question cards |
| `ACTION_APPROVAL` | `approve` / `reject` | Approve or reject the exact frozen action |
| `USER_STEERING` | `steer` | `text` with guidance after a pause |

Example (copy the actual card's digest when replying):

```text
id: 12
data: {"type":"human_interaction","content":{"request_id":"01a09fce-3a28-7860-8646-b0eec69d5f47","run_id":"01a09fce-3a28-7860-8646-b0eec69d5f46","kind":"CLARIFICATION","status":"PENDING","version":1,"digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expires_at":"2026-09-15T10:00:00+00:00","payload":{"schema_version":2,"questions":[{"id":"audience","type":"single_choice","title":"Who is the notice for?","required":true,"options":[{"id":"team","label":"Internal team"},{"id":"client","label":"Clients"}],"allow_other":true}]}}}
```

`payload.questions` supports `text`, `single_choice`, and `multiple_choice`, with at most five questions and one clarification card per run. Text answers use strings, single-choice answers use option IDs, and multiple-choice answers use arrays of option IDs. When `allow_other` is true, `other_text` can supplement an answer. Runtime validates required fields, allowed options and duplicate answers. Question-level `type` is separate from the outer SSE event type.

### Endpoints and decisions

The common prefix below is `/nb/v1/chat/human-interactions`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/capabilities` | Read actual runtime capabilities |
| GET | `/conversation/{conversation_id}` | Latest visible run for this API user; `data=null` if none |
| GET | `/{run_id}` | Read status and pending `requests` |
| POST | `/{run_id}/requests/{request_id}/decisions` | Submit a card response |
| GET | `/{run_id}/events?after_event=12` | Subscribe to later SSE events of the same run |
| POST | `/{run_id}/pause` | Request a pause at a safe boundary; does not immediately abort an executing tool |
| POST | `/{run_id}/steer` | Add guidance and cancel any pending card |
| POST | `/{run_id}/terminate` | Stop the run and cancel pending cards |

JSON success responses use `{"message":"success","requestId":"...","data":...}`. An accepted decision returns `data: {"run_id":"...","request_id":"...","accepted":true}`. SSE endpoints return the event stream directly.

Submit completed cards to the decision endpoint; **do not send the answer as a new `/chat/run` query**:

```bash
curl -X POST \
  'https://your-nexent-domain.com/api/nb/v1/chat/human-interactions/01a09fce-3a28-7860-8646-b0eec69d5f46/requests/01a09fce-3a28-7860-8646-b0eec69d5f47/decisions' \
  -H "Authorization: Bearer ${NEXENT_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "version":1,
    "digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "idempotency_key":"answer-20260914-0001",
    "decision":"answer",
    "answers":[{"question_id":"audience","value":"team"}]
  }'
```

Copy `version` and `digest` from the actual card. The JSON body must contain an `idempotency_key` of 8–100 characters. Retry a timed-out submission with the same key and identical body; reusing a key with different content returns `409`. Structured forms require `answers` without `text`. Legacy clarification and pause cards use `text`. Approvals use `approve` or `reject` without `answers`, and cannot change the tool's frozen arguments.

For additional guidance outside a card, submit `{"message_id":"guidance-0001","text":"Continue with the revised requirements"}` to `/{run_id}/steer`. `message_id` provides idempotency for that guidance. This cancels pending cards and does not approve a pending tool action.

A conversation may contain multiple runs and card versions, so `conversation_id` alone is insufficient for submission. Decisions bind to `run_id + request_id + version + digest`; the conversation snapshot endpoint recovers these identifiers.

### Waiting and reconnecting

1. Record the conversation ID, run ID, and SSE `id` of each fully consumed event. Merge cards from both `human_run.requests` and `human_interaction` by `request_id + version`.
2. Display `human_interaction` cards and update them when receiving `human_decision`.
3. `accepted=true` confirms input acceptance; subsequent output still arrives through SSE. Continue consuming the original stream if it is connected. Otherwise subscribe to `/{run_id}/events?after_event=<last-consumed-id>`.
4. If `after_event` is absent, the subscription endpoint also accepts `Last-Event-ID`. Explicit `after_event` takes precedence. The default `0` replays all persisted events. Subscribing neither writes a user message nor starts another Agent run.
5. Every subscription starts with a current `human_run` snapshot without an SSE `id`, followed by persisted events after the requested cursor. **Do not advance the consumed cursor to that initial snapshot's `event_seq`**: doing so would skip output not yet consumed. Snapshots and heartbeats do not advance the client cursor. After submitting a decision, continue from the last ID consumed before submission.
6. `WAITING_HUMAN` is not completion; the subscription may remain open or close while waiting. Terminal statuses are `COMPLETED`, `FAILED`, `STOPPED`, `EXPIRED`, and `RECOVERY_REQUIRED`. The last means execution cannot automatically resume; do not blindly replay the action.

The existing `GET /nb/v1/chat/stop/{conversation_id}` also terminates the API user's active HITL run in that conversation.

### Errors and deployment

| HTTP status | Meaning |
|---|---|
| 401 | Invalid API key or internal runtime authentication |
| 404 | Run/card missing or outside the authenticated user and tenant scope |
| 409 | Card already handled, stale version/digest, or conflicting idempotency key |
| 410 | Expiration detected during this submission; a previously processed expiration may instead return `409` |
| 422 | Invalid command, answer, decision kind or event cursor |
| 503 | Runtime HITL disabled for run queries and decisions |
| 502 / 504 | Runtime unavailable / timeout |

Apply `deploy/sql/migrations/v2.6.0_merged_migrations.sql`, configure a valid runtime `HITL_ENCRYPTION_KEY`, and enable `HITL_ENABLED` and `HITL_ACCEPT_NEW_RUNS`. Tool approval is independently controlled by `HITL_TOOL_APPROVAL_ENABLED`. The default `native-live-v1` mode preserves the live execution state; loss of its worker can require recovery instead of automatic replay. These northbound endpoints preserve the existing execution modes' limits.

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
