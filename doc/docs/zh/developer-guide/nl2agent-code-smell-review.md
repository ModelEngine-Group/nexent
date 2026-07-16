# NL2AGENT 代码坏味道复审

结论：截至 `HEAD 5fac109e`，首轮审计中的高风险权限、错序执行和资源决策并发问题已经修复，但 NL2AGENT 仍未达到“可长期恢复”的会话模型。重新扫描发现 2 项 P1、4 项 P2 和 2 项结构性问题。最重要的剩余工作是把会话权威状态持久化到数据库；在此之前，Redis 过期或丢失仍会让一个数据库中真实存在的草稿永久失去工作流上下文。

## P1：必须修复

### 1. 会话仍以 Redis 为唯一事实源，无法跨 TTL、缓存丢失或浏览器迁移恢复

当前 workflow state 与 catalog 分别存储在两个 Redis key，并固定使用 24 小时 TTL：[nl2agent_session_catalog.py:42](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:42)、[nl2agent_session_catalog.py:45](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:45)。

- 初始化只写 Redis，没有对应数据库 session 行：[nl2agent_session_catalog.py:153](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:153)。
- 普通读取不续期，也没有数据库回源：[nl2agent_session_catalog.py:210](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:210)。
- state CAS 只续 state key：[nl2agent_session_catalog.py:228](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:228)；catalog CAS 只续 catalog key：[nl2agent_session_catalog.py:1098](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:1098)。两个 key 仍可在活跃会话中发生寿命分裂。
- conversation→draft 映射仍仅保存在浏览器 `localStorage`：[chatInterface.tsx:65](</home/sil/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:65>)。解析现在是安全的，但换浏览器、清除站点数据或新设备登录后仍不能从服务端恢复：[chatInterface.tsx:188](</home/sil/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:188>)。
- 数据库没有 NL2AGENT session/workflow 表；Redis 删除函数只用于初始化补偿，没有 abandon API、完成归档或过期草稿清理任务。

影响：草稿 Agent 和 Conversation 已经提交到数据库，但 workflow/catalog 过期后，用户既不能继续，也不能可靠判断应清理还是恢复。跨存储 reservation 在 Redis 丢失后也无法审计或重放。

建议：新增以 `(tenant_id, user_id, conversation_id)` 唯一约束的 session 表，持久化 `draft_agent_id`、schema version、revision、状态 JSON、catalog 快照/引用、生命周期状态和时间戳。数据库作为恢复与生命周期事实源，Redis 仅作为带版本的缓存；所有 CAS 成功后同步持久化，缓存 miss 从数据库重建。提供按 conversation 查询、abandon 和完成归档接口，并给废弃 `draft_*` 增加清理策略。

### 2. Local Apply 的幂等键忽略工具配置值

Apply reservation 的 operation payload 只包含 batch ID、tool IDs 和 skill IDs：[nl2agent_resource_service.py:205](/home/sil/nexent/backend/services/nl2agent_resource_service.py:205)。实际工具参数直到 reservation 成功后、数据库事务内部才解析：[nl2agent_resource_service.py:222](/home/sil/nexent/backend/services/nl2agent_resource_service.py:222)。

因此，两个选择相同工具但提交不同配置值的请求会生成同一个 operation ID。第二个请求会被当作同一操作的幂等重试，也能进入数据库写入；如果第一次数据库已提交而 Redis completion 失败，使用不同配置重试还可能覆盖第一次配置。

建议：在 reservation 前完成全部配置规范化与校验，并把规范化后的参数纳入只存哈希的 operation payload。测试必须覆盖“相同选择、不同配置不能共享 reservation”和“相同配置的提交后重试可收敛”。

## P2：重要一致性问题

### 3. 同一 MCP 推荐的不同安装 option 使用不同锁

MCP 安装锁 key 的输入包含 `option_id`：[nl2agent_mcp_service.py:49](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:49)。安装入口直接用这个 key 获取锁：[nl2agent_mcp_service.py:98](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:98)。

同一个 `recommendation_id` 若同时提交 `remote-0` 和 `package-0`，两个请求会拿到不同锁，并发创建或更新不同 MCP 记录，随后互相覆盖同一个 workflow entry。当前 workflow CAS 不能阻止这种跨 option 竞争。

建议：互斥锁按 `(draft_agent_id, recommendation_id)` 建立；option/config 指纹作为锁内 operation ID，而不是锁作用域。只允许同一 operation 幂等恢复，其他 option 在当前操作完成前返回冲突。

### 4. Web Skill 安装没有服务端“安装中”状态，可与 Complete online 并发

MCP 安装会把 workflow 标记为 `installing`，因此 online completion 会阻止未解决 MCP；Web Skill 安装则直接执行外部安装、绑定和 catalog 删除：[nl2agent_catalog_service.py:420](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:420)、[nl2agent_catalog_service.py:472](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:472)。workflow state 没有 Skill 安装 reservation。

前端每张 Skill 卡和 Complete 按钮使用各自生命周期状态，客户端不能形成全局互斥。两个 API 请求可同时通过 `configure_online_resources` / `complete_online_configuration` 的前置检查；Complete 先确认后，Skill 仍可能在后台安装和绑定，甚至失败。

建议：为在线安装建立服务端 CAS operation（至少包含 recommendation key、`installing/completed/failed` 和 operation ID），`complete_online_configuration` 必须拒绝任何进行中的在线安装。数据库提交后 Redis 失败应允许同一操作重试收敛。

### 5. MCP URL 防护仍是“解析后再按域名连接”，存在 DNS rebinding 时间窗

当前策略会拒绝 URL 凭据，并检查 DNS 返回的每个地址都为公网：[nl2agent_mcp_url_security.py:15](/home/sil/nexent/backend/services/nl2agent_mcp_url_security.py:15)。这已经阻止字面私网 IP、混合公网/私网解析和常规内网域名。

但校验完成后，下游 FastMCP/HTTP 客户端仍使用原始 hostname 建立连接；校验与连接之间会再次解析 DNS。攻击者若控制短 TTL 域名，仍可能在两次解析之间切换到私网地址。`NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS=true` 是明确的部署级高权限逃生口，也应纳入审计。

建议：在网络出口实施私网 egress deny/allowlist，或让 HTTP transport 使用经过校验并固定的解析结果，同时为 HTTPS 保留正确 SNI/Host，且禁用或逐跳重新验证重定向。应用层预检查应保留为纵深防御，但不能单独宣称解决 DNS rebinding。

### 6. 有界 catalog 仍按会话完整复制并在每次运行注入三个工具

分页现在已有页数、条目数、字节数和总时间预算，失控 provider 不再能无限加载。但完整 registry/community/skill catalog 仍为每个 draft 单独序列化到 Redis：[nl2agent_session_catalog.py:1071](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:1071)，每次 Agent Run 再整体读取并展开到 NL2AGENT 工具 metadata：[create_agent_info.py:1082](/home/sil/nexent/backend/agents/create_agent_info.py:1082)、[create_agent_info.py:1108](/home/sil/nexent/backend/agents/create_agent_info.py:1108)。

影响：大租户的相同 catalog 被多个会话重复存储、反序列化和复制；三个搜索工具都接收展开后的 metadata，内存与构建延迟仍随会话数和 catalog 大小增长。

建议：持久化 session 时保存 catalog snapshot ID/版本和必要的推荐证据，不复制全量 provider payload；工具通过受限查询接口读取共享、租户隔离、带版本的 catalog 缓存。

## 结构性坏味道

- `backend/services/nl2agent_service.py` 仍有 1101 行。它已主要承担兼容 facade 和依赖装配，但仍混合名称生成、模型验证、状态前置检查与多个 service adapter；继续增长会重新形成中心化修改热点。
- `test/backend/services/test_nl2agent_service.py` 已有 4181 行。Seed 与 URL policy 已拆出独立测试文件，但 workflow、resource、MCP、catalog 和 publication facade 测试仍集中在同一模块，fixture 过度共享，失败定位和职责边界较差。

建议：按现有 focused service 拆分 facade wiring tests；共享 Redis/数据库 mock 移入窄作用域 fixture 模块。生产 facade 继续下沉纯校验和 dependency factory，最终只保留公开兼容入口。

## 已验证闭合的首轮问题

- 所有操作统一校验 `created_by`，并验证 Redis 中的 conversation 与用户可访问 Conversation 一致；`/agent/run` 在副作用前完成校验。
- 搜索 observation 在写入可信批次前执行 stage CAS；确定性 409 会释放前端 blocker。
- Local Apply/Skip、MCP Bind/Skip 已使用 reservation/complete/release 状态机，discovered tool 子集由 CAS 强制验证。
- Builder seed 对已有和新建实例都会幂等绑定全部内置工具，部分失败会使 readiness 失败。
- 身份保存只在数据库 commit 成功后确认 Redis，Redis 失败可重试收敛。
- `isSecret`/`is_secret` 均会脱敏；Marketplace 加载已有页数、条目数、字节数和时间预算。
- session state API 使用单一 Redis 快照计算状态；内部 operation ID 不暴露；前端 `localStorage` 解析不再因合法 `null`/数组 JSON 崩溃。

## 本轮只读验证结果

重新扫描了 104 个包含 NL2AGENT 引用的文件；重点复核 workflow、session catalog、resource/MCP/catalog/publication service、Agent Run 注入、前端生命周期与相关契约。扫描前工作区干净。

- Conda `nexent`：NL2AGENT 后端/SDK/契约测试 `231 passed`
- Backend venv：同一测试集 `231 passed`
- 前端 Vitest：`58 passed`
- TypeScript：`tsc --noEmit` 通过
- NL2AGENT 定向 Next lint：通过
- 相关 Prettier：通过
- Python 相关修改文件 Ruff：通过
- Shell：Docker/K8s 修改脚本 `bash -n` 通过

下一步顺序：先修复 Local Apply 配置指纹、MCP 推荐级安装互斥和 Web Skill 安装 reservation；再拆分结构性热点；最后设计并实现数据库 session 持久化、Redis 回源和生命周期清理。
