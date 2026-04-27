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
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http

docker-compose -f docker-compose-monitoring.yml up -d
```

## AI 可观测性平台对接

### Arize Phoenix

Arize Phoenix 提供针对 AI 的专业可观测性，原生支持 OpenInference 语义。

**配置：**

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://phoenix.arize.com/v1
OTEL_EXPORTER_OTLP_HEADERS=x-api-key=YOUR_PHOENIX_API_KEY
OTEL_EXPORTER_OTLP_PROTOCOL=http
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
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1

LANGFUSE_PUBLIC_KEY=pk-xxx
LANGFUSE_SECRET_KEY=sk-xxx

OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic BASE64_ENCODED_KEY
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
| `OTEL_SERVICE_NAME` | `nexent-backend` | 服务标识 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP 接收端点 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http` | 协议：`http` 或 `grpc` |
| `OTEL_EXPORTER_OTLP_HEADERS` | （空） | 认证头（逗号分隔） |

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

OpenTelemetry Collector 将数据路由到选定的后端：

```yaml
exporters:
  otlp:
    endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT}
    headers:
      authorization: ${OTEL_EXPORTER_OTLP_HEADERS}
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