# 调用 Agent 北向 API

Nexent 平台提供北向 RESTful API，允许外部业务系统通过 HTTP 协议与平台深度集成。本文档重点介绍 **对话与聊天** 相关的接口，帮助您将 Agent 能力嵌入到企业业务系统中，实现工作流自动化。

## 📋 概述

对话与聊天 API 提供了完整的会话生命周期管理能力：

| 能力 | 说明 |
|------|------|
| **启动对话** | 向指定 Agent 发起对话，支持流式响应和附件上传 |
| **会话管理** | 列出对话、查询历史、生成和更新标题 |
| **停止对话** | 中断正在进行的流式响应 |
| **会话清理** | 删除单个对话或批量删除对话（级联清理消息与关联的自动化任务） |
| **自动化任务查询** | 列出当前用户的定时自动化任务，查询任务详情 |
| **文件下载** | 下载对话附件或知识库文件，支持预签名 URL 与字节流两种模式 |

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

错误响应。北向接口的失败响应体**并不统一**，按来源分为三种形态，客户端应同时兼容：

```json
// ① 业务错误（资源不存在、无权限、参数越界等）：三字段信封 + requestId
{
  "code": "NOT_FOUND",
  "message": "Resource not found",
  "status": 404,
  "requestId": "req-uuid-here"
}

// ② 框架层参数校验失败（类型不符、超出取值范围、枚举外取值）：FastAPI 原生格式
{
  "detail": [
    { "loc": ["query", "page_size"], "msg": "Input should be less than or equal to 100", "type": "less_than_equal" }
  ]
}

// ③ 网关层拒绝（未携带 / 无效 API Key、路径未开放）
{ "message": "Invalid or missing credentials" }
```

完整的 `code` 对照表见下文 [错误码说明](#⚠️-错误码说明)。

## 📑 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/nb/v1/chat/attachments/upload` | POST | 上传对话附件 |
| `/nb/v1/chat/run` | POST | 启动对话（流式响应） |
| `/nb/v1/chat/stop/{conversation_id}` | GET | 停止对话 |
| `/nb/v1/conversations` | GET | 列出当前用户的所有对话 |
| `/nb/v1/conversations/{conversation_id}` | GET | 获取对话历史 |
| `/nb/v1/conversations/{conversation_id}` | DELETE | 删除对话 |
| `/nb/v1/conversations/batch-delete` | POST | 批量删除对话 |
| `/nb/v1/generate_title` | POST | 生成对话标题 |
| `/nb/v1/conversations/{conversation_id}/title` | PUT | 更新对话标题 |
| `/nb/v1/automations` | GET | 列出当前用户的自动化任务 |
| `/nb/v1/automations/{task_id}` | GET | 获取自动化任务详情 |
| `/nb/v1/file/download/{object_name}` | GET | 下载文件（预签名 URL 或字节流） |

> 标题前带 🆕 的章节为近期新增接口：会话清理（2 个）、自动化任务查询（2 个）、文件下载（1 个）。

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
| `conversation_id` | integer | 否 | 已有对话 ID，不填则创建新对话 |
| `attachments` | array | 否 | 附件列表（S3 URL 或附件元数据对象） |
| `model_id` | integer | 否 | 模型 ID（覆盖 Agent 默认模型） |
| `final_answer_mode` | string | 否 | 默认 `complete`：最终只返回一次完整的主 Agent `final_answer`；传 `delta` 保留增量答案协议 |
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

默认或显式传入 `"final_answer_mode":"complete"` 时，过程事件仍实时发送，最终答案在执行成功并完成持久化后一次性返回。旧客户端收到第一个 `final_answer` 即可读取全文。子 Agent 的答案不会作为最终结果提前返回；失败或停止不会把部分答案当作成功结果返回。

使用 smolagents 时，主 Agent 的答案正文还会以 `model_output_thinking` 增量发送，并带有 `answer_preview: true` 和 `answer_phase: "delta"`。这些事件是尚未确认的答案预览，与普通 thinking 分开处理。客户端应依据 `step_id`、`attempt_id` 和 invocation 范围更新同一个答案位置；最后的完整 `final_answer` 确认或替换该位置的内容，避免再次追加全文。收到 `model_attempt_control` 回滚事件时应撤销对应的预览。预览不会另存为 thinking，重新加载历史时只保留一份正式答案。`delta` 模式和 jiuwen 的现有事件行为保持不变。

```text
data: {"type":"model_output_thinking","answer_preview":true,"answer_phase":"delta","step_id":"s1","content":"分析"}

data: {"type":"model_output_thinking","answer_preview":true,"answer_phase":"delta","step_id":"s1","content":"完成"}

data: {"type":"final_answer","answer_phase":"complete","step_id":"s1","content":"分析完成"}
```

需要增量答案的客户端须在请求体中传入 `"final_answer_mode":"delta"`。事件类型仍为 `final_answer`，通过 `answer_phase` 区分阶段：

```text
data: {"type":"final_answer","answer_phase":"delta","content":"分析"}

data: {"type":"final_answer","answer_phase":"delta","content":"完成"}

data: {"type":"final_answer","answer_phase":"complete","content":""}
```

`delta` 片段应追加；`complete` 的非空正文是最终修订全文，应替换已有正文；空正文表示使用已累积的片段。保留现有重试回滚和 `reclassify_step` 处理，不要把每个 `final_answer` 都直接拼接。其他模式值返回 `422`。此前依赖增量答案的北向客户端升级时应显式传 `delta`。

## 结构化反问与停止后补充

Agent 在缺少关键信息时可返回结构化反问。本轮通过普通完成流程结束并释放 worker，客户端在收到流结束后，把答案作为同一 conversation 的普通新 query 发送。不需要开关、待办查询、决定提交或执行恢复接口。

### 反问 SSE

外层继续使用 `data: {"type": ..., "content": ...}`。`type="human_interaction"` 的 `content` 是 **JSON 对象**，直接包含 `schema_version: 1` 和 `questions`；紧随的普通 `final_answer` 包含完整可读问题回退。

```text
data: {"type":"human_interaction","content":{"schema_version":1,"questions":[{"id":"audience","type":"single_choice","title":"通知发给谁？","required":true,"options":[{"id":"team","label":"内部团队"},{"id":"client","label":"客户"}],"allow_other":true,"placeholder":""}]},"unit_index":1}

data: {"type":"final_answer","content":"1. 通知发给谁？\n   - 内部团队\n   - 客户\n   - 其他 / Other","unit_index":2}
```

`questions` 最多 5 项，支持 `text`、`single_choice`、`multiple_choice`。问题字段包括 `id`、`type`、`title`、`required`、`options`、`allow_other` 和 `placeholder`；选项使用 `id` 与 `label`。文本题没有选项；选择题提供 2–12 个选项。客户端可复用表单展示，在确认本轮流结束之前禁用提交。有效卡片已显示时可隐藏精确匹配的问题文本，纯文本客户端直接显示 `final_answer`。

### 回答作为下一 query

将问题和可读答案组合成普通文本，调用现有接口，并使用该会话的真实 `conversation_id`：

```bash
curl -N 'https://your-nexent-domain.com/api/nb/v1/chat/run' \
  -H "Authorization: Bearer ${NEXENT_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id":123,"agent_name":"general-assistant","query":"补充上一轮问题：通知发给内部团队，其他补充：仅研发部门。"}'
```

这里的 `123` 仅为示例。答案应包含选项文案以及用户填写的其他内容，而不只是问题 ID 或选项 ID。新运行读取普通会话历史，不恢复上一轮执行栈或计划游标。刷新后从普通消息中的 `human_interaction` 单元重建卡片；较早历史卡片只读，答案在后续 user 消息中查看。

### 普通停止与兼容性

使用 `GET /nb/v1/chat/stop/{conversation_id}` 停止当前运行。收到 HTTP 200 后，旧运行已释放会话占用，可以用原会话 ID 发送下一轮。新 query 可以读取原始任务、停止说明和已保存的部分结果。停止不会回滚已发生的外部操作。

旧 HITL 专属路由、审批、暂停续跑、四表运行依赖和密钥配置已移除。北向 `/chat/run` 若收到 `enable_hitl`、`hitl_run_id` 或 `hitl_after_event`，明确返回 `400`；字段即使为 false、null 或零也不能继续发送。Web 与 runtime 应同步更新。普通身份、权限、附件、元数据及错误响应保持原有约定。

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

请求取消后，接口最多等待 5 秒，确认目标任务退出并释放会话占用。HTTP 200 表示目标占用已经释放，或者会话本来就空闲。如果到期仍未释放，接口返回 HTTP 409，错误码为 `NORTHBOUND_STOP_IN_PROGRESS`，并携带 `Retry-After: 1`。取消仍在继续，请保留新消息，等确认停止后再发送。同一会话的并发启动请求仍可能发生冲突。

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

## 🆕 删除对话

删除当前用户名下的一个对话。**软删除**，对话记录、消息、消息单元、搜索来源、图片来源与轨迹摘要一并打上删除标记，不会物理清除；绑定在该对话上的自动化任务会被取消运行并软删除（尽力而为，清理失败不阻断删除）。每次调用（包括被拒绝的调用）都会写入一条安全审计记录。

```http
DELETE /nb/v1/conversations/{conversation_id}
```

### 路径参数

| 参数 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| `conversation_id` | integer | 是 | ≥ 1 | 对话 ID |

### 请求示例

```bash
curl -X DELETE "https://your-nexent-domain.com/nb/v1/conversations/123" \
  -H "Authorization: Bearer your-access-key-here"
```

### 响应参数

成功时 `data` 恒为 `true`。

| 字段 | 类型 | 说明 |
|------|------|------|
| `message` | string | 固定为 `success` |
| `data` | boolean | 删除成功恒为 `true` |
| `requestId` | string | 请求追踪 ID，排查问题时提供给运维 |

### 响应示例

```json
{
  "message": "success",
  "data": true,
  "requestId": "req-uuid-here"
}
```

### 错误情况

| HTTP | `code` | 场景 |
|------|--------|------|
| `404` | `NOT_FOUND` | 对话不存在、已被删除，或**不属于当前 API Key 所属用户**（三者返回一致，不泄露他人对话是否存在） |
| `401` | — | 未携带或无效 API Key |
| `500` | `INTERNAL_ERROR` | 服务端异常 |

> 对同一个对话重复调用删除，第二次起返回 `404`，这是幂等表现而非故障。

## 🆕 批量删除对话

一次请求删除多个对话，语义与[删除对话](#🆕-删除对话)一致。**整体请求不会因个别对话失败而失败**：无权访问、已删除的 ID 会被跳过并放入 `failed_ids`，其余正常删除。

```http
POST /nb/v1/conversations/batch-delete
Content-Type: application/json
```

### 请求体

| 参数 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| `conversation_ids` | array\<integer\> | 是 | 1 ~ 100 个元素 | 待删除的对话 ID 列表 |

约束细则：

- 超过 **100** 个 ID 返回 `400 VALIDATION_ERROR`，请分批调用
- 列表为空 `[]` 时返回 `{"deleted_count": 0, "failed_ids": []}`，不报错
- 列表中的重复 ID 会被去重，`deleted_count` 以实际删除数为准

### 请求示例

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/conversations/batch-delete" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{"conversation_ids": [123, 124, 125]}'
```

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.deleted_count` | integer | 实际删除的对话数 |
| `data.failed_ids` | array\<integer\> | 未能删除的对话 ID（不存在、已删除或不属于当前用户） |

### 响应示例

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

### 错误情况

| HTTP | `code` | 场景 |
|------|--------|------|
| `400` | `VALIDATION_ERROR` | ID 数量超过 100 |
| `422` | — | 请求体不是合法 JSON、缺少 `conversation_ids`、或元素不是整数（返回 FastAPI 原生 `detail` 数组） |
| `401` | — | 未携带或无效 API Key |

> 删除对话属于**不可逆操作**（软删除，但北向接口不提供恢复能力），建议先用 `GET /nb/v1/conversations` 核对 ID 再调用。

## 🆕 列出自动化任务

列出当前用户名下的自动化任务（定时任务）。仅返回当前用户创建且未删除的任务，按更新时间倒序排列。

```http
GET /nb/v1/automations
```

### 查询参数

| 参数 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| `status` | string | 否 | 见下表 | 按任务状态过滤 |
| `search` | string | 否 | ≤ 200 字符 | 按**任务标题**模糊匹配（不区分大小写） |
| `agent_name` | string | 否 | ≤ 200 字符 | 按 Agent 名称模糊匹配（不区分大小写，**先过滤再分页**） |
| `page` | integer | 否 | ≥ 1，默认 `1` | 页码 |
| `page_size` | integer | 否 | 1 ~ 100，默认 `20` | 每页条数 |

`status` 取值说明。为兼容前端语义，`ENABLED` 与 `RUNNING` 是两个**虚拟状态**，服务端会转换后再查询：

| 传入值 | 实际含义 |
|--------|----------|
| `ENABLED` | 处于启用状态且当前**没有**正在执行的运行 |
| `RUNNING` | 当前**有**正在执行的运行 |
| `ACTIVE` | 任务状态为活跃（可能正在执行） |
| `PAUSED` / `PAUSED_BY_SYSTEM` | 已暂停 / 被系统暂停 |
| `COMPLETED` | 已完成 |
| 不传 | 不过滤（`DELETED` 永远不会返回） |

> 传入枚举之外的值（如 `enabled` 小写）不会报错，只会返回空列表。

### 请求示例

```bash
# 第 1 页，每页 10 条，只看启用中的任务
curl "https://your-nexent-domain.com/nb/v1/automations?page=1&page_size=10&status=ENABLED" \
  -H "Authorization: Bearer your-access-key-here"

# 按标题关键词搜索
curl "https://your-nexent-domain.com/nb/v1/automations?search=%E5%91%A8%E6%8A%A5" \
  -H "Authorization: Bearer your-access-key-here"
```

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.items` | array\<object\> | 当前页的任务列表，元素结构见[自动化任务对象](#自动化任务对象) |
| `data.total` | integer | 过滤后的任务总数 |
| `data.page` | integer | 当前页码 |
| `data.page_size` | integer | 每页条数 |

### 响应示例

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
        "title": "每日晨报",
        "instruction": "汇总昨天的销售数据并生成简报",
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

### 错误情况

| HTTP | `code` | 场景 |
|------|--------|------|
| `422` | — | `page` / `page_size` 越界，或 `search` / `agent_name` 超 200 字符（FastAPI 原生 `detail` 数组） |
| `401` | — | 未携带或无效 API Key |

> 当传入 `status=ENABLED`、`status=RUNNING` 或 `agent_name` 时，服务端会先取出该用户全部匹配任务、在内存中过滤后再分页。任务数量很大（数千级）时这类查询会明显慢于普通分页。

### 自动化任务对象

`items` 中的每个元素包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | integer | 任务 ID，用于查询详情 |
| `conversation_id` | integer | 任务绑定的对话 ID |
| `agent_id` | integer | 绑定的 Agent ID |
| `agent_version_no` | integer \| null | 创建任务时锁定的 Agent 版本号 |
| `agent_name` | string | Agent 显示名称（解析失败时回退为 `Agent #<agent_id>`） |
| `title` | string | 任务标题 |
| `instruction` | string | 每次运行时下发给 Agent 的指令 |
| `status` | string | 任务生命周期状态：`DRAFT` / `ACTIVE` / `PAUSED` / `PAUSED_BY_SYSTEM` / `COMPLETED` |
| `is_running` | boolean | 当前是否有正在执行的运行 |
| `source` | string | 创建来源，目前只有 `CHAT_INTENT`（由对话中的用户意图创建） |
| `schedule_mode` | string | `ONCE`（单次）或 `RECURRING`（周期） |
| `schedule_rule_type` | string | `AT`（指定时刻）/ `INTERVAL`（固定间隔）/ `CRON` |
| `schedule_expr` | string \| null | 人类可读的调度表达式（如 cron 表达式） |
| `schedule_config` | object | 归一化后的调度配置，结构见下 |
| `timezone` | string | IANA 时区，默认 `Asia/Shanghai` |
| `next_fire_at` | string \| null | 下次触发时间（ISO 8601，UTC） |
| `last_fire_at` | string \| null | 上次触发时间 |
| `fire_count` | integer | 累计触发次数 |
| `last_run_status` | string \| null | 最近一次运行的状态，取值同自动化运行状态：`QUEUED` / `RUNNING` / `SUCCEEDED` / `FAILED` / `SKIPPED` / `CANCELED` / `TIMEOUT` |
| `last_error` | string \| null | 最近一次运行的错误信息 |
| `consecutive_failures` | integer | 连续失败次数 |
| `timeout_seconds` | integer | 单次运行的超时时间（秒） |
| `overlap_policy` | string | 上一次尚未结束又到触发点时的策略，当前实现固定为 `SKIP`（跳过本次触发） |
| `misfire_policy` | string | 错过触发点后的补偿策略：周期任务为 `SKIP`（跳过），单次任务为 `RUN_ONCE`（立即补跑一次） |
| `capability_requirements` | object \| null | 从用户意图解析出的能力需求 |
| `capability_bindings` | object \| null | 确认匹配到的能力绑定 |
| `runtime_snapshot` | object \| null | 创建任务时的 Agent / 运行时能力快照 |
| `create_time` | string | 创建时间（ISO 8601，UTC） |
| `update_time` | string | 更新时间 |

`schedule_config` 结构：

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

> 任务对象同时会携带 `tenant_id`、`user_id`、`created_by`、`updated_by`、`delete_flag`、`lock_owner`、`lock_until` 等审计与调度内部字段，均为只读，调用方不应依赖。

## 🆕 获取自动化任务详情

按 ID 获取当前用户名下的一个自动化任务，返回的字段与列表接口中的任务对象完全一致。

```http
GET /nb/v1/automations/{task_id}
```

### 路径参数

| 参数 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| `task_id` | integer | 是 | ≥ 1 | 任务 ID |

### 请求示例

```bash
curl "https://your-nexent-domain.com/nb/v1/automations/5" \
  -H "Authorization: Bearer your-access-key-here"
```

### 响应示例

```json
{
  "message": "success",
  "data": {
    "task_id": 5,
    "conversation_id": 123,
    "agent_id": 7,
    "agent_version_no": 3,
    "agent_name": "daily-report",
    "title": "每日晨报",
    "instruction": "汇总昨天的销售数据并生成简报",
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

### 错误情况

| HTTP | `code` | 场景 |
|------|--------|------|
| `404` | `AUTOMATION_TASK_NOT_FOUND` | 任务不存在、已删除，或不属于当前用户 |
| `422` | — | `task_id` 不是 ≥ 1 的整数（如传了 `abc` 或 `0`） |
| `401` | — | 未携带或无效 API Key |

## 🆕 下载文件

下载当前用户有权访问的文件，例如对话附件、知识库源文件或 Agent 生成的产物。支持两种模式：

- **`ignore`（默认）**：不传文件内容，返回一个**预签名 URL**，由客户端直接向对象存储拉取。适合把文件交给浏览器或第三方系统下载。
- **`stream`**：服务端直接返回**字节流**。适合服务端之间传输，或者对象存储不对外暴露的场景。

```http
GET /nb/v1/file/download/{object_name}
```

### 路径参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `object_name` | string | 是 | 对象存储中的对象名，**支持多级路径**，如 `attachments/user123/20261127_report.pdf` |

`object_name` 直接拼接在路径中，**不要**对 `/` 做 URL 编码；对象名含空格或中文等非 ASCII 字符时，需对每一段分别做 URL 编码。

### 查询参数

| 参数 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| `download` | string | 否 | 仅 `ignore` 或 `stream`，默认 `ignore` | 下载模式 |
| `expires` | integer | 否 | 1 ~ 604800，默认 `86400` | 预签名 URL 有效期（秒），最长 7 天。**仅 `ignore` 模式生效** |
| `filename` | string | 否 | — | 下载时使用的文件名。**仅 `stream` 模式生效**，不传则取对象名最后一段 |

> `redirect` 与 `base64` 两种模式**不对北向开放**：`redirect` 会暴露内部对象存储地址，`base64` 会把整个文件内联进响应。传入会返回 `422`。

### 访问权限

权限按对象名前缀分 category 判定，**跨租户一律拒绝**：

| 对象名前缀 | 规则 |
|------------|------|
| `knowledge_base/...` | 对象必须能解析到**当前租户**的有效知识库台账记录 |
| `attachments/{user_id}/...` | 仅 `user_id` 为当前 API Key 所属用户时可访问 |
| `attachments/<无子目录>` | 旧版裸附件 key，无归属信息，**一律拒绝** |
| `images_in_attachments/...` | 旧版共享渲染图，无归属信息，**一律拒绝** |
| `skill-files/{user_id}/...` | 仅 `user_id` 为当前用户时可访问 |
| `workspace/{user_id}/{run_id}/outputs/...` | 仅 `user_id` 为当前用户时可访问 |

无权访问返回 `403`、对象不存在返回 `404`。注意这**会**暴露「该对象是否存在」：对于调用方有权访问的前缀（如自己的 `attachments/{user_id}/`），`404` 即代表对象确实不存在；对于无权访问的前缀，无论对象是否存在一律 `403`。

### 请求示例

```bash
# 模式一：获取预签名 URL（有效期 1 小时）
curl "https://your-nexent-domain.com/nb/v1/file/download/attachments/user123/20261127_report.pdf?expires=3600" \
  -H "Authorization: Bearer your-access-key-here"

# 模式二：直接拉取字节流并保存
curl -o report.pdf \
  "https://your-nexent-domain.com/nb/v1/file/download/attachments/user123/20261127_report.pdf?download=stream" \
  -H "Authorization: Bearer your-access-key-here"

# 指定下载文件名
curl -o report.pdf \
  "https://your-nexent-domain.com/nb/v1/file/download/attachments/user123/20261127_report.pdf?download=stream&filename=Q3%E9%94%80%E5%94%AE%E6%8A%A5%E5%91%8A.pdf" \
  -H "Authorization: Bearer your-access-key-here"

# 知识库文件（多级路径）
curl "https://your-nexent-domain.com/nb/v1/file/download/knowledge_base/42/abc123/source.pdf?download=stream" \
  -H "Authorization: Bearer your-access-key-here"
```

### 响应参数

**`ignore` 模式**，返回标准信封：

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.success` | boolean | 固定为 `true`（失败时走错误响应，不会出现 `success: false`） |
| `data.object_name` | string | 回显的对象名 |
| `data.expires_in` | integer | 预签名 URL 有效期（秒） |
| `data.url` | string | 预签名下载 URL，签名地址基于**外部访问端点**生成，可直接交给客户端 |

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

**`stream` 模式**，直接返回字节流，**不套信封**：

| 响应头 | 说明 |
|--------|------|
| `Content-Type` | 按对象名后缀推断的 MIME 类型 |
| `Content-Disposition` | `attachment; filename="..."`，非 ASCII 文件名带 RFC 5987 编码 |
| `Cache-Control` | 固定 `private, no-store`，字节流不会被任何共享缓存保存 |
| `ETag` | 由对象名生成的引号包裹串 |

### 错误情况

| HTTP | `code` | 场景 |
|------|--------|------|
| `403` | `FORBIDDEN` | 对象不属于当前用户 / 不属于当前租户 / 属于不开放的前缀 |
| `404` | `NOT_FOUND` | 对象在存储中不存在（两种模式都会先探测存在性） |
| `422` | — | `download` 不是 `ignore` / `stream`，或 `expires` 超出 1 ~ 604800（FastAPI 原生 `detail` 数组） |
| `401` | — | 未携带或无效 API Key |

> `ignore` 模式返回的预签名 URL 在有效期内**任何人**凭 URL 都能下载，请像保管密码一样保管，不要写入日志或前端可见的位置。

## 📊 监控面板接口

北向监控面复用平台监控面板（Ops 仪表盘）的 24 个数据接口，路径前缀为
`/nb/v1/monitoring`。调用方只能读取**自己 API Key 所属租户**的监控数据：
传入 `tenant_id` 且与所属租户不匹配时返回 `403`。

### 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/nb/v1/monitoring/models` | GET | 模型监控列表（分页、搜索、排序） |
| `/nb/v1/monitoring/models/summary` | GET | 模型监控汇总 |
| `/nb/v1/monitoring/models/rankings` | GET | 模型调用量 Top 5 |
| `/nb/v1/monitoring/models/trends` | GET | 模型用量趋势 |
| `/nb/v1/monitoring/models/refresh` | POST | 提交模型监控重算等待令牌（202） |
| `/nb/v1/monitoring/models/refreshes/{refresh_id}` | GET | 查询源版本发布进度 |
| `/nb/v1/monitoring/skills` | GET | 技能监控列表 |
| `/nb/v1/monitoring/skills/summary` | GET | 技能监控汇总 |
| `/nb/v1/monitoring/skills/rankings` | GET | 技能用量 Top 5 |
| `/nb/v1/monitoring/skills/trends` | GET | 技能用量趋势 |
| `/nb/v1/monitoring/skills/refresh` | POST | 提交技能监控重算等待令牌（202） |
| `/nb/v1/monitoring/skills/refreshes/{refresh_id}` | GET | 查询源版本发布进度 |
| `/nb/v1/monitoring/agents` | GET | Agent 监控列表 |
| `/nb/v1/monitoring/agents/summary` | GET | Agent 监控汇总（含 Token 用量） |
| `/nb/v1/monitoring/agents/trends` | GET | Agent 执行趋势 |
| `/nb/v1/monitoring/agents/rankings` | GET | Agent 执行量 Top 5 |
| `/nb/v1/monitoring/mcp-tools` | GET | MCP 工具监控列表（支持 tools/services 维度） |
| `/nb/v1/monitoring/mcp-tools/summary` | GET | MCP 监控汇总 |
| `/nb/v1/monitoring/mcp-tools/rankings` | GET | MCP 调用量 Top 5 |
| `/nb/v1/monitoring/mcp-tools/trends` | GET | MCP 调用趋势 |
| `/nb/v1/monitoring/mcp-tools/catalog` | GET | MCP 服务目录（筛选项数据） |
| `/nb/v1/monitoring/mcp-tools/overview` | GET | 平台总览（按租户的服务清单与调用趋势） |
| `/nb/v1/monitoring/mcp-tools/refresh` | POST | 提交 MCP 监控重算等待令牌（202） |
| `/nb/v1/monitoring/mcp-tools/refreshes/{refresh_id}` | GET | 查询源版本发布进度 |

### 通用查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `start_date` / `end_date` | date | 是 | 统计区间（跨度须小于 366 天） |
| `group_ids` | int[] | 否 | 用户组过滤（最多 100 个） |
| `model_id` / `model_type` / `agent_id` / `skill_id` / `skill_name` / `server_id` / `server_type` / `tool_name` | — | 否 | 各维度专用过滤 |
| `page` / `page_size` / `search` / `sort_by` / `descending` | — | 否 | 列表分页与排序（`page_size` ≤ 100） |

### 响应格式

成功响应为统一信封，`data` 内携带监控面板原生响应体（含 `data` 结果字段与
`data_as_of` / `coverage_state` / `is_stale` 数据覆盖状态字段）：

```json
{
  "message": "success",
  "requestId": "req-uuid-here",
  "data": {
    "data": { "..." : "面板原生结果" },
    "data_as_of": "2026-11-27T00:00:00Z",
    "coverage_state": "covered",
    "is_stale": false
  }
}
```

### 重算等待令牌的语义

`POST .../refresh` **不创建重算任务**：它读取所选区间当前的源数据版本
（`source_revision`）并签发一个轮询令牌。调用方随后用
`GET .../refreshes/{refresh_id}` 轮询，直到该源版本被发布为可查询的统计结果
（“读己之写”语义）。若签发时源版本已发布，首次轮询即返回 `completed`；
若区间无已确认的源数据，POST 返回 `409 MONITORING_DATES_UNCOVERED`
（含 `missing_dates`）。等待期间状态为 `running`，超时判定为 `timed_out`。

错误响应为三段式结构 `{code, message, status, requestId}`，常见错误：
`403 HTTP_403`（租户越界）、`404 HTTP_404`（令牌不存在或不属于本租户）、
`409 MONITORING_DATES_UNCOVERED`（重算区间无数据源）、`422 HTTP_422`（参数校验失败）、
`429 RATE_LIMIT_EXCEEDED`（重算动作超过每租户限流，默认 120 次/分钟）、
`503 HTTP_503`（监控服务暂不可用）。

### 示例

```bash
curl -X GET "https://your-nexent-domain.com/nb/v1/monitoring/models/summary?start_date=2026-11-20&end_date=2026-11-27" \
  -H "Authorization: Bearer your-access-key-here"

curl -X POST "https://your-nexent-domain.com/nb/v1/monitoring/models/refresh" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-11-20", "end_date": "2026-11-27"}'
```

## ⚠️ 错误码说明

业务错误统一使用三字段信封 `{code, message, status, requestId}`。`code` 为稳定字符串，客户端应优先按 `code` 分支，HTTP 状态码仅作兜底。

| HTTP 状态码 | `code` | 说明 |
|-------------|--------|------|
| `400 Bad Request` | `VALIDATION_ERROR` | 业务参数校验失败（如批量删除超过 100 个对话、未知工具参数） |
| `400 Bad Request` | `AUTOMATION_ERROR` | 自动化任务操作失败 |
| `401 Unauthorized` | — | 认证失败或缺少 API Key（网关返回 `{"message": "Invalid or missing credentials"}`） |
| `403 Forbidden` | `FORBIDDEN` | 无权限访问该对话、任务或文件 |
| `404 Not Found` | `NOT_FOUND` | 对话 / 文件不存在，或不属于当前用户 |
| `404 Not Found` | `AUTOMATION_TASK_NOT_FOUND` | 自动化任务不存在，或不属于当前用户 |
| `404 Not Found` | — | 路径未开放或不存在（网关返回 `{"detail": "Not found"}`） |
| `409 Conflict` | `CHAT_METADATA_VERSION_CONFLICT` | 运行时元数据版本冲突 |
| `422 Unprocessable Entity` | — | 框架层参数校验失败：类型不符、超出取值范围、枚举外取值。响应体为 FastAPI 原生 `{"detail": [...]}` |
| `429 Too Many Requests` | `RATE_LIMIT_EXCEEDED` | 请求频率超限 |
| `429 Too Many Requests` | `TENANT_RESOURCE_EXCEEDED` | 租户资源配额超限 |
| `500 Internal Server Error` | `INTERNAL_ERROR` | 服务器内部错误，响应体不含内部细节 |
| `502 Bad Gateway` | — | 上游服务不可用 |
| `504 Gateway Timeout` | — | 上游服务超时 |

> 客户端建议按以下顺序判断：① HTTP 状态码是否为 `2xx`；② 响应体是否含 `code` 字段（业务错误）；③ 响应体是否含 `detail` 字段（参数校验错误）；④ 其余按网关错误处理。排查问题时把 `requestId` 一并提供给运维。

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

对话历史默认长期保留，除非用户主动删除或租户配置了过期策略。调用方可以通过 `DELETE /nb/v1/conversations/{conversation_id}` 或 `POST /nb/v1/conversations/batch-delete` 主动清理不再需要的对话，参见[删除对话](#🆕-删除对话)。

## 🔗 相关资源

- [API 总览](./overview) — 北向 API 完整能力地图
- [Agent 智能体导出与发布](./agents-export) — Agent 配置导出与发布
- [A2A 协议端点](./overview) — Agent-to-Agent 通信标准
