# Nexent API 文档

## 🔗 访问 API 文档

后端接口文档已托管在 Apifox，请通过以下链接查看最新版本：

[Nexent API](https://8icfxll43r.apifox.cn)

## 北向开放 API（/nb/v1）

面向第三方系统的开放接口，使用 `Authorization: Bearer <access_key>`（API Key）鉴权，支持多副本部署（服务端口 5013）：

| 端点 | 说明 |
|------|------|
| `/nb/v1/chat/run` | 智能体对话（POST，支持流式；配套 `/nb/v1/chat/stop/{conversation_id}` 与 `/nb/v1/chat/attachments/upload`） |
| `/nb/v1/knowledge/*` | 知识库查询与管理 |
| `/nb/v1/models` | 模型列表查询 |
| `/nb/v1/generate_title` | 会话标题生成 |
| `/nb/v1/api-users/batch` | API 用户批量管理 |
| `/nb/a2a/{endpoint_id}/.well-known/agent-card.json` | A2A Agent Card 发现 |
| `/nb/a2a/{endpoint_id}/v1` | A2A JSON-RPC 2.0（SendMessage / SendStreamingMessage / GetTask） |

内部管理接口（A2A、MCP、技能、评测、自动化任务等）请参见上方 Apifox 文档。
