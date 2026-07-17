当前分支已推送，但只读扫描确认存在阻断级回归，不能判定为“无坏味道”。

推送状态：

- 分支：`dyx/nl2a`
- 本地与远端：`738476ad0a46e64b7296fde22ff3a61f3702576f`
- 工作区干净
- 扫描阶段未修改任何仓库文件
- 未使用容器；Python 验证使用 `backend/.venv` 和 `deploy/env/.env`

## 核心发现

| 级别 | 问题 | 证据与影响 |
|---|---|---|
| P0 | Runtime 与 Config 服务无法导入 | [agent_service.py:90](/home/sil/nexent/backend/services/agent_service.py:90) 仍从 conversation service 导入 `get_latest_assistant_message` 和 `get_last_unit_for_message`，但二者已在提交 `9455aa21` 中从 [conversation_management_service.py:12](/home/sil/nexent/backend/services/conversation_management_service.py:12) 删除。实际导入 `apps.runtime_app`、`apps.config_app` 均稳定报 `ImportError`，两个服务无法启动。 |
| P1 | abandoned 会话仍可通过 Agent Run 授权 | [_get_owned_draft()](/home/sil/nexent/backend/services/nl2agent_service.py:318) 只检查草稿名称、创建者、conversation，不检查 session 是否 active；[validate_nl2agent_run_context()](/home/sil/nexent/backend/services/nl2agent_service.py:793) 直接依赖它。持久状态读取也不拒绝 terminal session。因此显式 abandon 后，只要 conversation 尚在，仍可触发 Builder Run。 |
| P1 | 契约发布门禁失效且快照过期 | `npm run contracts:check` 首先被上述导入错误阻断。通过内存 shim 旁路导入错误后，仍明确报告 `NL2AGENT OpenAPI snapshot is out of date`。旧快照缺少新增的 `minimum`、`maxItems`、`maxProperties`、`additionalProperties: false` 等约束，生成的前端 API 类型已经滞后。 |
| P2 | 卡片围栏修复不完整 | SDK 历史提取器已要求结束围栏独占一行，但 frontend [cardValidation.ts:274](/home/sil/nexent/frontend/components/nl2agent/cardValidation.ts:274) 和 backend [nl2agent_card_validation.py:83](/home/sil/nexent/backend/utils/nl2agent_card_validation.py:83) 仍使用任意第一个三反引号结束 JSON。包含三反引号的合法字符串会被截断。最小实验返回 `backend_card_with_inline_fence_valid=False`。 |
| P2 | Local Resources 注册与点击存在竞态 | 注册成功时先设置 `registered=true`，共享 lifecycle 仍处于 pending；按钮的 `disabled` 条件没有包含 pending，而 [execute()](/home/sil/nexent/frontend/components/nl2agent/useNl2AgentCardLifecycle.ts:53) 在 pending 时静默返回。并发门禁中实际出现一次“按钮进入 loading，但 Apply mock 从未调用”；顺序重跑通过，说明这是时序敏感的真实丢点击窗口。 |
| P2 | Skill 安装同步阻塞 async 事件循环 | [_install_skill_with_lock_heartbeat()](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:488) 是 async 函数，但在 [第 525 行](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:525) 直接执行同步 installer。ZIP、文件、数据库安装期间会阻塞整个 worker 的事件循环。 |
| P2 | 跨聚合更新仍依赖补偿而非原子提交 | 模型选择先在一个事务更新 Agent，再通过另一个事务推进 workflow，失败时再次写 workflow 补偿，见 [nl2agent_service.py:397](/home/sil/nexent/backend/services/nl2agent_service.py:397)。并发失败可能回退其他请求的确认状态。conversation 删除同样先 abandon、再单独删除；删除失败会留下“conversation 存在但 session 已终止”的中间状态，见 [conversation_management_service.py:349](/home/sil/nexent/backend/services/conversation_management_service.py:349)。 |
| P2 | 测试全局 stub 继续污染 collection | `test_agent_service.py` 在模块导入阶段直接覆盖大量 `sys.modules`，包括 `sqlalchemy`、`services` 和 `consts`，见 [test_agent_service.py:14](/home/sil/nexent/test/backend/services/test_agent_service.py:14)。与 conversation service 测试放在同一 pytest 进程时，两种文件顺序均 collection 失败；单独运行却通过。这正是生产导入错误未被 462 项定向测试发现的原因。 |
| P2 | Catalog 容量控制仍不完整 | marketplace 有页数、条数、字节限制，本地 Tool/Skill 有 2,000 条限制；但本地 tags/labels/usage 等嵌套内容没有字节边界，official skills 没有总条数/字节限制。官方 Skill 枚举还会对每个 ZIP 分别查询 tenant/global Skill，见 [skill_service.py:2797](/home/sil/nexent/backend/services/skill_service.py:2797)，仍有 N+1 特征。 |
| P3 | Agent Run 的 draft ID 并非严格整数 | [AgentRequest](/home/sil/nexent/backend/consts/model.py:312) 使用普通 `Optional[int]`。实测 `draft_agent_id=True` 被解析为整数 `1`，而 `_validate_draft_agent_id` 也未排除 bool。所有权检查降低了安全影响，但 API 类型契约仍不一致。 |
| P3 | 存在不可达异常处理 | [nl2agent_session_store.py:381](/home/sil/nexent/backend/agents/nl2agent_session_store.py:381) 先捕获 `Exception`，后面又捕获具体异常和第二个 `Exception`，后两个分支不可达；Ruff 报 `B025`。 |
| P3 | 巨型模块和长参数问题仍明显 | `nl2agent_session_catalog.py` 1,207 行、`nl2agent_service.py` 983 行、`nl2agent_mcp_service.py` 920 行。Ruff 确认 36 个 `PLR0913`、2 个 `C901`、2 个 `PLR0911`、16 个宽泛异常捕获。 |

## 验证结果

通过：

- Backend NL2AGENT 相关：462 passed
- SDK：150 passed
- Frontend 顺序运行：61 passed
- `test_agent_service.py` 单独运行：321 passed
- TypeScript type-check、目标 ESLint、Prettier：通过
- SQL migration tests：通过
- Card schema 源文件与 frontend 副本一致

失败或暴露问题：

- `apps.runtime_app` 导入失败
- `apps.config_app` 导入失败
- `contracts:check` 失败；旁路导入后仍确认 OpenAPI 快照过期
- Agent/Conversation 两组测试同进程 collection 失败
- Frontend 并发门禁出现 1 次真实竞态失败，顺序重跑恢复

因此，刚推送的坏味道报告中“没有已知高、中严重度问题”和“卡片协议风险已修复”的结论已经不成立。当前最高优先级应是恢复 Runtime/Config 导入，然后补充真实应用导入 smoke test，之后处理终态授权和契约同步。
