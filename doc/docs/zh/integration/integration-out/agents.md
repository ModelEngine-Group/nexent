# Agent 智能体导出与发布

Nexent 提供多种 Agent 导出与发布方式，满足不同的使用场景：

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| **导出配置** | 将 Agent 配置导出为 JSON/ZIP 文件 | 迁移到其他 Nexent 部署、备份 |
| **导入配置** | 从 JSON/ZIP 文件导入 Agent | 复用现有配置、跨环境迁移 |
| **发布为 A2A Agent** | 将 Agent 暴露为 A2A 服务 | 供外部系统通过 A2A 协议调用 |

## 方式一：导出 Agent 配置

### 操作步骤

1. 进入 **Agent 仓库** → **我的 Agent** 页面
2. 找到需要导出的 Agent
3. 点击 Agent 右侧的「导出」按钮
4. 选择导出格式：
   - **JSON**：仅包含配置，无技能包
   - **ZIP**：包含配置和所有技能文件

5. 系统生成文件并自动下载

### 导出文件说明

#### JSON 格式

```json
{
  "name": "data-analyst",
  "version": "1.0.0",
  "model": "gpt-4",
  "prompt": {
    "role": "你是一个专业的数据分析助手...",
    "requirements": "...",
    "examples": "..."
  },
  "tools": [
    {
      "type": "knowledge_base",
      "name": "kb_search"
    },
    {
      "type": "mcp",
      "name": "github-tools"
    }
  ],
  "skills": [
    {
      "name": "csv-analyzer",
      "params": {"top_k": 5}
    }
  ],
  "collaborators": [
    "visualization-agent"
  ],
  "memory": {
    "type": "layered",
    "short_term": {...},
    "long_term": {...}
  }
}
```

#### ZIP 格式

包含 JSON 配置文件和所有技能包：

```
data-analyst.zip
├── agent.json           # Agent 配置
└── skills/
    ├── csv-analyzer/
    │   ├── SKILL.md
    │   └── scripts/
    │       └── analyze.py
    └── report-generator/
        ├── SKILL.md
        └── assets/
            └── template.md
```

### 使用场景

- **跨环境迁移**：从开发环境迁移到生产环境
- **备份恢复**：定期导出作为配置备份
- **批量分发**：将成熟的 Agent 分发给其他租户

## 方式二：导入 Agent 配置

### 操作步骤

1. 进入 **Agent 仓库** → **我的 Agent** 页面
2. 点击「导入」按钮
3. 在弹出的文件选择框中选择 JSON 或 ZIP 文件
4. 系统验证配置文件格式和内容
5. 展示导入的 Agent 预览信息
6. 确认后完成导入

### 依赖处理

导入时系统会检查 Agent 的依赖配置：

| 依赖类型 | 处理方式 |
|----------|----------|
| **模型** | 检查是否已开通，未开通需先配置 |
| **知识库** | 继承导入者权限，检索范围受限于导入者权限 |
| **MCP 服务** | 检查是否已配置，未配置需手动添加 |
| **Skill** | 自动导入技能包（如 ZIP 中包含） |
| **协作 Agent** | 检查是否已存在，需手动配置 |

### 注意事项

- **名称冲突**：如导入同名 Agent，系统会提示修改
- **知识库权限**：导入不会继承原作者的知识库权限
- **变量名唯一性**：检查并确保变量名不冲突

### 两种导入方式

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| **直接导入** | 保留重复名称，导入后需手动修改 | 快速导入，后续手动处理 |
| **重新生成** | 调用 LLM 重命名 Agent | 名称冲突较多，希望自动处理 |

## 方式三：发布为 A2A Agent

将已发布的 Agent 进一步暴露为 A2A 服务，供外部系统通过 A2A 协议调用。

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

## 认证与安全

### 调用认证

调用 A2A Agent 需要在请求头中携带认证信息：

```http
Authorization: Bearer {access_key}
```

`access_key` 在平台的「个人信息」中通过「生成 API 密钥」获取。

### 安全建议

1. **保护 API Key**：不要在代码中硬编码，定期轮换
2. **限制访问**：仅授权可信系统访问 A2A 端点
3. **监控日志**：启用调用日志记录，便于审计
4. **数据隔离**：注意不要将敏感数据发送给不受控的调用方

## 版本管理

### 发布版本

- Agent 可以发布多个版本，每次发布生成一个新版本
- 已发布的版本不可修改，确保调用方获得一致的体验

### 版本更新

1. 修改 Agent 配置
2. 发布新版本（如需对外暴露，勾选「发布为 A2A Agent」）
3. 外部系统可以通过新版 Agent Card 获取更新

### Agent Card 缓存

- Agent Card 信息会被缓存
- 刷新间隔为 1 小时
- 如需立即更新，需要重新发布 Agent

## 常见问题

### Q: 导出的 Agent 在新环境无法使用

1. 检查依赖配置是否完整
2. 确认模型、知识库等资源是否已开通
3. 验证 MCP 服务和 Skill 是否已正确配置

### Q: A2A 调用返回 401 错误

确认请求头中包含有效的 `Authorization` 字段，且 `access_key` 正确。

### Q: 如何更新已发布的 A2A Agent？

重新发布 Agent 版本，更新后的信息会通过刷新后的 Agent Card 暴露。

### Q: 导入时知识库检索结果与原作者不同

导入不会继承原作者的知识库权限，检索范围受限于导入者权限。这是设计如此，请确保导入者在目标环境有足够的知识库访问权限。

## 相关资源

- [Agent 接入](../integration-in/agents) — 通过 A2A 协议接入第三方 Agent
- [智能体配置](../user-guide/agent-development/agent-configuration) — Agent 配置详解
- [北向 API](./northbound-api) — 通过 RESTful API 集成
