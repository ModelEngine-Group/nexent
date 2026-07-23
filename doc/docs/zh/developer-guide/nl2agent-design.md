# NL2AGENT v3 设计与切换手册

> 本文描述当前 NL2AGENT 实现。v2 Session、前端 Markdown fence 卡片解析、card delivery/registration API 和隐藏 continuation sentinel 均不再受支持。

## 1. 目标与边界

NL2AGENT 是嵌入 Agent 配置页的对话式 Builder。它负责需求确认、模型选择、本地 Tool/Skill 绑定、在线 MCP/Skill 安装、身份配置和 Draft Finalize。

核心约束：

- PostgreSQL 是 Session、workflow、目录和 installation operation 的唯一权威状态。
- 浏览器状态、LocalStorage 和 Redis 不能作为恢复或并发判断依据。
- LLM 不能提交任意租户、用户、资源 ID、凭据或 MCP URL。
- 所有写动作绑定完整 Session 身份并经过阶段门禁、recommendation proof 和 revision CAS。
- 外部 provider I/O 不持有数据库事务。
- Finalize 更新 Draft Agent，不自动创建发布版本。

完整 Session 身份为：

```text
tenant_id + user_id + runner_agent_id + draft_agent_id + conversation_id
```

任何一个字段不匹配时，读取和写入都必须失败关闭。

## 2. 当前端到端协议

```text
配置页
  ├─ POST /nl2agent/session/start
  │    └─ Draft + Builder Conversation + v3 Session（单事务）
  ├─ POST /agent/run
  │    ├─ SDK 搜索工具写入可信 recommendation proof
  │    ├─ LLM 完成整条 assistant answer
  │    ├─ 后端唯一解析器校验卡片
  │    ├─ workflow CAS + message + metadata + unit（单事务）
  │    └─ 单个 nl2agent_message SSE
  └─ POST /nl2agent/session/{draft_agent_id}/actions
       └─ Dispatcher → 领域服务 → action receipt → 下一轮 /agent/run
```

模型仍使用受控的 `nl2agent-*` fenced JSON 作为“模型到后端”的内部序列化格式。浏览器永远看不到或解析这些 fence；后端只在完整 final answer 到达后解析、校验并剥离它们。

## 3. Session 生命周期

独立生命周期接口：

| 接口 | 作用 |
|---|---|
| `POST /nl2agent/session/start` | 创建 Draft、隐藏 Builder Conversation 和 v3 Session |
| `POST /nl2agent/session/{draft_agent_id}/resume` | 将可恢复 Session 进入 revision mode |
| `POST /nl2agent/session/{draft_agent_id}/abandon` | 放弃 active Session |
| `GET /nl2agent/session/{draft_agent_id}` | 读取 Session 摘要 |
| `GET /nl2agent/session/{draft_agent_id}/state` | 读取权威 Draft/workflow 投影 |

Session 状态为 `active`、`completed` 或 `abandoned`。只有 `active` 可以执行业务动作。completed 历史只读，resume 后才可继续编辑。

Session 创建时将规范化、脱敏的资源目录存入 `session_catalogs`。运行期间不从 Redis 恢复目录或 workflow。

## 4. Workflow v3

`backend/agents/nl2agent_workflow.py` 是状态合同源，当前 `WORKFLOW_SCHEMA_VERSION = 3`。

v3 保留：

- requirements review；
- model selection confirmation；
- recommendation batches；
- MCP 业务结果和绑定状态；
- online configuration confirmation；
- identity confirmation；
- revision mode 和单调递增 revision。

v3 删除：

- `card_delivery`；
- `online_installations`；
- registration/delivery/retry 状态；
- 任何 workflow JSONB 内的安装 lease。

卡片是否需要生成由业务状态推导。例如 recommendation 从 `searched` 原子推进为 `presented`；安装执行状态由 `nl2agent_installation_operation_t` 管理。

旧 v2 workflow 不自动迁移。Pydantic 解析遇到非 v3 状态时直接拒绝。

## 5. 统一 Action Dispatcher

所有业务写操作使用：

```http
POST /nl2agent/session/{draft_agent_id}/actions
```

请求：

```json
{
  "action": "apply_local_resources",
  "action_id": "uuid",
  "expected_revision": 18,
  "display_text": "已应用本地资源",
  "payload": {}
}
```

响应：

```json
{
  "action_id": "uuid",
  "action": "apply_local_resources",
  "status": "applied",
  "workflow_revision": 19,
  "result": {}
}
```

支持的 action：

- `confirm_requirements`
- `save_model_selection`
- `apply_local_resources`
- `skip_local_resources`
- `install_mcp`
- `bind_mcp_tools`
- `skip_mcp_tools`
- `install_web_skill`
- `complete_online_configuration`
- `save_identity`
- `finalize`

`status` 为 `applied`、`pending` 或 `replayed`。payload 使用严格 discriminated Pydantic model，客户端不能指定 tenant、凭据、任意 MCP URL 或 installation operation ID。

`action_id` 写入 `conversation_message_t.message_metadata`。同一 Session 内相同指纹可以重放；相同 ID、不同指纹返回 `409`。用户可读的 `display_text` 只写入一次。

错误语义：

| HTTP | 含义 |
|---|---|
| 401/403 | 鉴权、租户、用户、Draft 或 Conversation 不匹配 |
| 409 | revision CAS、阶段、Session 状态或 action 指纹冲突 |
| 422 | action payload 不符合合同 |
| 502/503 | MCP/Skill provider 或持久化操作失败 |

旧 requirements/model/resource/MCP/Skill/identity/finalize 细粒度写接口没有 deprecated adapter。

## 6. Card Envelope、消息和 SSE

合同源为 `backend/consts/nl2agent_card.py`，生成：

- `contracts/nl2agent-card.schema.json`
- `contracts/nl2agent-openapi.json`
- `frontend/contracts/generated/*`

Envelope：

```json
{
  "schema_version": 1,
  "draft_agent_id": 123,
  "workflow_revision": 19,
  "cards": [
    {
      "card_type": "local_resources",
      "card_key": "local_xxx",
      "payload": {}
    }
  ]
}
```

允许的 `card_type`：requirements summary、model selection、local resources、web MCP、web Skill、agent identity 和 final review。

`backend/utils/nl2agent_card_validation.py` 是唯一 parser。它只处理完整 answer，并校验：

- Draft ID 和 workflow revision；
- card type/key、数量和严格 payload；
- recommendation batch、资源集合和 proof；
- 不重复的 card type/key；
- 完整 fence 和合法 JSON。

`finalize_nl2agent_message` 在一个事务中完成：

1. 校验完整 Session 身份和当前 revision；
2. 解析并校验卡片；
3. 应用不可分割的 presentation transition；
4. CAS 更新 v3 workflow；
5. 写入一条 `message_type = "nl2agent_card"` assistant message；
6. 将 Envelope 写入 `message_metadata.nl2agent_card`；
7. 仅将剥离 fence 后的文本写入 `message_content` 和一个 final-answer unit。

任一步失败都会回滚，不产生部分消息或部分 workflow 更新。

NL2AGENT 不逐 token 展示。成功时 SSE 只发送一个 `nl2agent_message`，其内容与已持久化消息一致。普通 Agent 保持原流式协议。

前端从 message metadata 读取 Envelope，通过 `cardRegistry.tsx` 渲染。历史读取只读，不注册卡片、不报告 delivery、不触发 action。通用 Markdown renderer 只处理普通 Markdown fence。

## 7. Durable Installation Runner

MCP 和 Web Skill 共用 `backend/services/nl2agent_installation_runner.py`：

- server-derived operation ID；
- request fingerprint；
- claim、lease owner/expiry 和 heartbeat；
- secret-free checkpoint；
- retry、stale lease takeover 和 completed replay；
- 脱敏 result/error。

状态表 `nl2agent_installation_operation_t` 支持 `pending`、`running`、`completed`、`failed`。数据库 claim/transition 是短事务；网络、容器和 provider 调用在事务外执行。

凭据只作为当前请求的运行时输入，不进入 fingerprint 明文、checkpoint、result、error、日志或响应。

## 8. MCP 网络安全

`backend/services/nl2agent_mcp_url_security.py` 是唯一 URL/DNS/redirect 安全入口。初始连接和每次重定向都重新执行 scheme、端口和解析地址检查，阻止 DNS rebinding、loopback、link-local 和 metadata endpoint 绕过。

`NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS` 只在 `backend/consts/const.py` 读取。默认允许私网；显式设置为 `false` 时只允许公网地址。MCP service 不重复实现网络策略。

## 9. 可观测性

阶段指标使用低基数、无敏感标签：

- action：success、replayed、pending、conflict、failure；
- workflow CAS conflict；
- installation retry、lease takeover/conflict、provider/heartbeat failure、replay、success；
- card parse success/failure；
- atomic finalize success/conflict/failure；
- structured SSE sent/failure/stopped。

指标不得包含 tenant/user ID、URL、payload、目录内容、错误文本、header、token 或 secret。日志、响应和 operation 持久化遵循相同规则。

## 10. v3 Cutover Runbook

这是不兼容切换，不提供 v2 自动转换或 deprecated adapter。

切换前：

1. 停止 NL2AGENT 新 Session 和写流量。
2. 备份 PostgreSQL，并记录当前应用 commit 和镜像。
3. 查询所有非 v3 Session 和 Builder Conversation，确认需要保留的 Draft Agent。
4. 软删除旧 Session 及其内部 Conversation/message/unit/source 记录；不要删除用户需要保留的 Draft Agent。
5. 运行只读检查：

```bash
source backend/.venv/bin/activate
python backend/scripts/check_nl2agent_cutover.py
```

检查脚本在以下情况返回非零：

- active Session 不是 schema v3；
- workflow 中仍有 `card_delivery` 或 `online_installations`；
- NL2AGENT Builder Conversation 未绑定到非删除的 v3 Session；
- PostgreSQL 无法读取。

清理操作建议先将目标 Session/Conversation ID 写入临时表并核对数量，再在单事务中更新 `delete_flag`。生产变更必须由数据库管理员执行并保留审计记录。

切换后验证：start、action replay/conflict、安装恢复、单一 `nl2agent_message`、history read-only、resume、finalize、abandon 和租户隔离。

## 11. 推送与回滚

完成后端、前端、合同和 cutover 检查后，分支只推送一次：

```bash
git push origin dyx/nl2a-branch-lite
```

不创建 PR，不对旧协议做双写。

回滚规则：

- 尚未创建任何 v3 Session：可停止流量并回滚到切换前应用 commit。
- 已创建 v3 Session：旧二进制不能读取 v3。必须停止写流量，同时恢复切换前数据库快照和应用版本；只回滚代码是不安全的。
- 不通过 force-push 或重写已发布历史回滚。使用部署回退或显式 revert，并重新运行 cutover 检查。

## 12. 主要实现位置

| 责任 | 文件 |
|---|---|
| HTTP 和错误映射 | `backend/apps/nl2agent_app.py` |
| Action Dispatcher | `backend/services/nl2agent_action_service.py` |
| v3 workflow | `backend/agents/nl2agent_workflow.py` |
| PostgreSQL 状态/CAS | `backend/agents/nl2agent_session_store.py` |
| Atomic message finalize | `backend/services/nl2agent_message_service.py` |
| Card contract/parser | `backend/consts/nl2agent_card.py`, `backend/utils/nl2agent_card_validation.py` |
| Installation runner | `backend/services/nl2agent_installation_runner.py` |
| MCP URL security | `backend/services/nl2agent_mcp_url_security.py` |
| 前端结构化事件/Registry | `frontend/lib/chat/nl2agentCardEvent.ts`, `frontend/components/nl2agent/cardRegistry.tsx` |
| Cutover guard | `backend/scripts/check_nl2agent_cutover.py` |
