# 工具用户信息透传 — 设计文档

> 分支：`edward/feature-tool-user-context`（worktree：`C:\Users\Edward\work\nexent-tool-user-context`）
> 基线：`origin/develop`（8f20f87cf，v2.5.0+）

## 1. 需求

智能体调用 MCP 工具和 Agent（子智能体 / 外部 A2A）时，**根据工具要求**传入调用者的用户信息：

| 字段 | 含义 |
|------|------|
| 租户名（tenant_name） | 租户显示名，如 `bug-repro` |
| 用户名（user_name） | 用户显示名（当前系统中即邮箱） |
| 用户账号（user_account） | 用户邮箱，如 `bug-admin@qq.com` |
| 用户组（user_groups） | 用户所属组名列表，如 `["Default Group"]` |

工具用这些信息在**访问数据前自行鉴权**。

**边界**：平台本身不做鉴权、不校验工具侧权限，只负责把**经过平台认证的会话身份**如实透传给工具。

## 2. 现状调研结论

### 2.1 用户信息的数据来源（已全部确认）

| 字段 | 存储位置 | 获取方式 |
|------|----------|----------|
| tenant_id | 会话上下文（JWT / access_key 解析） | 执行入口已有 |
| tenant_name | `tenant_config_t`（`config_key='TENANT_NAME'`） | `get_single_config_info(tenant_id, TENANT_NAME)`，缺失时回退 `tenant_id` |
| user_id | 会话上下文 | 执行入口已有 |
| user_name / user_account | `user_tenant_t.user_email` | `get_user_tenant_by_user_id(user_id)` |
| user_groups | `tenant_group_info_t` join `tenant_group_user_t` | `query_groups_by_user(user_id)` -> `group_name` 列表 |

### 2.2 运行时工具调用链路

```
run_agent_stream(user_id, tenant_id)                     [backend agent_service]
  -> prepare_agent_run -> create_agent_run_info          [backend create_agent_info]
  -> AgentRunInfo -> agent_run_thread                    [sdk run_agent]
  -> NexentAgent(user_id, tenant_id)                     [sdk nexent_agent]
      |-- MCP 工具: create_tool -> create_mcp_tool（smolagents MCPClientTool）
      |      -> 模型生成代码 -> MCPClientTool.forward(**kwargs) -> session.call_tool(name, kwargs)
      |-- 内部子 Agent: SubAgentToolWrapper.__call__(task=...)
      +-- 外部 A2A: ExternalA2AAgentWrapper.__call__(task=...)
             -> _build_message_payload(query, context) -> payload["metadata"]
```

关键事实：

1. **`NexentAgent.create_mcp_tool`（`sdk/nexent/core/agents/nexent_agent.py` L487-496）是 MCP 工具的唯一收口点**，当前不注入任何用户上下文（对比：本地工具已有注入 `tenant_id/user_id` 的先例）。
2. `user_id/tenant_id` 已逐层传到 `NexentAgent`（L253-254），**取用户身份不难，难的是取全四个字段并送到工具执行处**。
3. 外部 A2A 已有 `metadata` 透传通道（`runtime_metadata` -> `payload["metadata"]`）。
4. 内部子 Agent 与父 Agent 使用相同的 `user_id/tenant_id` 递归创建（`create_agent_config` L981-1007），上下文天然一致。

## 3. 总体设计

### 3.1 架构：构建 -> 传递 -> 注入

```
[构建]  create_agent_run_info（执行入口，每个请求重建）
        查询 4 字段 -> ToolUserContext
              |
[传递]  AgentRunInfo.user_context -> NexentAgent.user_context
              |
[注入]  |-- MCP 工具：create_mcp_tool 包装层（约定参数名注入，对模型隐藏）
        |-- 外部 A2A：ExternalA2AAgentWrapper 独立注入 message.metadata["user_context"]
        +-- 内部子 Agent：同一 NexentAgent 实例递归创建，工具注入链路天然一致
```

### 3.2 用户上下文数据结构

```python
class ToolUserContext(BaseModel):
    """透传给工具的用户信息。平台不鉴权，工具在访问数据前自行鉴权。"""
    tenant_id: str
    tenant_name: str          # TENANT_NAME 配置，缺失回退 tenant_id
    user_id: str
    user_name: str            # = user_email
    user_account: str         # = user_email
    user_groups: list[str]    # 组名列表，如 ["Default Group"]
```

构建位置：`backend/agents/create_agent_info.py` 的 `create_agent_run_info`（此处 user_id/tenant_id 已就位）。

**条件构建（性能）**：仅当智能体树包含 MCP 工具（任意层级 `source == "mcp"`）或外部 A2A Agent 时才执行构建（`_agent_tree_needs_user_context` 递归判断）；纯本地/内置工具的对话**零额外 DB 查询**，高并发场景避免每请求 3 次无谓查询。

**防御性降级**：`_resolve_tool_user_context` 整体捕获异常返回 `None`；单个字段查询失败降级为最小上下文——**任何情况下都不阻断对话**。

### 3.3 注入通道一：MCP 工具（约定参数名，对模型隐藏）

**核心原则：用户信息完全不进入模型视野——平台在模型传输外面包一层注入。** 模型不知道这些参数存在、不会为其生成值，也就无从伪造。

**两份 schema**：
- **模型可见 schema**：构建智能体工具列表时，从工具 `inputs` 中移除约定字段——模型看到的提示词/工具说明不含这些参数（不占 token、不引起困惑、无法填充）；
- **实际调用 schema**：MCP 服务端的 `inputSchema` 保持不变（它即工具的"要求声明"），真正执行时由包装层把约定字段值补进参数。

**声明方式**：工具的 MCP 服务端 `inputSchema` 中定义了**约定字段名**，即视为"该工具要求此用户信息"：

| 约定参数名 | 注入值 |
|-----------|--------|
| `tenant_id` | tenant_id |
| `tenant_name` | 租户显示名 |
| `user_id` | user_id |
| `user_name` | user_email |
| `user_account` | user_email |
| `user_groups` | 组名列表（JSON 数组） |

**注入点**：`NexentAgent.create_mcp_tool` 返回的工具对象包一层代理（属性转发可参考 `SubAgentToolWrapper` 的先例）：

```python
# 1) 构建工具列表时：从模型可见 schema 移除约定字段
tool.inputs = {k: v for k, v in tool.inputs.items() if k not in USER_CONTEXT_FIELDS}

# 2) 工具执行时：模型只生成业务参数，包装层在转发前补入约定值
def __call__(self, **model_kwargs):
    # model_kwargs 不含约定字段（模型不可见），原参数校验照常通过
    injected = dict(model_kwargs)
    for field in USER_CONTEXT_FIELDS:
        if field in real_schema:               # 工具真实 schema 声明了才注入
            injected[field] = user_context[field]
    return inner_forward(**injected)           # 绕过二次校验，直达执行
```

> 实现注记：smolagents 的 `Tool.__call__` 会按 `self.inputs` 校验参数，包装层在校验通过后注入、再调 `forward`，避开二次校验；具体以 smolagents 1.23 的实际结构适配。

**安全特性**：
- 模型**看不到**约定参数 → 不会填 → 伪造路径被彻底消除（比"事后强制覆盖"更彻底）；
- 约定字段的值只来自认证过的会话上下文，工具侧鉴权可以信任。

**为什么用参数而不是 Header**：工具声明参数即可，无需改 MCP 传输层；"没声明 = 不要求 = 不注入"天然满足"根据工具要求"。

**沙箱兼容**：Docker 沙箱模式下 host 工具经 `_ToolBridge` 回调（`sandbox.py` L403-436），包装层在工具对象上，两条路径都生效。

### 3.4 注入通道二：外部 A2A Agent

`ExternalA2AAgentWrapper.__call__` 调用时将 `user_context` 并入 `context`（最终进入 `payload["metadata"]["user_context"]`）。外部 agent 从 metadata 读取，按需鉴权。不占用消息正文。

### 3.5 注入通道三：内部子 Agent

- 子 Agent 由 `create_agent_config` 递归创建，整个智能体树共享同一个 `NexentAgent` 实例（`self.user_context` 一致），其自身的工具注入链路与父一致，无需额外处理。
- **不合并进 `runtime_metadata`**（审计后移除）：外部 A2A 的注入已由 wrapper 独立完成，合并会造成双路径冗余与每请求额外拷贝；且当前没有从 `agent.state["metadata"]` 读取 `user_context` 的消费方，保持最小化。

### 3.6 不做的事（边界）

- 平台**不做**工具侧鉴权、不校验工具返回；
- 不改 smolagents 外部依赖（包装而非修改）；
- 不做自定义字段映射配置（如工具想叫 `operator_email`）——一期约定参数名覆盖，映射配置留作扩展点（`ToolConfig.params` 可承载）；
- 不含 northbound 等 API 层改动（透传只发生在工具调用链）。

## 4. 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `sdk/nexent/core/agents/agent_model.py` | `AgentRunInfo` 增加 `user_context: Optional[dict]` 字段 |
| 2 | `backend/agents/create_agent_info.py` | `create_agent_run_info` 中构建 `ToolUserContext`（查 TENANT_NAME / user_email / groups），放入 `AgentRunInfo` |
| 3 | `backend/database/` | 复用已有查询（`get_single_config_info` / `get_user_tenant_by_user_id` / `query_groups_by_user`），如缺少按 user_id 查 email 的聚合函数则补一个 |
| 4 | `sdk/nexent/core/agents/nexent_agent.py` | `NexentAgent` 接收 `user_context`；`create_mcp_tool` 返回包装对象（约定参数注入 + 强制覆盖） |
| 5 | `sdk/nexent/core/agents/a2a_agent_proxy.py` | `ExternalA2AAgentWrapper.__call__` 把 `user_context` 并入 context -> metadata |
| 7 | `sdk/nexent/core/agents/run_agent.py` | `agent_run_thread` 把 `AgentRunInfo.user_context` 传入 `NexentAgent` |
| 8 | 单元测试 | 注入逻辑（声明/未声明/覆盖模型值）、降级路径、A2A metadata |

## 5. 测试方案

1. **单测**：
   - 工具声明 `user_account` 参数 -> 注入发生且值 = 会话邮箱；
   - 工具未声明约定字段 -> 不注入、不污染参数；
   - 模型看不到约定字段（可见 schema 已移除，不生成），包装层在执行时补值；
   - tenant_name 配置缺失 -> 回退 tenant_id；查询异常 -> 最小上下文降级。
2. **集成验证**（本地环境）：
   - 本地 MCP 工具（`mcp_server.py`）定义 `user_account/tenant_name/user_groups` 参数，对话触发调用，断言收到的值与当前登录用户一致；
   - A2A：观察外发请求 `metadata.user_context` 内容。

## 6. 待确认项

1. 约定参数名集合是否就用上表 6 个？（可增删）
2. 是否需要租户级开关（默认全开 / 可关闭透传）？一期建议**默认开启、无开关**，保持简单。
