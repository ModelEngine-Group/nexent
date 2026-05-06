# Nexent OpenTelemetry 可观测性设计

生成日期：2026-04-28
基准分支：`dev/opentelemetry`

## 设计目标

Nexent 的监控能力以 OpenTelemetry 为主干，SDK 和后端只负责生成标准 span、event、metric，并通过 OTLP 导出。Phoenix、Langfuse、Jaeger 等平台只作为可配置的 exporter 或可选 SDK 增强层，避免把业务代码绑定到单一平台。

目标：

- Agent 流式运行期间保持 trace 上下文，完整覆盖 API、服务准备、Agent 线程、LLM 流式输出、工具调用。
- 支持 `otlp`、`phoenix`、`langfuse`、`jaeger`、`custom` provider profile。
- 同时支持环境变量和 JSON/YAML 配置文件，环境变量可覆盖文件配置。
- 支持 base endpoint 和 signal-specific endpoint，避免 `/v1/traces`、`/v1/metrics` 路径重复拼接。
- 保持 OpenTelemetry 原生实现，平台 SDK 只通过 `MONITORING_USE_PLATFORM_SDK=true` 显式启用。

## 技术栈

| 分类 | 实现 |
|------|------|
| 标准框架 | OpenTelemetry API/SDK |
| 导出协议 | OTLP HTTP、OTLP gRPC |
| Trace exporter | `opentelemetry-exporter-otlp` HTTP/gRPC trace exporter |
| Metric exporter | `opentelemetry-exporter-otlp` HTTP/gRPC metric exporter |
| 自动埋点 | FastAPI instrumentation、requests instrumentation |
| AI 语义 | OpenInference 风格属性：`llm.*`、`agent.*`、`agent.tool.*` |
| 配置 | 环境变量、`MONITORING_CONFIG_FILE` JSON/YAML |
| Collector | `otel/opentelemetry-collector-contrib`，使用 `otlphttp` 转发 HTTP 平台；本地可选择 logging、Phoenix、Langfuse 三类部署形态 |
| 可选 SDK | `phoenix.otel.register`、`langfuse.get_client`，默认不启用；Phoenix SDK 成功注册时复用其 tracer provider |

## 配置模型

### 环境变量

| 变量 | 说明 |
|------|------|
| `ENABLE_TELEMETRY` | 总开关 |
| `MONITORING_CONFIG_FILE` | JSON/YAML 配置文件路径 |
| `MONITORING_PROVIDER` | `otlp`、`phoenix`、`langfuse`、`jaeger`、`custom` |
| `MONITORING_STACK` | 本地部署形态：`collector`、`phoenix`、`langfuse` |
| `MONITORING_USE_PLATFORM_SDK` | 是否额外初始化平台 SDK |
| `MONITORING_PROJECT_NAME` | 平台项目名 |
| `OTEL_SERVICE_NAME` | OpenTelemetry service name |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP base endpoint |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | 可选 trace 专用 endpoint |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | 可选 metric 专用 endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http` 或 `grpc` |
| `OTEL_EXPORTER_OTLP_HEADERS` | 通用 `key=value,key2=value2` header |
| `OTEL_EXPORTER_OTLP_AUTHORIZATION` | `Authorization` header，常用于 Phoenix bearer auth 和 Langfuse Basic Auth |
| `OTEL_EXPORTER_OTLP_X_API_KEY` | `x-api-key` header，用于兼容需要该 header 的平台 |
| `OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION` | Langfuse 摄取版本，例如 `4` |
| `OTEL_EXPORTER_OTLP_METRICS_ENABLED` | 是否导出 metric |

### 配置文件

```yaml
monitoring:
  enable_telemetry: true
  service_name: nexent-backend
  project_name: nexent-production
  exporter:
    provider: langfuse
    protocol: http
    endpoint: https://cloud.langfuse.com/api/public/otel
    headers:
      Authorization: Basic BASE64_ENCODED_KEY
      x-langfuse-ingestion-version: "4"
    export_traces: true
    export_metrics: false
    use_platform_sdk: false
```

环境变量中显式设置的非默认值会覆盖配置文件，便于同一镜像在不同环境接入不同平台。

## Endpoint 规则

HTTP exporter 支持两种输入：

- base endpoint：`https://cloud.langfuse.com/api/public/otel`
- signal endpoint：`https://cloud.langfuse.com/api/public/otel/v1/traces`

SDK 会按 signal 派生最终地址：

| 输入 | Trace endpoint | Metric endpoint |
|------|----------------|-----------------|
| `https://host/api/public/otel` | `https://host/api/public/otel/v1/traces` | `https://host/api/public/otel/v1/metrics` |
| `https://host/api/public/otel/v1/traces` | 原值 | `https://host/api/public/otel/v1/metrics` |
| `https://host/api/public/otel/v1/metrics` | `https://host/api/public/otel/v1/traces` | 原值 |

## 平台接入

### 纯 OTLP / 自建 Collector

```bash
MONITORING_PROVIDER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
```

### Phoenix

Phoenix 支持通过 OTLP HTTP 接收 traces，也提供 `phoenix.otel` SDK 包装 OpenTelemetry。

```bash
MONITORING_PROVIDER=phoenix
OTEL_EXPORTER_OTLP_ENDPOINT=https://app.phoenix.arize.com/s/YOUR_SPACE
OTEL_EXPORTER_OTLP_AUTHORIZATION="Bearer YOUR_PHOENIX_API_KEY"
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
MONITORING_PROJECT_NAME=nexent-production
```

可选启用平台 SDK。启用后如果 `phoenix.otel.register` 成功返回 tracer provider，Nexent 会复用该 provider，避免重复注册全局 OpenTelemetry tracer provider：

```bash
MONITORING_USE_PLATFORM_SDK=true
```

### Langfuse

Langfuse 的 OTLP HTTP base endpoint 是 `/api/public/otel`，使用 Basic Auth。实时摄取建议带 `x-langfuse-ingestion-version=4`。

```bash
MONITORING_PROVIDER=langfuse
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_AUTHORIZATION="Basic BASE64_PUBLIC_SECRET"
OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION=4
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

## 本地化部署设计

本地化部署通过 `docker/start-monitoring.sh` 选择形态。所有形态都保留 OpenTelemetry Collector 作为入口，Nexent 后端统一上报到 `http://otel-collector:4318` 或宿主机的 `http://localhost:4318`，平台差异只体现在 Collector exporter 和本地服务组合上。

| 形态 | Collector 配置 | 本地服务 | 数据去向 | 说明 |
|------|----------------|----------|----------|------|
| `collector` | `otel-collector-config.yml` | Collector | logging exporter | 最小形态，用于验证 span/metric 是否产生，或手动改配置转发到云端平台 |
| `phoenix` | `otel-collector-phoenix-config.yml` | Collector + Phoenix | `http://phoenix:6006/v1/traces` | Phoenix 容器同时提供 UI 和 OTLP HTTP/gRPC trace collector，适合本地 trace debug |
| `langfuse` | `otel-collector-langfuse-config.yml` | Collector + Langfuse Web/Worker + Postgres + ClickHouse + MinIO + Redis | `http://langfuse-web:3000/api/public/otel/v1/traces` | Langfuse v3 依赖多组件，适合完整 LLMOps 能力验证 |

启动命令：

```bash
cd docker
./start-monitoring.sh --stack collector
./start-monitoring.sh --stack phoenix
./start-monitoring.sh --stack langfuse
```

部署脚本职责：

- 创建或复用 `nexent-network`。
- 首次启动时从 `monitoring.env.example` 生成 `monitoring.env`。
- 根据 `MONITORING_STACK` 或 `--stack` 选择 Docker Compose profile。
- 根据部署形态设置 `OTEL_COLLECTOR_CONFIG_FILE`。
- Langfuse 本地形态下，如果 `LANGFUSE_OTLP_AUTH_HEADER` 未显式配置，则使用初始化项目的 public/secret key 生成 Basic Auth header。

### Phoenix 本地形态

Phoenix 使用 `arizephoenix/phoenix` 镜像，默认暴露：

| 端口 | 用途 |
|------|------|
| `6006` | Phoenix UI 和 OTLP HTTP `/v1/traces` |
| `4319` | 映射到容器内 gRPC OTLP `4317`，避免与 Collector gRPC 端口冲突 |

Compose 中设置 `PHOENIX_WORKING_DIR=/mnt/data` 并挂载 `phoenix-data` volume，确保本地重启后 trace 数据不丢失。Collector 使用 `otlphttp/phoenix` exporter 的 base endpoint `http://phoenix:6006`，由 Collector 按 OTLP HTTP 规则追加 `/v1/traces`。

### Langfuse 本地形态

Langfuse v3 本地形态按官方自托管架构拆分为应用容器和存储组件：

| 组件 | 用途 |
|------|------|
| `langfuse-web` | UI、API、OTLP HTTP ingestion |
| `langfuse-worker` | 异步消费和处理 trace 事件 |
| `langfuse-postgres` | 事务型元数据 |
| `langfuse-clickhouse` | trace/observation/score 分析数据 |
| `langfuse-minio` | S3 兼容对象存储，保存事件和大对象 |
| `langfuse-redis` | 队列和缓存 |

初始化参数通过 `LANGFUSE_INIT_*` 配置，默认创建 `nexent-local` 项目和本地 API Key。Collector 使用 `otlphttp/langfuse` exporter，endpoint 为 `http://langfuse-web:3000/api/public/otel`，并携带：

```yaml
headers:
  Authorization: ${env:LANGFUSE_OTLP_AUTH_HEADER}
  x-langfuse-ingestion-version: "4"
```

默认密钥仅用于本地验证。生产或共享环境必须替换认证密钥、数据库密码、对象存储密钥和 `LANGFUSE_ENCRYPTION_KEY`，并补充备份、高可用和升级策略。

## 埋点信息

| 埋点 | 位置 | 内容 | 目的 |
|------|------|------|------|
| FastAPI 自动 span | `backend/apps/app_factory.py` | route、method、status、duration | API 入口耗时和错误定位 |
| requests 自动 span | `MonitoringManager` 初始化 | 外部 HTTP 调用 | 观测模型服务、工具服务、MCP 等依赖 |
| `agent.run` | `backend/apps/agent_app.py` | `/agent/run` 请求 | Agent 运行入口追踪 |
| `agent_service.run_agent_stream` | `backend/services/agent_service.py` | `agent_id`、`conversation_id`、debug、文件数、记忆开关、策略、准备耗时 | 分析 SSE 创建前的准备阶段 |
| `user_resolution.*` | `run_agent_stream` | 用户、租户、语言和耗时 | 鉴权与租户解析定位 |
| `user_message_save.*` | `run_agent_stream` | 保存或跳过原因、耗时 | 判断会话写入是否正常 |
| `memory_context_build.*` | `run_agent_stream` | 记忆开关、共享策略、耗时 | 定位记忆上下文瓶颈 |
| `streaming_strategy.*` | `run_agent_stream` | `with_memory` 或 `no_memory` | 判断实际执行分支 |
| `generate_stream_no_memory.*` | `generate_stream_no_memory` | 准备与流式输出事件 | 追踪无记忆流式执行 |
| `agent_run` | `sdk/nexent/core/agents/run_agent.py` | 线程启动、缓存读取、消息 yield | 追踪 Agent 流式输出 |
| `agent_run_thread` | `run_agent.py` | Agent 创建、MCP 工具装载、执行错误 | 追踪实际 Agent 执行线程 |
| `chat_completion` | `openai_llm.py` | 模型、温度、top_p、消息数、token、TTFT、chunk 数、输出长度 | LLM 性能、成本和异常分析 |
| `trace_agent_step` | SDK 公共 API | `agent.name`、`agent.step.name`、`agent.step.type` | 供后续推理步骤、工具选择等细粒度埋点扩展 |
| `trace_tool_call` | SDK 公共 API | 工具名、输入、输出、耗时、错误 | 工具可用性和延迟分析 |

### 事件清单

| Span / 位置 | Event | 主要属性 | 目的 |
|-------------|-------|----------|------|
| `monitor_endpoint` 通用装饰器 | `<operation>.started` / `<operation>.completed` / `<operation>.error` | `param.*`、`duration`、`error.*` | 统一记录接口和服务函数的开始、结束、异常 |
| `agent_service.run_agent_stream` | `user_resolution.started` / `user_resolution.completed` | `duration`、`user_id`、`tenant_id`、`language` | 定位用户、租户、语言解析耗时和结果 |
| `agent_service.run_agent_stream` | `user_message_save.started` / `user_message_save.completed` / `user_message_save.skipped` | `duration`、`reason` | 判断用户消息是否写入，以及跳过原因 |
| `agent_service.run_agent_stream` | `memory_context_build.started` / `memory_context_build.completed` | `duration`、`memory_enabled`、`agent_share_option`、`debug_mode` | 观测记忆上下文构建耗时和开关状态 |
| `agent_service.run_agent_stream` | `streaming_strategy.selected` / `streaming_strategy.completed` | `strategy`、`selected_strategy`、`duration` | 识别实际流式分支与选择耗时 |
| `agent_service.run_agent_stream` | `stream_generator.memory_stream.creating` / `stream_generator.no_memory_stream.creating` | 无 | 标记 generator 创建分支 |
| `agent_service.run_agent_stream` | `streaming_response.creating` / `streaming_response.created` / `run_agent_stream.preparation_completed` | `duration`、`media_type`、`total_preparation_time` | 观测 SSE 响应创建和整体准备耗时 |
| `generate_stream_no_memory` | `generate_stream_no_memory.started` / `generate_stream_no_memory.completed` / `generate_stream_no_memory.streaming.started` / `generate_stream_no_memory.streaming.completed` | 无 | 观测无记忆路径的准备和流式消费边界 |
| `agent_run` | `agent_run.started` / `agent_run.thread_started` / `agent_run.get_cached_message` / `agent_run.get_cached_message_completed` / `agent_run.yield_message` | 无 | 观测 Agent 线程启动、缓存轮询和消息 yield |
| `monitor_llm_call` | `llm_call_started` / `llm_call_completed` / `llm_call_error` | `error.*` | 统一记录 LLM 调用生命周期 |
| `openai_chat.chat_completion` | `completion_started` / `completion_finished` / `model_stopped` / `error_occurred` | `model_id`、`temperature`、`top_p`、`message_count`、`total_duration`、`output_length`、`chunk_count`、`error.*` | 分析模型参数、流式输出耗时、停止和异常 |
| `trace_tool_call` | span 属性 `agent.tool.input` / `agent.tool.output` | JSON 字符串、`agent.tool.duration_ms`、`error.*` | 分析工具输入输出、耗时和异常 |

## 指标

| 指标 | 类型 | 维度 | 用途 |
|------|------|------|------|
| `llm.request.duration` | histogram | model、operation | LLM 请求延迟 |
| `llm.token.generation_rate` | histogram | model | token/s |
| `llm.time_to_first_token` | histogram | model | 首 token 延迟 |
| `llm.token_count.prompt` | counter | model | 输入 token 成本 |
| `llm.token_count.completion` | counter | model | 输出 token 成本 |
| `llm.error.count` | counter | model、operation | LLM 错误率 |
| `agent.step.count` | counter | agent、step type、tool | Agent 步骤和工具调用量 |
| `agent.execution.duration` | histogram | agent、status | Agent 总耗时 |
| `agent.error.count` | counter | agent、error type | Agent 异常统计 |

## Agent 运行数据流

```mermaid
flowchart TD
  U[用户] --> FE[前端 Chat]
  FE --> API[POST /agent/run]
  API --> S1[agent.run span]
  S1 --> S2[agent_service.run_agent_stream span]
  S2 --> A[user_resolution]
  S2 --> B[user_message_save]
  S2 --> C[memory_context_build]
  C --> D{streaming_strategy}
  D -->|with_memory| E[generate_stream_with_memory]
  D -->|no_memory| F[generate_stream_no_memory span]
  E --> G[StreamingResponse]
  F --> G
  G --> H[agent_run async generator span]
  H --> I[agent_run_thread span]
  I --> J[NexentAgent]
  J --> K[Tool / MCP / HTTP spans]
  J --> L[chat_completion span]
  L --> M[token events and LLM metrics]
  K --> OTel[OpenTelemetry Tracer/Meter Provider]
  M --> OTel
  OTel --> Collector[OTLP Collector]
  Collector --> Phoenix[Phoenix]
  Collector --> Langfuse[Langfuse]
  Collector --> Other[Jaeger / Custom Backend]
```

## 监控页面结构

```mermaid
flowchart TB
  Page[Agent 监控页] --> Filters[筛选区: 时间 / 租户 / 用户 / Agent / 会话 / 模型 / 状态]
  Page --> KPIs[指标区: 成功率 / P95 / TTFT / tokens/s / token 成本 / 错误数]
  Page --> List[Trace 列表]
  Page --> Detail[Trace 详情]
  Detail --> Waterfall[Span 瀑布图]
  Detail --> Timeline[Agent 时间线]
  Detail --> LLM[LLM 调用面板]
  Detail --> Tool[工具调用面板]
  Detail --> Raw[原始 OTel 属性]
  Detail --> Eval[反馈和评估]
```

与 Phoenix 和 Langfuse 对比：

| 方案 | 优点 | 不足 |
|------|------|------|
| Phoenix | OpenInference 生态匹配好，适合 trace debug、实验、评估；`phoenix.otel` 可降低接入成本 | Nexent 的租户、权限、Agent 配置需要额外映射 |
| Langfuse | Trace、session、user、prompt、evaluation、dashboard 能力完整，OTLP endpoint 和 SDK 都基于 OpenTelemetry | 需要补充 `langfuse.*` 属性才能获得更好的筛选聚合体验 |
| Nexent 自建页 | 可直接关联租户、会话、Agent 配置和权限，适合产品内闭环 | 需要自建 trace 存储、查询、聚合和瀑布图 |

推荐路径：

1. 短期使用 OTLP 对接 Phoenix/Langfuse，先满足调试和分析。
2. 中期在 Nexent 增加 trace 跳转、轻量指标概览。
3. 长期按租户、会话、Agent 版本建立自有监控页，同时保留 OTLP 双写能力。

## 已修复的设计风险

| 风险 | 修复 |
|------|------|
| async generator span 提前结束 | `monitor_endpoint` 使用 `inspect.isasyncgenfunction`，在 `async for` 消费期间保持 span 打开 |
| `/v1/traces` 路径重复拼接 | SDK 支持 base endpoint 和 signal endpoint 自动归一化 |
| Collector header 无法兼容平台 | Collector 默认只 logging；平台转发示例改用 `otlphttp/<provider>` exporter，并拆分 `Authorization`、`x-api-key`、`x-langfuse-ingestion-version` |
| 单测漏掉流式函数 | 增加 async generator 装饰器测试 |

## 参考

- Phoenix Setup Tracing: https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing
- Phoenix Setup OTEL: https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel
- Phoenix Authentication: https://arize.com/docs/phoenix/deployment/authentication
- Phoenix Self-Hosting: https://arize.com/docs/phoenix/self-hosting
- Phoenix Docker Deployment: https://arize.com/docs/phoenix/self-hosting/deployment-options/docker
- Langfuse OpenTelemetry: https://langfuse.com/integrations/native/opentelemetry
- Langfuse Self-Hosting: https://langfuse.com/self-hosting
- Langfuse Docker Compose: https://langfuse.com/self-hosting/local
- Langfuse Overview: https://langfuse.com/docs
