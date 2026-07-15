# Nexent SDK Langfuse Functional Test Design

## Environment Discovery

Load repo `.env` values when present, but let process environment override file values. Check these files in order if they exist:

1. `<repo>/.env`
2. `<repo>/backend/.env`
3. `<repo>/sdk/.env`
4. `<repo>/deploy/env/.env`
5. `<repo>/docker/.env`

Model credential precedence:

1. `LLM_API_KEY`, `LLM_MODEL_NAME`, `LLM_API_URL`
2. `NEXENT_LLM_KEY`, `NEXENT_LLM_NAME`, `NEXENT_LLM_URL`

Use the resolved values to create `ModelConfig(cite_name="functional_llm", api_key=..., model_name=..., url=...)`.

Langfuse/OTLP readiness requires either:

- `OTEL_EXPORTER_OTLP_ENDPOINT` plus an auth mechanism such as `OTEL_EXPORTER_OTLP_AUTHORIZATION`, or
- `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`, from which OTLP endpoint/auth can be derived.

## Agent Shape To Exercise Context

Build an agent config that includes as many context surfaces as possible without depending on backend services:

- `SystemPromptComponent` with stable policy text.
- `ToolsComponent` or actual small local tool, such as a deterministic echo/calculation tool.
- `SkillsComponent` with at least one synthetic skill description.
- `MemoryComponent` with formatted user/project memory.
- `KnowledgeBaseComponent` with a concise fake KB summary.
- `ManagedAgentsComponent` or an actual lightweight managed sub-agent if the SDK constructor supports it in the target branch.
- `ExternalAgentsComponent` with a synthetic external A2A definition for prompt/context assembly; avoid calling a real external A2A service unless the test explicitly provisions one.
- `ContextManagerConfig(enabled=True, token_threshold=<small but safe>)`.

The user prompt should force a short final answer and, if a real tool is included, require exactly one tool invocation. Keep the run deterministic and cheap.

## Test Structure

Recommended pytest flow:

1. Load env with a helper that redacts secrets.
2. Skip with a clear reason unless `NEXENT_RUN_SDK_LANGFUSE_FUNCTIONAL=1` is set, or if model or Langfuse config is incomplete.
3. Configure OTLP/Langfuse env before importing or initializing Nexent monitoring code when the target code initializes telemetry at import time.
4. Create `NexentAgent` with a `MessageObserver`, one real `ModelConfig`, and an `AgentConfig` containing context components.
5. Run one agent query with a unique `trace_id`, `session_id`, or marker string embedded in input and metadata where available.
6. Flush/shutdown OpenTelemetry providers if the SDK exposes a helper; otherwise sleep briefly for export.
7. Query Langfuse API for the unique marker and assert trace/span shape.

## Langfuse Verification Targets

Assert at least these facts when the API makes them available:

- A trace exists for the unique test marker.
- There is an agent run or chain span.
- There is a model generation span with non-empty input and output.
- Context preparation spans exist, such as `context.prepare_step` and final-answer preparation if the run reaches final answer.
- Tool spans exist when the test includes a real tool call.
- Final answer/output is captured.
- No span has error status unless the test explicitly covers error handling.

Do not overfit exact span IDs or timing. Prefer stable span names, attributes, and marker text.

## Skip And Failure Rules

Skip when the explicit opt-in flag `NEXENT_RUN_SDK_LANGFUSE_FUNCTIONAL=1` is absent, or when credentials or Langfuse endpoint are missing. Fail when the opt-in flag and credentials exist but:

- the model call fails,
- telemetry export is configured but no trace appears after retry,
- the trace lacks required spans,
- the final answer is empty, or
- context components are not visible in model input or trace evidence.

## Useful Commands

Inspect readiness:

```bash
python /path/to/skill/scripts/inspect_env.py --project-root /path/to/nexent
```

Generate a scaffold:

```bash
python /path/to/skill/scripts/scaffold_langfuse_test.py --output test/sdk/core/agents/test_sdk_functional_langfuse.py
```
