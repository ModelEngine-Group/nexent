# 调用 Agent 北向 API

Nexent 平台提供北向 RESTful API，允许外部业务系统通过 HTTP 协议与平台深度集成。本文档重点介绍 **对话与聊天** 相关的接口，帮助您将 Agent 能力嵌入到企业业务系统中，实现工作流自动化。

## 📋 概述

对话与聊天 API 提供了完整的会话生命周期管理能力：

| 能力 | 说明 |
|------|------|
| **启动对话** | 向指定 Agent 发起对话，支持流式响应和附件上传 |
| **会话管理** | 列出对话、查询历史、生成和更新标题 |
| **停止对话** | 中断正在进行的流式响应 |

> 其他能力（如 API Key 管理、Agent 发现、知识库管理、A2A 协议等）请参阅后续章节或 [API 总览](./overview)。

## 🔑 认证方式

所有对话与聊天 API 均需认证，采用 **Bearer Token**（API Key）机制。

### 获取 API Key

1. 登录 Nexent 平台
2. 进入「个人信息」页面
3. 点击「生成 API 密钥」
4. 复制生成的 Access Key

### 使用 API Key

在请求头中携带 `Authorization` 字段：

```http
Authorization: Bearer {access_key}
```

### 示例请求

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "general-assistant",
    "query": "你好，请介绍一下你自己"
  }'
```

### 响应格式

成功响应：

```json
{
  "message": "success",
  "requestId": "req-uuid-here",
  "data": { ... }
}
```

错误响应：

```json
{
  "detail": "Error description"
}
```

## 📑 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/nb/v1/chat/attachments/upload` | POST | 上传对话附件 |
| `/nb/v1/chat/run` | POST | 启动对话（流式响应） |
| `/nb/v1/chat/stop/{conversation_id}` | GET | 停止对话 |
| `/nb/v1/conversations` | GET | 列出当前用户的所有对话 |
| `/nb/v1/conversations/{conversation_id}` | GET | 获取对话历史 |
| `/nb/v1/generate_title` | POST | 生成对话标题 |
| `/nb/v1/conversations/{conversation_id}/title` | PUT | 更新对话标题 |

## ▶️ 启动对话

启动与 Agent 的对话，返回流式响应（SSE）。

```http
POST /nb/v1/chat/run
```

### 请求体

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_name` | string | 是 | 目标 Agent 名称 |
| `query` | string | 是 | 用户输入内容 |
| `enable_hitl` | boolean | 否 | 是否启用人在回路，默认 `false` |
| `conversation_id` | integer | 否 | 已有对话 ID，不填则创建新对话 |
| `attachments` | array | 否 | 附件列表（S3 URL 或附件元数据对象） |
| `model_id` | integer | 否 | 模型 ID（覆盖 Agent 默认模型） |
| `metadata` | object | 否 | 运行时元数据（对 Agent 可见） |
| `meta_data` | object | 否 | 审计元数据（仅记录，不暴露给 Agent） |
| `tool_params` | object | 否 | 工具参数覆盖 |

### 请求头

| 头 | 必填 | 说明 |
|-----|------|------|
| `Authorization` | 是 | `Bearer {access_key}` |
| `Content-Type` | 是 | `application/json` |
| `Idempotency-Key` | 否 | 幂等键，用于防止重复提交 |

### 请求示例

基础对话请求：

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "general-assistant",
    "query": "请帮我分析一下这份销售数据"
  }'
```

带附件的对话请求：

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "data-analyst",
    "query": "请分析这份销售报告",
    "attachments": ["s3://nexent/attachments/user123/20260609_report.pdf"],
    "metadata": {"project_id": "P001", "manager": "Alice"},
    "meta_data": {"source": "crm", "ticket_id": "INC-1001"}
  }'
```

带工具参数覆盖的请求：

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "common_sense_qa_assistant",
    "query": "总结一下这份文档",
    "attachments": ["s3://nexent/attachments/user123/doc.pdf"],
    "tool_params": {
      "agents": {
        "common_sense_qa_assistant": {
          "tools": {
            "analyze_text_file": {
              "chunk_size": 4000,
              "summary_only": true,
              "prompt": "请提供简洁的摘要，聚焦于核心要点"
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

### tool_params 结构说明

`tool_params` 用于在单次请求中覆盖工具的默认参数：

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

参数合并规则：

- **优先级**：请求参数 > 数据库持久化参数
- **工具匹配**：先按 `tool.name` 匹配，再按 `tool.class_name` 匹配
- **未知参数**：传入未知参数名将返回 `400 ValidationError`
- **元数据字段**：如 `vdb_core`、`embedding_model` 等会基于合并后的参数自动重新计算

### 响应（流式）

接口返回 Server-Sent Events（SSE）流，逐块返回 Agent 响应：

```text
data: {"type":"model_output_thinking","content":"正在分析数据","unit_index":1}

data: {"type":"model_output_thinking","content":"，请稍候...","unit_index":1}

data: {"type":"final_answer","content":"分析完成","unit_index":2}
```

## 人在回路（HITL）

对话入口为 `POST /api/nb/v1/chat/run`。本文其他路径省略网关公共前缀 `/api`；直连服务时请按实际部署的根路径访问。所有 HITL 接口沿用 `Authorization: Bearer {access_key}`，用户和租户由 API Key 解析，不接受调用方指定 `user_id` 或 `tenant_id`。

### 开启与运行过程

```bash
curl -N 'https://your-nexent-domain.com/api/nb/v1/chat/run' \
  -H "Authorization: Bearer ${NEXENT_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"agent_name":"general-assistant","query":"帮我准备通知","enable_hitl":true}'
```

`enable_hitl` 默认为 `false`。客户端应先查询 `GET /nb/v1/chat/human-interactions/capabilities`，读取响应的 `data.enabled`、`data.accept_new_runs` 和 `data.tool_approval_enabled`。runtime 关闭 HITL 或停止接收新 HITL 运行时，启动请求沿用普通对话行为；`enable_hitl=true` 不保证一定生成卡片，Agent 只在需要补充关键信息时提问。

启动后，runtime 为当前会话建立一个 `run_id`。遇到人工交互时持久化卡片并进入 `WAITING_HUMAN`；提交有效决定后进入 `READY`，由当前执行线程或调度器继续同一次运行。北向服务通过内部 JWT 代理到 runtime，复用其持久化、租户及用户归属校验、版本校验和幂等处理。

### 流式事件协议

继续使用 `data: {"type": ..., "content": ...}`。**卡片的 `type` 固定为 `human_interaction`**，卡片内容为 JSON 对象，不需要再次 `JSON.parse(content)`。

| `type` | `content` | 用途 |
|---|---|---|
| `conversation_created` | 对象，包含 `conversation_id` | 新建会话时的北向通知 |
| `human_run` | 对象，包含 `run_id`、`status`；快照还包含 `conversation_id`、`event_seq`、`requests` | 运行状态和待处理卡片快照 |
| `human_interaction` | 卡片对象 | 展示人工输入或确认卡片 |
| `human_decision` | 对象，包含 `run_id`、`request_id`、`status` | 决定已接受，更新卡片状态 |
| `human_execution` | 对象，包含工具执行槽位及状态 | 工具执行进度通知 |
| `model_output_thinking`、`final_answer`、`token_count` 等 | 沿用原运行时格式 | 普通 Agent 输出，北向原样透传 |

`human_interaction.content.kind` 进一步区分：

| `kind` | 提交的 `decision` | 输入 |
|---|---|---|
| `CLARIFICATION` | `answer` | 结构化卡片用 `answers`；兼容旧单问题卡片时用 `text` |
| `ACTION_APPROVAL` | `approve` / `reject` | 审批原卡片中的动作；不能修改工具参数后沿用原审批 |
| `USER_STEERING` | `steer` | 使用 `text` 提交暂停后的指导意见 |

卡片示例（`digest` 仅为示例，提交时必须原样复制实际卡片的值）：

```text
id: 12
data: {"type":"human_interaction","content":{"request_id":"01a09fce-3a28-7860-8646-b0eec69d5f47","run_id":"01a09fce-3a28-7860-8646-b0eec69d5f46","kind":"CLARIFICATION","status":"PENDING","version":1,"digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expires_at":"2026-09-15T10:00:00+00:00","payload":{"schema_version":2,"questions":[{"id":"audience","type":"single_choice","title":"通知发给谁？","required":true,"options":[{"id":"team","label":"内部团队"},{"id":"client","label":"客户"}],"allow_other":true}]}}}
```

`payload.questions` 支持 `text`、`single_choice`、`multiple_choice`，最多 5 个问题，同一次运行最多 1 张澄清卡片。单选提交选项 ID 字符串，多选提交选项 ID 数组；允许其他答案时可加 `other_text`。必答项、未知选项及重复问题答案均由 runtime 校验。不要把卡片的内部题型 `type` 和外层流事件 `type` 混淆。

### 查询与提交接口

以下表格中的公共前缀为 `/nb/v1/chat/human-interactions`：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/capabilities` | 查询 runtime 的实际能力开关 |
| GET | `/conversation/{conversation_id}` | 当前 API 用户在此会话的最新 HITL 运行；没有可见运行时 `data=null` |
| GET | `/{run_id}` | 查询运行状态及 `requests` 中的待处理卡片 |
| POST | `/{run_id}/requests/{request_id}/decisions` | 提交卡片答案、批准、拒绝或暂停后的意见 |
| GET | `/{run_id}/events?after_event=12` | 订阅同一运行的后续 SSE 事件 |
| POST | `/{run_id}/pause` | 请求在安全执行边界暂停；不代表立即中断正在执行的工具 |
| POST | `/{run_id}/steer` | 在当前运行追加指导意见；会取消当前待处理卡片 |
| POST | `/{run_id}/terminate` | 终止当前运行并取消待处理卡片 |

JSON 成功响应统一为 `{"message":"success","requestId":"...","data":...}`。决定接口的 `data` 为 `{"run_id":"...","request_id":"...","accepted":true}`。SSE 接口仍直接返回事件流。

填写卡片后，**调用决定接口，不要将答案作为新的 `query` 再调用 `/chat/run`**：

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

- `version`、`digest` 从原卡片复制；它们将决定绑定到具体版本和动作。
- `idempotency_key` 放在 JSON 请求体中，长度 8–100。同一提交超时重试时复用同一键和完全相同的内容；相同键对应不同内容返回 `409`。
- 结构化澄清只传 `answers`，不要同时传 `text`；旧单问题澄清或 `USER_STEERING` 使用 `text`。
- 审批使用同一接口，将 `decision` 改为 `approve` 或 `reject`，不传 `answers`。
- 没有待处理卡片时需要补充新意见，可调用 `/{run_id}/steer`，请求体为 `{"message_id":"guidance-0001","text":"请按新的要求继续"}`。`message_id` 是该条指导意见的幂等标识。此操作会取消待处理卡片，并不表示批准待审工具动作。

只凭 `conversation_id` 无法明确区分同一会话的多轮运行、不同卡片和卡片版本，因此提交接口必须绑定 `run_id + request_id + version + digest`。会话查询接口用于找回这些信息。

### 等待、断线和恢复

1. 消费启动流，保存 `conversation_id`、`run_id` 和已经完整消费的 SSE `id`。`human_run.requests` 也可能包含待处理卡片，按 `request_id + version` 合并，避免重复展示。
2. 收到 `human_interaction` 后展示卡片，收到 `human_decision` 后关闭或更新卡片。
3. 决定接口返回 `accepted=true` 只表示输入已接受，执行结果仍从 SSE 读取。原流还连接时可继续消费；原流已结束或断开时，订阅 `GET /nb/v1/chat/human-interactions/{run_id}/events?after_event=<最后消费的ID>`。
4. 未提供 `after_event` 时，订阅接口也接受 `Last-Event-ID` 请求头；显式 `after_event` 优先。默认 `0` 重放全部持久化事件。订阅不写入用户消息、不重新启动 Agent。
5. 每次订阅先发送无 SSE `id` 的当前 `human_run` 快照，再按顺序重放大于游标的持久化事件。**不要把初始快照的 `event_seq` 当作已消费游标**，否则会跳过尚未读取的输出；无 `id` 的快照和心跳不推进客户端游标。提交答案后应继续使用提交前最后消费的 ID。
6. `WAITING_HUMAN` 是等待输入，不是完成；此时 SSE 可能保持连接，也可能结束订阅。只有 `human_run.status` 为 `COMPLETED`、`FAILED`、`STOPPED`、`EXPIRED` 或 `RECOVERY_REQUIRED` 时，客户端才应结束本轮等待。`RECOVERY_REQUIRED` 表示执行无法自动恢复，不能将原动作盲目重发。

`GET /nb/v1/chat/stop/{conversation_id}` 同样会终止此会话当前 API 用户的活跃 HITL 运行。

### 错误与部署要求

| HTTP 状态 | 含义 |
|---|---|
| 401 | API Key 或内部 runtime 身份验证失败 |
| 404 | 运行/卡片不存在，或不属于当前租户及用户 |
| 409 | 卡片已处理、版本/摘要不一致，或幂等键对应不同内容 |
| 410 | 本次提交检测到卡片过期；若过期状态已被调度器处理，也可能返回 `409` |
| 422 | 请求体、回答、决定类型或事件游标不合法 |
| 503 | runtime 未启用 HITL，无法查询运行或处理决定 |
| 502 / 504 | runtime 不可连接 / 请求超时 |

部署需已应用 `deploy/sql/migrations/v2.6.0_merged_migrations.sql`，runtime 配置有效的 `HITL_ENCRYPTION_KEY`，并开启 `HITL_ENABLED`、`HITL_ACCEPT_NEW_RUNS`。工具审批另外受 `HITL_TOOL_APPROVAL_ENABLED` 控制；默认的 `native-live-v1` 保留原执行现场以继续运行，worker 丢失后不能保证自动恢复，会进入需要恢复处理的状态。北向接口不改变已有执行模式的能力边界。

## 📎 上传对话附件

在调用 `/nb/v1/chat/run` 之前，先上传附件获取可在请求中引用的 URL。

```http
POST /nb/v1/chat/attachments/upload
Content-Type: multipart/form-data
```

### 表单字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | file | 是 | 上传的文件（支持多个） |

### 请求示例

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/attachments/upload" \
  -H "Authorization: Bearer your-access-key-here" \
  -F "files=@report.pdf" \
  -F "files=@diagram.png"
```

### 响应示例

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

将返回的 `s3_url` 作为 `/nb/v1/chat/run` 接口中 `attachments` 字段的值。

## ⏹️ 停止对话

终止正在进行的对话（流式响应）。

```http
GET /nb/v1/chat/stop/{conversation_id}
```

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | integer | 对话 ID |

### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `meta_data` | string | 否 | 元数据（JSON 字符串） |

### 请求示例

```bash
curl -X GET "https://your-nexent-domain.com/nb/v1/chat/stop/123" \
  -H "Authorization: Bearer your-access-key-here"
```

## 📜 获取对话历史

获取指定对话的所有消息历史。

```http
GET /nb/v1/conversations/{conversation_id}
```

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | integer | 对话 ID |

### 响应示例

```json
{
  "conversation_id": 123,
  "title": "销售数据分析",
  "messages": [
    {
      "role": "user",
      "content": "请分析本月销售数据",
      "timestamp": "2026-08-30T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "根据您的销售数据，本月销售额较上月增长 15%...",
      "timestamp": "2026-08-30T10:00:05Z"
    }
  ]
}
```

## 📑 列出对话

获取当前用户的所有对话列表。

```http
GET /nb/v1/conversations
```

### 响应示例

```json
{
  "conversations": [
    {
      "conversation_id": 123,
      "title": "销售数据分析",
      "create_time": "2026-08-30T10:00:00Z",
      "update_time": "2026-08-30T10:30:00Z"
    },
    {
      "conversation_id": 124,
      "title": "客户画像分析",
      "create_time": "2026-08-30T14:00:00Z",
      "update_time": "2026-08-30T14:20:00Z"
    }
  ]
}
```

## ✨ 生成对话标题

根据对话的初始问题自动生成标题并持久化。

```http
POST /nb/v1/generate_title
```

### 请求体

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `conversation_id` | integer | 是 | 对话 ID |
| `question` | string | 是 | 初始问题（用于生成标题） |

### 请求示例

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/generate_title" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": 123,
    "question": "请帮我分析一下本季度各区域的销售表现，并指出表现最好的三个区域"
  }'
```

### 响应示例

```json
{
  "title": "本季度各区域销售表现分析"
}
```

## ✏️ 更新对话标题

手动更新对话的标题。

```http
PUT /nb/v1/conversations/{conversation_id}/title
```

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | integer | 对话 ID |

### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 是 | 新标题 |
| `meta_data` | string | 否 | 元数据（JSON 字符串） |

### 请求头

| 头 | 说明 |
|-----|------|
| `Idempotency-Key` | 幂等键（可选），用于防止重复提交 |

### 请求示例

```bash
curl -X PUT "https://your-nexent-domain.com/nb/v1/conversations/123/title?title=Q3销售分析" \
  -H "Authorization: Bearer your-access-key-here"
```

## ⚠️ 错误码说明

| HTTP 状态码 | 说明 |
|-------------|------|
| `200 OK` | 请求成功 |
| `400 Bad Request` | 请求参数错误（如未知工具参数） |
| `401 Unauthorized` | 认证失败或缺少 API Key |
| `403 Forbidden` | 无权限访问该对话或资源 |
| `404 Not Found` | 对话不存在 |
| `429 Too Many Requests` | 请求频率超限 |
| `500 Internal Server Error` | 服务器内部错误 |
| `502 Bad Gateway` | 上游服务不可用 |
| `504 Gateway Timeout` | 上游服务超时 |

## 💻 完整使用示例

### Python 示例：带附件的对话

```python
import requests

BASE_URL = "https://your-nexent-domain.com"
API_KEY = "your-access-key-here"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 1. 上传附件
upload_response = requests.post(
    f"{BASE_URL}/nb/v1/chat/attachments/upload",
    headers={"Authorization": f"Bearer {API_KEY}"},
    files={"files": open("sales-data.csv", "rb")}
)
upload_data = upload_response.json()
s3_url = upload_data["files"][0]["s3_url"]

# 2. 启动对话（流式响应）
with requests.post(
    f"{BASE_URL}/nb/v1/chat/run",
    headers=headers,
    json={
        "agent_name": "data-analyst",
        "query": "分析这份销售数据，找出关键趋势",
        "attachments": [s3_url],
        "metadata": {"project_id": "Q3-REPORT"},
        "meta_data": {"source": "etl-pipeline", "batch_id": "B001"}
    },
    stream=True
) as response:
    for line in response.iter_lines():
        if line:
            print(line.decode("utf-8"))

# 3. 查询对话历史
history_response = requests.get(
    f"{BASE_URL}/nb/v1/conversations/123",
    headers=headers
)
print(history_response.json())
```

### JavaScript 示例：发起流式对话

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
      query: "请帮我写一首关于秋天的诗",
      conversation_id: 123  // 可选，不填则创建新对话
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

## ❓ 常见问题

### Q: 如何获取 API Key？

在 Nexent 平台的「个人信息」页面，点击「生成 API 密钥」获取。

### Q: 对话接口支持流式输出吗？

是的，`POST /nb/v1/chat/run` 返回 SSE（Server-Sent Events）流式响应，可实时接收 Agent 的部分输出。

### Q: 如何停止正在进行的对话？

调用 `GET /nb/v1/chat/stop/{conversation_id}` 终止对话。

### Q: tool_params 中的未知参数会怎样？

如果 `tool_params` 中传入了工具不支持的参数名，会返回 `400 Bad Request` 错误，提示参数验证失败。

### Q: 附件是否必须先上传？

是的，附件需要先通过 `/nb/v1/chat/attachments/upload` 上传，获取 `s3_url` 后再通过 `attachments` 字段传递给对话接口。

### Q: 本地开发环境如何访问？

| 部署方式 | 路径前缀 |
|----------|----------|
| Docker 部署 | 替换为 `http://localhost:5013/nb/v1` |
| Kubernetes 部署 | 替换为 `http://localhost:30013/nb/v1` |
| 生产环境 | 替换为实际服务器域名或公网 IP |

### Q: 多个附件如何上传？

在 `multipart/form-data` 请求中，使用多个同名字段 `files` 上传多个文件。

### Q: 对话历史会保留多久？

对话历史默认长期保留，除非用户主动删除或租户配置了过期策略。

## 🔗 相关资源

- [API 总览](./overview) — 北向 API 完整能力地图
- [Agent 智能体导出与发布](./agents-export) — Agent 配置导出与发布
- [A2A 协议端点](./overview) — Agent-to-Agent 通信标准