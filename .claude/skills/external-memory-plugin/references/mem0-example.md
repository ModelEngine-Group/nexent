# Mem0 reference implementation

Inspect these source files before adapting the example:

- `backend/memory_provider_plugins/mem0/plugin.yaml`
- `backend/memory_provider_plugins/mem0/provider.py`
- `test/backend/memory_provider_plugins/test_mem0_provider.py`

## Configuration

The manifest exposes `api_key` as a required secret, plus optional `org_id` and `base_url`. Runtime configuration also supplies `timeout_seconds`.

Mem0 uses `Authorization: Token <key>`, not Bearer authentication. Add `X-Org-Id` when configured.

## Mapping

Search posts `query`, `limit`, `user_id`, and optional `agent_id` to `/v1/memories/search/`. Results map `id`, `memory`/`content`, `score`, and `metadata` to `MemorySearchResult`. The bundled implementation retries an empty user-and-Agent search at user scope.

Ingest posts each unit to `/v1/memories/` as a user message. It maps Nexent `conversation_id` to Mem0 `run_id` and merges request/unit metadata with event identifiers. Each HTTP result becomes a unit acceptance or rejection.

## Isolated test pattern

Patch the provider's `httpx.AsyncClient` construction with `httpx.MockTransport`, then assert request headers and JSON in the transport handler:

```python
original_async_client = httpx.AsyncClient
transport = httpx.MockTransport(handler)

def client(**kwargs):
    return original_async_client(transport=transport, **kwargs)

monkeypatch.setattr(httpx, "AsyncClient", client)
```

Return synthetic `httpx.Response` objects for success, 401, 403, 429, 5xx, and malformed responses. Raise `httpx.ReadTimeout` and `httpx.ConnectError` from handlers for transport failures. Use placeholder credentials only.

Run:

```bash
source backend/.venv/bin/activate
pytest test/backend/memory_provider_plugins/test_mem0_provider.py -v \
  --cov=backend.memory_provider_plugins.mem0.provider --cov-report=term-missing
```

The test must pass without Mem0 environment variables or internet access.
