结论：**存在明显坏味道，且包含真实功能缺陷。**

在 `dyx/nl2a` 分支、HEAD `807a7742` 上完成只读扫描，共确认：

- **3 个 P1 高严重度问题**
- **8 个 P2 中严重度问题**
- **5 个 P3 低严重度/可维护性问题**
- **1 个条件性协议注入风险**
- 未发现 P0 级越权、任意 SSRF 或数据破坏漏洞

## P1：高严重度

1. **自定义租户无法正常启动 Agent Builder**

启动过程只为默认租户创建 `nl2agent`：

- 启动调用不传租户：[config_app.py:59](/home/sil/nexent/backend/apps/config_app.py:59)
- seed 默认使用 `DEFAULT_TENANT_ID`：[nl2agent_service.py:946](/home/sil/nexent/backend/services/nl2agent_service.py:946)
- 新租户创建流程没有 seed Builder：[tenant_service.py:181](/home/sil/nexent/backend/services/tenant_service.py:181)
- 启动会话时却严格按当前租户查询：[nl2agent_session_service.py:143](/home/sil/nexent/backend/services/nl2agent_session_service.py:143)、[agent_db.py:43](/home/sil/nexent/backend/database/agent_db.py:43)

因此，通过正常 `create_tenant()` 创建的非默认租户会得到：

> NL2AGENT default agent is not initialized.

测试中 Builder 查询被 mock，未覆盖真实多租户集成。

2. **浏览器草稿缓存成为权威状态，发布或删除后会持续注入失效草稿 ID**

草稿映射被保存在未按用户隔离的全局 `localStorage`：

- 读取和写入映射：[chatInterface.tsx:73](</home/sil/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:73>)
- 只要本地存在值，就不会向服务端重新验证：[chatInterface.tsx:192](</home/sil/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:192>)
- 每次 Agent Run 都继续注入该 ID：[chatInterface.tsx:782](</home/sil/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:782>)
- 发布成功仅跳转页面，没有清理映射：[FinalizeCard.tsx:202](/home/sil/nexent/frontend/components/nl2agent/FinalizeCard.tsx:202)

发布后 draft 已被重命名并进入 completed 状态，旧 ID 不再满足 owned draft 校验。重新打开会话后会持续失败，直到用户手工清除浏览器缓存。删除 conversation 同样没有清理该映射，也没有 abandon 对应 session。

这不是越权漏洞——后端最终会拒绝——但属于稳定可复现的用户功能故障。

3. **16 个 NL2Agent API 在鉴权失败时返回 500，而不是 401**

`_current_user()` 在这些端点的 `try` 语句之前执行，例如：

- [nl2agent_app.py:131](/home/sil/nexent/backend/apps/nl2agent_app.py:131)
- [nl2agent_app.py:155](/home/sil/nexent/backend/apps/nl2agent_app.py:155)

缺少或无效认证会抛出普通 `UnauthorizedError`，最终落入全局 generic handler：

- [app_factory.py:98](/home/sil/nexent/backend/apps/app_factory.py:98)

扫描到 16 个此类端点；只有 start/apply-local/install-skill/finalize 等少数端点正确捕获并映射到 401。影响包括错误监控污染、客户端错误重试以及 API 契约不一致，但没有形成鉴权绕过。

## P2：中严重度

4. **Active Session 不会自动淘汰，且一个入口可双击创建孤儿会话**

清理逻辑只处理 `abandoned`：

- [nl2agent_session_db.py:211](/home/sil/nexent/backend/database/nl2agent_session_db.py:211)
- [nl2agent_session_lifecycle_service.py:109](/home/sil/nexent/backend/services/nl2agent_session_lifecycle_service.py:109)

前端虽然定义了 list/abandon API，但生产界面没有调用。用户直接离开、删除 conversation 或关闭浏览器后，session、draft agent、conversation 和 catalog snapshot 都会继续存在。

另外，[AgentManageComp.tsx:47](</home/sil/nexent/frontend/app/[locale]/agents/components/AgentManageComp.tsx:47>) 的 Builder 入口没有 loading/mutex 防护，快速双击会创建两个独立 session，只有最后一次导航被采用。

5. **Redis 被描述成缓存，但实际上是创建和写入路径的硬依赖**

读取路径支持数据库 fallback，但：

- 创建状态必须先写 Redis：[nl2agent_session_store.py:169](/home/sil/nexent/backend/agents/nl2agent_session_store.py:169)
- 状态修改先执行 Redis WATCH/GET：[nl2agent_session_store.py:280](/home/sil/nexent/backend/agents/nl2agent_session_store.py:280)
- Redis 在数据库提交前失败会直接中止操作

因此 Redis 故障时无法创建 session，也无法修改已有 workflow。它实际上属于强一致写依赖，而不是可丢弃缓存。

6. **数据库提交成功后，Redis 可能保留最长 24 小时的旧状态**

更新顺序是：

1. 数据库 CAS 提交新 revision。
2. Redis `SETEX` 更新缓存。
3. Redis 更新失败时仅 best-effort 重试并吞掉错误。

见 [nl2agent_session_store.py:311](/home/sil/nexent/backend/agents/nl2agent_session_store.py:311)。

Redis 恢复后，读取逻辑只要看到已有值就直接信任，不比较 Redis revision 与数据库 revision：[nl2agent_session_store.py:231](/home/sil/nexent/backend/agents/nl2agent_session_store.py:231)。

结果是旧 workflow 可能在 Redis TTL 内继续被 Agent Run 使用。现有测试验证“数据库提交不应回滚”，但没有验证 Redis 恢复后的缓存新鲜度。

7. **本地 Tool/Skill Catalog 无界加载，并存在 Skill N+1 查询**

每次创建 session 都会加载租户全部本地资源：

- Tool/Skill 全量物化：[nl2agent_catalog_service.py:173](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:173)
- Skill 查询 `.all()` 后逐条查询 tool relations：[skill_db.py:220](/home/sil/nexent/backend/database/skill_db.py:220)

然而 NL2Agent 投影只需要 skill 的 ID、名称、描述和标签，额外的逐条 relation 查询没有被使用。大租户下会造成数据库 N+1、内存放大、JSONB snapshot 膨胀和搜索上下文膨胀。

8. **请求集合和 Workflow 状态缺乏容量边界，整数类型也不严格**

多个请求模型只配置了 `extra="forbid"`，没有：

- `max_length`
- 严格整数
- 字典大小限制
- batch 数量上限

见 [model.py:449](/home/sil/nexent/backend/consts/model.py:449) 和 [nl2agent_workflow.py:119](/home/sil/nexent/backend/agents/nl2agent_workflow.py:119)。

实测 Pydantic 会把：

```python
draft_agent_id=True
primary_model_id=True
```

解析成整数 `1`。所有权检查仍会阻止越权，但类型契约不可靠。另一方面，持续创建不同 search batch/recommendation batch 会令 workflow JSONB 无界增长。

9. **MCP/Skill 安装锁释放可能掩盖成功结果或原始异常**

锁释放位于未保护的 `finally`：

- MCP：[nl2agent_mcp_service.py:152](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:152)
- Skill：[nl2agent_catalog_service.py:448](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:448)

如果 Redis 在 release 阶段失败：

- 成功安装可能被报告成失败
- 原始异常可能被 release 异常覆盖

MCP 安装有 heartbeat；Skill 使用相同的五分钟锁 TTL，却没有续约机制。长时间安装超过 TTL 后，另一请求可以重新获取锁并重复执行。

10. **Catalog Snapshot 只有创建和读取，没有垃圾回收**

Snapshot 使用内容哈希去重，但扫描未发现删除或 GC 路径：

- Snapshot 模型：[db_models.py:486](/home/sil/nexent/backend/database/db_models.py:486)
- Session 外键没有 cascade：[db_models.py:502](/home/sil/nexent/backend/database/db_models.py:502)

Session 清理是软删除，外键引用仍然存在，因此 abandoned/completed session 会永久固定 snapshot。租户目录持续变化时，该表只增不减。

11. **默认 Builder seed 存在 check-then-create 并发竞争**

Seed 先按名称查询，再创建 agent，没有数据库锁、upsert 或 `(tenant_id, name, version_no)` 唯一约束：

- [nl2agent_seed_service.py:253](/home/sil/nexent/backend/services/nl2agent_seed_service.py:253)
- AgentInfo 当前只有 `(agent_id, version_no)` 主键：[db_models.py:433](/home/sil/nexent/backend/database/db_models.py:433)

多个 config 实例同时启动时可能创建重复 Builder；后续 `.first()` 会任意选择其中一个。

## P3：可维护性和工程坏味道

12. **生产模块暴露仅供测试使用的全局 API**

`clear_session_cache()` 会扫描并删除全部 NL2Agent cache key，文档明确写着供测试使用，但它仍位于生产模块并被导出：

- [nl2agent_session_store.py:475](/home/sil/nexent/backend/agents/nl2agent_session_store.py:475)

`record_trusted_search_batch()` 同样只有测试调用，并绕过生产使用的阶段校验入口。这类测试 seam 应避免成为生产公共 API。

13. **前端错误类型不统一**

服务层定义了 `Nl2AgentRequestError`，但大部分方法仍抛出：

```typescript
new Error(await response.text())
```

见 [nl2agentService.ts:27](/home/sil/nexent/frontend/services/nl2agentService.ts:27) 和 [nl2agentService.ts:119](/home/sil/nexent/frontend/services/nl2agentService.ts:119)。

这会丢失 HTTP status/error code，且可能把原始 JSON 文本直接展示给用户，使冲突、认证和可重试错误无法统一处理。

14. **模块和依赖对象继续膨胀**

静态扫描结果：

- `nl2agent_session_catalog.py`：约 1230 行
- `nl2agent_service.py`：约 951 行
- 生产代码共 **39 个 PLR0913** “参数过多”命中
- `McpInstallationDependencies`、`PublicationDependencies` 均达到约 16 个依赖字段

不过 `C901`、`PLR0912`、`PLR0915` 没有命中，因此问题主要是职责聚集和依赖耦合，而不是单个函数的高圈复杂度。

15. **NL2Agent 边界入口没有完全通过前端格式门禁**

专用 NL2Agent components/service/chat 集成 lint 通过，但包括 Builder 两个入口后，Prettier 检查失败：

- [AgentManageComp.tsx:51](</home/sil/nexent/frontend/app/[locale]/agents/components/AgentManageComp.tsx:51>)
- [AgentSelectorHeader.tsx:213](</home/sil/nexent/frontend/app/[locale]/agents/components/AgentSelectorHeader.tsx:213>)

没有把入口文件里的全部旧 lint 问题归因于该 feature；可以确认的是本次 NL2Agent 集成行本身仍未满足格式门禁。

16. **Python 测试依赖“每个文件独立子进程”**

官方 runner 下 643 个测试全部通过，但把 18 个 NL2Agent 测试文件放入同一个标准 pytest 进程时出现 16 个 collection error。原因是测试模块向 `sys.modules` 注入 stub，污染后续测试导入。

因此测试结果依赖 [run_all_test.py](/home/sil/nexent/test/run_all_test.py:1) 的逐文件子进程隔离，普通 `pytest <多个文件>` 不可靠。

## 条件性风险

Prompt 要求模型把 Observation JSON “原样”复制进三反引号卡片：

- [nl2agent_system_prompt_en.yaml:64](/home/sil/nexent/backend/prompts/nl2agent_system_prompt_en.yaml:64)

卡片解析器却使用第一个三反引号作为结束位置：

- [nexent_agent.py:46](/home/sil/nexent/sdk/nexent/core/agents/nexent_agent.py:46)

本地及在线目录的名称、描述、标签没有对反引号做转义。如果不可信 marketplace 描述包含 ` ``` `，模型按 prompt 原样输出时可能截断卡片或改变卡片边界。这更接近协议破坏/拒绝服务，不是权限绕过；尚未用恶意 marketplace 端到端样本验证，因此单列为条件性风险。

## 验证结果

通过：

- Python NL2Agent 测试：18 个文件，**643/643**
- 两个 Python 调用入口均通过，但最终解析到同一个 Python 3.11 解释器，因此不能算独立运行时覆盖
- Frontend Vitest：8 个文件，**64/64**
- Frontend type-check
- NL2Agent contracts check
- 专用 NL2Agent lint
- Python Ruff 默认规则
- SQL migration/init 一致性测试
- `git diff --check`

安全路径中未发现明显问题：

- Agent Run 在副作用前校验 runner、draft owner、tenant 和 conversation
- MCP URL 拒绝凭据、非 HTTP(S)、私有/保留地址，并限制跨 host/port redirect
- marketplace secret metadata 有脱敏
- Workflow 使用数据库 revision CAS，terminal session 会拒绝继续修改

工作区最终 `git status --short` 为空。**未修改任何文件。**
