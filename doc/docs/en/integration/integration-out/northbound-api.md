# Northbound RESTful API — Conversation and Chat

Nexent platform provides a Northbound RESTful API, allowing external business systems to deeply integrate with the platform via HTTP protocol. This document focuses on **conversation and chat** related interfaces, helping you embed Agent capabilities into enterprise business systems for workflow automation.

## Overview

The conversation and chat API provides complete conversation lifecycle management capabilities:

| Capability | Description |
|-----------|-------------|
| **Start conversation** | Initiate conversation with specified Agent, supports streaming response and attachment upload |
| **Session management** | List conversations, query history, generate and update titles |
| **Stop conversation** | Interrupt ongoing streaming response |
| **Session cleanup** | Delete a single conversation or delete conversations in batch (cascades to messages and bound automation tasks) |
| **Automation task query** | List scheduled automation tasks of the current user and query task details |
| **File download** | Download conversation attachments or knowledge base files, in presigned-URL or byte-stream mode |

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

Error response. Failure bodies of northbound APIs are **not uniform**; they come in three forms depending on the source, and clients must handle all of them:

```json
// ① Business error (resource not found, no permission, value out of range, etc.): three-field envelope + requestId
{
  "code": "NOT_FOUND",
  "message": "Resource not found",
  "status": 404,
  "requestId": "req-uuid-here"
}

// ② Framework-level parameter validation failure (type mismatch, value out of range, value outside the allowed set): FastAPI native format
{
  "detail": [
    { "loc": ["query", "page_size"], "msg": "Input should be less than or equal to 100", "type": "less_than_equal" }
  ]
}

// ③ Gateway rejection (missing / invalid API Key, path not exposed)
{ "message": "Invalid or missing credentials" }
```

See [Error Codes](#error-codes) below for the full `code` mapping.

## API List

| API | Method | Description |
|-----|--------|-------------|
| `/nb/v1/chat/attachments/upload` | POST | Upload conversation attachments |
| `/nb/v1/chat/run` | POST | Start conversation (streaming response) |
| `/nb/v1/chat/stop/{conversation_id}` | GET | Stop conversation |
| `/nb/v1/conversations` | GET | List all conversations for current user |
| `/nb/v1/conversations/{conversation_id}` | GET | Get conversation history |
| `/nb/v1/conversations/{conversation_id}` | DELETE | Delete a conversation |
| `/nb/v1/conversations/batch-delete` | POST | Delete conversations in batch |
| `/nb/v1/generate_title` | POST | Generate conversation title |
| `/nb/v1/conversations/{conversation_id}/title` | PUT | Update conversation title |
| `/nb/v1/automations` | GET | List automation tasks of the current user |
| `/nb/v1/automations/{task_id}` | GET | Get automation task details |
| `/nb/v1/file/download/{object_name}` | GET | Download a file (presigned URL or byte stream) |

> Sections whose title is prefixed with 🆕 are recently added APIs: session cleanup (2), automation task query (2), and file download (1).

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
| `final_answer_mode` | string | No | Defaults to `complete`: one full root Agent `final_answer`; use `delta` to retain incremental answer events |
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

When `final_answer_mode` is omitted or set to `complete`, process events still stream immediately. After successful execution and persistence, one root `final_answer` contains the entire answer. Legacy clients can read the full result from the first `final_answer`. Child answers are not published as final results; failed or stopped runs do not promote partial answers to success.

For smolagents, root answer fragments also stream as `model_output_thinking` with `answer_preview: true` and `answer_phase: "delta"`. These are unconfirmed answer previews, distinct from ordinary thinking. Use their `step_id`, `attempt_id` and invocation scope to update one answer slot; the final full `final_answer` confirms or replaces that slot rather than appending another copy. Honor `model_attempt_control` rollback events to discard rejected previews. Previews are not stored as thinking units; reloaded history contains the canonical answer once. Delta mode and jiuwen retain their existing event behavior.

```text
data: {"type":"model_output_thinking","answer_preview":true,"answer_phase":"delta","step_id":"s1","content":"Analysis "}

data: {"type":"model_output_thinking","answer_preview":true,"answer_phase":"delta","step_id":"s1","content":"complete"}

data: {"type":"final_answer","answer_phase":"complete","step_id":"s1","content":"Analysis complete"}
```

Clients requiring incremental answers must send `"final_answer_mode":"delta"` in the request body. The event type remains `final_answer`, with `answer_phase` identifying the stage:

```text
data: {"type":"final_answer","answer_phase":"delta","content":"Analysis "}

data: {"type":"final_answer","answer_phase":"delta","content":"complete"}

data: {"type":"final_answer","answer_phase":"complete","content":""}
```

Append delta fragments. A nonempty complete body replaces the accumulated draft; an empty complete body confirms the accumulated answer. Retain existing retry rollback and `reclassify_step` handling rather than concatenating every `final_answer`. Unsupported modes return `422`. Existing northbound clients relying on incremental answers must explicitly opt in to `delta` when upgrading.

## Structured clarification and follow-up after stopping

When essential information is missing, the Agent can return a structured clarification. The ordinary completion path ends that run and releases its worker. After the stream ends, send the answers as a normal new query in the same conversation. No capability switch, pending-request lookup, decision endpoint, or execution-resume API is required.

### Clarification SSE

The envelope remains `data: {"type": ..., "content": ...}`. For `type="human_interaction"`, `content` is a **JSON object** containing `schema_version: 1` and `questions`. An ordinary `final_answer` also contains the complete readable questions as a text fallback.

```text
data: {"type":"human_interaction","content":{"schema_version":1,"questions":[{"id":"audience","type":"single_choice","title":"Who is the notice for?","required":true,"options":[{"id":"team","label":"Internal team"},{"id":"client","label":"Clients"}],"allow_other":true,"placeholder":""}]},"unit_index":1}

data: {"type":"final_answer","content":"1. Who is the notice for?\n   - Internal team\n   - Clients\n   - 其他 / Other","unit_index":2}
```

There are at most five questions, using `text`, `single_choice`, or `multiple_choice`. Question fields include `id`, `type`, `title`, `required`, `options`, `allow_other`, and `placeholder`; each option has an `id` and `label`. Text questions have no options, and choice questions have 2–12 options. Render the form and keep submission disabled until the current stream ends. Clients rendering a valid card may hide its exactly matching text fallback; text-only clients display `final_answer`.

### Send answers as the next query

Combine the questions, readable option labels, and any additional text into an ordinary query using the actual conversation ID:

```bash
curl -N 'https://your-nexent-domain.com/api/nb/v1/chat/run' \
  -H "Authorization: Bearer ${NEXENT_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id":123,"agent_name":"general-assistant","query":"Answers to the previous questions: the notice is for the internal team, specifically the engineering department."}'
```

`123` is only an example. Send readable answers, not just question or option IDs. The new run reads ordinary conversation history without restoring a previous execution stack or plan cursor. On refresh, rebuild the card from its ordinary `human_interaction` message unit. Older cards are read-only, and their answers appear in the following user message.

### Ordinary stop and compatibility

Use `GET /nb/v1/chat/stop/{conversation_id}` to cancel the current run. After HTTP 200, the stopped run has released its conversation reservation and you can send the next query with the same ID. A new query can read the original task, the stop notice, and saved partial results. Stopping does not roll back external operations already performed.

The old HITL routes, approvals, pause/resume engine, four-table runtime dependencies, and encryption-key settings have been removed. Northbound `/chat/run` returns `400` for any request containing `enable_hitl`, `hitl_run_id`, or `hitl_after_event`, including false, null, and zero values. Update Web and runtime together. Existing identity, permissions, attachment, metadata, and ordinary error contracts remain unchanged.

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

After requesting cancellation, this endpoint waits up to 5 seconds for the targeted worker to exit and the conversation reservation to clear. HTTP 200 confirms release or an already idle conversation. If release is still pending, the endpoint returns HTTP 409 with `code: NORTHBOUND_STOP_IN_PROGRESS` and `Retry-After: 1`. Cancellation continues. Keep the next query pending until stop is confirmed. Concurrent requests starting a new run can still conflict.

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

## 🆕 Delete Conversation

Delete one conversation owned by the current user. This is a **soft delete**: the conversation record, messages, message units, search sources, image sources and trajectory summaries are all flagged as deleted rather than physically removed. Automation tasks bound to the conversation are cancelled and soft-deleted on a best-effort basis (a cleanup failure does not block the deletion). Every call, including rejected ones, writes a security audit record.

```http
DELETE /nb/v1/conversations/{conversation_id}
```

### Path Parameters

| Parameter | Type | Required | Constraint | Description |
|-----------|------|----------|------------|-------------|
| `conversation_id` | integer | Yes | ≥ 1 | Conversation ID |

### Request Example

```bash
curl -X DELETE "https://your-nexent-domain.com/nb/v1/conversations/123" \
  -H "Authorization: Bearer your-access-key-here"
```

### Response Parameters

On success `data` is always `true`.

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | Always `success` |
| `data` | boolean | Always `true` on successful deletion |
| `requestId` | string | Request tracing ID; provide it to operations when troubleshooting |

### Response Example

```json
{
  "message": "success",
  "data": true,
  "requestId": "req-uuid-here"
}
```

### Errors

| HTTP | `code` | Scenario |
|------|--------|----------|
| `404` | `NOT_FOUND` | The conversation does not exist, has already been deleted, or **does not belong to the user of the current API Key** (all three return the same response, so the existence of other users' conversations is not disclosed) |
| `401` | — | Missing or invalid API Key |
| `500` | `INTERNAL_ERROR` | Server-side exception |

> Calling delete repeatedly on the same conversation returns `404` from the second call onwards. This is idempotent behavior, not a failure.

## 🆕 Batch Delete Conversations

Delete multiple conversations in one request, with the same semantics as [Delete Conversation](#🆕-delete-conversation). **The request as a whole does not fail because individual conversations fail**: IDs that cannot be accessed or were already deleted are skipped and returned in `failed_ids`, while the rest are deleted normally.

```http
POST /nb/v1/conversations/batch-delete
Content-Type: application/json
```

### Request Body

| Parameter | Type | Required | Constraint | Description |
|-----------|------|----------|------------|-------------|
| `conversation_ids` | array\<integer\> | Yes | 1 to 100 elements | List of conversation IDs to delete |

Constraint details:

- More than **100** IDs returns `400 VALIDATION_ERROR`; call in batches
- An empty list `[]` returns `{"deleted_count": 0, "failed_ids": []}` without an error
- Duplicate IDs in the list are deduplicated; `deleted_count` reflects the actual number deleted

### Request Example

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/conversations/batch-delete" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{"conversation_ids": [123, 124, 125]}'
```

### Response Parameters

| Field | Type | Description |
|-------|------|-------------|
| `data.deleted_count` | integer | Number of conversations actually deleted |
| `data.failed_ids` | array\<integer\> | Conversation IDs that could not be deleted (nonexistent, already deleted, or not owned by the current user) |

### Response Example

```json
{
  "message": "success",
  "data": {
    "deleted_count": 2,
    "failed_ids": [125]
  },
  "requestId": "req-uuid-here"
}
```

### Errors

| HTTP | `code` | Scenario |
|------|--------|----------|
| `400` | `VALIDATION_ERROR` | More than 100 IDs |
| `422` | — | The request body is not valid JSON, `conversation_ids` is missing, or an element is not an integer (returns the FastAPI native `detail` array) |
| `401` | — | Missing or invalid API Key |

> Deleting a conversation is **irreversible** through the northbound API (it is a soft delete internally, but no restore capability is exposed). Verify the IDs with `GET /nb/v1/conversations` before calling.

## 🆕 List Automation Tasks

List the automation tasks (scheduled tasks) owned by the current user. Only tasks created by and not deleted by the current user are returned, sorted by update time descending.

```http
GET /nb/v1/automations
```

### Query Parameters

| Parameter | Type | Required | Constraint | Description |
|-----------|------|----------|------------|-------------|
| `status` | string | No | See table below | Filter by task status |
| `search` | string | No | ≤ 200 characters | Fuzzy match on the **task title** (case-insensitive) |
| `agent_name` | string | No | ≤ 200 characters | Fuzzy match on the Agent name (case-insensitive, **filtered before pagination**) |
| `page` | integer | No | ≥ 1, default `1` | Page number |
| `page_size` | integer | No | 1 to 100, default `20` | Items per page |

`status` values. For compatibility with frontend semantics, `ENABLED` and `RUNNING` are two **virtual statuses** that the server translates before querying:

| Value | Actual meaning |
|-------|----------------|
| `ENABLED` | Enabled and currently **not** executing a run |
| `RUNNING` | Currently **has** a run in progress |
| `ACTIVE` | Task status is active (may be executing) |
| `PAUSED` / `PAUSED_BY_SYSTEM` | Paused / paused by the system |
| `COMPLETED` | Completed |
| omitted | No filtering (`DELETED` is never returned) |

> Passing a value outside this set (such as lowercase `enabled`) does not raise an error; it simply returns an empty list.

### Request Example

```bash
# Page 1, 10 items per page, only enabled tasks
curl "https://your-nexent-domain.com/nb/v1/automations?page=1&page_size=10&status=ENABLED" \
  -H "Authorization: Bearer your-access-key-here"

# Search by title keyword
curl "https://your-nexent-domain.com/nb/v1/automations?search=daily%20report" \
  -H "Authorization: Bearer your-access-key-here"
```

### Response Parameters

| Field | Type | Description |
|-------|------|-------------|
| `data.items` | array\<object\> | Task list of the current page; element structure see [Automation Task Object](#automation-task-object) |
| `data.total` | integer | Total number of tasks after filtering |
| `data.page` | integer | Current page number |
| `data.page_size` | integer | Items per page |

### Response Example

```json
{
  "message": "success",
  "data": {
    "items": [
      {
        "task_id": 5,
        "conversation_id": 123,
        "agent_id": 7,
        "agent_version_no": 3,
        "agent_name": "daily-report",
        "title": "Daily Morning Report",
        "instruction": "Summarize yesterday's sales data and generate a brief",
        "status": "ACTIVE",
        "is_running": false,
        "schedule_mode": "RECURRING",
        "schedule_rule_type": "CRON",
        "schedule_expr": "0 9 * * 1-5",
        "timezone": "Asia/Shanghai",
        "next_fire_at": "2026-11-30T09:00:00Z",
        "last_fire_at": "2026-11-27T09:00:00Z",
        "fire_count": 42,
        "last_run_status": "SUCCEEDED",
        "last_error": null,
        "consecutive_failures": 0,
        "timeout_seconds": 600,
        "overlap_policy": "SKIP",
        "misfire_policy": "SKIP",
        "source": "CHAT_INTENT"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 10
  },
  "requestId": "req-uuid-here"
}
```

### Errors

| HTTP | `code` | Scenario |
|------|--------|----------|
| `422` | — | `page` / `page_size` out of range, or `search` / `agent_name` longer than 200 characters (FastAPI native `detail` array) |
| `401` | — | Missing or invalid API Key |

> When `status=ENABLED`, `status=RUNNING` or `agent_name` is passed, the server first fetches all matching tasks of the user, filters them in memory, and then paginates. With a large number of tasks (thousands), such queries are noticeably slower than ordinary pagination.

### Automation Task Object

Each element in `items` contains the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | integer | Task ID, used to query details |
| `conversation_id` | integer | ID of the conversation the task is bound to |
| `agent_id` | integer | Bound Agent ID |
| `agent_version_no` | integer \| null | Agent version number locked when the task was created |
| `agent_name` | string | Agent display name (falls back to `Agent #<agent_id>` when resolution fails) |
| `title` | string | Task title |
| `instruction` | string | Instruction sent to the Agent on each run |
| `status` | string | Task lifecycle status: `DRAFT` / `ACTIVE` / `PAUSED` / `PAUSED_BY_SYSTEM` / `COMPLETED` |
| `is_running` | boolean | Whether a run is currently in progress |
| `source` | string | Creation source; currently only `CHAT_INTENT` (created from a user intent in a conversation) |
| `schedule_mode` | string | `ONCE` (one-shot) or `RECURRING` (periodic) |
| `schedule_rule_type` | string | `AT` (at a specific time) / `INTERVAL` (fixed interval) / `CRON` |
| `schedule_expr` | string \| null | Human-readable schedule expression (such as a cron expression) |
| `schedule_config` | object | Normalized schedule configuration; structure below |
| `timezone` | string | IANA time zone, default `Asia/Shanghai` |
| `next_fire_at` | string \| null | Next trigger time (ISO 8601, UTC) |
| `last_fire_at` | string \| null | Last trigger time |
| `fire_count` | integer | Cumulative number of triggers |
| `last_run_status` | string \| null | Status of the most recent run, same values as automation run status: `QUEUED` / `RUNNING` / `SUCCEEDED` / `FAILED` / `SKIPPED` / `CANCELED` / `TIMEOUT` |
| `last_error` | string \| null | Error message of the most recent run |
| `consecutive_failures` | integer | Number of consecutive failures |
| `timeout_seconds` | integer | Timeout of a single run (seconds) |
| `overlap_policy` | string | Policy when the previous run has not finished at the next trigger point; the current implementation is always `SKIP` (skip this trigger) |
| `misfire_policy` | string | Compensation policy for a missed trigger: `SKIP` for recurring tasks, `RUN_ONCE` (run once immediately) for one-shot tasks |
| `capability_requirements` | object \| null | Capability requirements parsed from the user intent |
| `capability_bindings` | object \| null | Confirmed matched capability bindings |
| `runtime_snapshot` | object \| null | Agent / runtime capability snapshot taken when the task was created |
| `create_time` | string | Creation time (ISO 8601, UTC) |
| `update_time` | string | Last update time |

`schedule_config` structure:

```json
{
  "mode": "RECURRING",
  "rule_type": "CRON",
  "timezone": "Asia/Shanghai",
  "start_at": "2026-11-01T00:00:00Z",
  "end_at": null,
  "cron_expr": "0 9 * * 1-5",
  "interval_seconds": null,
  "max_fire_count": null
}
```

> Task objects also carry audit and scheduling-internal fields such as `tenant_id`, `user_id`, `created_by`, `updated_by`, `delete_flag`, `lock_owner` and `lock_until`. They are all read-only and callers should not depend on them.

## 🆕 Get Automation Task Details

Get one automation task owned by the current user by ID. The returned fields are identical to the task object in the list endpoint.

```http
GET /nb/v1/automations/{task_id}
```

### Path Parameters

| Parameter | Type | Required | Constraint | Description |
|-----------|------|----------|------------|-------------|
| `task_id` | integer | Yes | ≥ 1 | Task ID |

### Request Example

```bash
curl "https://your-nexent-domain.com/nb/v1/automations/5" \
  -H "Authorization: Bearer your-access-key-here"
```

### Response Example

```json
{
  "message": "success",
  "data": {
    "task_id": 5,
    "conversation_id": 123,
    "agent_id": 7,
    "agent_version_no": 3,
    "agent_name": "daily-report",
    "title": "Daily Morning Report",
    "instruction": "Summarize yesterday's sales data and generate a brief",
    "status": "PAUSED",
    "is_running": false,
    "schedule_mode": "RECURRING",
    "schedule_rule_type": "CRON",
    "schedule_expr": "0 9 * * 1-5",
    "timezone": "Asia/Shanghai",
    "next_fire_at": null,
    "last_fire_at": "2026-11-27T09:00:00Z",
    "fire_count": 42,
    "last_run_status": "SUCCEEDED",
    "consecutive_failures": 0,
    "timeout_seconds": 600,
    "overlap_policy": "SKIP",
    "misfire_policy": "SKIP",
    "source": "CHAT_INTENT",
    "create_time": "2026-10-01T08:00:00Z",
    "update_time": "2026-11-27T09:00:05Z"
  },
  "requestId": "req-uuid-here"
}
```

### Errors

| HTTP | `code` | Scenario |
|------|--------|----------|
| `404` | `AUTOMATION_TASK_NOT_FOUND` | The task does not exist, has been deleted, or does not belong to the current user |
| `422` | — | `task_id` is not an integer ≥ 1 (such as `abc` or `0`) |
| `401` | — | Missing or invalid API Key |

## 🆕 Download File

Download a file the current user is permitted to access, such as conversation attachments, knowledge base source files, or artifacts generated by an Agent. Two modes are supported:

- **`ignore` (default)**: does not transfer the file content; returns a **presigned URL** that the client uses to fetch directly from object storage. Suitable for handing the file to a browser or a third-party system.
- **`stream`**: the server returns the **byte stream** directly. Suitable for server-to-server transfer, or when object storage is not exposed externally.

```http
GET /nb/v1/file/download/{object_name}
```

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `object_name` | string | Yes | Object name in object storage; **multi-level paths are supported**, e.g. `attachments/user123/20261127_report.pdf` |

`object_name` is appended directly to the path, so **do not** URL-encode `/`. When the object name contains spaces or non-ASCII characters such as Chinese, URL-encode each path segment separately.

### Query Parameters

| Parameter | Type | Required | Constraint | Description |
|-----------|------|----------|------------|-------------|
| `download` | string | No | Only `ignore` or `stream`, default `ignore` | Download mode |
| `expires` | integer | No | 1 to 604800, default `86400` | Validity of the presigned URL in seconds, up to 7 days. **Only effective in `ignore` mode** |
| `filename` | string | No | — | File name used for the download. **Only effective in `stream` mode**; defaults to the last segment of the object name |

> The `redirect` and `base64` modes are **not exposed to northbound callers**: `redirect` would disclose the internal object storage address, and `base64` would inline the entire file into the response. Passing either returns `422`.

### Access Control

Permissions are decided per category based on the object name prefix; **cross-tenant access is always denied**:

| Object name prefix | Rule |
|--------------------|------|
| `knowledge_base/...` | The object must resolve to a valid knowledge base ledger record of the **current tenant** |
| `attachments/{user_id}/...` | Accessible only when `user_id` is the user of the current API Key |
| `attachments/<no sub-directory>` | Legacy bare attachment key with no ownership information; **always denied** |
| `images_in_attachments/...` | Legacy shared rendered images with no ownership information; **always denied** |
| `skill-files/{user_id}/...` | Accessible only when `user_id` is the current user |
| `workspace/{user_id}/{run_id}/outputs/...` | Accessible only when `user_id` is the current user |

No permission returns `403`; a nonexistent object returns `404`. Note that this **does** disclose whether the object exists: for prefixes the caller is allowed to access (such as their own `attachments/{user_id}/`), a `404` means the object really does not exist; for prefixes the caller has no access to, the response is always `403` regardless of whether the object exists.

### Request Example

```bash
# Mode 1: get a presigned URL (valid for 1 hour)
curl "https://your-nexent-domain.com/nb/v1/file/download/attachments/user123/20261127_report.pdf?expires=3600" \
  -H "Authorization: Bearer your-access-key-here"

# Mode 2: fetch the byte stream directly and save it
curl -o report.pdf \
  "https://your-nexent-domain.com/nb/v1/file/download/attachments/user123/20261127_report.pdf?download=stream" \
  -H "Authorization: Bearer your-access-key-here"

# Specify the download file name
curl -o report.pdf \
  "https://your-nexent-domain.com/nb/v1/file/download/attachments/user123/20261127_report.pdf?download=stream&filename=Q3%20Sales%20Report.pdf" \
  -H "Authorization: Bearer your-access-key-here"

# Knowledge base file (multi-level path)
curl "https://your-nexent-domain.com/nb/v1/file/download/knowledge_base/42/abc123/source.pdf?download=stream" \
  -H "Authorization: Bearer your-access-key-here"
```

### Response Parameters

**`ignore` mode** returns the standard envelope:

| Field | Type | Description |
|-------|------|-------------|
| `data.success` | boolean | Always `true` (failures go through the error response, so `success: false` never appears) |
| `data.object_name` | string | Echoed object name |
| `data.expires_in` | integer | Validity of the presigned URL in seconds |
| `data.url` | string | Presigned download URL; the signed address is generated from the **external access endpoint** and can be handed to clients directly |

```json
{
  "message": "success",
  "data": {
    "success": true,
    "object_name": "attachments/user123/20261127_report.pdf",
    "expires_in": 3600,
    "url": "https://minio.example.com/nexent/attachments/user123/20261127_report.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Expires=3600&X-Amz-Signature=..."
  },
  "requestId": "req-uuid-here"
}
```

**`stream` mode** returns the byte stream directly **without an envelope**:

| Response header | Description |
|-----------------|-------------|
| `Content-Type` | MIME type inferred from the object name extension |
| `Content-Disposition` | `attachment; filename="..."`; non-ASCII file names are RFC 5987 encoded |
| `Cache-Control` | Always `private, no-store`; the byte stream is never stored by any shared cache |
| `ETag` | Quoted string generated from the object name |

### Errors

| HTTP | `code` | Scenario |
|------|--------|----------|
| `403` | `FORBIDDEN` | The object does not belong to the current user / tenant, or is under a prefix that is not exposed |
| `404` | `NOT_FOUND` | The object does not exist in storage (both modes probe existence first) |
| `422` | — | `download` is neither `ignore` nor `stream`, or `expires` is outside 1 to 604800 (FastAPI native `detail` array) |
| `401` | — | Missing or invalid API Key |

> The presigned URL returned in `ignore` mode allows **anyone** holding the URL to download within its validity period. Treat it like a password: do not write it to logs or anywhere visible to the frontend.

## Monitoring Dashboard APIs

The northbound monitoring surface reuses the platform monitoring dashboard's
24 data endpoints under the `/nb/v1/monitoring` prefix. A caller may only
read monitoring data for the tenant that owns the API key: passing a
`tenant_id` that does not match returns `403`.

### Endpoint List

| API | Method | Description |
|-----|--------|-------------|
| `/nb/v1/monitoring/models` | GET | Model monitoring list (paginated, searchable, sortable) |
| `/nb/v1/monitoring/models/summary` | GET | Model monitoring summary |
| `/nb/v1/monitoring/models/rankings` | GET | Top 5 models |
| `/nb/v1/monitoring/models/trends` | GET | Model usage trends |
| `/nb/v1/monitoring/models/refresh` | POST | Submit a model recompute wait token (202) |
| `/nb/v1/monitoring/models/refreshes/{refresh_id}` | GET | Query source revision publication progress |
| `/nb/v1/monitoring/skills` | GET | Skill monitoring list |
| `/nb/v1/monitoring/skills/summary` | GET | Skill monitoring summary |
| `/nb/v1/monitoring/skills/rankings` | GET | Top 5 skills |
| `/nb/v1/monitoring/skills/trends` | GET | Skill usage trends |
| `/nb/v1/monitoring/skills/refresh` | POST | Submit a skill recompute wait token (202) |
| `/nb/v1/monitoring/skills/refreshes/{refresh_id}` | GET | Query source revision publication progress |
| `/nb/v1/monitoring/agents` | GET | Agent monitoring list |
| `/nb/v1/monitoring/agents/summary` | GET | Agent monitoring summary (incl. token usage) |
| `/nb/v1/monitoring/agents/trends` | GET | Agent execution trends |
| `/nb/v1/monitoring/agents/rankings` | GET | Top 5 agents |
| `/nb/v1/monitoring/mcp-tools` | GET | MCP tool monitoring list (tools/services dimension) |
| `/nb/v1/monitoring/mcp-tools/summary` | GET | MCP monitoring summary |
| `/nb/v1/monitoring/mcp-tools/rankings` | GET | Top 5 MCP tools |
| `/nb/v1/monitoring/mcp-tools/trends` | GET | MCP call trends |
| `/nb/v1/monitoring/mcp-tools/catalog` | GET | MCP service catalog (filter options) |
| `/nb/v1/monitoring/mcp-tools/overview` | GET | Platform overview (per-tenant inventory and call trend) |
| `/nb/v1/monitoring/mcp-tools/refresh` | POST | Submit an MCP recompute wait token (202) |
| `/nb/v1/monitoring/mcp-tools/refreshes/{refresh_id}` | GET | Query source revision publication progress |

### Common Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` / `end_date` | date | Yes | Statistics window (span must be under 366 days) |
| `group_ids` | int[] | No | User-group filter (at most 100) |
| `model_id` / `model_type` / `agent_id` / `skill_id` / `skill_name` / `server_id` / `server_type` / `tool_name` | — | No | Dimension-specific filters |
| `page` / `page_size` / `search` / `sort_by` / `descending` | — | No | List pagination and sorting (`page_size` ≤ 100) |

### Response Format

A successful response uses the unified envelope; `data` carries the
dashboard-native body (its `data` result field plus the `data_as_of` /
`coverage_state` / `is_stale` coverage fields):

```json
{
  "message": "success",
  "requestId": "req-uuid-here",
  "data": {
    "data": { "...": "dashboard-native result" },
    "data_as_of": "2026-11-27T00:00:00Z",
    "coverage_state": "covered",
    "is_stale": false
  }
}
```

### Semantics of the recompute wait token

`POST .../refresh` **does not create a recompute job**: it reads the current
source data revision (`source_revision`) for the selected window and issues a
polling token. The caller then polls `GET .../refreshes/{refresh_id}` until
that source revision has been published as queryable statistics (a
read-your-writes semantic). When the source revision is already published, the
first poll returns `completed` immediately; when the window has no confirmed
source data, the POST answers `409 MONITORING_DATES_UNCOVERED` (with
`missing_dates`). While waiting the status is `running`; a timeout is
reported as `timed_out`.

Error responses use the three-field shape `{code, message, status, requestId}`.
Common errors: `403 HTTP_403` (tenant mismatch), `404 HTTP_404` (recompute job
missing or owned by another tenant), `409 MONITORING_DATES_UNCOVERED`
(recompute window has no source data), `422 HTTP_422` (validation failure),
`429 RATE_LIMIT_EXCEEDED` (recompute actions exceed the per-tenant limit,
default 120/min), `503 HTTP_503` (monitoring temporarily unavailable).

### Example

```bash
curl -X GET "https://your-nexent-domain.com/nb/v1/monitoring/models/summary?start_date=2026-11-20&end_date=2026-11-27" \
  -H "Authorization: Bearer your-access-key-here"

curl -X POST "https://your-nexent-domain.com/nb/v1/monitoring/models/refresh" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-11-20", "end_date": "2026-11-27"}'
```

## Error Codes

Business errors use the three-field envelope `{code, message, status, requestId}`. `code` is a stable string; clients should branch on `code` first and use the HTTP status code only as a fallback.

| HTTP Status Code | `code` | Description |
|------------------|--------|-------------|
| `400 Bad Request` | `VALIDATION_ERROR` | Business parameter validation failed (e.g., batch delete with more than 100 conversations, unknown tool parameter) |
| `400 Bad Request` | `AUTOMATION_ERROR` | Automation task operation failed |
| `401 Unauthorized` | — | Authentication failed or missing API Key (gateway returns `{"message": "Invalid or missing credentials"}`) |
| `403 Forbidden` | `FORBIDDEN` | No permission to access the conversation, task, or file |
| `404 Not Found` | `NOT_FOUND` | The conversation / file does not exist, or does not belong to the current user |
| `404 Not Found` | `AUTOMATION_TASK_NOT_FOUND` | The automation task does not exist, or does not belong to the current user |
| `404 Not Found` | — | Path not exposed or nonexistent (gateway returns `{"detail": "Not found"}`) |
| `409 Conflict` | `CHAT_METADATA_VERSION_CONFLICT` | Runtime metadata version conflict |
| `422 Unprocessable Entity` | — | Framework-level parameter validation failed: type mismatch, value out of range, or value outside the allowed set. Body is the FastAPI native `{"detail": [...]}` |
| `429 Too Many Requests` | `RATE_LIMIT_EXCEEDED` | Request rate limit exceeded |
| `429 Too Many Requests` | `TENANT_RESOURCE_EXCEEDED` | Tenant resource quota exceeded |
| `500 Internal Server Error` | `INTERNAL_ERROR` | Server internal error; the body contains no internal details |
| `502 Bad Gateway` | — | Upstream service unavailable |
| `504 Gateway Timeout` | — | Upstream service timeout |

> Recommended client-side decision order: ① check whether the HTTP status is `2xx`; ② check whether the body has a `code` field (business error); ③ check whether the body has a `detail` field (parameter validation error); ④ treat everything else as a gateway error. Always provide `requestId` to operations when troubleshooting.

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

Conversation histories are retained by default indefinitely unless users actively delete them or the tenant has configured an expiration policy. Callers can actively clean up conversations they no longer need via `DELETE /nb/v1/conversations/{conversation_id}` or `POST /nb/v1/conversations/batch-delete`; see [Delete Conversation](#🆕-delete-conversation).

## Related Resources

- [API Overview](./overview) — Complete northbound API capability map
- [Agent Export](./agents-export) — Agent configuration export and publish
- [A2A Protocol Endpoints](./overview) — Agent-to-Agent communication standard
