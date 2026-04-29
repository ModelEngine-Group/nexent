# Nexent Agent 可观测性（OTLP）

基于 OpenTelemetry OTLP 协议的 AI Agent 企业级可观测性方案。支持对接 Arize Phoenix、Langfuse 等主流 AI 可观测性平台。

## 系统架构

```
NexentAgent ──► OpenTelemetry SDK ──► OTLP Collector ──► Arize Phoenix / Langfuse / Jaeger
     │                                        │
     │   OpenInference 语义约定                │
     │   (llm.*, agent.* 属性)                 │
     └────────────────────────────────────────┘
```

## 快速启动

```bash
cd docker
cp .env.example .env

vim .env
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http

docker-compose -f docker-compose-monitoring.yml up -d
```

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

如果希望使用 Phoenix 官方 SDK 负责部分 OpenTelemetry 初始化，可额外启用。启用后 SDK 返回的 tracer provider 会被复用，避免重复注册 OpenTelemetry 全局 provider：

```bash
MONITORING_USE_PLATFORM_SDK=true
MONITORING_PROJECT_NAME=nexent-production
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

### 本地 Jaeger（OTLP）

本地开发可继续使用 Jaeger，通过 OTLP 协议对接。

**配置：**

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
```

**Docker 配置：**

```yaml
jaeger:
  image: jaegertracing/all-in-one:1.52
  environment:
    - COLLECTOR_OTLP_ENABLED=true
  ports:
    - "16686:16686"
    - "4318:4318"
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_TELEMETRY` | `false` | 启用/禁用监控 |
| `MONITORING_CONFIG_FILE` | （空） | JSON/YAML 监控配置文件路径 |
| `MONITORING_PROVIDER` | `otlp` | 平台配置：`otlp`、`phoenix`、`langfuse`、`jaeger`、`custom` |
| `MONITORING_USE_PLATFORM_SDK` | `false` | 是否额外初始化平台 SDK |
| `MONITORING_PROJECT_NAME` | `nexent` | 监控平台项目名 |
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

## 配置文件

除环境变量外，也可以通过 `MONITORING_CONFIG_FILE` 指定 JSON/YAML 文件。环境变量中显式设置的非默认值会覆盖文件配置。

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
    export_metrics: false
```

## 代码集成

### 端点监控

```python
from utils.monitoring import monitoring_manager

@monitoring_manager.monitor_endpoint("my_service.my_function")
async def my_api_function():
    return {"status": "ok"}
```

### LLM 调用监控

```python
@monitoring_manager.monitor_llm_call("gpt-4", "chat_completion")
def call_llm(messages):
    return llm_response
```

### Agent 步骤追踪

```python
with monitoring_manager.trace_agent_step("web_search", "research_agent", "tool_call") as span:
    result = execute_tool()
    monitoring_manager.set_tool_output(result)
```

### 工具调用追踪

```python
with monitoring_manager.trace_tool_call("web_search", "agent_name", {"query": "test"}) as span:
    results = search_web("test")
    monitoring_manager.set_tool_output({"results": results})
```

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
| `agent.tool.input` | 工具输入（JSON） |
| `agent.tool.output` | 工具输出（JSON） |

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

OpenTelemetry Collector 默认只通过 logging exporter 打印数据，避免没有外部后端时把数据转发回自身。需要通过 Collector 转发到平台时，增加对应 exporter：

```yaml
exporters:
  otlphttp/langfuse:
    endpoint: https://cloud.langfuse.com/api/public/otel
    headers:
      Authorization: Basic BASE64_ENCODED_KEY
      x-langfuse-ingestion-version: "4"

service:
  pipelines:
    traces:
      exporters: [otlphttp/langfuse, logging]
```

完整配置见 `docker/monitoring/otel-collector-config.yml`。

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
