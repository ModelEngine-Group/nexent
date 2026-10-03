# ext-knowledge-mock

A single-process mock service that stands in for every external knowledge
service the Nexent knowledge-base modules integrate with, plus a controlled
HTTP asset server. One port, multiple route sets:

| Route set | Prefix | Stands in for | Credential convention |
|---|---|---|---|
| AIDP protocol | `/` (root) | Managed AIDP **and** independent AIDP | `Authorization: Bearer mock-aidp-key`, tenant `aidp` |
| dify | `/dify` | Dify datasets / retrieve / upload-file | `Authorization: Bearer <any>` |
| datamate | `/datamate` | DataMate knowledge-base + download APIs | Authorization forwarded, not validated |
| idata | `/idata` | iData knowledgeSpaces / knowledgeBases / retrievals | `Authorization: Bearer <any>` |
| ragflow | `/ragflow` | RAGFlow datasets / search | `Authorization: Bearer <any>` |
| haotian | `/haotian` | Haotian knowledge-sets / retrieve | raw `Authorization` header |
| assets | `/assets` | arbitrary external HTTP resources | none (per-asset status codes instead) |
| fault | `/fault/v1` | OpenAI-compatible model gateway with controlled failures | none (model record carries any key) |

The AIDP protocol is mounted at the root (not under a prefix) because the
product's image proxy (`backend/services/image_service.py`) rebuilds AIDP
image URLs from `AIDP_SERVER_URL` keeping only scheme+netloc, and its path
allowlist requires paths to start with `/KnowledgeBase/Tenants/`. A prefixed
base would break the AIDP image flow. Independent AIDP
(`backend/services/ind_aidp_service.py`) has the same behaviour, so managed
AIDP and ind-AIDP share the root route set — ind-AIDP tests configure
`server_url` at this service with tenant `aidp` and the AIDP mock key.

The AIDP implementation is the existing, unmodified mock at
`test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py`, loaded via
`importlib` and mounted as an ASGI sub-app. Its own `/_reset`,
`/_mock/fail-next` and `/health` endpoints are shadowed by the unified
control plane below, which forwards AIDP operations to the sub-app
in-process.

## Base URL conventions for tests

| Product configuration | Value |
|---|---|
| `AIDP_SERVER_URL` (env) | `http://<host>:30090` |
| ind-AIDP tool `server_url` | `http://<host>:30090` (tenant `aidp`, key `mock-aidp-key`) |
| Dify `dify_api_base` / dify_search tool | `http://<host>:30090/dify` (retrieve/upload-file answer both `/dify/datasets/...` and `/dify/v1/datasets/...`) |
| `DATAMATE_URL` (tenant config) | `http://<host>:30090/datamate` |
| iData `idata_api_base` / tool | `http://<host>:30090/idata` |
| RAGFlow base / tool | `http://<host>:30090/ragflow` |
| Haotian `list_url` / `retrieve_url` | `http://<host>:30090/haotian/api/knowledge-sets` / `.../api/retrieve` |
| Arbitrary asset URLs | `http://<host>:30090/assets/<name>` |
| Fault-model `base_url` (LLM record) | `http://<host>:30090/fault/v1` |

## Control plane

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness; reports per-service status incl. AIDP |
| `POST /_reset` | `{"services": ["dify", ...]}` or empty body → reset all (route sets + AIDP) back to seeds |
| `POST /_mock/fail-next` | `{"service", "count", "status"}` — next N requests to that route set fail; `service: "aidp"` proxies to the AIDP sub-app |
| `POST /_mock/fail-reset` | `{"service": ...}` or empty → clear failure plan |
| `POST /_mock/latency` | `{"service", "delay_ms"}` (prefixed route sets only) |
| `POST /_mock/assets` | `{"assets": [{name, content_type, size?, content_b64?, filename?, support_ranges?, status?, redirect_to?, latency_ms?}]}` — runtime asset declaration |
| `GET /_wire-log?service=&limit=` | Request log for evidence |

State persists per route set under `_state/` and survives restarts; `/_reset`
restores seeds. Failure counters and latency are in-memory only.

## Running

Standalone (local dev / AIDP-minimal profile):

```bash
python test/mock-services/ext-knowledge-mock/server.py --port 30090
```

Through the mock-services dispatcher (builds the image, waits for readiness,
attaches the product network; the product must already be deployed):

```bash
python3 test/mock-services/deploy.py up ext-knowledge
python3 test/mock-services/deploy.py status ext-knowledge
python3 test/mock-services/deploy.py stop ext-knowledge
```

The compose build context is the `test/` directory so the image can embed the
AIDP mock in place; `test/.dockerignore` keeps the context minimal. Run a
single uvicorn worker — all state lives in-process.

## Deliberate quirks (do not "fix" without checking the adapters)

- Dify retrieve/upload-file are registered under both `/dify/datasets/...`
  and `/dify/v1/datasets/...`: the backend datasets proxy strips a trailing
  `/v1` while the SDK tool's `server_url` conventionally includes it.
- DataMate routes live under `/datamate/api/...`: the product appends `/api`
  to a path-prefixed base when building download URLs
  (`backend/apps/file_management_app.py` `_build_datamate_url_from_parts`).
- DataMate `entity.metadata` is a JSON **string**, and its
  `absolute_directory_path` ends with the dataset id (the tool's
  `_extract_dataset_id` takes the last path segment).
- DataMate list responses paginate via `data.totalPages`; seeds contain 22
  KBs so the default page size of 20 exercises the client's auto-pagination.
- The AIDP quirk set (current-page `total_count`, `next_link` as the only
  "more pages" signal, ModelService not filtering by `app`) lives in the
  AIDP mock file itself.
- Haotian seeds include a knowledge base with `dify_dataset_id: "null"`; the
  product replaces it with a default UUID, which also has seeded chunks.
- The fault provider is minimal by design: one endpoint
  (`POST /fault/v1/chat/completions`), two markers
  (`force-regenerate-name-failure` -> 503, `provider 429` -> first two calls
  per marker 429 then recover), fixed recovery content, SSE variant. `/models`,
  the `failure probe` / `forced fault` markers and usage stats are deliberately
  absent because no suite case consumes them — extend only when a case does
  (pinned by test_models_endpoint_intentionally_absent).

## Fidelity tests

`test/ext_components/ext_knowledge/` drives the **real product adapters**
(DataMateClient, dify/idata/ragflow/haotian services) against a live
instance of this service, so adapter-contract drift turns into a red test in
CI instead of a late E2E failure:

```bash
pytest test/ext_components/ext_knowledge -v
```
