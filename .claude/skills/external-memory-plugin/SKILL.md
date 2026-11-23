---
name: external-memory-plugin
description: Develop, adapt, review, test, and troubleshoot Nexent external memory provider plugins, including plugin.yaml manifests, searchable and ingestible provider protocols, error mapping, network-isolated unit tests, deployment configuration, and Mem0-based examples. Use when adding a new external memory vendor, changing an existing memory plugin, validating partner adapters, or diagnosing plugin discovery, authentication, retrieval, ingestion, or CI failures.
---

# External Memory Plugin

Develop external memory adapters against the current Nexent contract and prove them without live-service CI dependencies.

## Establish scope

1. Read the repository `AGENTS.md` and invoke its SPEC workflow for production behavior changes.
2. Inspect, rather than assume, these current contracts:
   - `sdk/nexent/memory/providers/base.py`
   - `sdk/nexent/memory/models.py`
   - `backend/services/memory_provider_plugin_loader.py`
   - `backend/services/memory_external_provider_service.py`
3. Read [references/plugin-contract.md](references/plugin-contract.md) before creating or reviewing a manifest or provider.
4. Read [references/mem0-example.md](references/mem0-example.md) when implementing HTTP transport, error mapping, or tests.
5. Preserve tenant, user, Agent, and conversation scope. Never print or persist credentials.

## Implement the adapter

1. Create `<plugin-dir>/<name>/plugin.yaml` and `provider.py`.
2. Declare only implemented capabilities in `implements`.
3. Make protocol methods asynchronous and return the exact Nexent models.
4. Honor provider-level `timeout_seconds` and result limits.
5. Map remote failures to `ProviderError` and the retry exception matching recovery semantics.
6. Keep OTel attributes low-cardinality and free of queries, memory content, user identifiers, tenant identifiers, and secrets. Rely on the orchestration service's standard instrumentation unless provider-specific spans add actionable detail.
7. Treat the deployment search/ingest switches as kill switches and the provider `enabled` field as the instance switch; do not bypass them in normal runtime paths.

## Test without external dependencies

1. Test manifest discovery and protocol validation with a temporary plugin directory.
2. Mock the network at the HTTP client transport boundary; for `httpx`, use `MockTransport`.
3. Cover successful, empty, partial, malformed, unauthorized, forbidden, rate-limited, timeout, connection, and server-error responses as applicable.
4. Assert request scope and authentication shape without using real credentials.
5. Assert every ingest unit receives a result and retry classification is correct.
6. Run the narrow plugin and loader suites first, then affected service and integration suites.
7. Reach at least 90% coverage for each new or modified module.

Do not let a test silently reach the internet. Real-provider tests require explicit authorization and must remain separate from CI unit tests.

## Verify installation and runtime

1. Keep partner code outside the Nexent Git worktree and image. Locate the deployment's `nexent-data` root, then copy the plugin to its `memory-provider-plugins/<plugin-name>` child.
2. For Docker, resolve `ROOT_DIR` from the deployment argument or `deploy/env/.env` (default `$HOME/nexent-data`). For Kubernetes local storage, read `global.sharedStorage.memoryPlugins.localPath`; for other storage classes, inspect the `nexent-memory-plugins` PVC. Do not redefine the established in-container path `/mnt/nexent-data/memory-provider-plugins`.
3. Restart both services, then confirm discovery through `GET /memory/provider-plugins` or the Memory Management UI.
4. Create a disabled provider configuration and run test search and ingest.
5. Enable the provider and the required deployment kill switch only after connectivity succeeds.
6. Use unique internal and external memory markers in an Agent conversation.
7. Inspect `nexent.memory.external_provider` spans and standard metrics for operation, provider, outcome, error code, latency, and result/unit counts.
8. Record sanitized evidence. Do not call the feature complete when real-runtime or required telemetry evidence is unavailable; mark that verification blocked.

## Review checklist

- Manifest fields and class name match the files.
- `config_schema` marks secrets and required fields correctly.
- Search results set `source` and `is_external=True`.
- Ingest handles idempotency and partial acceptance.
- Error types match retry behavior.
- Logs, exceptions, metrics, and spans contain no sensitive payloads.
- Unit tests are deterministic and network-isolated.
- Deployment and user documentation name both switch levels.
