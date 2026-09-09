# Nexent external memory plugin contract

## Files and manifest

Each direct child of `MEMORY_PROVIDER_PLUGINS_DIR` is scanned as a plugin directory. Deployed containers use `/mnt/nexent-data/memory-provider-plugins`, backed by Docker `${ROOT_DIR}/memory-provider-plugins` or the Kubernetes `nexent-memory-plugins` PVC. A plugin must contain `plugin.yaml` and its declared Python entry point. Partner code belongs in this data directory, not under `backend/memory_provider_plugins`.

Plugin entry points execute trusted Python in the backend process. Review third-party code and dependencies before installation, restrict directory writes, and prefer a read-only container mount after provisioning.

Required manifest fields:

| Field | Contract |
|---|---|
| `name` | Stable plugin identifier used by `plugin.name` configuration. |
| `version` | Quoted semantic version string. |
| `entry_point` | Python file relative to the plugin directory. |
| `class_name` | Provider class exported by the entry module. |
| `implements` | List containing `searchable`, `ingestible`, or both. |

Optional `description` is returned by discovery. Optional `config_schema` drives validation and the UI form. Supported schema keys currently include `key`, `label`, `type`, `required`, and `default`. Use `type: secret` for credentials.

The persisted parameter map includes `plugin.name` and uses `plugin.<key>` for schema values. `MemoryExternalProviderService.build_provider` strips `plugin.` before calling the provider constructor and adds `timeout_seconds` from the provider configuration.

## Searchable protocol

```python
async def search(
    request: MemorySearchRequest,
    limit: int = 5,
    filters: dict | None = None,
) -> list[MemorySearchResult]: ...
```

Use request scope fields only as supported by the remote system. Return:

- `external_id`: stable remote identifier;
- `content`: normalized text;
- `score`: float relevance score;
- `source`: provider name;
- `is_external`: `True`;
- `metadata`: optional safe metadata.

Return an empty list for a successful empty search. Do not return another user's or tenant's data as a fallback.

## Ingestible protocol

```python
async def ingest(request: MemoryIngestRequest) -> MemoryIngestResult: ...
```

Return one `UnitIngestResult` per input unit. Use `accepted`, `rejected`, or `degraded`, and keep aggregate counts consistent with unit results. Overall status is normally `ok`, `partial`, or `error`. Preserve `event_id` or the request idempotency key when the remote API supports deduplication.

## Failure mapping

| Remote condition | Error code | Exception |
|---|---|---|
| Timeout | `timeout` | `RetryableProviderError` |
| Rate limit | `rate_limited` | `RetryableProviderError` |
| Connection or 5xx | `provider_error` | `RetryableProviderError` |
| Authentication failure | `unauthorized` | `NonRetryableProviderError` |
| Permission failure | `forbidden` | `NonRetryableProviderError` |
| Invalid payload/schema | `invalid_payload` or `schema_mismatch` | `NonRetryableProviderError` |

Use `DegradableProviderError` only when the provider can explicitly degrade without invalidating the Agent run. Never include keys or full remote response bodies that may contain sensitive data.

## Runtime controls and observation

- `EXTERNAL_MEMORY_SEARCH_ENABLED`: deployment search kill switch.
- `EXTERNAL_MEMORY_INGEST_ENABLED`: deployment ingest kill switch.
- provider `enabled`: per-tenant provider instance switch.
- provider `timeout_seconds`: timeout passed to the plugin.

The orchestration service emits `nexent.memory.external_provider` spans and request, duration, result, and ingest-unit metrics. Keep metric attributes low-cardinality. Do not attach query text, content, user/tenant/Agent IDs, or credentials.
