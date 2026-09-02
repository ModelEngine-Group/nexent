# Agent 智能体接入

Nexent 支持通过 **A2A（Agent-to-Agent）协议**接入第三方 Agent，实现跨平台的多智能体协作。通过 A2A 协议，您可以发现并使用其他平台开发的 Agent，将其作为协作智能体纳入您的工作流程。

## 🤝 什么是 A2A 协议

A2A（Agent-to-Agent）是一个开放协议，旨在实现不同平台、不同技术栈的 AI Agent 之间的互操作。通过 A2A 协议：

- **标准化通信**：统一的 Agent 发现和调用机制
- **能力抽象**：Agent 可以声明自己的能力，无需了解对方实现细节
- **跨平台协作**：来自不同供应商的 Agent 可以无缝协作

### A2A 协议核心概念

| 概念 | 说明 |
|------|------|
| **Agent Card** | Agent 的元数据描述文件，包含名称、描述、端点、能力等信息 |
| **Task** | 任务实体，代表一次 Agent 调用 |
| **Message** | 消息，支持同步和流式两种模式 |
| **Skill** | Agent 提供的具体能力列表 |

## 🔍 发现外部 A2A Agent

Nexent 支持两种发现外部 A2A Agent 的方式：

| 发现方式 | 适用场景 | 前置条件 |
|----------|----------|----------|
| **URL 发现** | 已知 Agent Card 地址 | Agent Card URL 可访问 |
| **Nacos 发现** | 批量发现注册到 Nacos 的 Agent | Nacos 服务运行中 |

### 方式一：URL 发现

当您知道目标 Agent 的 Agent Card 地址时，可以使用 URL 发现方式。

#### Agent Card 示例

符合 A2A 1.0 规范的 Agent Card 如下：

```json
{
  "name": "data-analysis-agent",
  "description": "专业的数据分析助手，可以执行统计分析、生成图表、解读数据趋势",
  "url": "https://agent.example.com/nb/a2a/agent-123",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "statistical-analysis",
      "name": "统计分析",
      "description": "执行描述性统计和推断性统计"
    },
    {
      "id": "chart-generation",
      "name": "图表生成",
      "description": "根据数据生成各种类型的图表"
    }
  ],
  "endpoints": {
    "http": "https://agent.example.com/nb/a2a/agent-123"
  }
}
```

#### 操作步骤

1. 进入 **智能体开发** → **协作 Agent** 页面
2. 在「外部 A2A Agent」页签下，点击「添加外部 Agent」
3. 选择「URL 发现」页签
4. 填写 Agent Card URL，例如：`https://example.com/.well-known/agent.json`
5. 如需认证，填写自定义请求头（JSON 格式）：

```json
{"Authorization": "Bearer <token>"}
```

6. 点击「发现」按钮
7. 系统获取 Agent 信息后，展示 Agent 详情
8. 确认无误后点击「添加到列表」

#### 注意事项

- 自定义请求头仅用于获取和刷新 Agent Card，不会用于后续调用
- 再次发现同一 URL 时，留空会保留现有配置，填写 `{}` 可清空配置

### 📡 方式二：Nacos 发现

如果目标 Agent 注册在 Nacos 服务发现平台，可以使用 Nacos 发现方式批量接入。

#### 操作步骤

1. 进入 **智能体开发** → **协作 Agent** 页面
2. 在「外部 A2A Agent」页签下，点击「添加外部 Agent」
3. 选择「Nacos 发现」页签
4. 首次使用时，配置 Nacos 连接信息：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| **Nacos 服务器地址** | Nacos 服务地址 | `http://127.0.0.1:8848` |
| **命名空间 ID** | Nacos 命名空间（可选） | `dev` |
| **分组名** | 服务分组名（默认 DEFAULT_GROUP） | `DEFAULT_GROUP` |
| **用户名/密码** | Nacos 访问凭证（可选） | `nacos` / `nacos` |

5. 点击「保存配置」
6. 填写要扫描的 Agent 服务名称
7. 点击「扫描」，系统从 Nacos 获取匹配的 Agent 列表
8. 选择需要的 Agent，点击「添加」

#### 前提条件

- Nacos 服务正常运行
- 目标 Agent 已正确注册到 Nacos
- 服务元数据中包含 Agent Card 地址

## 🛠️ 管理外部 Agent

在外部 A2A Agent 列表中，您可以执行以下操作：

### 查看 Agent 详情

点击 Agent 卡片，可以查看完整信息：
- 名称、描述、版本
- URL 端点
- 支持的能力列表（Skills）
- 调用协议支持

### 测试 Agent

点击「测试」按钮，向 Agent 发送测试消息，验证其是否正常工作。

### 与 Agent 对话

点击「对话」按钮，打开对话窗口，与 Agent 进行实时交互测试。

### 配置调用协议

点击「协议配置」按钮，选择该 Agent 的调用协议：

| 协议 | 说明 | 适用场景 |
|------|------|----------|
| **HTTP + JSON** | REST API 风格调用 | 通用场景 |
| **JSON-RPC** | JSON-RPC 2.0 协议调用 | 标准化 RPC 调用 |

### 配置认证

如果 Agent Card 声明了 `securitySchemes`，点击「Agent 认证」填写认证信息。

支持的认证方式：
- Bearer Token
- API Key（Header/Query）
- Basic Auth

### 刷新 Agent 信息

Agent 信息变更后，点击「刷新」重新获取最新的 Agent Card。

### 移除 Agent

点击「移除」将 Agent 从已发现列表中删除。

## 👥 与外部 Agent 协作

发现并配置外部 Agent 后，可以将其设为当前智能体的协作智能体。

### 操作步骤

1. 在 **智能体开发** 页面，进入「协作 Agent」配置
2. 在「外部 A2A Agent」列表中，点击选择目标 Agent
3. Agent 会出现在「已选择的协作 Agent」列表中
4. 保存智能体配置

### 协作调用示例

当主智能体需要执行特定任务时，可以调用协作智能体：

```
用户：帮我分析这份销售数据，并生成周报

主智能体分析任务后，决定：
- 调用「数据分析 Agent」执行统计计算
- 调用「图表生成 Agent」生成可视化图表
- 综合结果生成最终周报
```

### 示例：接入 DataAgent A2A Agent

[DataAgent](https://gitcode.com/datagallery/dataagent) 是一个支持 A2A 协议的智能体平台，以下是接入步骤：

#### 1. 部署 DataAgent

参考 DataAgent 文档，以 A2A 服务模式启动：

> 注意：当前 Nexent 不支持带认证的 Agent，启动时请勿设置 auth-token

#### 2. 获取 Agent Card 地址

DataAgent 以 A2A 模式启动后，其 Agent Card 地址为：
```
http://<IP>:9999/.well-known/agent-card.json
```

#### 3. 在 Nexent 中添加

1. 选择「URL 发现」
2. 填写 URL：`http://<IP>:9999/.well-known/agent-card.json`
3. 点击「发现」
4. 添加成功后配置调用协议为 HTTP + JSON

#### 4. 测试和使用

添加成功后，可以测试 Agent 响应，确认正常后将其设为协作智能体使用。

## ❓ 常见问题

### Q: Agent 发现失败怎么办？

1. 确认 Agent Card URL 可访问
2. 检查网络连通性和防火墙配置
3. 验证 Agent 服务是否正常运行
4. 确认认证信息是否正确

### Q: 调用协议应该如何选择？

- **HTTP + JSON**：大多数场景首选，兼容性更好
- **JSON-RPC**：如 Agent 端明确要求 JSON-RPC 协议

### Q: 如何开发支持 A2A 的 Agent？

请参阅 [A2A 协议规范](https://github.com/model-context-protocol/specification)，或参考 Nexent 的实现方式。

## 🔗 相关资源

- [添加外部 A2A Agent](../../user-guide/agent-development/a2a-external) — 在协作 Agent 中添加外部 A2A Agent 的完整操作指南
- [A2A 协议规范](https://github.com/model-context-protocol/specification) — 官方协议文档
