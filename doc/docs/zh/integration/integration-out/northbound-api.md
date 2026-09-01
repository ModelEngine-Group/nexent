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
data: {"type":"text","content":"正在分析数据"}

data: {"type":"text","content":"，请稍候..."}

data: {"type":"done","conversation_id":123,"content":"分析完成"}
```

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