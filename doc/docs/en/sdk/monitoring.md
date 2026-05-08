# Nexent Agent Observability (OTLP)

Enterprise-grade observability for AI agents using OpenTelemetry OTLP protocol. Supports integration with AI observability platforms like Arize Phoenix, Langfuse, and more.

## Architecture

```
NexentAgent ──► OpenTelemetry SDK ──► OTLP Collector ──► Arize Phoenix / Langfuse / Grafana Tempo / OTLP Backend
     │                                        │
     │   OpenInference Semantics              │
     │   (llm.*, agent.* attributes)          │
     └────────────────────────────────────────┘
```

## Quick Start

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

## AI Observability Platforms

### Arize Phoenix

Arize Phoenix provides AI-specific observability with OpenInference semantic support.

**Configuration:**

```bash
MONITORING_PROVIDER=phoenix
OTEL_EXPORTER_OTLP_ENDPOINT=https://app.phoenix.arize.com/s/YOUR_SPACE
OTEL_EXPORTER_OTLP_AUTHORIZATION="Bearer YOUR_PHOENIX_API_KEY"
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

**Features:**
- LLM trace visualization with prompt/completion
- Token-level performance metrics
- Agent step tracing
- Cost analysis

### Langfuse

Langfuse offers prompt management and LLM observability with OTLP support.

**Configuration:**

```bash
MONITORING_PROVIDER=langfuse
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel

LANGFUSE_PUBLIC_KEY=pk-xxx
LANGFUSE_SECRET_KEY=sk-xxx

OTEL_EXPORTER_OTLP_AUTHORIZATION=Basic BASE64_ENCODED_KEY
OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION=4
```

Generate the encoded key:

```bash
echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64
```

**Features:**
- Prompt versioning and management
- Session-based trace grouping
- User feedback collection
- Model cost tracking

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_TELEMETRY` | `false` | Enable/disable monitoring |
| `MONITORING_PROVIDER` | `otlp` | Provider profile: `otlp`, `phoenix`, `langfuse`, `grafana` |
| `MONITORING_PROJECT_NAME` | `nexent` | Observability platform project name |
| `OTEL_SERVICE_NAME` | `nexent-backend` | Service identifier |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP base endpoint; SDK derives `/v1/traces` and `/v1/metrics` |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | (empty) | Optional trace-specific endpoint |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | (empty) | Optional metric-specific endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http` | Protocol: `http` or `grpc` |
| `OTEL_EXPORTER_OTLP_HEADERS` | (empty) | Generic auth headers (comma-separated) |
| `OTEL_EXPORTER_OTLP_AUTHORIZATION` | (empty) | `Authorization` header, commonly used by Phoenix bearer auth and Langfuse |
| `OTEL_EXPORTER_OTLP_X_API_KEY` | (empty) | `x-api-key` header for platforms that require it |
| `OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION` | (empty) | Langfuse ingestion version, for example `4` |
| `OTEL_EXPORTER_OTLP_METRICS_ENABLED` | `true` | Whether to export OTLP metrics |

## Code Integration

### Endpoint Monitoring

```python
from utils.monitoring import monitoring_manager

@monitoring_manager.monitor_endpoint("my_service.my_function")
async def my_api_function():
    return {"status": "ok"}
```

### LLM Call Monitoring

```python
@monitoring_manager.monitor_llm_call("gpt-4", "chat_completion")
def call_llm(messages):
    return llm_response
```

### Agent Step Tracing

```python
with monitoring_manager.trace_agent_step("web_search", "research_agent", "tool_call") as span:
    result = execute_tool()
    monitoring_manager.set_tool_output(result)
```

### Tool Call Tracing

```python
with monitoring_manager.trace_tool_call("web_search", "agent_name", {"query": "test"}) as span:
    results = search_web("test")
    monitoring_manager.set_tool_output({"results": results})
```

## OpenInference Semantic Attributes

The system uses OpenInference semantic conventions for AI-specific observability:

### LLM Attributes

| Attribute | Description |
|-----------|-------------|
| `llm.model_name` | Model identifier (e.g., `gpt-4`) |
| `llm.operation.name` | Operation type (e.g., `chat_completion`) |
| `llm.token_count.prompt` | Input token count |
| `llm.token_count.completion` | Output token count |
| `llm.invocation_parameters` | Model parameters (JSON) |
| `llm.time_to_first_token` | TTFT in seconds |

### Agent Attributes

| Attribute | Description |
|-----------|-------------|
| `agent.name` | Agent identifier |
| `agent.step.name` | Step name (e.g., `web_search`) |
| `agent.step.type` | Step type: `tool_call`, `reasoning`, `action_selection` |
| `agent.tool.name` | Tool name |
| `agent.tool.input` | Tool input (JSON) |
| `agent.tool.output` | Tool output (JSON) |

## Metrics

| Metric | Description |
|--------|-------------|
| `llm.request.duration` | Request latency |
| `llm.token.generation_rate` | Tokens per second |
| `llm.time_to_first_token` | TTFT |
| `llm.token_count.prompt` | Input tokens |
| `llm.token_count.completion` | Output tokens |
| `agent.step.count` | Agent step count |
| `agent.execution.duration` | Agent execution time |
| `agent.error.count` | Agent errors |

## Collector Configuration

By default, the OpenTelemetry Collector only logs data through the logging exporter. This avoids forwarding data back into itself when no external backend is configured. To forward through the Collector, add a platform exporter:

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

See `docker/monitoring/otel-collector-config.yml` for full configuration with platform examples.

## Graceful Degradation

When OpenTelemetry dependencies are not installed, monitoring gracefully disables:

```python
pip install nexent          # Basic package - no monitoring
pip install nexent[performance]  # With OTLP support
```

All monitoring methods work without errors when disabled - decorators pass through, context managers yield None.

## Troubleshooting

### No data appearing

1. Check `ENABLE_TELEMETRY=true` in `.env`
2. Verify OTLP endpoint is reachable
3. Check authentication headers are correct

### Connection errors

1. Test endpoint: `curl -v $OTEL_EXPORTER_OTLP_ENDPOINT/v1/traces`
2. Verify protocol matches endpoint (`http` vs `grpc`)
3. Check Collector logs: `docker logs nexent-otel-collector`

### Wrong attributes

1. Verify OpenInference attributes in platform UI
2. Check span attribute naming: `llm.model_name` not `model_name`
3. Review platform-specific attribute requirements
