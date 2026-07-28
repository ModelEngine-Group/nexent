# NL2Agent 临时智能体设计方案

## 1. 当前流程

NL2Agent 内嵌在 `/agents` 创建页。打开生成助手时进入创建模式，并启动仅属于当前页面的助手 runtime。

完整流程如下：

1. 通过普通对话澄清智能体需求。
2. 搜索当前租户已安装且可用的 MCP 工具。
3. 渲染可选择的工具推荐卡。
4. 用户确认工具后，通过 `updateTools()` 写入当前可编辑智能体。
5. 将同一份已确认工具元数据作为下一轮 query 发送给 NL2Agent。
6. 生成并渲染智能体 Draft 卡。
7. 用户确认 Draft 后，通过 `updateAgentConfig()` 写入非工具字段。
8. 通过现有智能体配置保存流程完成保存。

NL2Agent runtime 及其对话保持临时状态；可编辑智能体状态由现有智能体配置 store 管理。

## 2. 运行接口

前端通过现有流式 adapter 的 NL2Agent runtime 模式调用：

```http
POST /agent/nl2agent/run
```

```json
{
  "query": "用户当前输入",
  "history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "minio_files": []
}
```

确认推荐卡时，adapter 将 `metadata.custom.nl2agentToolSelection` 序列化为当前 query：

```json
{
  "type": "nl2agent_tool_selection",
  "tools": [
    {
      "tool_id": 10,
      "name": "weather_forecast",
      "origin_name": "weather",
      "description": "获取天气预报",
      "source": "mcp",
      "usage": "weather-server",
      "labels": ["weather"],
      "inputs": "{\"city\":\"string\"}"
    }
  ]
}
```

用户可见消息仍是本地化的选择摘要。请求不携带持久化的智能体 ID 或会话 ID。

## 3. 临时智能体与 MCP 搜索

每次请求都使用当前租户默认模型，在内存中构建名为 `__nl2agent_runtime__` 的 `AgentConfig`，并且只绑定内部 Local MCP 工具 `search_installed_mcp_tools`。

搜索工具负责：

- 从经过鉴权的 MCP 请求中解析租户。
- 只搜索已安装且可用的 MCP 工具。
- 接收 1 到 10 个规范化能力关键词。
- 最多返回五个确定性排序结果。
- 只暴露安全展示元数据和原始 `inputs` schema。

Local MCP 工具只负责搜索目录。智能体草稿的编辑由前端配置 store 完成。

## 4. NL2A 结构化 Payload

继续复用现有 `<nl2a>...</nl2a>` 提取逻辑和 `nl2a` SSE type。wrapper 内 JSON 使用 subtype 判别联合。

工具推荐成功：

```json
{
  "subtype": "local_mcp_recommendation",
  "status": "success",
  "recommendation_count": 1,
  "recommendations": []
}
```

工具推荐失败：

```json
{
  "subtype": "local_mcp_recommendation",
  "status": "error",
  "code": "tool_search_failed",
  "retryable": true
}
```

智能体 Draft：

```json
{
  "subtype": "agent_draft",
  "name": "weather_assistant",
  "display_name": "天气助手",
  "description": "查询天气并提供出行建议",
  "duty_prompt": "...",
  "constraint_prompt": "...",
  "few_shots_prompt": null
}
```

`GeneratedAgentDraft` 只包含 `updateAgentConfig()` 接受的字段，不重复携带已选择工具。

## 5. 前端状态写入

### 5.1 工具确认

推荐卡默认选择所有返回工具，并支持全选、部分选择和零工具确认。

确认时依次执行：

1. 按卡片展示顺序筛选已选择推荐。
2. 映射为 `Tool[]`，其中 `id = String(tool_id)`，`initParams = []`。
3. 使用该集合调用 `updateTools()`。
4. 将同一选择集合保存到消息 metadata 并启动下一轮请求。
5. 将当前推荐卡设为只读。

当前推荐卡中已确认的选择是本次工具更新的唯一来源。

### 5.2 Draft 确认

Draft 卡只展示生成完成状态、智能体名称和简短介绍，不展示完整提示词。

确认时调用 `updateAgentConfig()` 写入：

- `name`
- `display_name`
- `description`
- `duty_prompt`
- `constraint_prompt`
- `few_shots_prompt`

`few_shots_prompt` 为 null 时转换为空字符串。之前确认的工具集合保持不变。

## 6. assistant-ui 映射

流式 adapter 将 `nl2a` SSE 内容解析到 `message.metadata.custom.nl2a`。`AssistantMessage` 在消息分组内容之后按 subtype 渲染：

- `local_mcp_recommendation` 使用 `ToolRecommendations`。
- `agent_draft` 使用 `AgentDraftCard`。

原始 MCP `execution_logs` 继续关联到对应工具调用。

## 7. 验证

后端测试覆盖中英文提示词契约、两个 subtype 以及精简后的 `GeneratedAgentDraft` schema。

前端验证覆盖：

- 全选、部分选择和零工具确认会更新 `editedAgent.tools`。
- 发送给 NL2Agent 的选择 metadata 与写入 store 的工具来自同一集合。
- Draft 确认只更新非工具配置字段。
- 现有智能体保存行为能够保存完整的可编辑配置。
