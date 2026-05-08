# Nexent OpenTelemetry 可观测性设计

生成日期：2026-05-06
基准分支：当前 OpenTelemetry 功能分支

## 设计目标

Nexent 的监控能力以 OpenTelemetry 为主干，SDK 和后端只负责生成标准 span、event、metric，并通过 OTLP 导出。Phoenix、Langfuse、Grafana Tempo、Jaeger 等平台作为可配置 exporter 或可选 SDK 增强层接入，业务代码不绑定单一平台。

核心目标：

- Agent 流式运行期间保持 trace 上下文，覆盖 API、服务准备、Agent 异步 generator、Agent 线程、LLM 流式输出、Python 解释器执行、真实工具调用和最终答案。
- 通过 OpenInference 属性适配 Phoenix，通过 `langfuse.*` 属性适配 Langfuse，同一套业务埋点可同时服务多个监控平台。
- 支持 `otlp`、`phoenix`、`langfuse`、`jaeger`、`grafana`、`custom` provider profile。
- 同时支持环境变量和 JSON/YAML 配置文件，环境变量可覆盖文件配置。
- 支持 base endpoint 和 signal-specific endpoint，避免 `/v1/traces`、`/v1/metrics` 路径重复拼接。
- FastAPI/requests 自动埋点可配置，默认压制流式接口中的 ASGI `receive/send` 噪声。
- 平台 SDK 只通过 `MONITORING_USE_PLATFORM_SDK=true` 显式启用，默认保持 OpenTelemetry 原生实现。

## 技术栈

| 分类 | 实现 |
|------|------|
| 标准框架 | OpenTelemetry API/SDK |
| 导出协议 | OTLP HTTP、OTLP gRPC |
| Trace exporter | `opentelemetry-exporter-otlp` HTTP/gRPC trace exporter |
| Metric exporter | `opentelemetry-exporter-otlp` HTTP/gRPC metric exporter |
| 自动埋点 | FastAPI instrumentation、requests instrumentation；requests 默认关闭 |
| AI 语义 | OpenInference 属性、Langfuse OTel 属性、Nexent 自定义业务属性 |
| Agent 框架 | SmolAgents `CodeAgent` 扩展、Nexent `CoreAgent`、`NexentAgent` |
| 配置 | 环境变量、`MONITORING_CONFIG_FILE` JSON/YAML |
| Collector | `otel/opentelemetry-collector-contrib`，支持 logging、Phoenix、Langfuse、Grafana/Tempo 四类本地部署形态 |
| 可选 SDK | `phoenix.otel.register`、`langfuse.get_client`；Phoenix SDK 成功注册时复用其 tracer provider |

## 总体架构

```mermaid
flowchart LR
  Backend[Nexent Backend / SDK] --> OTel[OpenTelemetry TracerProvider / MeterProvider]
  OTel --> Exporter[OTLP Trace / Metric Exporter]
  Exporter --> Collector[OpenTelemetry Collector]
  Collector --> Phoenix[Arize Phoenix]
  Collector --> Langfuse[Langfuse]
  Collector --> Tempo[Grafana Tempo]
  Collector --> Other[Jaeger / Custom Backend]

  Backend --> FastAPI[FastAPI Auto Instrumentation]
  Backend --> Manual[Manual AI Spans]
  Manual --> OI[OpenInference Attributes]
  Manual --> LF[Langfuse Attributes]
```

## 配置模型

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_TELEMETRY` | `false` | 监控总开关 |
| `MONITORING_CONFIG_FILE` | 空 | JSON/YAML 配置文件路径 |
| `MONITORING_PROVIDER` | `otlp` | `otlp`、`phoenix`、`langfuse`、`jaeger`、`grafana`、`custom` |
| `MONITORING_STACK` | `collector` | 本地部署形态：`collector`、`phoenix`、`langfuse`、`grafana` |
| `MONITORING_USE_PLATFORM_SDK` | `false` | 是否额外初始化平台 SDK |
| `MONITORING_PROJECT_NAME` | `nexent` | 平台项目名 |
| `OTEL_SERVICE_NAME` | `nexent-backend` | OpenTelemetry service name |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP base endpoint |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | 空 | 可选 trace 专用 endpoint |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | 空 | 可选 metric 专用 endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http` | `http` 或 `grpc` |
| `OTEL_EXPORTER_OTLP_HEADERS` | 空 | 通用 `key=value,key2=value2` header |
| `OTEL_EXPORTER_OTLP_AUTHORIZATION` | 空 | `Authorization` header，常用于 Phoenix bearer auth 和 Langfuse Basic Auth |
| `OTEL_EXPORTER_OTLP_X_API_KEY` | 空 | `x-api-key` header，用于兼容需要该 header 的平台 |
| `OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION` | 空 | Langfuse 摄取版本，例如 `4` |
| `OTEL_EXPORTER_OTLP_METRICS_ENABLED` | `true` | 是否导出 metric |
| `MONITORING_INSTRUMENT_FASTAPI` | `true` | 是否启用 FastAPI 自动 HTTP server span |
| `MONITORING_INSTRUMENT_REQUESTS` | `false` | 是否启用 requests 自动 HTTP client span |
| `MONITORING_FASTAPI_EXCLUDED_URLS` | 空 | FastAPI 自动埋点排除 URL，逗号分隔正则 |
| `MONITORING_FASTAPI_EXCLUDE_SPANS` | `receive,send` | 排除 ASGI 内部 `receive/send` span，流式接口建议保持默认 |
| `OTEL_COLLECTOR_VERSION` | `0.150.0` | 本地 OpenTelemetry Collector Contrib 镜像版本 |
| `PHOENIX_VERSION` | `15` | 本地 Phoenix 镜像版本 |
| `LANGFUSE_VERSION` | `3` | 本地 Langfuse Web/Worker 镜像版本 |
| `LANGFUSE_POSTGRES_VERSION` | `15-alpine` | 本地 Langfuse Postgres 镜像版本 |
| `LANGFUSE_CLICKHOUSE_VERSION` | `26.3-alpine` | 本地 Langfuse ClickHouse 镜像版本 |
| `LANGFUSE_MINIO_VERSION` | `RELEASE.2023-12-20T01-00-02Z` | 本地 Langfuse MinIO 镜像版本 |
| `LANGFUSE_REDIS_VERSION` | `alpine` | 本地 Langfuse Redis 镜像版本 |
| `GRAFANA_VERSION` | `12.4` | 本地 Grafana 镜像版本 |
| `GRAFANA_PORT` | `3002` | 本地 Grafana UI 端口 |
| `GRAFANA_DEFAULT_LANGUAGE` | `zh-Hans` | 本地 Grafana 默认界面语言 |
| `TEMPO_VERSION` | `2.10.5` | 本地 Tempo 镜像版本，避免浮动 tag 带来的配置兼容性漂移 |
| `TEMPO_PORT` | `3200` | 本地 Tempo HTTP API 端口 |

### 配置文件

```yaml
monitoring:
  enable_telemetry: true
  service_name: nexent-backend
  project_name: nexent-production
  instrument_fastapi: true
  instrument_requests: false
  fastapi_excluded_urls: ""
  fastapi_exclude_spans: [receive, send]
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

前端顶栏监控入口只根据后端 `MONITORING_PROVIDER` 映射 UI 端口和路径，最终跳转地址由前端使用当前页面 URL 的 hostname 组装，避免固定写死 `localhost`：

- `phoenix` -> `${currentHostname}:${PHOENIX_PORT:-6006}/`
- `langfuse` -> `${currentHostname}:${LANGFUSE_PORT:-3001}/project/nexent`
- `jaeger` -> `${currentHostname}:${JAEGER_UI_PORT:-16686}/`
- `grafana` -> `${currentHostname}:${GRAFANA_PORT:-3002}/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1`
- `otlp` / `custom` 默认不显示顶栏监控入口

因此本地 Grafana 形态需要在后端 `.env` 中设置：

```bash
MONITORING_PROVIDER=grafana
```

### Phoenix

Phoenix 通过 OpenInference 属性识别 AI span 类型，核心字段是 `openinference.span.kind`。

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

当前实现会同时写入 `langfuse.observation.type`、`langfuse.session.id`、`langfuse.user.id`、`langfuse.trace.tags`、`langfuse.trace.metadata.*`、`langfuse.observation.input`、`langfuse.observation.output` 等属性，以便 Langfuse 正确展示 generation/tool/agent 并支持过滤聚合。

## 本地化部署设计

本地化部署通过 `docker/start-monitoring.sh` 选择形态。所有形态都保留 OpenTelemetry Collector 作为入口，Nexent 后端统一上报到 `http://otel-collector:4318` 或宿主机的 `http://localhost:4318`，平台差异只体现在 Collector exporter 和本地服务组合上。

| 形态 | Collector 配置 | 本地服务 | 数据去向 | 说明 |
|------|----------------|----------|----------|------|
| `collector` | `otel-collector-config.yml` | Collector | logging exporter | 最小形态，用于验证 span/metric 是否产生，或手动改配置转发到云端平台 |
| `phoenix` | `otel-collector-phoenix-config.yml` | Collector + Phoenix | `http://phoenix:6006/v1/traces` | Phoenix 容器同时提供 UI 和 OTLP HTTP/gRPC trace collector，适合本地 trace debug |
| `langfuse` | `otel-collector-langfuse-config.yml` | Collector + Langfuse Web/Worker + Postgres + ClickHouse + MinIO + Redis | `http://langfuse-web:3000/api/public/otel/v1/traces` | Langfuse v3 依赖多组件，适合完整 LLMOps 能力验证 |
| `grafana` | `otel-collector-grafana-config.yml` | Collector + Grafana + Tempo | traces 转发到 `tempo:4317`，metrics 只进入 Collector logging pipeline | Grafana + Tempo trace 查询 |

启动命令：

```bash
cd docker
./start-monitoring.sh --stack collector
./start-monitoring.sh --stack phoenix
./start-monitoring.sh --stack langfuse
./start-monitoring.sh --stack grafana
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

Langfuse v3 本地形态按自托管架构拆分为应用容器和存储组件：

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

### Grafana 本地形态

Grafana 本地形态面向 trace 调试：

| 组件 | 用途 |
|------|------|
| `grafana` | 展示 Nexent Agent trace dashboard，并预置 Tempo datasource |
| `tempo` | 接收 Collector 转发的 OTLP traces，并提供 Grafana Explore 查询后端 |

Collector trace pipeline 使用 `otlp/tempo` exporter 转发到 `tempo:4317`。Tempo 启用 `metrics-generator` 的 `local-blocks` processor，用于支持 Grafana trace breakdown 中的 TraceQL metrics 查询。Collector metrics pipeline 保留为 logging exporter，用于兼容后端仍开启 OTLP metrics 的场景，但本地 Grafana 形态不再提供 Prometheus 指标存储和指标 dashboard。

默认访问地址：

- Grafana：`http://localhost:3002`
- Tempo API：`http://localhost:3200`

## Span 语义映射

| Nexent 场景 | Phoenix / OpenInference | Langfuse |
|-------------|-------------------------|----------|
| Agent 入口 | `openinference.span.kind=AGENT` | `langfuse.observation.type=agent` |
| 服务准备、流式生成、线程执行、普通步骤 | `openinference.span.kind=CHAIN` | `langfuse.observation.type=chain` |
| LLM 调用 | `openinference.span.kind=LLM` | `langfuse.observation.type=generation` |
| 工具调用 | `openinference.span.kind=TOOL` | `langfuse.observation.type=tool` |
| 检索类调用 | `openinference.span.kind=RETRIEVER` | `langfuse.observation.type=retriever` |

上下文属性：

| 属性 | 说明 |
|------|------|
| `input.value` / `output.value` | OpenInference 输入输出 |
| `metadata` | OpenInference JSON metadata |
| `session.id` / `user.id` | OpenInference 会话和用户 |
| `tag.tags` | OpenInference tags |
| `langfuse.observation.input` / `langfuse.observation.output` | Langfuse observation 输入输出 |
| `langfuse.session.id` / `langfuse.user.id` | Langfuse 会话和用户 |
| `langfuse.trace.tags` | Langfuse trace tags |
| `langfuse.trace.metadata.*` / `langfuse.observation.metadata.*` | Langfuse 可过滤业务 metadata |

## 埋点信息

| 埋点 | 位置 | 类型 | 内容 | 目的 |
|------|------|------|------|------|
| FastAPI 自动 span | `MonitoringManager.setup_fastapi_app` | HTTP server | route、method、status、duration | API 入口耗时和错误定位 |
| FastAPI `receive/send` 排除 | `fastapi_exclude_spans` | 降噪配置 | 默认 `receive,send` | 避免 SSE 流式接口生成大量 `unknown POST /agent/run http ...` |
| requests 自动 span | `MonitoringConfig.instrument_requests` | HTTP client | 外部请求 URL、method、status | 默认关闭；需要分析外部 HTTP 依赖时开启 |
| `agent.run` | `backend/apps/agent_app.py` | AGENT | `/agent/run` 请求入口 | 作为一次 Agent 运行的顶层业务 trace |
| `agent_service.run_agent_stream` | `backend/services/agent_service.py` | CHAIN | `agent_id`、`conversation_id`、debug、文件数、记忆开关、策略、准备耗时 | 分析 SSE 创建前的准备阶段 |
| `set_openinference_agent_context` | `run_agent_stream` | 当前 span 上下文 | session、user、tenant、agent、metadata、tags | 给 Phoenix/Langfuse 建立 Agent、用户、会话维度 |
| `user_resolution.*` | `run_agent_stream` | event | 用户、租户、语言和耗时 | 鉴权与租户解析定位 |
| `user_message_save.*` | `run_agent_stream` | event | 保存或跳过原因、耗时 | 判断会话写入是否正常 |
| `memory_context_build.*` | `run_agent_stream` | event | 记忆开关、共享策略、耗时 | 定位记忆上下文瓶颈 |
| `streaming_strategy.*` | `run_agent_stream` | event | `with_memory` 或 `no_memory` | 判断实际执行分支 |
| `generate_stream_with_memory` | `backend/services/agent_service.py` | CHAIN | memory token、预处理任务、fallback 分支 | 追踪带记忆路径的流式执行 |
| `generate_stream_no_memory` | `backend/services/agent_service.py` | CHAIN | 准备与流式输出事件 | 追踪无记忆流式执行 |
| `agent_run` | `sdk/nexent/core/agents/run_agent.py` | CHAIN | 线程启动、缓存读取、消息 yield | 追踪 Agent 异步 generator 消费过程 |
| `agent_run_thread` | `sdk/nexent/core/agents/run_agent.py` | CHAIN | Agent 创建、MCP 工具装载、执行错误 | 追踪实际 Agent 执行线程 |
| `{display_name or model_id}.generate` | `sdk/nexent/core/models/openai_llm.py` | LLM / generation | 模型、温度、top_p、消息、输入输出、token、TTFT、chunk 数 | LLM 性能、成本、输出和异常分析 |
| `python_interpreter` | `sdk/nexent/core/agents/core_agent.py` | TOOL | 生成代码、step number、执行输出、日志、是否最终答案 | 观测 CodeAgent 解释器执行 |
| 真实工具名 | `sdk/nexent/core/agents/nexent_agent.py` | TOOL | local/MCP/langchain/builtin 工具输入输出 | 观测真实工具可用性、延迟、错误和输入输出 |
| `FinalAnswerTool` | `sdk/nexent/core/agents/core_agent.py` | TOOL | 最终答案输出 | 让 Phoenix/Langfuse 中能明确看到最终答案节点 |
| `trace_agent` / `trace_chain` / `trace_retriever` | SDK 公共 API | AGENT / CHAIN / RETRIEVER | 自定义输入输出、metadata、tags、session、user | SDK 用户自定义层级埋点 |
| `trace_tool_call` | SDK 公共 API | TOOL | 工具名、输入、输出、耗时、错误 | SDK 用户自定义工具埋点 |

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
| LLM span | `completion_started` / `first_token_received` / `token_generated` / `completion_finished` / `model_stopped` / `error_occurred` | `model_id`、`temperature`、`top_p`、`message_count`、`total_duration`、`output_length`、`chunk_count`、`error.*` | 分析模型参数、流式输出耗时、停止和异常 |
| Tool span | span 属性 `agent.tool.input` / `agent.tool.output` | JSON 字符串、`agent.tool.duration_ms`、`error.*` | 分析工具输入输出、耗时和异常 |

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
  API --> HTTP[FastAPI HTTP span: 可配置隐藏]
  HTTP --> A0[agent.run span: AGENT]
  A0 --> S1[agent_service.run_agent_stream: CHAIN]
  S1 --> R[user_resolution events]
  S1 --> Save[user_message_save events]
  S1 --> Mem[memory_context_build events]
  Mem --> Strategy{streaming_strategy}
  Strategy -->|with_memory| G1[generate_stream_with_memory: CHAIN]
  Strategy -->|no_memory| G2[generate_stream_no_memory: CHAIN]
  G1 --> AR[agent_run async generator: CHAIN]
  G2 --> AR
  AR --> Thread[agent_run_thread: CHAIN]
  Thread --> NX[NexentAgent / CoreAgent]
  NX --> Step[Agent step / code action]
  Step --> LLM[Model.generate: LLM / generation]
  Step --> PY[python_interpreter: TOOL]
  PY --> Tool[Real local / MCP / langchain / builtin tool: TOOL]
  PY --> Final[FinalAnswerTool: TOOL]
  LLM --> Attr1[OpenInference + Langfuse attrs]
  Tool --> Attr1
  Final --> Attr1
  Attr1 --> OTel[OpenTelemetry Tracer/Meter Provider]
  OTel --> Collector[OTLP Collector]
  Collector --> Phoenix[Phoenix]
  Collector --> Langfuse[Langfuse]
  Collector --> Tempo[Grafana Tempo]
  Collector --> Other[Jaeger / Custom Backend]
```

预期平台树形结构：

```text
agent.run                         agent
└─ agent_service.run_agent_stream chain
   └─ agent_service.generate_*    chain
      └─ agent_run                chain
         └─ agent_run_thread      chain
            ├─ Model.generate     llm / generation
            ├─ python_interpreter tool
            │  └─ RealTool        tool
            └─ FinalAnswerTool    tool
```

FastAPI HTTP span 可以保留在最上层用于接口视角，也可以通过 `MONITORING_FASTAPI_EXCLUDED_URLS=/agent/run` 在 AI trace 视图中隐藏。

## 监控页面结构

```mermaid
flowchart TB
  Page[Agent 监控页] --> Filters[筛选区: 时间 / 租户 / 用户 / Agent / 会话 / 模型 / 状态]
  Page --> KPIs[指标区: 成功率 / P95 / TTFT / tokens/s / token 成本 / 工具错误数]
  Page --> TraceList[Trace 列表: Agent / 会话 / 用户 / 状态 / 耗时 / Token / 模型 / 最后错误]
  Page --> Detail[Trace 详情]
  Detail --> Waterfall[Span 瀑布图: agent / chain / llm / tool]
  Detail --> Timeline[Agent 时间线: 准备 / 记忆 / LLM / 工具 / 最终答案]
  Detail --> LLMPanel[LLM 面板: prompt / output / token / TTFT / generation rate]
  Detail --> ToolPanel[工具面板: 工具名 / 输入 / 输出 / 耗时 / 错误]
  Detail --> Session[会话和用户上下文]
  Detail --> Raw[原始 OTel 属性和 events]
  Detail --> Eval[反馈、评分和评估]
```

与 Phoenix 和 Langfuse 对比：

| 方案 | 优点 | 不足 | Nexent 当前适配 |
|------|------|------|----------------|
| Phoenix | OpenInference 生态匹配好，适合 trace debug、实验、评估；`phoenix.otel` 可降低接入成本 | Nexent 的租户、权限、Agent 配置需要通过属性映射；HTTP 自动 span 容易产生 `unknown` 噪声 | 写入 `openinference.span.kind`、`input.value`、`output.value`、`metadata`、`session.id`、`user.id`，并支持 FastAPI 降噪 |
| Langfuse | Trace、session、user、prompt、evaluation、dashboard 能力完整，适合 LLMOps 闭环 | 需要 `langfuse.*` 属性才能获得更好的 observation 类型、用户、会话和 metadata 聚合 | 写入 `langfuse.observation.type`、`langfuse.session.id`、`langfuse.user.id`、`langfuse.trace.metadata.*`、`langfuse.observation.input/output` |
| Nexent 自建页 | 可直接关联租户、会话、Agent 配置、权限、版本和业务动作，适合产品内闭环 | 需要自建 trace 存储、查询、聚合、瀑布图、权限隔离和成本统计 | 当前先通过 OTLP 对接外部平台，后续可基于同一批属性构建自有页面 |

推荐路径：

1. 短期使用 OTLP 对接 Phoenix/Langfuse，满足调试和分析。
2. 中期在 Nexent 增加 trace 跳转、轻量指标概览和异常聚合。
3. 长期按租户、会话、Agent 版本建立自有监控页，同时保留 OTLP 双写能力。

## 已修复的设计风险

| 风险 | 修复 |
|------|------|
| async generator span 提前结束 | `monitor_endpoint` 使用 `inspect.isasyncgenfunction`，在 `async for` 消费期间保持 span 打开 |
| `/v1/traces` 路径重复拼接 | SDK 支持 base endpoint 和 signal endpoint 自动归一化 |
| Collector header 无法兼容平台 | Collector 默认只 logging；平台转发配置拆分 `Authorization`、`x-api-key`、`x-langfuse-ingestion-version` |
| Phoenix 只看到接口看不到 Agent | 顶层 `agent.run` 标记为 AGENT，内部服务、线程、generator 标记为 CHAIN |
| Phoenix/Langfuse 中出现大量 `unknown POST /agent/run http ...` | 默认排除 FastAPI ASGI `receive/send` span；requests 自动埋点默认关闭；可配置隐藏 `/agent/run` HTTP span |
| Langfuse 无法识别 observation 类型 | 增加 `langfuse.observation.type` 和 trace/session/user/metadata/input/output 属性 |
| LLM span 不明显或缺输出 | LLM span 命名为 `{display_name or model_id}.generate`，并写入 `output.value` 和 `langfuse.observation.output` |
| 工具 span 缺失 | 在 `NexentAgent.create_single_agent` 统一包装 local/MCP/langchain/builtin 工具，并在 `CoreAgent` 增加 `python_interpreter` 和 `FinalAnswerTool` span |
| 单测漏掉流式函数 | 增加 async generator 装饰器测试和 OpenInference/Langfuse 属性测试 |

## 使用建议

只看 Agent 业务链路时：

```bash
MONITORING_INSTRUMENT_FASTAPI=true
MONITORING_FASTAPI_EXCLUDE_SPANS=receive,send
MONITORING_FASTAPI_EXCLUDED_URLS=/agent/run
MONITORING_INSTRUMENT_REQUESTS=false
```

同时看接口入口和 Agent 业务链路时：

```bash
MONITORING_INSTRUMENT_FASTAPI=true
MONITORING_FASTAPI_EXCLUDE_SPANS=receive,send
MONITORING_FASTAPI_EXCLUDED_URLS=
MONITORING_INSTRUMENT_REQUESTS=false
```

需要排查外部 HTTP 依赖时：

```bash
MONITORING_INSTRUMENT_REQUESTS=true
```

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
