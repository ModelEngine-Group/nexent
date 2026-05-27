# Nexent Agent 可观测性（OTLP）

基于 OpenTelemetry OTLP 协议的 AI Agent 企业级可观测性方案。支持对接 Arize Phoenix、Langfuse、LangSmith、Grafana Tempo、Zipkin 等可观测性平台。

## 系统架构

```
NexentAgent ──► OpenTelemetry SDK ──► OTLP Collector ──► Arize Phoenix / Langfuse / LangSmith / Grafana Tempo / Zipkin / OTLP Backend
     │                                        │
     │   OpenInference 语义约定                │
     │   (llm.*, agent.* 属性)                 │
     └────────────────────────────────────────┘
```

## 快速启动

```bash
cd docker
[ -f .env ] || cp .env.example .env
cp monitoring/monitoring.env.example monitoring/monitoring.env

vim .env
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http

vim monitoring/monitoring.env
MONITORING_PROVIDER=otlp

./start-monitoring.sh --stack collector
```

## 本地化部署形态

`docker/start-monitoring.sh` 支持多种形态，均以 OpenTelemetry Collector 作为统一入口。业务服务只需要把 OTLP 发到 Collector，不需要感知后端平台差异。

| 形态 | 命令 | 包含服务 | 适用场景 |
|------|------|----------|----------|
| `collector` | `./start-monitoring.sh --stack collector` | OpenTelemetry Collector | 只验证埋点、或转发到外部云端平台 |
| `phoenix` | `./start-monitoring.sh --stack phoenix` | Collector + Phoenix | 本地 trace 调试、OpenInference 属性查看、实验分析 |
| `langfuse` | `./start-monitoring.sh --stack langfuse` | Collector + Langfuse Web/Worker + Postgres + ClickHouse + MinIO + Redis | 本地完整 LLMOps 体验、会话/用户/反馈/成本分析 |
| `langsmith` | `./start-monitoring.sh --stack langsmith` | OpenTelemetry Collector | 转发 traces 到在线 LangSmith 平台 |
| `grafana` | `./start-monitoring.sh --stack grafana` | Collector + Grafana + Tempo | 本地 Tempo trace 查询 |
| `zipkin` | `./start-monitoring.sh --stack zipkin` | Collector + Zipkin | 本地 trace 查询 |

也可以在 `docker/monitoring/monitoring.env` 中设置默认形态：

```bash
MONITORING_PROVIDER=phoenix
```

### 本地 Phoenix

Phoenix 本地部署使用 `arizephoenix/phoenix` 镜像，默认 UI 端口为 `6006`，gRPC OTLP 端口映射为 `4319`，数据持久化到 Docker volume `phoenix-data`。

```bash
cd docker
./start-monitoring.sh --stack phoenix
```

访问地址：

- Phoenix UI：`http://localhost:6006`
- Collector OTLP HTTP：`http://localhost:4318`
- Collector OTLP gRPC：`localhost:4317`

Nexent 后端在 Docker 网络内运行时：

```bash
ENABLE_TELEMETRY=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

后端直接在宿主机运行时，把 endpoint 改为 `http://localhost:4318`。

### 本地 Langfuse

Langfuse 本地部署使用 v3 架构：Web、Worker、Postgres、ClickHouse、MinIO、Redis。默认 UI 端口为 `3001`，初始化项目和 API Key 来自 `monitoring.env`。

```bash
cd docker
./start-monitoring.sh --stack langfuse
```

访问地址：

- Langfuse UI：`http://localhost:3001`
- 默认管理员：`admin@nexent.local` / `nexent-langfuse-admin`
- 默认项目 Key：`pk-lf-nexent-local` / `sk-lf-nexent-local`

启动脚本会在 `LANGFUSE_OTLP_AUTH_HEADER` 为空时自动生成 `Basic base64(public_key:secret_key)`，并让 Collector 将 trace 转发到 `http://langfuse-web:3000/api/public/otel`。本地默认密钥只适合开发验证，生产部署必须替换 `LANGFUSE_NEXTAUTH_SECRET`、`LANGFUSE_SALT`、`LANGFUSE_ENCRYPTION_KEY`、数据库密码和对象存储密钥。

### 在线 LangSmith

LangSmith 支持通过在线 OTLP endpoint 摄取 traces。Nexent 可以先把 OTLP 发到本地 Collector，再由 Collector 转发到 LangSmith，业务服务无需直接保存 LangSmith API Key。

```bash
cd docker
vim monitoring/monitoring.env

MONITORING_PROVIDER=langsmith
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=nexent
LANGSMITH_OTLP_TRACES_ENDPOINT=https://api.smith.langchain.com/otel/v1/traces

./start-monitoring.sh --stack langsmith
```

后端在 Docker 网络内运行时：

```bash
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=langsmith
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

LangSmith 当前配置只转发 traces，OTLP metrics 会留在 Collector debug pipeline。若需要后端直接写入 LangSmith，可设置 `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.smith.langchain.com/otel`、`LANGSMITH_API_KEY` 和可选的 `LANGSMITH_PROJECT`。

### 本地 Grafana + Tempo

Grafana 本地部署使用 Grafana Tempo 存储 traces，并启用 Tempo `metrics-generator` 的 `local-blocks` processor 支持 Grafana trace breakdown 中的 TraceQL metrics 查询。Collector 接收 Nexent 后端的 OTLP traces/metrics，其中 traces 通过 OTLP gRPC 转发到 Tempo；OTLP metrics 只进入 Collector debug pipeline，不提供独立指标存储或指标 dashboard。

```bash
cd docker
./start-monitoring.sh --stack grafana
```

后端 `.env` 使用 `MONITORING_DASHBOARD_URL` 控制前端顶栏监控入口：

```bash
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=grafana
MONITORING_DASHBOARD_URL=http://localhost:3002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
```

访问地址：

- Grafana UI：`http://localhost:3002`
- 默认管理员：`admin` / `nexent-grafana-admin`
- Tempo API：`http://localhost:3200`

Grafana 会自动预置 Tempo datasource，并加载 `Nexent Agent Trace Monitoring` dashboard。Trace 查询入口在 Grafana Explore 中选择 `Tempo` datasource，示例 TraceQL 为 `{ resource.service.name = "nexent-backend" }`。

### 本地 Zipkin

Zipkin 本地部署使用 `openzipkin/zipkin` 镜像。Collector 接收 Nexent 后端的 OTLP traces/metrics，其中 traces 转发到 Zipkin v2 spans endpoint；OTLP metrics 当前只进入 Collector debug pipeline。

```bash
cd docker
./start-monitoring.sh --stack zipkin
```

后端 `.env`：

```bash
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=zipkin
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
MONITORING_DASHBOARD_URL=http://localhost:9411
```

访问地址：

- Zipkin UI：`http://localhost:9411`

## AI 可观测性平台对接

### Arize Phoenix

Arize Phoenix 提供针对 AI 的专业可观测性，原生支持 OpenInference 语义。

**配置：**

```bash
MONITORING_PROVIDER=phoenix
OTEL_EXPORTER_OTLP_ENDPOINT=https://app.phoenix.arize.com/s/YOUR_SPACE
OTEL_EXPORTER_OTLP_AUTHORIZATION="Bearer YOUR_PHOENIX_API_KEY"
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

**功能特性：**
- LLM 调用链可视化（Prompt/Completion）
- Token 级性能指标
- Agent 步骤追踪
- 成本分析

### Langfuse

Langfuse 提供 Prompt 管理和 LLM 可观测性，支持 OTLP 协议。

**配置：**

```bash
MONITORING_PROVIDER=langfuse
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel

LANGFUSE_PUBLIC_KEY=pk-xxx
LANGFUSE_SECRET_KEY=sk-xxx

OTEL_EXPORTER_OTLP_AUTHORIZATION=Basic BASE64_ENCODED_KEY
OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION=4
```

生成认证 Key：

```bash
echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64
```

**功能特性：**
- Prompt 版本管理
- 会话级 Trace 分组
- 用户反馈收集
- 模型成本追踪

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_TELEMETRY` | `false` | 启用/禁用监控 |
| `MONITORING_PROVIDER` | `otlp` | 平台配置和本地部署形态：`otlp`、`phoenix`、`langfuse`、`langsmith`、`grafana`、`zipkin` |
| `MONITORING_DASHBOARD_URL` | （空） | 前端顶栏监控入口跳转 URL，需配置为浏览器可访问地址 |
| `MONITORING_PROJECT_NAME` | `nexent` | 监控平台项目名 |
| `MONITORING_TRACE_CONTENT_MODE` | `summary` | Trace payload 记录模式：`summary` 写入有界预览和结构元数据，`metrics` 只写结构/大小元数据，`full` 在 `MONITORING_TRACE_MAX_CHARS` 限制内保留完整 payload |
| `MONITORING_TRACE_MAX_CHARS` | `4000` | 每个 payload 预览最多写入的字符数 |
| `MONITORING_TRACE_MAX_ITEMS` | `20` | dict/list 预览最多写入的 key 或 item 数 |
| `OTEL_SERVICE_NAME` | `nexent-backend` | 服务标识 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP base endpoint，SDK 会派生 `/v1/traces` 和 `/v1/metrics` |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | （空） | 可选 trace 专用 endpoint |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | （空） | 可选 metric 专用 endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http` | 协议：`http` 或 `grpc` |
| `OTEL_EXPORTER_OTLP_HEADERS` | （空） | 通用认证头（逗号分隔） |
| `OTEL_EXPORTER_OTLP_AUTHORIZATION` | （空） | `Authorization` header，常用于 Phoenix bearer auth 和 Langfuse |
| `OTEL_EXPORTER_OTLP_X_API_KEY` | （空） | `x-api-key` header，用于兼容需要该 header 的平台 |
| `OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION` | （空） | Langfuse 实时摄取版本，例如 `4` |
| `OTEL_EXPORTER_OTLP_METRICS_ENABLED` | `true` | 是否导出 OTLP metrics |
| `LANGSMITH_API_KEY` | （空） | LangSmith API Key，会映射为 OTLP `x-api-key` header |
| `LANGSMITH_PROJECT` | （空） | 可选 LangSmith project header |
| `LANGSMITH_OTLP_TRACES_ENDPOINT` | `https://api.smith.langchain.com/otel/v1/traces` | Collector 转发到在线 LangSmith 的 trace endpoint |
| `MONITORING_INSTRUMENT_REQUESTS` | `false` | 是否启用 requests 自动 HTTP client span；默认关闭，避免 AI trace 被普通 HTTP 请求刷屏 |
| `MONITORING_FASTAPI_EXCLUDED_URLS` | （空） | FastAPI 自动埋点排除 URL，逗号分隔正则；例如只看 agent 业务 span 时可设为 `/agent/run` |
| `MONITORING_FASTAPI_EXCLUDE_SPANS` | `receive,send` | 排除 ASGI 内部 `receive/send` span；流式接口建议保持默认值 |
| `OTEL_COLLECTOR_VERSION` | `0.150.0` | 本地 OpenTelemetry Collector Contrib 镜像版本 |
| `PHOENIX_VERSION` | `15` | 本地 Phoenix 镜像版本 |
| `LANGFUSE_VERSION` | `3` | 本地 Langfuse Web/Worker 镜像版本 |
| `LANGFUSE_POSTGRES_VERSION` | `15-alpine` | 本地 Langfuse Postgres 镜像版本 |
| `LANGFUSE_CLICKHOUSE_VERSION` | `26.3-alpine` | 本地 Langfuse ClickHouse 镜像版本 |
| `LANGFUSE_MINIO_VERSION` | `RELEASE.2023-12-20T01-00-02Z` | 本地 Langfuse MinIO 镜像版本 |
| `LANGFUSE_REDIS_VERSION` | `alpine` | 本地 Langfuse Redis 镜像版本 |
| `GRAFANA_VERSION` | `12.4` | 本地 Grafana 镜像版本 |
| `GRAFANA_PORT` | `3002` | 本地 Grafana UI 端口 |
| `GRAFANA_ADMIN_USER` | `admin` | 本地 Grafana 管理员用户名 |
| `GRAFANA_ADMIN_PASSWORD` | `nexent-grafana-admin` | 本地 Grafana 管理员密码 |
| `GRAFANA_DEFAULT_LANGUAGE` | `zh-Hans` | 本地 Grafana 默认界面语言 |
| `TEMPO_VERSION` | `2.10.5` | 本地 Tempo 镜像版本，避免浮动 tag 带来的配置兼容性漂移 |
| `TEMPO_PORT` | `3200` | 本地 Tempo HTTP API 端口 |
| `ZIPKIN_VERSION` | `latest` | 本地 Zipkin 镜像版本 |
| `ZIPKIN_PORT` | `9411` | 本地 Zipkin UI/API 端口 |

## 代码集成

### Agent 边界上下文

业务层只需要在请求入口解析出用户和 Agent 信息后绑定一次上下文，后续 Agent、LLM、Tool span 由 SDK 生命周期自动生成：

```python
from nexent.monitor.agent_observability import AgentRunMetadata
from utils.monitoring import monitoring_manager

monitoring_manager.bind_agent_context(AgentRunMetadata(
    tenant_id=tenant_id,
    user_id=user_id,
    agent_id=agent_request.agent_id,
    conversation_id=agent_request.conversation_id,
    query=agent_request.query,
    is_debug=agent_request.is_debug,
    language=language,
))
```

`monitor_endpoint` 仍保留为兼容 API 和低层 escape hatch，不建议业务层新增常规埋点时继续使用。

### Trace Payload 策略

工具输入输出、检索输出，以及 OpenInference 的 `input.value` / `output.value` 属性统一使用同一套 payload 策略。默认写入有界预览，并额外写入 `type`、`size_chars`、`item_count`、`truncated`、`keys` 等结构化属性。记忆检索 span 只记录结果摘要和统计信息，不写完整 memory 正文。

Agent 上下文指标由 SDK 生命周期自动写入。每个 action step 会产生 `agent.step.metrics` event，包含上下文 token 估算、压缩调用数、缓存命中、压缩率和 token 阈值。Agent 结束时还会在顶层 span 写入聚合 step 数、最大上下文 token、平均压缩率、压缩调用总数和缓存命中总数。

### LLM 调用监控

```python
@monitoring_manager.monitor_llm_call("gpt-4", "chat_completion")
def call_llm(messages):
    return llm_response
```

### Agent 步骤追踪

```python
with monitoring_manager.trace_agent_step("web_search", step_type="tool_call") as span:
    result = execute_tool()
    monitoring_manager.set_tool_output(result)
```

### 工具调用追踪

```python
with monitoring_manager.trace_tool_call("web_search", "agent_name", {"query": "test"}) as span:
    results = search_web("test")
    monitoring_manager.set_tool_output({"results": results})
```

### Phoenix 自定义层级埋点

如果希望 Phoenix 展示 `agent -> chain -> llm/retriever/tool` 的层级结构，使用 SDK Agent 生命周期入口和 OpenInference span kind 封装方法：

```python
from nexent.monitor.agent_observability import AgentRunMetadata, get_monitoring_manager

monitoring_manager = get_monitoring_manager()

metadata = AgentRunMetadata(
    tenant_id="tenant_id",
    user_id="user_id",
    agent_id=1,
    conversation_id=1001,
    agent_name="TestAgent",
    query="你好",
)

with monitoring_manager.start_agent_run(metadata):
    with monitoring_manager.trace_agent_step("Step 0", metadata, step_type="agent_loop"):
        with monitoring_manager.trace_llm_request("OpenAIModel.generate", "gpt-4"):
            result = call_llm()

        with monitoring_manager.trace_retriever_call(
            "knowledge_base_search",
            "TestAgent",
            {"query": "你好"},
        ):
            documents = search_knowledge_base("你好")
            monitoring_manager.set_retriever_output(documents)

        with monitoring_manager.trace_tool_call("FinalAnswerTool", "TestAgent", {"query": "你好"}):
            monitoring_manager.set_tool_output({"answer": result})

        monitoring_manager.set_openinference_output({"answer": result})
```

Phoenix 左侧的 `agent`、`chain`、`llm`、`retriever`、`tool` 标签来自 `openinference.span.kind`。span 必须通过嵌套 `with` 创建，Phoenix 才会显示成树形结构。

同一套方法只写入通用 OpenInference / Nexent 属性，不再写入 Langfuse 专用 span 字段。Langfuse provider 仍通过 OTLP endpoint 接收 trace，但展示和过滤以通用 OTLP/OpenInference 属性为准。

## OpenInference 语义属性

系统使用 OpenInference 语义约定，专为 AI 可观测性设计：

### LLM 属性

| 属性 | 说明 |
|------|------|
| `llm.model_name` | 模型标识（如 `gpt-4`） |
| `llm.operation.name` | 操作类型（如 `chat_completion`） |
| `llm.token_count.prompt` | 输入 Token 数 |
| `llm.token_count.completion` | 输出 Token 数 |
| `llm.invocation_parameters` | 模型参数（JSON） |
| `llm.time_to_first_token` | TTFT（秒） |

### Agent 属性

| 属性 | 说明 |
|------|------|
| `agent.name` | Agent 标识 |
| `agent.step.name` | 步骤名称（如 `web_search`） |
| `agent.step.type` | 步骤类型：`tool_call`、`reasoning`、`action_selection` |
| `agent.tool.name` | 工具名称 |
| `agent.tool.input` | 按 trace payload 策略处理后的工具输入预览 |
| `agent.tool.input.*` | 工具输入结构化元数据：类型、大小、item 数、截断状态、keys |
| `agent.tool.output` | 按 trace payload 策略处理后的工具输出预览 |
| `agent.tool.output.*` | 工具输出结构化元数据：类型、大小、item 数、截断状态、keys |
| `agent.tool.success` | 工具调用是否成功 |
| `agent.tool.duration_ms` | 工具调用耗时 |
| `retriever.name` | 检索器名称 |
| `retrieval.query` | 检索查询 |
| `retrieval.results.count` | 检索结果数量 |
| `retrieval.top_score` | 可用时记录最高检索分数 |
| `retriever.input.*` | 检索输入结构化元数据 |
| `retriever.output` | 按 trace payload 策略处理后的检索输出预览 |
| `retriever.output.*` | 检索输出结构化元数据 |
| `context.tokens.estimated_input` | 每个 Agent step event 的上下文输入 token 估算 |
| `context.tokens.uncompressed_estimated` | 每个 Agent step event 的未压缩上下文 token 估算 |
| `context.compression.calls` | 每个 Agent step event 的压缩调用数 |
| `context.compression.cache_hits` | 每个 Agent step event 的压缩缓存命中数 |
| `context.compression.ratio` | 每个 Agent step event 的压缩率 |

## 指标

| 指标 | 说明 |
|------|------|
| `llm.request.duration` | 请求延迟 |
| `llm.token.generation_rate` | Token 生成速率 |
| `llm.time_to_first_token` | TTFT |
| `llm.token_count.prompt` | 输入 Token |
| `llm.token_count.completion` | 输出 Token |
| `agent.step.count` | Agent 步骤数 |
| `agent.execution.duration` | Agent 执行时间 |
| `agent.error.count` | Agent 错误数 |

## Collector 配置

OpenTelemetry Collector 默认只通过 debug exporter 打印数据，避免没有外部后端时把数据转发回自身。需要通过 Collector 转发到平台时，增加对应 exporter：

```yaml
exporters:
  otlphttp/langsmith:
    traces_endpoint: https://api.smith.langchain.com/otel/v1/traces
    headers:
      x-api-key: YOUR_LANGSMITH_API_KEY
      Langsmith-Project: nexent

service:
  pipelines:
    traces:
      exporters: [otlphttp/langsmith, debug]
```

本地 Phoenix 和 Langfuse 分别使用独立 Collector 配置：

- `docker/monitoring/otel-collector-phoenix-config.yml`
- `docker/monitoring/otel-collector-langfuse-config.yml`
- `docker/monitoring/otel-collector-langsmith-config.yml`

基础 debug 配置见 `docker/monitoring/otel-collector-config.yml`。

## 优雅降级

未安装 OpenTelemetry 依赖时，监控自动禁用：

```python
pip install nexent          # 基础包 - 无监控
pip install nexent[performance]  # 包含 OTLP 支持
```

禁用时所有监控方法均正常工作 - 装饰器透传，上下文管理器返回 None。

## 故障排除

### 数据未显示

1. 检查 `.env` 中 `ENABLE_TELEMETRY=true`
2. 验证 OTLP 端点可访问
3. 检查认证头配置正确

### 连接错误

1. 测试端点：`curl -v $OTEL_EXPORTER_OTLP_ENDPOINT/v1/traces`
2. 确认协议匹配端点（`http` vs `grpc`）
3. 查看 Collector 日志：`docker logs nexent-otel-collector`

### 属性错误

1. 在平台 UI 中验证 OpenInference 属性
2. 检查 Span 属性命名：使用 `llm.model_name` 而非 `model_name`
3. 查看平台特定属性要求
