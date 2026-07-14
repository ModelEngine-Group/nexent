---
name: sdk-functional-test-langfuse
description: Create, run, and debug Nexent SDK functional tests that call a real LLM service and verify OpenTelemetry/Langfuse traces. Use when testing SDK modules with real-world model credentials from .env or environment variables, when validating agent runs with ContextManager components, tools, skills, memory, knowledge-base summaries, managed agents, external A2A definitions, or when checking that Langfuse captured every agent step.
---

# SDK Functional Test Langfuse

## Purpose

Use this skill to build a real Nexent SDK functional test that executes an agent against an actual model service and verifies the resulting Langfuse trace. Treat these tests as opt-in functional/integration tests, not normal unit tests.

## Workflow

1. Inspect environment readiness before writing or running the test:

```bash
python scripts/inspect_env.py --project-root <repo-root>
```

2. Resolve model credentials in this precedence:

- Already configured repo `.env` / process env values: `LLM_API_KEY`, `LLM_MODEL_NAME`, `LLM_API_URL`.
- Fallback values requested for this skill: `NEXENT_LLM_KEY`, `NEXENT_LLM_NAME`, `NEXENT_LLM_URL`.
- Do not invent credentials. If neither set is complete, stop and ask the user to provide them.

3. Resolve Langfuse/OpenTelemetry config from process env or repo `.env`:

- Preferred SDK tracing path: OTLP variables used by Nexent monitoring code, especially `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_AUTHORIZATION`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION`, and `OTEL_SERVICE_NAME`.
- Optional API verification variables: `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.
- If only Langfuse public/secret keys are available, derive `OTEL_EXPORTER_OTLP_AUTHORIZATION` as `Basic base64(public:secret)` and use the Langfuse OTLP endpoint for the host.

4. Read `references/test-design.md` before implementing a new functional test. It contains the target agent shape, assertions, trace checks, and skip rules.

5. If creating a new pytest file, generate a starting scaffold instead of writing from scratch:

```bash
python scripts/scaffold_langfuse_test.py --output test/sdk/core/agents/test_sdk_functional_langfuse.py
```

6. Run only when real external calls are intended. Use a dedicated marker/name such as `functional`, `real_model`, or `langfuse`; keep the test skipped when required env is missing.

7. Require an explicit opt-in flag for real external execution. For Nexent SDK Langfuse functional tests, use `NEXENT_RUN_SDK_LANGFUSE_FUNCTIONAL=1`. Without this flag, the test must skip even when `.env` contains model and Langfuse credentials, so ordinary unit-test runs do not call external services.

## Guardrails

- Never print API keys, Basic auth headers, or Langfuse secret keys. Redact sensitive values in logs and summaries.
- Do not commit real `.env` values.
- Do not run the functional test automatically during ordinary unit-test verification.
- Prefer one deterministic prompt and a small max-step count so traces are easy to inspect.
- Verify both SDK behavior and Langfuse evidence. A successful model answer without a trace is not sufficient for this skill.

## Expected Outcome

The final test should create a real SDK `NexentAgent` run with representative Nexent context, wait briefly for OTLP export, then verify Langfuse contains a trace/session with agent run, model call, context preparation, tool/managed-agent steps when configured, and final answer output.
