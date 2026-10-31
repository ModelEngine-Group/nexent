# Agent 发布

Nexent 支持将 Agent 智能体发布为外部可调用的服务，发布后可以通过标准化的方式与外部业务系统集成。本文档介绍两种发布方式：

| 发布方式 | 说明 | 适用场景 |
|----------|------|----------|
| **普通发布** | 发布后通过北向 RESTful API 调用 Agent | 与业务系统深度集成，实现工作流自动化 |
| **A2A 发布** | 发布为符合 A2A 1.0 规范的 Agent | 跨平台 Agent 协作、支持 A2A 协议的外部系统调用 |

## 🚀 方式一：普通发布（北向 RESTful API）

普通发布是指将 Agent 发布到平台后，外部业务系统通过 Nexent 提供的北向 RESTful API 与 Agent 通信，支持流式响应、附件上传、会话管理等能力。

### 发布步骤

1. 进入 **智能体开发** 页面，创建或编辑 Agent
2. 完成 Agent 配置并保存
3. 点击「发布」按钮
4. 在发布选项中确认默认发布（不勾选 A2A）
5. 确认发布，生成 API Key 后即可调用

### 获取 API Key

发布成功后，需要为调用方生成 API Key：

1. 登录 Nexent 平台
2. 进入「个人信息」页面
3. 点击「生成 API 密钥」
4. 复制生成的 Access Key

### 调用示例

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/chat/run" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "general-assistant",
    "query": "你好，请介绍一下你自己"
  }'
```

### 接口能力概览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/nb/v1/chat/run` | POST | 启动对话（流式响应） |
| `/nb/v1/chat/stop/{conversation_id}` | GET | 停止对话 |
| `/nb/v1/chat/attachments/upload` | POST | 上传对话附件 |
| `/nb/v1/conversations` | GET | 列出对话 |
| `/nb/v1/conversations/{conversation_id}` | GET | 获取对话历史 |
| `/nb/v1/generate_title` | POST | 生成对话标题 |
| `/nb/v1/conversations/{conversation_id}/title` | PUT | 更新对话标题 |

> 完整的接口定义、请求/响应示例、错误码说明，请参阅 [调用 Agent 北向 API](./northbound-api)。

### 本地开发注意事项

| 部署方式 | 路径前缀 |
|----------|----------|
| Docker 部署 | 替换为 `http://localhost:5013/nb/v1` |
| Kubernetes 部署 | 替换为 `http://localhost:30013/nb/v1` |
| 生产环境 | 替换为实际服务器域名或公网 IP |

## 🌐 方式二：发布为 A2A Agent

将已发布的 Agent 进一步暴露为 A2A 服务，供外部系统通过 A2A 1.0 协议发现并调用。

### 发布步骤

1. 进入 **智能体开发** 页面，创建或编辑 Agent
2. 完成 Agent 配置并保存
3. 点击「发布」按钮
4. 在发布选项中勾选「发布为 A2A Agent」
5. 确认发布

### 获取调用信息

发布成功后，系统显示 A2A Agent 的调用信息：

| 信息项 | 说明 |
|--------|------|
| **Endpoint ID** | A2A Agent 的唯一标识符 |
| **Agent Card URL** | Agent 发现端点，外部系统通过此地址获取 Agent 描述 |
| **协议版本** | A2A 协议版本，当前为 1.0 |
| **REST 端点** | 基于 REST 风格的 API 端点 |
| **JSON-RPC 端点** | 基于 JSON-RPC 2.0 协议的调用端点 |

### 调用示例

#### REST API

```bash
# 获取 Agent Card
GET /nb/a2a/{endpoint_id}/.well-known/agent-card.json

# 发送同步消息
POST /nb/a2a/{endpoint_id}/message:send
Content-Type: application/json

{
  "message": {
    "role": "user",
    "content": "请帮我分析这份销售数据"
  }
}

# 发送流式消息（SSE）
POST /nb/a2a/{endpoint_id}/message:stream
Content-Type: application/json

{
  "message": {
    "role": "user",
    "content": "请帮我分析这份销售数据"
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
      "content": "请帮我分析这份销售数据"
    }
  },
  "id": 1
}
```

### 本地开发注意事项

- **Docker 部署**：路径前缀 `/nb/a2a` 替换为 `http://localhost:5013/nb/a2a`
- **Kubernetes 部署**：路径前缀 `/nb/a2a` 替换为 `http://localhost:30013/nb/a2a`
- **生产环境**：替换为实际服务器域名或公网 IP 地址

## 🔒 认证与安全

### 调用认证

两种发布方式的调用均需要在请求头中携带认证信息：

```http
Authorization: Bearer {access_key}
```

`access_key` 在平台的「个人信息」中通过「生成 API 密钥」获取。

### 安全建议

1. **保护 API Key**：不要在代码中硬编码，定期轮换
2. **限制访问**：仅授权可信系统访问调用端点
3. **监控日志**：启用调用日志记录，便于审计
4. **数据隔离**：注意不要将敏感数据发送给不受控的调用方

## 🏷️ 版本管理

### 发布版本

- Agent 可以发布多个版本，每次发布生成一个新版本
- 已发布的版本不可修改，确保调用方获得一致的体验

### 版本更新

1. 修改 Agent 配置
2. 发布新版本（按需选择发布方式）
3. 外部系统可通过新版 Agent Card 获取更新（A2A 场景）

### Agent Card 缓存

- Agent Card 信息会被缓存（A2A 场景）
- 刷新间隔为 1 小时
- 如需立即更新，需要重新发布 Agent

## ❓ 常见问题

### Q: 普通发布和 A2A 发布可以同时开启吗？

可以。在发布时既默认开放北向 RESTful API，又勾选「发布为 A2A Agent」，即可同时支持两种调用方式。

### Q: A2A 调用返回 401 错误

确认请求头中包含有效的 `Authorization` 字段，且 `access_key` 正确。

### Q: 如何更新已发布的 A2A Agent？

重新发布 Agent 版本，更新后的信息会通过刷新后的 Agent Card 暴露。

### Q: 北向 API 接口的详细参数在哪里？

请参阅 [调用 Agent 北向 API](./northbound-api) 获取完整的接口参数、请求/响应示例与错误码说明。

## 🔗 相关资源

- [发布为 A2A Agent](../../user-guide/agent-development/a2a-publish) — 发布和调用 A2A Agent 的完整操作指南
- [调用 Agent 北向 API](./northbound-api) — 北向 RESTful API 详细参考
- [智能体配置](../../user-guide/agent-development/agent-configuration) — Agent 配置详解
