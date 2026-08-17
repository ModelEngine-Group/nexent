# External Memory Plugin Development and Usage

Nexent external memory plugins connect third-party memory services to Agent retrieval and conversation ingestion. A plugin consists of a manifest and a Python provider implementation; no SDK retrieval changes are required.

## Runtime model

A plugin can implement either or both capabilities:

- `searchable`: retrieve external memories during Agent initialization and `search_memory` execution, then merge them with built-in memory context.
- `ingestible`: send extracted memory units to the provider after a conversation turn.

The deployment kill switches `EXTERNAL_MEMORY_SEARCH_ENABLED` and `EXTERNAL_MEMORY_INGEST_ENABLED` default to `false`. The provider configuration's `enabled` field is tenant- and instance-scoped. Normal Agent traffic calls a plugin only when both levels are enabled. The UI test actions bypass the instance `enabled` state for connectivity checks.

## Plugin layout

Place each plugin in its own directory under `MEMORY_PROVIDER_PLUGINS_DIR`:

```text
memory-provider-plugins/
└── example-provider/
    ├── plugin.yaml
    └── provider.py
```

Docker mounts the host `memory-provider-plugins` directory at `/mnt/nexent-data/memory-provider-plugins` by default. The bundled Mem0 reference lives in `backend/memory_provider_plugins/mem0/`.

## Define plugin.yaml

```yaml
name: example-provider
version: "1.0.0"
description: "Example external memory provider"
entry_point: "provider.py"
class_name: "ExampleProvider"
implements:
  - searchable
  - ingestible
config_schema:
  - key: api_key
    label: "API Key"
    type: secret
    required: true
  - key: base_url
    label: "API Base URL"
    type: string
    required: false
    default: "https://memory.example.com"
```

The required fields are `name`, `version`, `entry_point`, `class_name`, and `implements`. Only `searchable` and `ingestible` are accepted. `config_schema` drives the UI form and backend validation. The provider constructor receives keys without the database `plugin.` prefix.

Use `type: secret` for credentials. Nexent masks those values in read APIs while passing the original values at runtime. Never put API keys in source, logs, exceptions, test snapshots, or OTel attributes.

## Implement the provider

Protocols are defined in `sdk/nexent/memory/providers/base.py`; request and result models are in `sdk/nexent/memory/models.py`. Implement protocol methods asynchronously.

```python
from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
)


class ExampleProvider:
    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://memory.example.com")
        self.timeout = int(config.get("timeout_seconds", 30))

    @property
    def provider_name(self) -> str:
        return "example-provider"

    async def search(
        self,
        request: MemorySearchRequest,
        limit: int = 5,
        filters: dict | None = None,
    ) -> list[MemorySearchResult]:
        ...

    async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult:
        ...
```

### Search mapping

Forward `query`, `user_id`, optional `agent_id` and `conversation_id`, and honor `limit`. Map every result to `MemorySearchResult` with a stable `external_id`, Agent-ready `content`, floating-point `score`, stable `source`, `is_external=True`, and credential-free `metadata`. Never merge data from another tenant or user. Document any scope fallback required by the remote API.

### Ingest mapping

Process every `MemoryIngestRequest.units` item and return a `UnitIngestResult` for each. Aggregate `accepted_count`, `rejected_count`, and `status`: `ok`, `partial`, or `error`. Forward `idempotency_key` or `event_id` so retries do not create duplicate memories.

### Error classification

Raise exceptions from `nexent.memory.providers.retry`:

- `RetryableProviderError`: timeout, connection failure, HTTP 429, or HTTP 5xx.
- `NonRetryableProviderError`: HTTP 401/403, invalid input, or unrecoverable configuration.
- `DegradableProviderError`: a failure that can be safely ignored while the Agent continues.

Attach a `ProviderError` with a stable `ProviderErrorCode`. The external provider service supplies retry, degradation, error persistence, and OTel instrumentation. Do not log memory content or credentials in the plugin.

## Mem0 reference plugin

Use these files as the complete example:

- `backend/memory_provider_plugins/mem0/plugin.yaml`
- `backend/memory_provider_plugins/mem0/provider.py`
- `test/backend/memory_provider_plugins/test_mem0_provider.py`

The plugin implements both capabilities and authenticates to the hosted API with `Authorization: Token ...`:

- Search: `POST /v1/memories/search/`
- Ingest: `POST /v1/memories/`
- Optional organization header: `X-Org-Id`

It maps Nexent `user_id`, `agent_id`, and `conversation_id` to Mem0 `user_id`, `agent_id`, and `run_id`. An empty user-and-Agent search falls back to user scope. HTTP 401/403 is non-retryable; HTTP 429/5xx and transport failures are retryable.

## Network-isolated unit tests

CI tests must mock the HTTP boundary. They must not read a real API key or contact a live service. The Mem0 tests use `httpx.MockTransport`:

```python
import httpx


def install_transport(monkeypatch, handler):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
```

Cover manifest loading, construction, successful and empty search, successful and partial ingest, scope mapping, 401/403, 429, 5xx, timeout, connection failure, and missing response fields. Suggested commands:

```bash
source backend/.venv/bin/activate
pytest test/backend/services/test_memory_provider_plugin_loader.py -v
pytest test/backend/memory_provider_plugins/test_mem0_provider.py -v \
  --cov=backend.memory_provider_plugins.mem0.provider --cov-report=term-missing
```

New or changed modules should maintain at least 90% coverage. A real-service integration test must be explicitly authorized and supplements rather than replaces isolated unit tests.

## Install and configure

1. Copy the plugin directory into `MEMORY_PROVIDER_PLUGINS_DIR`.
2. Restart the configuration service so the loader rescans plugins.
3. Open **Memory Management → External Memory Services**, add a provider, select the plugin, and complete its generated form.
4. Keep the provider disabled while running test search and test ingest.
5. Enable the provider and the required deployment kill switches after both tests pass.
6. Run an Agent conversation with unique markers to verify built-in and external retrieval independently.

Use `GET /memory/provider-plugins` to inspect discovery and the `/memory/providers` APIs to manage configuration. All endpoints are tenant-scoped from the authentication token.

## Observability and troubleshooting

External operations produce a `nexent.memory.external_provider` span plus request, duration, search-result, and ingest accepted/rejected metrics. Useful attributes include `operation`, `provider`, `outcome`, `error_code`, and the span-only `provider_config_id`.

Troubleshoot in this order:

1. Confirm the plugin appears in `/memory/provider-plugins`; otherwise inspect its path, manifest, entry module, and startup logs.
2. Run the test actions. `unauthorized` usually means the credential format, organization, or target environment is wrong.
3. Confirm the provider is enabled and the matching deployment kill switch is `true`.
4. Inspect OTel `outcome` and `error_code` without adding queries or credentials as attributes.
5. Verify user, Agent, and conversation scope mapping against the remote data.

Telemetry is fail-open. If spans are absent, inspect telemetry enablement and OTLP exporter configuration rather than assuming the plugin did not run.
