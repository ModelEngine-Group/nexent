# 北向监控面板接口暴露设计（门控式，`/nb/v1/monitoring`）

| 项目 | 内容 |
| --- | --- |
| 日期 | 2026-11-27（v2 门控式重做：2026-11-28） |
| 状态 | 已实施（分支 `dc-feat-northbound-monitoring-1127`） |
| 范围 | Ops 监控面板 24 个接口的北向暴露（models 6 / skills 6 / agents 4 / mcp-tools 8） |
| 关联 | PR #4347（网关能力门体系）；`backend/ops/README.md` "Northbound interfaces remain deferred" 的落地 |

## 1. 背景与目标

监控面板（Ops 仪表盘，`backend/ops/api/monitoring.py`，24 个接口）此前仅支持浏览器
session 凭据。本设计将其暴露给北向调用方（API Key 认证）。经两轮演进定稿：

1. **路径**：`/nb/v1/monitoring/*`——进入 `/nb/v1` 规范命名空间（与 Management 的
   `/nb/v1/automations` 等同级）。外层 `/nb` 是网关凭据策略判定前缀
   （`gateway/exposure/registry.py` 与 `management/services/permission/identity/dependency.py`
   的安全不变量，保持不动）。
2. **门控式**：手写 24 个薄门控函数（Management 门控的正统做法，`@nb_exposed` 声明 →
   生成器编译进快照）。v1 曾用"双挂载复用"（`include_router(ops_router, prefix="/nb")` →
   `/nb/ops/v1/monitoring/*`），因路径无法去掉 `ops` 段而改为门控式；**业务逻辑零复制**：
   门控直接调用原 handler 函数与既有依赖。
3. **租户锁定**：数据范围锁定为 API Key 所属租户（`tenant_id` 不匹配返回 403）。
4. **统一信封**：与 PR #4347 已发布的 `{message, data, requestId}` 伙伴契约一致。
5. **动作防护**：3 个 refresh POST 带每租户限流（默认 120/min，超限 429）；不记审计
   事件（评审决定）。

### 1.1 与 PR #4347 契约的关系

门控式即 PR #4347 的正统扩展：`@nb_exposed` 声明（capability_id + 凭据类型）→
`scripts/generate_exposure_registry.py` 离线编译 → 网关按行转发、未列路径 404、
`GATEWAY_NB_EXCLUDED_CAPABILITIES` 能力粒度急停。生成器的 `SERVICE_OWNERSHIP` 本就预留
`"ops"`，本设计补上 `ops.api.northbound_gates` 包的导入，**注册表行由生成器唯一生产**
（无手工行、无防漂移测试——`--check` 即漂移防线）。

### 1.2 容器解耦：共享层下沉（Web 层 + 存储适配层）

Ops 容器以 Dockerfile COPY 白名单实现模块解耦（逐文件挑选，不含完整
`backend/management`）。本分支曾向 ops 引入 4 个白名单外的 management 符号——本地全树
可导入因此测试全绿，但**容器启动即 ImportError**。修正遵循 PR #4347 原则（"the shared
layer must not import business source"），把传输层原语下沉到共享层，management 原位置
重导出（既有调用方与测试零改动）：

| 原位置（management） | 新位置（共享层） | 内容 |
| --- | --- | --- |
| `services/permission/identity/dependency.py` | `http/server/northbound.py` | `is_northbound_path`、`credential_kind_for_path`（纯路径策略） |
| `services/northbound.py` | `http/server/northbound.py` | `check_and_consume_rate_limit`（限流核心，可注入调用方状态，Redis 适配器惰性导入） |
| `services/monitor/audit.py` | `http/server/security_audit.py` | `record_security_event`（纯日志 `[SEC_AUDIT]`，management 现为唯一消费者） |
| `utils/envelope.py` | `http/server/northbound.py` | `northbound_envelope`（统一信封构造） |
| `utils/request_context.py` | `http/server/request_context.py` | `get_client_ip`（供共享审计层使用） |
| `services/permission/identity/northbound.py` | `http/server/northbound.py` | `record_api_key_usage`（API Key 用量记账编排，fail-open） |
| `db/identity/models.py` + `db/identity/token.py` | `infrastructure/rdb/token_usage.py` | `UserTokenUsageLog` 模型 + `log_token_usage`（账本表，唯一定义） |

配套：`test/backend/deploy/test_ops_image_whitelist.py` 以子进程运行 Ops 入口导入图
（含 `ops.api.northbound_gates`）逐一核对 COPY 白名单；
`test/backend/ops/test_ops_management_import_surface.py` 冻结 **Ops→management 导入面
不得超出 develop 基线**（11 个既有模块）。

### 1.3 /nb 通道身份与记账：零新增 management 依赖

门控的身份依赖复用 v1 已解耦的 `ops_principal`（`ops/api/monitoring.py`）：`/nb` 分支
直接读网关签名身份 `gateway.identity.context.trusted_identity()`（runtime voice 路由同款
先例）。网关凭据策略（`gateway/security/credentials.py`）明确把 `/nb/` 排除在一切旁路
之外——`/nb` 流量必须在边缘完成真实 API Key 校验并签名；无签名身份或 kind 不符 → 401。

API Key 用量记账写入**同一张账本表（`user_token_usage_log_t`）**：模型与写入器为
`infrastructure/rdb/token_usage.py` 唯一定义；编排函数在共享 Web 层，Ops 提交到本进程
线程管理器的 `control-io` lane（fail-open）。门控式 router 的 `route.path` 自带完整
`/nb/v1` 前缀（APIRouter 注册时即内嵌），账本按路由模板原样记录。

**仍在的 management 依赖 = develop 基线**：session 通道的 `authenticate`
（`services/permission/identity/session`）、监控目录查询的 db 模型、
`conversation_agent_history_db`（延迟）、`resource_denylist`、`serialization`、
`api.permission.ops_access`。门控不新增任何一项。

## 2. 架构设计

### 2.1 架构逻辑图（容器与分层）

```mermaid
flowchart TB
    P[北向调用方] -- "Bearer API Key" --> GW
    B[浏览器面板] -- "session" --> GW

    subgraph GW["Gateway 容器 :5013"]
        REG["exposure/registry.json（643 行，生成器产出）<br/>+ /nb/v1/monitoring ×24<br/>credential_kinds=[api_key]"]
        CRED["凭据策略：/nb/ 无旁路<br/>API Key 直查业务 PG"]
        SIGN["sign_identity（aud=ops）"]
    end

    subgraph SHARED["共享层（不导入业务源）"]
        CONTRACTS["contracts<br/>认证类型 / 域错误 / 常量"]
        WEBSH["backend/http/server<br/>路径策略 · 统一信封 · 限流 · 记账编排<br/>security_audit（management 消费）"]
        RDASH["infrastructure<br/>rdb/token_usage：账本模型+写入器"]
    end

    subgraph OPS["Ops 容器 :5016"]
        GIM["GatewayIdentityMiddleware 验签"]
        GATES["northbound_gates/monitoring.py<br/>24 个 @nb_exposed 门控<br/>/nb/v1/monitoring（api_key）"]
        PRIN["ops_principal<br/>trusted_identity → 验签身份"]
        HANDLERS["原 handler x24<br/>/ops/v1/monitoring（session）"]
        ENVM["信封中间件"]
        KERNEL["共享查询内核 ops/monitoring/*"]
    end

    subgraph MGMT["Management 容器 :5010"]
        MGATES["northbound_gates 门控（/nb/v1 其余面）"]
        SHIM["5 处重导出 shim"]
    end

    subgraph DATA["数据层"]
        BPG[("业务 PG<br/>user_token_info_t<br/>user_token_usage_log_t")]
        OPG[("Ops 控制库 PG")]
        ES[("Elasticsearch")]
        RDS[("Redis")]
    end

    GW -- "原路径转发 + 签名身份" --> OPS
    GW -- "/nb/v1 其余路由" --> MGMT
    GIM --> PRIN
    GATES --> PRIN
    GATES -->|"直接调用（零复制）"| HANDLERS
    HANDLERS --> KERNEL
    PRIN -- "记账 control-io" --> WEBSH
    MGATES --> WEBSH
    SHIM -. "重导出" .-> WEBSH
    WEBSH --> RDASH
    RDASH --> BPG
    WEBSH --> RDS
    KERNEL --> OPG
    KERNEL --> ES
    CRED --> BPG
```

### 2.2 请求时序（北向读查询）

```mermaid
sequenceDiagram
    participant P as 北向调用方
    participant GW as Gateway
    participant OPS as Ops App
    P->>GW: GET /nb/v1/monitoring/models (Bearer API Key)
    GW->>GW: 注册表行匹配(credential_kinds=[api_key])→API Key 校验
    GW->>OPS: 原路径转发 + x-nexent-identity(aud=ops, 签名绑定 method/path/query)
    OPS->>OPS: GatewayIdentityMiddleware 验签(强制 kind=api_key)
    OPS->>OPS: ops_principal 读 trusted_identity<br/>→API Key 身份+用量记账(control-io lane)
    OPS->>OPS: 门控→ops_scoped_tenant: tenant=身份租户<br/>(tenant_id 不匹配→403)
    OPS->>OPS: 直接调用原 handler→共享内核查询→内部体
    OPS->>OPS: /nb 包装中间件→统一信封
    OPS-->>P: 200 {message:"success", data:{data:..., data_as_of, coverage_state, is_stale}, requestId}
```

### 2.3 关键机制

- **门控**：`ops/api/northbound_gates/monitoring.py`，`APIRouter(prefix="/nb/v1/monitoring")`
  下 24 个 `@nb_exposed("monitoring.<domain>.<action>")` 薄函数。复用四件套：
  ① `ops_principal`（身份/租户锁）② `selection`/`agent_selection`/`tool_selection`
  依赖（**公共查询参数契约零抄写**——日期/租户/组过滤等由共享依赖声明，无"抄漏"风险）
  ③ 原 handler 函数（分页/排序/装配/响应体逐行复用）④ `RefreshSelection` body 模型。
  仅每路由特有参数（page/sort_by/dimension/metric 等 4-6 行）重声明。
  `nb_capability_routers()` 供应用挂载与生成器导入。
- **应用挂载**：`ops/api/application.py` 在 `OPS_MONITORING_ENABLED` 块内挂载
  `ops_router`（session 面，不变）+ 全部门控路由。v1 的
  `include_router(ops_router, prefix="/nb")` 双挂载已移除。
- **限流**：3 个 refresh 门控声明 `Depends(nb_action_guard)`（共享层
  `check_and_consume_rate_limit`，超限 429 三段式错误体）；原内部 handler 的 guard
  参数已移除（限流只属北向动作）。查询门控不限流（与 `automations.list` 惯例一致）。
- **响应契约**：`NorthboundEnvelopeMiddleware` 只对 `/nb` 路径生效：2xx 包成
  `{message, data, requestId}`（data 为内部体原样，零漂移）；≥400 翻译为三段式
  `{code, message, status, requestId}`。session 通道字节不变。
- **注册表**：生成器扩展为多包导入（`GATE_PACKAGES = ("management.api.northbound_gates",
  "ops.api.northbound_gates")`），24 行由声明编译产出；v1 的 24 行手工行已删除。
- **急停**：`GATEWAY_NB_EXCLUDED_CAPABILITIES` 按 capability id（`monitoring.*`）或原始
  路径排除。

## 3. 接口清单（24 个能力）

路径为 `/nb/v1/monitoring/` 前缀；查询参数与内部接口一致（`tenant_id` 除外——北向
不接受跨租户查询）；响应统一信封。

| capability_id | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| monitoring.models.list | GET | models | 模型监控列表（分页/搜索/排序） |
| monitoring.models.summary | GET | models/summary | 模型监控汇总 |
| monitoring.models.rankings | GET | models/rankings | 模型 Top 5 |
| monitoring.models.trends | GET | models/trends | 模型趋势 |
| monitoring.models.refresh | POST | models/refresh | 触发重算（202，限流） |
| monitoring.models.refresh_status | GET | models/refreshes/{refresh_id} | 重算状态 |
| monitoring.skills.list | GET | skills | 技能监控列表 |
| monitoring.skills.summary | GET | skills/summary | 技能监控汇总 |
| monitoring.skills.rankings | GET | skills/rankings | 技能 Top 5 |
| monitoring.skills.trends | GET | skills/trends | 技能趋势 |
| monitoring.skills.refresh | POST | skills/refresh | 触发重算（202，限流） |
| monitoring.skills.refresh_status | GET | skills/refreshes/{refresh_id} | 重算状态 |
| monitoring.agents.list | GET | agents | Agent 监控列表 |
| monitoring.agents.summary | GET | agents/summary | Agent 监控汇总（含 Token 用量） |
| monitoring.agents.trends | GET | agents/trends | Agent 趋势 |
| monitoring.agents.rankings | GET | agents/rankings | Agent Top 5 |
| monitoring.mcp_tools.list | GET | mcp-tools | MCP 工具监控列表（tools/services 维度） |
| monitoring.mcp_tools.summary | GET | mcp-tools/summary | MCP 监控汇总 |
| monitoring.mcp_tools.rankings | GET | mcp-tools/rankings | MCP Top 5 |
| monitoring.mcp_tools.trends | GET | mcp-tools/trends | MCP 调用趋势 |
| monitoring.mcp_tools.catalog | GET | mcp-tools/catalog | MCP 服务目录（筛选项） |
| monitoring.mcp_tools.overview | GET | mcp-tools/overview | 平台总览 |
| monitoring.mcp_tools.refresh | POST | mcp-tools/refresh | 触发重算（202，限流） |
| monitoring.mcp_tools.refresh_status | GET | mcp-tools/refreshes/{refresh_id} | 重算状态 |

## 4. 请求与响应示例

查询（`start_date`/`end_date` 必填，`group_ids` 可选）：

```bash
curl -X GET "https://your-nexent-domain.com/nb/v1/monitoring/models/summary?start_date=2026-11-20&end_date=2026-11-27" \
  -H "Authorization: Bearer your-access-key-here"
```

```json
{
  "message": "success",
  "data": {
    "data": {"current_model_count": 3, "request_count": 120, "total_tokens": 456789},
    "data_as_of": "2026-11-27T00:00:00Z",
    "coverage_state": "covered",
    "is_stale": false
  },
  "requestId": "0f2c6f1e-..."
}
```

触发重算（动作类，受限流约束）：

```bash
curl -X POST "https://your-nexent-domain.com/nb/v1/monitoring/models/refresh" \
  -H "Authorization: Bearer your-access-key-here" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-11-20", "end_date": "2026-11-27"}'
```

```json
{"message": "success", "data": {"data": {"refresh_id": "<jwt>", "status": "queued"}}, "requestId": "..."}
```

错误（三段式，如租户越界）：

```json
{"code": "HTTP_403", "message": "Northbound monitoring is limited to the API key's tenant", "status": 403, "requestId": "..."}
```

## 5. 错误码

| 状态 | code | 场景 |
| --- | --- | --- |
| 401 | —（网关层） | API Key 缺失/无效（网关直接拒绝，不进入 Ops） |
| 403 | HTTP_403 | `tenant_id` 与 API Key 租户不匹配 |
| 404 | HTTP_404 | refresh 令牌不存在或不属于本租户 |
| 409 | MONITORING_DATES_UNCOVERED | refresh 日期区间无数据源（含 `missing_dates`） |
| 422 | HTTP_422 | 日期区间/组 ID 校验失败 |
| 429 | RATE_LIMIT_EXCEEDED | refresh 动作超过每租户限流（默认 120/min） |
| 503 | HTTP_503 | 监控服务暂不可用 |

## 6. 变更文件与验证

| 文件 | 变更 |
| --- | --- |
| `backend/ops/api/northbound_gates/monitoring.py` | 新增：24 个 `@nb_exposed` 门控（复用 `ops_principal`/selection 依赖/原 handler） |
| `backend/ops/api/northbound_gates/__init__.py` | 新增：`nb_capability_routers()` |
| `backend/ops/api/monitoring.py` | `OpsPrincipal`/`ops_principal`/`ops_scoped_tenant` 路径感知身份；refresh handler 的 guard 参数移除（移入门控）；handler 业务逻辑零改动 |
| `backend/ops/api/northbound_envelope.py` | 新增：`/nb` 响应包装中间件 |
| `backend/http/server/northbound.py` | 新增（共享 Web 层）：路径策略、统一信封、限流、记账编排 |
| `backend/http/server/security_audit.py` | 新增（共享 Web 层）：`[SEC_AUDIT]`（management 消费） |
| `backend/http/server/request_context.py` | `get_client_ip` 下沉至此 |
| `infrastructure/rdb/token_usage.py` | 新增（共享存储适配层）：账本模型 + 写入器 |
| `backend/management` 5 处 | 原实现改为重导出（见 §1.2），既有调用方零改动 |
| `backend/ops/api/application.py` | 挂载门控路由（替代 v1 双挂载）；信封中间件 |
| `scripts/generate_exposure_registry.py` | `GATE_PACKAGES` 多包导入（+`ops.api.northbound_gates`） |
| `backend/gateway/exposure/registry.json` | 24 行由生成器产出（v1 手工行已删），`--check` 通过 |
| `deploy/images/dockerfiles/ops/Dockerfile` | 白名单扩展（共享 Web 层模块 + `infrastructure/redis` + `token_usage.py`） |
| `backend/ops/README.md` | "Northbound interfaces remain deferred" → 北向面描述 |
| `test/backend/ops/test_northbound_monitoring_reuse.py` | UT：接口契约扫描（24 路由）、信封、租户锁、令牌绑定、限流、错误翻译、记账同一性与提交链路、无签名身份 401、session 对照 |
| `test/backend/ops/test_ops_management_import_surface.py` | 新增：Ops→management 导入面 ⊆ develop 基线防护 |
| `test/backend/gateway/test_exposure.py` | `/nb/v1/monitoring` 行断言与能力急停测试 |
| `test/backend/gateway/test_generate_exposure_registry.py` | `EXPECTED_ENABLED` +24 条 ops 门控（target 按路径判定） |
| `test/backend/gateway/test_model_monitoring.py` | 网关↔Ops 北向集成测试（D3 级证据，24 路由全扫） |
| `test/backend/deploy/test_ops_image_whitelist.py` | 新增：Ops 导入图 ↔ 镜像白名单防护（子进程隔离，含门控包） |
| 伙伴文档 zh/en | 北向 API 文档监控章节（`/nb/v1/monitoring`） |

验证：本地全套回归（含 CI 同款逐文件 runner 的既有结论——本机环境性失败与干净
develop 逐项一致）、生成器 `--check` 新鲜、容器化复验（真实 API Key → 容器化网关 →
Ops 容器 → 真实数据库，24 接口 + 安全边界 + refresh 回路 + 账本路由模板）。最新数字
见 PR #4479 评论记录。

## 7. 方案演进记录（如实）

- **v1（2026-11-27）**：双挂载复用 `/nb/ops/v1/monitoring`——24 个 handler 零新路由代码，
  注册表手工行 + 防漂移测试。问题：路径含 `ops` 段（不入 `/nb/v1` 规范命名空间）；
  手工行偏离生成器唯一生产原则。
- **v2（2026-11-28，本版）**：评审定稿路径 `/nb/v1/monitoring` + 门控式。代价是 24 个
  门控（约 400 行样板）与特有参数重声明（靠接口扫描测试逐路由钉死公共参数集合兜底）；
  收益是路径规范、与 Management 门控架构同构、注册表回归生成器唯一生产。
- 容器化接口测试在 v1 期发现过一个真实缺陷（`include_router` 挂载的 route.path 不带
  前缀导致记账错位）；门控式 router 前缀内嵌 `route.path`，该问题形态不再存在，
  对应修复分支已随 v1 移除。

## 8. 已知权衡

- 24 个门控约 400 行样板 + 特有参数重声明（抄漏=契约 bug——接口扫描测试逐路由钉死
  公共参数集合兜底）；
- 路由层不复用（v1 的双挂载移除），业务逻辑/装配/响应体仍零复制；
- 信封 `data` 内为完整内部体（含其 `data` 键与 coverage 字段），存在一层嵌套。
