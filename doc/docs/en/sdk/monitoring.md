# Nexent Agent Observability (OTLP)

Enterprise-grade observability for AI agents using OpenTelemetry OTLP protocol. Supports integration with observability platforms like Arize Phoenix, Langfuse, LangSmith, Grafana Tempo, Zipkin, and more.

## Architecture

```
NexentAgent ──► OpenTelemetry SDK ──► OTLP Collector ──► Arize Phoenix / Langfuse / LangSmith / Grafana Tempo / Zipkin / OTLP Backend
     │                                        │
     │   OpenInference Semantics              │
     │   (llm.*, agent.* attributes)          │
     └────────────────────────────────────────┘
```

## Quick Start

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

### LangSmith

LangSmith supports online OTLP trace ingestion through the OpenTelemetry endpoint. Nexent can send traces to a local Collector first, and the Collector forwards them to LangSmith.

**Collector forwarding:**

```bash
cd docker
vim monitoring/monitoring.env

MONITORING_PROVIDER=langsmith
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=nexent
LANGSMITH_OTLP_TRACES_ENDPOINT=https://api.smith.langchain.com/otel/v1/traces

./start-monitoring.sh --stack langsmith
```

Nexent backend configuration when it sends OTLP to the Collector:

```bash
ENABLE_TELEMETRY=true
MONITORING_PROVIDER=langsmith
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

For direct backend-to-LangSmith export, set `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.smith.langchain.com/otel`, `LANGSMITH_API_KEY`, and optionally `LANGSMITH_PROJECT`.

### Zipkin

Zipkin provides a lightweight local trace query UI. For local deployment, Nexent sends OTLP to the Collector, and the Collector forwards traces to Zipkin.

```bash
MONITORING_PROVIDER=zipkin
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
MONITORING_DASHBOARD_URL=http://localhost:9411
```

Set `MONITORING_DASHBOARD_URL` to the browser-accessible monitoring UI URL. The backend returns this value to the frontend top bar without deriving a provider-specific path.

```bash
MONITORING_DASHBOARD_URL=http://localhost:6006
MONITORING_DASHBOARD_URL=http://localhost:3001/project/nexent
MONITORING_DASHBOARD_URL=http://localhost:3002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1
MONITORING_DASHBOARD_URL=http://localhost:9411
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_TELEMETRY` | `false` | Enable/disable monitoring |
| `MONITORING_PROVIDER` | `otlp` | Provider profile: `otlp`, `phoenix`, `langfuse`, `langsmith`, `grafana`, `zipkin` |
| `MONITORING_DASHBOARD_URL` | (empty) | Browser-accessible monitoring UI URL used by the frontend top bar |
| `MONITORING_PROJECT_NAME` | `nexent` | Observability platform project name |
| `MONITORING_TRACE_CONTENT_MODE` | `summary` | Trace payload mode: `summary` records bounded previews plus metadata, `metrics` records only structure/size metadata, `full` keeps full payloads subject to `MONITORING_TRACE_MAX_CHARS` |
| `MONITORING_TRACE_MAX_CHARS` | `4000` | Maximum characters for each payload preview written to trace attributes |
| `MONITORING_TRACE_MAX_ITEMS` | `20` | Maximum dict keys/list items included in payload previews |
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
| `LANGSMITH_API_KEY` | (empty) | LangSmith API key; mapped to the `x-api-key` OTLP header |
| `LANGSMITH_PROJECT` | (empty) | Optional LangSmith project header |
| `LANGSMITH_OTLP_TRACES_ENDPOINT` | `https://api.smith.langchain.com/otel/v1/traces` | Collector trace endpoint for online LangSmith |

## Code Integration

### Agent Boundary Context

At the request boundary, business code only binds the resolved user and Agent metadata once. The SDK then creates Agent, LLM, and Tool spans from the runtime lifecycle:

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

`monitor_endpoint` is still kept as a compatibility API and low-level escape hatch, but it is no longer the recommended way to add normal Agent observability.

### Trace Payload Policy

Tool input/output, retriever output, and Langfuse-compatible `input.value` / `output.value` attributes share the same payload policy. By default Nexent writes a bounded preview plus structured metadata such as `type`, `size_chars`, `item_count`, `truncated`, and `keys`. Memory search spans intentionally record only result summaries and statistics, not full memory text bodies.

Agent context metrics are emitted from the SDK lifecycle. Each action step records an `agent.step.metrics` event with estimated context tokens, compression calls, cache hits, compression ratio, and token threshold. The final Agent span also receives aggregate step count, max context size, average compression ratio, total compression calls, and cache hit totals.

### LLM Call Monitoring

```python
@monitoring_manager.monitor_llm_call("gpt-4", "chat_completion")
def call_llm(messages):
    return llm_response
```

### Agent Step Tracing

```python
with monitoring_manager.trace_agent_step("agent.run.loop", step_type="agent_loop") as span:
    result = execute_tool()
    monitoring_manager.set_tool_output(result)
```

### Tool Call Tracing

```python
with monitoring_manager.trace_tool_call("web_search", "agent_name", {"query": "test"}) as span:
    results = search_web("test")
    monitoring_manager.set_tool_output({"results": results})
```

### Retriever Call Tracing

Knowledge-base search tools are classified as retriever spans automatically by the SDK. Custom retriever integrations can use the same semantics directly:

```python
with monitoring_manager.trace_retriever_call("knowledge_base_search", "agent_name", {"query": "test"}) as span:
    documents = search_knowledge_base("test")
    monitoring_manager.set_retriever_output(documents)
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
| `agent.tool.input` | Tool input preview using the configured trace payload policy |
| `agent.tool.input.*` | Structured tool input metadata: type, size, item count, truncation, keys |
| `agent.tool.output` | Tool output preview using the configured trace payload policy |
| `agent.tool.output.*` | Structured tool output metadata: type, size, item count, truncation, keys |
| `agent.tool.success` | Whether the tool call completed successfully |
| `agent.tool.duration_ms` | Tool call duration |
| `retriever.name` | Retriever name |
| `retrieval.query` | Retriever query |
| `retrieval.results.count` | Retriever result count |
| `retrieval.top_score` | Highest numeric result score when available |
| `retriever.input.*` | Structured retriever input metadata |
| `retriever.output` | Retriever output preview using the configured trace payload policy |
| `retriever.output.*` | Structured retriever output metadata |
| `context.tokens.estimated_input` | Estimated context input tokens per Agent step event |
| `context.tokens.uncompressed_estimated` | Estimated uncompressed context tokens per Agent step event |
| `context.compression.calls` | Compression calls per Agent step event |
| `context.compression.cache_hits` | Compression cache hits per Agent step event |
| `context.compression.ratio` | Compression ratio per Agent step event |

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

By default, the OpenTelemetry Collector only logs data through the debug exporter. This avoids forwarding data back into itself when no external backend is configured. To forward through the Collector, add a platform exporter:

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
