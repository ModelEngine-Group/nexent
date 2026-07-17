# NL2AGENT 代码坏味道复审

## 结论

截至被审代码 `ffdc73b3`，本轮对 NL2AGENT 后端、SDK、前端、数据库、迁移、契约与测试进行了重新扫描。此前文档记录的 3 项 P2 设计债务和 3 项结构性热点均已闭合；复扫过程中另外发现并修复了 TLS 认证回归、数据库提交后成功结果可能被补偿性回读失败覆盖、剩余高圈复杂度函数和失效兼容别名。

当前未发现仍成立的 P0、P1、P2 代码坏味道。用户可见的卡片协议、阶段顺序、自动续写、安装/绑定/跳过、会话恢复和最终发布交互保持不变。

这份文档整体替代旧审查正文，不再保留已经失效的“当前仍存在”描述。

## 已闭合的原始设计债务

### 1. MCP URL DNS rebinding 与 TLS 认证

入口仍拒绝 URL 凭据、非 HTTP(S)、解析失败、私网或非公网地址；连接阶段不再使用 hostname 进行第二次 DNS 解析，而是把 TCP 连接固定到同一次安全解析得到的地址集合：[nl2agent_mcp_url_security.py:58](/home/sil/nexent/backend/services/nl2agent_mcp_url_security.py:58)、[nl2agent_mcp_url_security.py:146](/home/sil/nexent/backend/services/nl2agent_mcp_url_security.py:146)。

固定 transport 保留原始 Host、TLS SNI、系统 CA 证书链和主机名校验；跨 hostname 或端口的重定向会在建连层被拒绝。代理和环境代理被禁用，调用方不能用额外参数覆盖受控 transport。`NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS=true` 仍是显式部署级能力，但即使启用，目标也会先解析并固定，不会重新引入连接时 DNS rebinding。

复扫曾发现固定 transport 误把 TLS 证书校验关闭；已恢复 `CERT_REQUIRED` 和 hostname verification，并加入直接检查 SSL context 的回归测试。

### 2. 会话发现、abandon 与保留期清理

服务端现已提供所有者隔离的活跃会话列表、按 Conversation 恢复 draft、显式 abandon，以及有界的废弃会话保留期清理：[nl2agent_session_lifecycle_service.py:42](/home/sil/nexent/backend/services/nl2agent_session_lifecycle_service.py:42)、[nl2agent_session_lifecycle_service.py:73](/home/sil/nexent/backend/services/nl2agent_session_lifecycle_service.py:73)、[nl2agent_session_lifecycle_service.py:109](/home/sil/nexent/backend/services/nl2agent_session_lifecycle_service.py:109)。HTTP 入口位于 [nl2agent_app.py:126](/home/sil/nexent/backend/apps/nl2agent_app.py:126)，前端在本地 conversation→draft 映射缺失时会通过服务端恢复。

清理只处理超过保留期的 `abandoned` 会话，使用有界 batch 和 `skip_locked`；它会软删除对应 draft、资源实例、关系与 Conversation 数据，不根据 Redis TTL 删除数据库实体。Redis 仅是可丢弃投影。

### 3. session 级 catalog 重复存储

数据库使用租户隔离、内容寻址的不可变共享快照 `Nl2AgentCatalogSnapshot`，session 仅保存 `(tenant_id, catalog_snapshot_id)` 引用：[db_models.py:486](/home/sil/nexent/backend/database/db_models.py:486)、[nl2agent_session_db.py:30](/home/sil/nexent/backend/database/nl2agent_session_db.py:30)。相同租户的相同 catalog 由 SHA-256 snapshot ID 去重，不同租户不能共享引用。

Redis 同样缓存共享 snapshot 与每会话引用，不再为每个 session 复制完整 catalog。搜索注入读取受限投影，并根据 workflow 安装状态过滤或标记条目；不可变 catalog 不参与 workflow CAS 写放大。

## 会话状态持久化与一致性

`Nl2AgentSession` 持久化 tenant、owner、draft、Conversation、生命周期状态、workflow schema/revision/state 与共享 catalog 引用：[db_models.py:498](/home/sil/nexent/backend/database/db_models.py:498)。新会话的 Agent、Conversation、session snapshot 在同一数据库事务创建；workflow 写入使用数据库 revision CAS，数据库是并发与恢复事实源。

Redis miss 会从数据库回填，Redis 读取故障会直接回源。数据库已经提交而 Redis CAS/write-back 失败时，API 保留已提交的成功结果并尽力重建缓存：[nl2agent_session_store.py:143](/home/sil/nexent/backend/agents/nl2agent_session_store.py:143)、[nl2agent_session_store.py:280](/home/sil/nexent/backend/agents/nl2agent_session_store.py:280)。复扫补上了“补偿性数据库回读自身失败”分支，避免把已提交成功误报为失败。

finalize 在同一事务内更新 Agent 与 session `completed` 终态；`completed`/`abandoned` session 拒绝后续状态变更。Docker、Kubernetes fresh-init schema 与版本化 migration 均包含 session、共享 snapshot、复合外键和清理索引。

## 权责分离与复杂度复审

原 `nl2agent_session_catalog.py` 中的数据库、Redis、恢复和 CAS 职责已迁移到 [nl2agent_session_store.py](/home/sil/nexent/backend/agents/nl2agent_session_store.py)；catalog 模块只保留 workflow 命令、可信搜索证据、推荐批次与安装锁语义。状态模型和纯状态评估继续位于 `nl2agent_workflow.py`。

`nl2agent_service.py` 现为兼容 facade 和依赖装配层；catalog、MCP、local resource、workflow、publication、session lifecycle、seed 与 summary projection 分别由聚焦 service 负责。模型/资源摘要与失效引用判断已抽到无基础设施依赖的 [nl2agent_summary_service.py](/home/sil/nexent/backend/services/nl2agent_summary_service.py)。

原 4477 行 `test_nl2agent_service.py` 已删除，按 catalog、workflow、MCP、resource、publication 拆成 5 个聚焦测试模块，共享构造集中在非测试收集模块 `nl2agent_test_support.py`；持久化、生命周期、URL 安全、seed 和纯 summary 另有独立测试文件。

最终对全部 NL2AGENT Python 生产模块执行 `C901`、分支数和语句数检查，无函数超过项目复杂度阈值。SDK 的 MCP candidate normalization 已拆出 community/fallback option 构造；无效私有兼容别名和未使用前端 handler/state/import 已删除。全量定向 Ruff 与前端 lint 均未发现 unused、duplicate definition 或 warning。

## 行为与安全边界

- 所有 draft 操作在副作用前校验 tenant、owner、draft 类型和 Conversation 绑定。
- requirements、model、local resource、online MCP/Skill、identity、finalize 仍按原卡片生命周期推进；确定性冲突继续映射为稳定错误响应。
- Local Apply、MCP Bind、MCP/Skill Install 使用 reservation/complete/release 与幂等 operation ID；数据库事务失败和 workflow reconciliation 失败路径均有真实回归测试。
- MCP 配置 secret、header、environment 与 marketplace metadata 持续脱敏；catalog 加载保持页数、条目、字节和总耗时上限。
- session state API 只返回公开摘要，不暴露内部 operation ID、安装 bookkeeping 或完整 catalog。
- 前端跨设备恢复优先使用服务端 discovery；`localStorage` 只是优化缓存，损坏、数组或 `null` 不会中断聊天。

## 最终扫描与验证结果

最终扫描覆盖 123 个包含 NL2AGENT/NL2Agent 引用的代码、契约、SQL、迁移与测试文件（不含本审查文档、依赖目录和 coverage 产物），并重点复核权限边界、状态机、数据库/Redis 一致性、共享 catalog、MCP 网络 transport、前端恢复、契约和发布事务。

- Backend venv：18 个定向测试文件，`643 passed`，失败为 0。
- Conda `nexent`：同一 18 文件测试矩阵，`643 passed`，失败为 0。
- 覆盖矩阵包含 Agent Run 注入、session workflow/catalog、应用异常映射、数据库 repository、生命周期、持久化故障、MCP TLS/DNS 固定、MCP/Skill/local resource、publication、summary、契约和 SDK 搜索工具。
- NL2AGENT SDK 搜索工具在该矩阵中的行覆盖率为 88%–100%；`create_agent_info.py` 为 91%。
- 前端契约生成一致性检查通过；Vitest `64 passed`；`tsc --noEmit` 通过。
- NL2AGENT 前端与 chat integration 定向 Next lint：零 warning、零 error；相关文件 Prettier 检查通过。
- NL2AGENT Python 生产代码与测试定向 Ruff 通过；生产代码 `C901/PLR0912/PLR0915` 通过。
- 仓库自带 `deploy/tests/test_sql_migrations.sh` 通过，fresh-init 与增量迁移约束一致。
- `git diff --check` 通过。

结论：本次复审范围内没有需要继续保留在文档中的未修复代码坏味道。生产部署仍建议在应用层固定目标之外配置私网 egress deny/allowlist，作为网络层纵深防御；这是部署加固建议，不是当前 NL2AGENT 代码缺陷。
