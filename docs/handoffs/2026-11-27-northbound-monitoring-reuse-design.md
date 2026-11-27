# 北向监控面板接口暴露设计（复用内部路由方案）

| 项目 | 内容 |
| --- | --- |
| 日期 | 2026-11-27 |
| 状态 | 已实施（分支 `dc-feat-northbound-monitoring-1127`） |
| 范围 | Ops 监控面板 24 个接口的北向暴露（models 6 / skills 6 / agents 4 / mcp-tools 8） |
| 关联 | PR #4347（网关能力门体系）；`backend/ops/README.md` "Northbound interfaces remain deferred" 的落地 |

## 1. 背景与目标

监控面板（Ops 仪表盘，`backend/ops/api/monitoring.py`，24 个接口）此前仅支持浏览器
session 凭据，外部业务系统无法读取监控数据。本设计将其暴露给北向调用方
（API Key 认证），并满足三个明确决策：

1. **复用内部接口**：不新建 24 个门控函数，同一组 handler 双挂载；
2. **前缀带 `ops`**：北向路径为 `/nb/ops/v1/monitoring/*`（外层 `/nb` 是网关凭据
   策略判定前缀，`gateway/exposure/registry.py` 与
   `management/services/permission/identity/dependency.py` 的安全不变量，保持不动）；
3. **响应用统一信封**：与 PR #4347 已发布的 `{message, data, requestId}` 伙伴契约一致；
   数据范围锁定为 API Key 所属租户（`tenant_id` 不匹配返回 403）。

### 1.1 与 PR #4347 契约的调和

PR #4347 建立了北向能力门体系（`nb_exposed` 声明 → `scripts/generate_exposure_registry.py`
生成快照行 → 网关按行转发）。复用方案不写门控，与之有四处偏差，按下述方式调和：

| 偏差 | 调和方式 |
| --- | --- |
| 注册表行由谁生产 | 手工行附带 `capability_id`（快照的急停排除按 `row.get("capability_id")` 匹配，对手工行同样生效）；生成器只重写 `northbound_gates` 来源行，手工行保留 |
| 防漂移 | 防漂移测试钉死"注册表行 ↔ `ops_router` 声明 ↔ capability ID"三方一致（`test_registry_rows_match_nb_mounted_routes_and_capabilities`），并以行为断言证明 `/nb` 挂载存活 |
| 响应信封 | 仅对 `/nb` 路径生效的响应包装中间件（`ops/api/northbound_envelope.py`），handler 返回语句零改动 |
| 门控隔离哲学 | `ops_principal` 路径感知依赖在 handler 内分流；session 分支行为保持由全部既有监控测试回归保障 |

### 1.2 容器解耦：共享 Web 层下沉

Ops 容器以 Dockerfile COPY 白名单实现模块解耦（`deploy/images/dockerfiles/ops/Dockerfile`
逐文件挑选，不含完整 `backend/management`）。初版实现从 management 导入了 4 个未列入
白名单的符号——本地全树可导入因此测试全绿，但**容器启动即 ImportError**。修正遵循
PR #4347 确立的原则（"the shared layer must not import business source"，见
`management/utils/request_context.py` 的迁移注释），将 Ops 需要的传输层原语下沉到共享
Web 层 `backend/http/server/`，management 原位置改为重导出（既有调用方与测试零改动）：

| 原位置（management） | 新位置（共享 Web 层） | 内容 |
| --- | --- | --- |
| `services/permission/identity/dependency.py` | `http/server/northbound.py` | `is_northbound_path`、`credential_kind_for_path`（纯路径策略） |
| `services/northbound.py` | `http/server/northbound.py` | `check_and_consume_rate_limit`（限流核心，`runtime_state_service` 惰性导入 + ImportError 时退化为进程内限流） |
| `services/monitor/audit.py` | `http/server/security_audit.py` | `record_security_event`（纯日志审计 `[SEC_AUDIT]`，无 DB 依赖） |
| `utils/envelope.py` | `http/server/northbound.py` | `northbound_envelope`（统一信封构造） |
| `utils/request_context.py` | `http/server/request_context.py` | `get_client_ip`（供共享审计层使用） |

配套变更：Ops 镜像白名单扩展（`http/server/northbound.py`、`security_audit.py`、
`infrastructure/redis`）；新增 `test/backend/deploy/test_ops_image_whitelist.py` 以
子进程运行 Ops 入口导入图，逐一核对落在 COPY 白名单内——该防护使此类"本地可导入、
容器崩溃"的耦合在 CI 即被拦截。

保留的既存耦合（显式记录）：`ops_principal` 的身份解析仍使用
`management/services/permission/identity/session.py`（`authenticate`/`authenticate_identity`，
白名单内，develop 既有依赖，身份解析与用户库属 management 数据所有权）。彻底消除需要
把身份解析下沉为共享 adapter 或走服务间协议，应单独立项。

## 2. 架构设计

### 2.1 组件视图

```mermaid
flowchart LR
    P[北向调用方 Partner] -- "Bearer API Key" --> G[Gateway :5013]
    subgraph G[Gateway]
        EM[ExposureMiddleware 注册表匹配<br/>未列路径一律 404]
        CI[凭据校验 principal.kind=api_key<br/>须命中行的 credential_kinds]
        SI[sign_identity<br/>audience=ops 30s TTL]
    end
    G -- "raw path /nb/ops/v1/monitoring/*" --> O[Ops App :5016]
    subgraph O[Ops App]
        GIM[GatewayIdentityMiddleware<br/>audience=ops 验签]
        ENV["/nb 响应包装中间件<br/>成功→{message,data,requestId}<br/>错误→{code,message,status,requestId}"]
        SH["同一组内部 handler x24<br/>双挂载: /ops/v1/monitoring(session)<br/>+/nb/ops/v1/monitoring(api_key)"]
        PA["ops_principal 路径感知<br/>/nb→API Key 身份+用量记账<br/>session→authenticate 不变"]
        TL["ops_scoped_tenant 路径感知<br/>/nb→租户=身份租户(锁定)<br/>session→operations_scope 不变"]
    end
    B[浏览器面板] -- "session" --> G
    G --> SH
    SH --> PA --> TL
    SH --> K[共享查询内核 ops/monitoring/*]
    K --> D[(Ops 控制库 PG<br/>ops_monitoring_*_t / ES / 业务库 catalogs)]
```

### 2.2 请求时序（北向读查询）

```mermaid
sequenceDiagram
    participant P as 北向调用方
    participant GW as Gateway
    participant OPS as Ops App
    P->>GW: GET /nb/ops/v1/monitoring/models (Bearer API Key)
    GW->>GW: 注册表行匹配(credential_kinds=[api_key])→API Key 校验
    GW->>OPS: 原路径转发 + x-nexent-identity(aud=ops, 签名绑定 method/path/query)
    OPS->>OPS: GatewayIdentityMiddleware 验签
    OPS->>OPS: ops_principal 判定 /nb 通道→API Key 身份+用量记账
    OPS->>OPS: ops_scoped_tenant: tenant=身份租户<br/>(tenant_id 不匹配→403)
    OPS->>OPS: 同一 handler→共享内核查询→内部体
    OPS->>OPS: /nb 包装中间件→统一信封
    OPS-->>P: 200 {message:"success", data:{data:..., data_as_of, coverage_state, is_stale}, requestId}
```

### 2.3 关键机制

- **双挂载**：`ops/api/application.py` 在 `OPS_MONITORING_ENABLED` 块内执行
  `include_router(ops_router, prefix="/nb", include_in_schema=False)`。网关按注册表行
  `target=ops` 原路径转发（`gateway/routing.py` 的 `exposure_target` 直返 `match.target`，
  northbound 逻辑别名已废弃）。
- **路径感知身份**：`ops_principal`（`ops/api/monitoring.py`）按 `is_northbound_path`
  分流：`/nb` 通道用 `authenticate_identity(kind=API_KEY)` 解析网关签名身份并做 API Key
  用量记账（提交到 ops 进程自有线程管理器的 `control-io` lane，fail-open）；session 通道
  保持原 `authenticate`（并镜像 FastAPI 的 `dependency_overrides` 查找，既有测试夹具不动）。
- **租户锁定**：`ops_scoped_tenant` 在 `/nb` 通道返回身份租户；`tenant_id` 参数传入且不等于
  身份租户时返回 403。refresh 令牌签发时 `tenant` 恒为身份租户；refresh status 校验令牌内
  租户等于身份租户，不匹配按 404 处理（与"不存在"不可区分，防跨租户探测）。
- **动作防护**：3 个 refresh POST 在 `/nb` 通道附加每租户限流
  （复用 `management/services/northbound.py` 的 `check_and_consume_rate_limit`，超限 429
  三段式错误体）与审计（`record_security_event`，事件名
  `northbound_monitoring_*_refresh`，失败/拒绝也留痕，fail-open）。查询门控不限流
  （与 `automations.list` 门控惯例一致）。
- **响应契约**：`NorthboundEnvelopeMiddleware`（`ops/api/northbound_envelope.py`）只对
  `/nb` 路径生效：2xx 包成 `{message, data, requestId}`（`data` 为内部体原样，含其 `data`
  键与 `data_as_of`/`coverage_state`/`is_stale` 字段，零漂移）；≥400 翻译为三段式
  `{code, message, status, requestId}`（域错误体原样透传；HTTPException 静态文案保留；
  409 结构化 detail 的诊断键如 `missing_dates` 保留）。session 通道字节不变。
- **急停**：`GATEWAY_NB_EXCLUDED_CAPABILITIES` 按新 capability id（`monitoring.*`）或
  原始路径排除，无需新增环境变量。

## 3. 接口清单（24 个能力）

路径为 `/nb/ops/v1/monitoring/` 前缀；查询参数与内部接口一致（`tenant_id` 除外——北向
不接受跨租户查询）；响应统一信封。

| capability_id | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| monitoring.models.list | GET | models | 模型监控列表（分页/搜索/排序） |
| monitoring.models.summary | GET | models/summary | 模型监控汇总 |
| monitoring.models.rankings | GET | models/rankings | 模型 Top 5 |
| monitoring.models.trends | GET | models/trends | 模型趋势 |
| monitoring.models.refresh | POST | models/refresh | 触发重算（202，审计+限流） |
| monitoring.models.refresh_status | GET | models/refreshes/{refresh_id} | 重算状态 |
| monitoring.skills.list | GET | skills | 技能监控列表 |
| monitoring.skills.summary | GET | skills/summary | 技能监控汇总 |
| monitoring.skills.rankings | GET | skills/rankings | 技能 Top 5 |
| monitoring.skills.trends | GET | skills/trends | 技能趋势 |
| monitoring.skills.refresh | POST | skills/refresh | 触发重算（202，审计+限流） |
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
| monitoring.mcp_tools.refresh | POST | mcp-tools/refresh | 触发重算（202，审计+限流） |
| monitoring.mcp_tools.refresh_status | GET | mcp-tools/refreshes/{refresh_id} | 重算状态 |

## 4. 请求与响应示例

查询（`start_date`/`end_date` 必填，`group_ids` 可选）：

```bash
curl -X GET "https://your-nexent-domain.com/nb/ops/v1/monitoring/models/summary?start_date=2026-11-20&end_date=2026-11-27" \
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

触发重算（动作类，受限流与审计约束）：

```bash
curl -X POST "https://your-nexent-domain.com/nb/ops/v1/monitoring/models/refresh" \
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
| `backend/ops/api/monitoring.py` | `OpsPrincipal`/`ops_principal`/`ops_scoped_tenant`/`nb_action_guard`/`_nb_audit`；11 个 handler 与 `_read_agent_views` 换用路径感知身份；响应体与校验零改动 |
| `backend/ops/api/northbound_envelope.py` | 新增：`/nb` 响应包装中间件 |
| `backend/http/server/northbound.py` | 新增（共享 Web 层）：路径策略、统一信封、每租户限流 |
| `backend/http/server/security_audit.py` | 新增（共享 Web 层）：`[SEC_AUDIT]` 安全审计（自 management 下沉） |
| `backend/http/server/request_context.py` | `get_client_ip` 下沉至此（自 management utils） |
| `backend/management/services/permission/identity/dependency.py` 等 4 处 | 原实现改为重导出（见 §1.2），既有调用方零改动 |
| `backend/ops/api/application.py` | 注册中间件；`ops_router` 以 `/nb` 前缀二次挂载 |
| `deploy/images/dockerfiles/ops/Dockerfile` | 白名单扩展：共享 Web 层两个新模块 + `infrastructure/redis` |
| `backend/gateway/exposure/registry.json` | 手工新增 24 行（`capability_id`、`target=ops`、`credential_kinds=["api_key"]`），`--check` 通过 |
| `test/backend/ops/test_northbound_monitoring_reuse.py` | 新增 12 个 UT：信封、租户锁、令牌绑定、审计、限流、错误翻译、session 对照、防漂移 |
| `test/backend/gateway/test_exposure.py` | 新增 `/nb/ops` 行断言与能力急停测试 |
| `test/backend/gateway/test_model_monitoring.py` | 新增网关↔Ops 北向集成测试（D3 级证据） |
| `test/backend/deploy/test_ops_image_whitelist.py` | 新增：Ops 导入图 ↔ 镜像白名单一致性防护（子进程隔离） |

验证：`pytest test/backend/ops/ test/backend/gateway/ ... -q`（1076 通过；10 个失败为本机
存量环境问题，与干净 develop 逐项一致）；`python scripts/generate_exposure_registry.py
--check`；`python scripts/check_copyright.py`。

**端到端验证**：本地以本分支代码并行启动网关（:5023）与 Ops（:5026）实例，复用运行
栈的 PostgreSQL/Redis/Elasticsearch 数据，用栈内真实 API Key（租户 465522b1…）执行
18 项检查：12 个查询接口（models/skills/agents/mcp-tools 全域）信封响应、租户越界 403、
未注册路径 404、缺凭据 401、refresh 动作 202→状态查询 200 回路、日期越界 422——全部
通过（完整链路：伙伴凭据 → 网关注册表/凭据校验/签名身份 → Ops 双挂载/路径感知身份/
租户锁定 → 真实监控数据）。正式 test-e2e 案例（API-142 起）需 NEXENT_TEST_HOME 与
northbound.yaml 测试资产，本机缺失，故以本地双实例 e2e 为等价证据。

## 7. 已知权衡（显式选型）

- 修改内部路由文件（session 分支行为不变，靠回归测试保障），与 PR #4347 的
  "门控隔离"哲学不同；
- 手工注册表行靠防漂移测试（而非生成器）保障一致；
- 信封 `data` 内为完整内部体（含其 `data` 键与 coverage 字段），存在一层嵌套；
- 查询门控不限流（对齐既有门控惯例），仅 refresh 动作受限流。
