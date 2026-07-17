# NL2AGENT 代码坏味道复审

结论：截至 `HEAD dc17ffbf`，本轮扫描确认的可在应用代码内闭合的权限、流程错序、并发、幂等、敏感信息、无界加载和 Redis-only 会话问题均已修复。当前没有 P0/P1 级代码坏味道；仍有 3 项 P2 设计债务和 3 项结构性热点。其中 DNS rebinding 需要网络出口策略或可固定解析结果的 transport 才能彻底闭合，另外两项属于服务端会话发现/清理和 catalog 存储模型的后续演进，不影响现有 NL2AGENT 卡片 UX。

## 当前仍存在的 P2 设计债务

### 1. MCP URL 应用层预检查仍不能独立消除 DNS rebinding

当前入口拒绝 URL 凭据，限制为 HTTP/HTTPS，并验证 DNS 返回的每个地址都是公网地址：[nl2agent_mcp_url_security.py:15](/home/sil/nexent/backend/services/nl2agent_mcp_url_security.py:15)。这已经阻止字面私网 IP、混合公网/私网解析和常规内网域名。

校验完成后，下游 FastMCP/HTTP 客户端仍使用原始 hostname 建立连接，连接阶段会再次解析 DNS。攻击者若控制短 TTL 域名，仍可能在预检查和实际连接之间切换解析结果。`NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS=true` 还是明确的部署级高权限逃生口：[const.py:302](/home/sil/nexent/backend/consts/const.py:302)。

建议：在生产网络出口实施私网 egress deny/allowlist；或者让 HTTP transport 使用经过验证并固定的解析结果，同时为 HTTPS 保留正确 SNI/Host，并对每次重定向重新验证。现有应用层检查应作为纵深防御保留。

### 2. 数据库已能恢复已知 draft，但缺少服务端会话发现、abandon 和清理闭环

数据库现已持久化 `tenant_id`、`user_id`、`draft_agent_id`、`conversation_id`、workflow/catalog 双 revision、JSONB 快照和生命周期状态：[db_models.py:486](/home/sil/nexent/backend/database/db_models.py:486)。Redis miss 会从数据库回填：[nl2agent_session_catalog.py:221](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:221)、[nl2agent_session_catalog.py:304](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:304)、[nl2agent_session_catalog.py:1422](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:1422)。因此，Redis TTL 到期或缓存丢失不再使已知 draft 永久失去上下文。

剩余缺口是 discovery/lifecycle API：repository 目前只按 `(tenant_id, draft_agent_id)` 查询，并可附加 `user_id` 所有者过滤：[nl2agent_session_db.py:48](/home/sil/nexent/backend/database/nl2agent_session_db.py:48)。前端 conversation→draft 映射仍存放在 `localStorage`：[chatInterface.tsx:65](</home/sil/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:65>)。换浏览器、清除站点数据或新设备登录后，客户端没有按 conversation 或“我的活跃会话”发现 draft 的服务端入口。表和 repository 已支持 `abandoned` 终态，但当前没有 abandon API，也没有清理长期废弃 `draft_*`、Conversation 和 session 行的任务。

影响：当前设备上的长期恢复已经成立；跨设备发现和废弃草稿治理尚未闭环。

建议：新增所有者隔离的按 conversation 查询与活跃会话列表；新增显式 abandon 操作；定义保留期并由清理任务只处理已 abandon 或超期且无活动的草稿。不要根据 Redis TTL 直接删除数据库实体。

### 3. 有界 catalog 仍按 session 完整复制，并在数据库和 Redis 各存一份

Marketplace/provider 加载已有页数、条目数、字节数和总时间预算，不再能无界增长。但每个 session 仍保存完整 `tool_catalog`、`skill_catalog`、registry/community 结果和 official Skills；持久化后这些内容同时存在于数据库 `session_catalogs` JSONB 与 Redis cache。每次 Agent Run 还会整体读取并展开到三个 NL2AGENT 搜索工具的 metadata：[create_agent_info.py:1082](/home/sil/nexent/backend/agents/create_agent_info.py:1082)。

影响：相同租户 catalog 会随并发 session 数重复序列化、存储和反序列化。当前上限保证了单次请求有界，但总体存储与内存仍近似按“session 数 × catalog 大小”增长。

建议：引入租户隔离、带版本的共享 catalog snapshot；session 只保存 snapshot ID、搜索证据和被展示推荐的最小快照。搜索工具改为调用受限查询接口，不再把三个完整 catalog 展开复制到每个工具 metadata。

## 结构性坏味道

- `backend/agents/nl2agent_session_catalog.py` 已有 1578 行，混合 Redis cache、数据库 write-through/recovery、workflow 状态机、可信搜索批次、Local/MCP/Web Skill operation 与安装锁。持久化逻辑虽然集中在文件前部，但模块仍是主要修改热点。建议先抽出 `nl2agent_session_store`（database repository + cache adapter），再按 requirements/local/online operation 拆状态命令；状态模型与纯校验继续保留在 `nl2agent_workflow.py`。
- `backend/services/nl2agent_service.py` 已有 1116 行。它主要是兼容 facade 和依赖装配，但仍包含名称生成、模型验证、状态前置检查与多个 service adapter。建议继续把纯校验和 dependency factory 下沉，facade 最终只保留公开兼容入口。
- `test/backend/services/test_nl2agent_service.py` 已有 4454 行，workflow、resource、MCP、catalog 和 publication facade 测试仍共享大型 fixture。新的持久化测试已独立放入 `test_nl2agent_session_persistence.py`，但旧模块仍应按 focused service 拆分，避免 fixture 修改造成大面积隐式耦合。

这些是可维护性和容量热点，不是当前行为正确性缺陷；拆分时应保持现有公开函数、卡片协议和前端生命周期不变。

## 本轮已闭合的问题

### 权限与流程边界

- 所有 draft 操作统一校验 `created_by`，并验证 workflow 中的 conversation 与当前用户可访问 Conversation 一致；Agent Run 在任何副作用前完成校验。
- 搜索 observation 在写入可信批次前执行 stage 检查；确定性 409 会释放前端 blocker。
- Builder seed 对已有和新建实例都会幂等绑定全部内置工具，部分失败会使 readiness 失败。

### 并发与幂等

- Local Apply/Skip、MCP Bind/Skip 使用 reservation/complete/release 状态机，discovered tool 子集由 CAS 强制验证。
- Local Apply operation 指纹包含规范化后的工具配置哈希；相同资源选择但不同配置不再共享幂等操作。
- MCP 安装锁按 recommendation 建立，不同 option 不能并发覆盖同一 workflow entry。
- Web Skill 安装使用服务端 `installing/completed/failed` operation；Complete online 会拒绝仍在安装的 Skill。
- 身份保存只在数据库 commit 成功后确认 workflow，失败重试能够收敛。

### 输入、敏感信息与容量

- `isSecret` 和 `is_secret` 均会脱敏；Marketplace 加载受页数、条目数、字节数和时间预算约束。
- MCP URL 会拒绝凭据、非 HTTP(S)、解析失败、私网或非公网地址；剩余 DNS rebinding 风险见上文。
- session state API 使用单一快照计算公开状态；内部 operation ID 与在线安装 bookkeeping 不暴露。
- 前端 `localStorage` 解析不会再因合法 `null`、数组或损坏 JSON 崩溃。

### 数据库 session 持久化

- 新增 `nexent.nl2agent_session_t`、ORM model、增量迁移和 fresh-init schema；启动时 Agent、Conversation 与 session snapshot 在同一数据库事务创建：[nl2agent_session_service.py:66](/home/sil/nexent/backend/services/nl2agent_session_service.py:66)、[nl2agent_session_service.py:100](/home/sil/nexent/backend/services/nl2agent_session_service.py:100)。
- workflow 与 catalog 使用独立 revision 做数据库 CAS；数据库是恢复和并发事实源，Redis 保留 24 小时带版本投影。
- Redis key 缺失会从数据库重建；Redis 读取失败时只读路径直接回源；数据库已经提交而 Redis 回写失败时不会把成功操作误报为失败。
- 最终确认在同一事务内更新 Agent 和 session `completed` 状态：[nl2agent_publication_service.py:291](/home/sil/nexent/backend/services/nl2agent_publication_service.py:291)。终态 session 的后续写入会被确定性拒绝，不会耗尽 CAS 重试后才返回泛化冲突。

## 最终验证结果

最终扫描覆盖 93 个包含 NL2AGENT 引用的 Python、TypeScript/TSX 和 SQL 文件；重点复核 workflow、session catalog、数据库 repository/migration、resource/MCP/catalog/publication service、Agent Run 注入、前端生命周期与契约。

- Backend venv：NL2AGENT 后端、SDK、契约与持久化测试 `254 passed`
- Conda `nexent`：同一测试集 `254 passed`
- 新增持久化专项测试覆盖：事务内初始化、Redis miss 回源、Redis 读取/回写故障、workflow/catalog 双 revision、数据库冲突恢复、终态写保护、finalize 原子生命周期
- Python 相关文件 Ruff：通过
- `git diff --check`：通过
- 前端 NL2AGENT Vitest：`58 passed`
- TypeScript：`tsc --noEmit` 通过
- NL2AGENT 定向 Next lint 与相关 Prettier：通过

后续建议顺序：先补服务端 session discovery/abandon/cleanup；再引入共享 catalog snapshot；随后拆分 session catalog 与 facade/test 热点；DNS rebinding 的最终闭合应与部署网络出口策略一起实施。
