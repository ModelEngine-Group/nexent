# Nexent 三平面解耦与 Management 竞争力规划（代码实证版）

**日期**：2026-10-12
**视角**：软件架构（Software Architect）
**上游输入**：`competitive-analysis-admin-console-2026-10-08.md`（竞品与痛点）、`roadmap-admin-console-2026-10-08.md`
**本文定位**：把「runtime / management / 运维监控」三条解耦主线落到代码边界与平面契约上，并给出 Management 面的能力补齐清单与分阶段验收标准。10-08 报告管"做什么、为什么"，本文管"边界在哪、怎么切、切完怎么验收"。

---

## 1. 现状盘点（全部经代码核实）

### 1.1 进程与平面现状

| 平面 | 入口 | 端口 | 实际内容 | 证据 |
|------|------|------|---------|------|
| Management | `backend/config_service.py` → `apps/config_app.py` | 5010 | 40+ 管理路由：租户/用户/配额/模型/MCP/记忆/评测/标签/APIKey/邀请/通知/A2A 等；**还挂着 monitoring 读路由与 runtime 代理转发** | `config_app.py` L168-229 共 30 个 `include_router`；compose `entrypoint ... config_service.py` |
| Runtime | `backend/runtime_service.py` → `apps/runtime_app.py` | 5014 | agent 执行流、自动化调度、会话/分享/文件/语音运行时路由、skill creator；lifespan 管理线程池、任务恢复、沙箱池关闭 | `runtime_app.py` L110-118；helm chart `nexent-runtime` |
| MCP / 北向 | `mcp_service.py` / `northbound_service.py` | 5011/5015、5013 | MCP 容器与市场、北向开放 API（`/nb/v1`、`/nb/a2a`） | compose entrypoint；`northbound_app.py` L66 |
| Observability（**尚未成平面**） | 无独立进程 | — | 写侧：`sdk/nexent/monitor/monitoring.py`（2876 行，OTLP 导出 + `MonitoringRecordBuffer` 批量写 PG `model_monitoring_record_t`）；读侧：仅 `monitoring_app.py` 两个路由（`/monitoring/models`、`/monitoring/status`）；前端无监控页面，dashboard 靠 `MONITORING_DASHBOARD_URL` 外链 | `monitoring_app.py` 全文件 169 行；前端 grep `monitoring` 无命中 |
| Gateway | nginx（TLS 终结）→ nexent-web | 3100→3000 | SSE 已做 `proxy_buffering off` + 3600s 超时 | `deploy/docker/assets/nginx/nginx.conf` |

**结论一**：runtime 与 management 的进程切分**已经完成**（双 entrypoint、双 helm chart、可独立 replicas），但**代码归属与数据边界没切干净**——这是"解耦优化"真正的欠债所在，不是再拆进程。

### 1.2 耦合热点（对应现状图 C1-C4）

| # | 热点 | 代码证据 | 危害 |
|---|------|---------|------|
| C1 | 执行引擎住在 management 目录 | `management/services/agent/run.py` 2462 行，import `nexent.core.agents.run_agent`、`database.*`、`services.*`，经 `agent_app.agent_runtime_router` 挂到 **runtime 进程** | 目录语义与进程归属错位；改"管理功能"会编译进运行时镜像，反之亦然 |
| C2 | management 代理持有运行会话 | `services/runtime_proxy_service.py`：`forward_agent_run`（SSE 透传）、`forward_agent_stop`、评测转发；`runtime_state_service.py`（Redis 短状态）被两面共用 | 管理面重启/发布会掐断在飞会话；SSE 长连接把两平面生命周期绑死 |
| C3 | 共享 PG 无读写归属 | runtime 侧 `agents/create_agent_info.py` 直读 `agent_db / agent_version_db / tool_db / model_management_db / knowledge_db`；监控记录由 SDK buffer 直写业务库 | 配置表结构变更即运行时事故；监控写流量与业务库争抢（现已用独立连接池缓解但未隔离写入方） |
| C4 | 可观测只有写侧没有平面 | 无 `/metrics`（全仓 grep prometheus 无命中）；trace 仅 OTLP 外链（`span_processor.py` 只做噪音过滤）；无 trace 查询 API；无运维告警规则（`quota_service` 的 warning 是业务配额告警，不是平台告警） | 运维监控作为第三条主线目前**只有素材没有系统** |

### 1.3 已有资产（解耦时不要扔掉）

- **版本化基础**：`services/agent_version_service.py` 已有 publish / rollback / compare / get_current / 快照可用性检查——"配置发布契约"的雏形已存在，缺的是 runtime 侧只读快照的强制化与灰度。
- **多副本友好调度**：`agent_automation/scheduler.py`、`memory_dreaming_scheduler.py` 均为 SDK durable lease 调度（claim/renew/release），非单例假设。
- **监控独立连接池**：`database/client.get_monitoring_db_session` 已隔离读流量——observability 独立成面的第一个支点。
- **健康契约**：`apps/health_app.py` 的 `install_health_contract`（live/ready）可统一三平面探针。
- **配额框架**：`quota_service.py` 1676 行，平台→租户→个人三层 + KB 软配额 + 告警阈值配置，**但维度只有存储字节**。

---

## 2. 解耦目标：三平面 + 三类契约

目标形态（见目标图）：Management = 配置真相源与治理面；Runtime = 无状态执行面；Observability = 第四平面（指标/trace/计量/告警）。平面间只允许三类契约通信：

| 契约 | 方向 | 内容 | 现状差距 |
|------|------|------|---------|
| 配置发布契约 | Management → Runtime | 带版本号的 agent/工具/模型**快照**；runtime 启动与加载只读快照 | 现 runtime 直读配置草稿表（C3），需改为快照读 + 版本号校验 |
| 运行契约 | Runtime 对外 | `run / stop / status / capacity`；已有 `/internal/thread-capacity` 与 lease 状态 | management 的代理层（C2）只允许调契约，不允许持有会话状态；stop 语义改为"发给 runtime"而非"管理面代管" |
| 遥测上报契约 | Runtime/SDK → Observability | 异步批量的模型调用记录、span、容量快照（buffer 机制已有） | 写入目的地从"业务 PG 直写"改为 observability 摄入端（可先同库异池，后异库） |

**存储归属表（切分验收依据）**：

| 数据 | 写方 | 读方 |
|------|------|------|
| 配置/资产/权限/配额/审计表 | Management | Management（runtime 仅经快照） |
| 版本快照表 | Management（publish 时固化） | Runtime（只读） |
| 会话/流/线程/租约（Redis + 会话表） | Runtime | Runtime + Management（经运行契约查询，不直读） |
| `model_monitoring_record_t`、trace、计量聚合 | Observability 摄入 | Observability 查询 API → 管理台/运维看板 |

**明确不做**：不引入消息中间件、不拆微服务。保持"模块化单体 + 进程切分 + 契约约束"，用 import 边界检查（import-linter / CI lint）固化 C1 类违规，成本最低且可回退（reversibility 优先）。

---

## 3. Management 竞争力规划：能力补齐清单

沿用 10-08 报告定位：**L3-L4 水位，开源侧稀缺组合（多租户 + 三层配额 + CAS/OAuth + 审计雏形）**；补齐下表后成为"唯一开箱即企业级管控的开源 Agent 平台"。优先级与 10-08 四季度主题对齐。

| # | 能力域 | 现状（代码证据） | 补齐动作 | 优先级 | 依赖平面 |
|---|--------|----------------|---------|--------|---------|
| M1 | 审计合规 | `audit_service.py` 仅 131 行、只写 `[SEC_AUDIT]` 日志行，无表/无 API/无 UI（Issue #2189） | 新建 `audit_log_t`（走 `deploy/sql/migrations/`）+ 查询/导出 API + 管理台页面；与 M2 共用异步写入管道 | **P0**（26Q4 合规基座） | Observability 管道 |
| M2 | 计量与三维配额 | 配额仅存储字节；监控记录已含 `total_tokens/ttft/generation_rate` 字段但**未参与配额与计费** | token/调用次数两维计量入账；配额升级为 存储×token×调用 三维；80%/95% 预算告警（关 #2854/#2807） | **P0/P1**（27Q1 成本治理） | Observability 计量摄入 |
| M3 | 身份纵深 | CAS+OAuth 已通；OIDC/SAML/企微钉钉飞书扫码缺失；角色映射手写 JSON | OIDC 接入 + SSO 界面化配置 + 至少一家国产扫码 | P1（27Q2） | — |
| M4 | 版本治理与发布 | publish/rollback/compare 已有 | 灰度/金丝雀发布（按租户/分组）、staging-prod 环境位、发布审批链——**开源竞品全空白，差异化主打** | P1（27Q1-Q2） | 配置发布契约 |
| M5 | 运营级管理台 | 40+ 路由但无统一检索/批量/排序（#3449）；SU 无改密（#3413） | 统一管理台：全局检索、批量操作、结构化错误提示、UserManageComp 拆分 | P2（27Q2-Q3） | — |
| M6 | 可观测管理面 | monitoring 仅 2 路由、无前端页 | 租户级用量/成本大盘、trace 查询（conversation→span）、SLO 告警规则管理 | P1（与 M2 同管道） | Observability 查询 API |
| M7 | 生态与 marketplace | agent/skill repository、MCP market、official bundle 已有 | 审核工作流、官方 bundle 签名校验、上架指标（下载/调用）回流 M6 大盘 | P2 | Observability |

**竞争力叙事**：M1+M2 追平企业门槛（合规一票否决项）→ M4+M6 差异化进攻（Agent 版本治理 + FinOps，开源无竞品覆盖）→ M3+M5 体验还债。与 10-08 报告结论一致，本文新增的是**每条能力的架构落点与依赖**（右两列）。

---

## 4. 分阶段路线与验收标准

| 阶段 | 时间 | 主题 | 关键交付 | 验收标准（可测） |
|------|------|------|---------|----------------|
| P0a | 即刻（低风险） | 边界清理 | `management/services/agent/run.py` 等执行代码迁移/重命名至 runtime 归属；monitoring 读路由移入 observability 模块；三平面统一 health 契约 | CI import 边界检查通过：management 包不得 import 执行引擎；runtime 镜像构建不再包含管理路由 |
| P0b | 26Q4 | 合规基座 | M1 审计表化 + M2 计量埋点（复用 buffer 异步管道） | 审计可按用户/时间/事件查询导出（关 #2189）；每次模型调用的 token 入账率 ≥99%（抽样对账） |
| P1 | 27Q1 | 成本治理 + 版本治理 | 三维配额 + 预算告警；配置发布契约落地（runtime 只读快照）；灰度发布 v1 | runtime 直读配置表归零（grep + 集成测试）；改配置不重启 runtime 生效且带版本号回滚 |
| P2 | 27Q2 | 身份 + 可观测管理面 | M3 OIDC/扫码；M6 用量大盘 + trace 查询 + 告警规则 | 管理台可见租户级 token 成本与单会话 trace；告警规则可配置可触发 |
| P3 | 27Q3 | 治理升级 | M5 运营级管理台、自定义角色、合规文档包；契约 OpenAPI 化 | #3449/#3413 关闭；三平面契约有 OpenAPI 文档与契约测试 |

**解耦顺序原则**：先切"代码归属与代理语义"（P0a，零功能变化）→ 再切"监控读写"（P0b/P1，写侧已有 buffer 天然异步）→ 最后上"计量/告警/trace 查询"（P2，依赖前两阶段的数据管道）。每步可独立回退。

---

## 5. 架构决策记录（ADR）

### ADR-001: 执行代码归属与平面边界
- **Status**: Proposed
- **Context**: C1/C2——2462 行执行引擎位于 management 目录却运行在 runtime 进程；管理面代理持有在飞 SSE 会话，发布即断流。
- **Decision**: 执行类代码统一归属 runtime 包；management 对 runtime 仅经运行契约（run/stop/status/capacity）交互，代理层无状态化；CI 增加 import 边界检查固化。
- **Consequences**: 易——镜像职责清晰、管理面发布不影响在飞会话；难——run.py 迁移涉及大量 import 调整，需一次性迁移 + 别名过渡期；代理无状态化后 stop/重连语义需前端配合。

### ADR-002: Observability 提升为第四平面
- **Status**: Proposed
- **Context**: C4——写侧 2876 行 SDK 代码 + 直写业务库，读侧 2 路由、无前端、无告警；运维监控是三条主线之一却无系统承载。
- **Decision**: 独立模块/服务（复用已有独立连接池起步，后独立存储）；统一摄入（模型调用记录/span/计量/审计共用异步批量管道）；对外提供查询与告警 API，管理台与运维看板只做消费方。
- **Consequences**: 易——M1/M2/M6 一次管道三处受益；审计与计量不再各建一套写路径；难——异步管道需补 replay/死信，否则丢记录影响计费对账。

### ADR-003: Runtime 配置读取改为版本化快照
- **Status**: Proposed
- **Context**: C3——runtime 直读配置草稿表，配置表变更即运行时事故；版本服务已有 publish/快照能力但未被 runtime 强制使用。
- **Decision**: publish 时固化快照；runtime 加载只读快照 + 版本号，禁止直读草稿表；变更生效经主动刷新或下一会话生效。
- **Consequences**: 易——配置与执行隔离、可回滚、可灰度；难——引入一致性窗口（配置变更到生效有延迟），需版本号展示与强制刷新开关补偿。

---

## 6. 风险与权衡

| 风险 | 权衡决策 |
|------|---------|
| 快照读的一致性窗口 | 接受秒级~会话级延迟；管理台显示"生效版本"，提供强制刷新 |
| 监控/审计异步写入丢数据 | 补本地 spool + 死信重放；计费对账以 spool 为准 |
| 边界检查拖慢开发 | import-linter 规则白名单渐进收紧，先禁新增违规再清存量 |
|  observability 独立服务增加部署复杂度 | 渐进：先同进程异模块异连接池（现状已有），流量与需求验证后再独立部署——不提前付微服务税 |

---

## 7. 与上游文档的衔接

- 10-08 竞品结论（无开源免费版同时具备多租户+RBAC+配额+审计+SSO）不变，本文的 M1-M3 即其 P0/P1 项的架构落点。
- 10-08 路线图 Q3'27"架构重构"主题被本文**前移拆解**：边界清理（P0a）不必等到 27Q3，本季度即可零风险启动；27Q3 只做管理台整合与角色模型。
- 后续建议：对 P0a 出迁移 PR 清单（run.py 依赖图），对 ADR-002 出摄入管道设计稿，两者可作为下个迭代的输入。
