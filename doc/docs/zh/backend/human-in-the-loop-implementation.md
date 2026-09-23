# 结构化反问与普通停止实现

本文对应 `_doc/agent-human-in-the-loop-design.md` v10，更新于 2026-09-21。旧 HITL 的审批、暂停续跑、执行检查点、调度器和专属四表运行依赖已移除。当前实现复用普通聊天的完成、停止、持久化和下一轮 query。

## 运行行为

普通聊天根 Agent 可输出独立的 `ask_user(questions=[...])`。解析器在 Python 执行及工具 precheck 之前识别该终结动作，仅接受字面量表单；赋值、混合业务动作、嵌套调用、动态表达式和别名引用整块拒绝，不执行其中任何业务动作。同名业务工具继续使用原名称，平台反问依次选择 `nexent_ask_user`、`nexent_ask_user_1` 等可用名称，并同步注入系统上下文。

有效表单经过现有内容过滤，产生 `human_interaction` 消息单元和包含全部问题、选项的普通 `final_answer`，通过 `RuntimeFinalAnswer` 结束本轮。没有等待人工的运行实例，不调用 Python executor、最终质量重试或额外模型总结。Planning 的未完成步骤不因反问自动完成。托管子 Agent、NL2Agent、NL2Skill 保持各自原协议。

Web 直接复用原 `ClarificationCard` 的外框、图标、文本/单选/多选/其他输入和 footer 样式。问题正在流出时可填写，流完成后才允许提交。提交把问题和可读答案组合成同一会话的普通新 query。请求被拒绝时保留卡片输入；普通 composer 同样恢复草稿和附件，且不自动重试。切换会话后的回调绑定原会话。较早历史、失败或停止的卡片只读；有效卡片隐藏精确匹配的问题文本回退，不支持卡片的客户端仍获得完整文本。

停止仍调用既有 stop 接口并触发协作取消。stop 成功只代表已受理，实际 worker 退出之前继续保留运行占位。下一次发送若遇到 `X-Stream-Status: conflict`，前端显示“上一轮正在结束，请稍后再发送”并保留输入。停止后不再进入新 step、质量重试或 max-steps 总结。

## 普通历史与持久化

卡片使用既有 `conversation_message_unit_t` 的 `unit_type=human_interaction`，表单 JSON 带 `schema_version: 1`。SSE 的 `content` 直接输出 JSON 对象，仅在入库时序列化为文本；历史回放兼容旧 `clarification` 单元。普通 completed assistant 正文保留问题回退；消息终态和输出单元沿用原批量保存事务，没有新增表或字段。

下一轮历史允许 completed 和 stopped，保留 owner、tenant、软删除和当前消息边界限制。stopped assistant 带固定说明“上一轮已由用户停止，以下内容为已保存的部分结果。”，优先使用已保存正文；无正文时仅投影已完成 execution_logs 与成果引用，限制数量及字符数。工具开始、parse 和未完成观察不解释为成功结果。没有有效回复的旧 user 仍保留任务及“该轮未生成有效回复”的说明。历史摘要 covered-through 规则未扩展为执行检查点。

## 代码位置

| 位置 | 职责 |
| --- | --- |
| `sdk/nexent/core/agents/clarification.py` | 纯表单、提示词、名称选择及问题文本 |
| `sdk/nexent/core/agents/output_protocol.py` | 完整 AST 字面量识别与拒绝非法动作 |
| `sdk/nexent/core/agents/core_agent.py` | 过滤、普通终结和停止边界 |
| `sdk/nexent/core/agents/nexent_agent.py` | 根 Agent 能力与生产系统上下文注入 |
| `sdk/nexent/core/concurrency/cancellation.py` | 普通 `RunTerminated(BaseException)` |
| `backend/management/services/agent/run.py` | 普通 producer、保存与 worker 退出后注销 |
| `backend/database/conversation_db.py` | 停止轮次和未配对任务历史投影 |
| `frontend/lib/clarification.ts` | 表单校验、映射、可读 query 和回退去重 |
| `frontend/app/[locale]/newchat/components/clarification-message-card.tsx` | 普通消息卡片及普通发送接线 |
| `frontend/app/[locale]/newchat/utils/ordinary-send.ts` | 被拒绝发送的乐观消息、草稿和附件恢复 |

## 接口与部署

保留普通 `POST /agent/run`、`GET /agent/stop/{run_id}` 和 northbound 对应普通能力。携带 `enable_hitl`、`hitl_run_id`、`hitl_after_event` 的旧执行请求明确返回参数错误，包括 false、null 和零值；旧专属路由不再注册。

新增 `deploy/sql/migrations/v2.6.1_001_remove_human_interaction.sql`，依次删除 `human_event_t`、`human_execution_t`、`human_request_t`、`human_run_t` 和仅供四表使用的审计函数，不使用 CASCADE。已合入的初始化及历史 SQL 保持原样。新安装先执行历史 SQL，再执行清理迁移，最终不存在四表。

部署时须先停止旧进程和旧 scheduler，再同步更新 Web/runtime 并执行清理迁移。清理直接删除旧 HITL 数据，不提供搬迁或执行恢复。本次开发验证只对隔离临时 PostgreSQL 容器执行迁移，没有部署或修改现有业务数据库。

## 验证

使用 Python 3.11 的 backend 环境，单独运行既有测试文件以避免旧测试模块级 mock 相互污染。新增测试覆盖 AST 非执行边界、结构化输出、真实 CoreAgent 终结、真实 worker 槽位释放、内容过滤、停止与 Planning、普通批量消息保存、隔离 SQL 历史查询及旧字段拒绝。普通运行、附件/子 Agent 上下文、停止、northbound 和代理回归也已运行。

隔离 PostgreSQL 15 已验证：初始化加全部版本迁移、旧四表升级清理、清理重复执行、专属审计函数消失及普通消息保留。临时容器验证后自动删除。

验证结果如下，均为本次实际运行结果：

| 检查 | 结果 |
| --- | --- |
| SDK / 后端 Python 测试 | 1958 项通过；673 项 SDK、1285 项后端 |
| 前端纯逻辑测试 | 17 项通过 |
| Playwright Chrome 普通聊天测试 | 7 项通过 |
| TypeScript 类型检查 | 通过 |
| Next.js 生产构建 | 通过；另行运行类型和 lint 检查，因为仓库构建配置跳过它们 |
| 新增前端文件 lint | 无错误或警告 |
| 已修改前端文件 lint 与 HEAD 对比 | 无新增错误；36 个既有错误仍存在 |
| 本次前端文件格式检查 | 18 个文件通过 |
| Python 语法、部署脚本 bash 语法、git diff 空白检查 | 通过 |
| PostgreSQL 15 新装、升级、重复清理和普通消息保留 | 通过 |

七项浏览器用例覆盖文本/单选/多选/其他答案、必填禁用、冲突后保留答案、普通新 query 的可读内容、历史只读、中文窄屏，以及 composer 按钮和回车冲突恢复；还覆盖流式问题可填写但不能提前提交、完成后启用提交、停止后卡片只读、停止时保留草稿及分享页只读。已检查中英文卡片截图，窄屏 footer 允许换行，避免提示被按钮挤成逐字排列。

前端测试 mock HTTP 服务和可控 SSE，SDK 使用可控模型/工具，并实际执行 CoreAgent 循环和 ThreadManager worker。没有调用外部真实模型，也没有部署当前业务实例。全量 `npm run lint` 仍受仓库既有格式和 any 类型问题阻碍，本次未扩展修改无关代码。

复验入口：

```bash
# Run Python files separately because existing tests install module-level mocks.
backend/.venv/bin/python -m pytest test/sdk/core/agents/test_clarification_protocol.py test/sdk/core/agents/test_clarification_form.py test/sdk/core/agents/test_clarification_runtime.py -q
backend/.venv/bin/python -m pytest test/backend/database/test_conversation_history_stopped.py test/backend/app/test_agent_legacy_fields.py -q
```

在 frontend 目录中可执行 `node --experimental-strip-types --test tests/humanClarification.test.ts tests/ordinarySend.test.ts tests/reasoningAccumulator.test.ts`、`npm run type-check` 和 `npm run build`。浏览器测试需先以 `pnpm exec next dev --hostname 127.0.0.1 --port 3100` 启动页面，再执行 `pnpm exec playwright test e2e/clarification-message.spec.ts --workers=1`；测试使用本机 Chrome，并拦截业务 API，避免写入实际服务。
