# ext-knowledge-mock

A single-process mock that stands in for every external knowledge service
the Nexent knowledge-base modules integrate with, plus a controlled HTTP
asset server. One port, every route set mounted at its **real path shape**
(all root-mounted, like the actual services — the path namespaces are
disjoint, so one port hosts them all):

| Route set | Real paths | Stands in for | Credential convention |
|---|---|---|---|
| DataMate | `/api/knowledge-base/*`, `/api/data-management/*` | DataMate knowledge-base + download APIs | Authorization forwarded, not validated |
| RAGFlow | `/api/v1/datasets*` | RAGFlow datasets / search | `Authorization: Bearer <any>` |
| dify | `/v1/datasets*`, `/datasets/*` | Dify datasets / retrieve / upload-file | `Authorization: Bearer <any>` |
| iData | `/apiaccess/*` | iData knowledgeSpaces / knowledgeBases / retrievals | `Authorization: Bearer <any>` |
| haotian | `/haotian/*` | Haotian knowledge-sets / retrieve | raw `Authorization` header |
| assets | `/assets/*` | arbitrary external HTTP resources | none (per-asset status codes instead) |
| fault | `POST /v1/chat/completions` | OpenAI-compatible model gateway with controlled failures | none (model record carries any key) |
| AIDP protocol | `/KnowledgeBase/*`, `/ModelService/*` | Managed AIDP **and** independent AIDP | `Authorization: Bearer mock-aidp-key`, tenant `aidp` |

Root mounting is not cosmetic: the product drops base paths in two places —
`backend/management/services/file/image_proxy.py` and `ind_aidp_service.py` rebuild AIDP
image URLs from scheme+netloc only, and the SDK's
`DataMateSearchTool._parse_server_url` rebuilds its base from
scheme+host+port only — so a path-prefixed base can never work for the AIDP
image flow or the DataMate retrieval tool. Root-mounted bases serve every
product chain (sync AND tool), exactly like real deployments. Independent
AIDP tests configure `server_url` at this service's root with tenant `aidp`
and the AIDP mock key.

The AIDP implementation is the existing, unmodified mock at
`test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py`, loaded via
`importlib` and mounted as an ASGI sub-app. Its own `/health`, `/_reset`,
`/_mock/*` endpoints are shadowed by the unified control plane below, which
forwards AIDP operations to the sub-app in-process. Note the AIDP import
defaults (`processing=0`, `upload=0`); only the standalone CLI defaults
`--upload-seconds` to 10.

## Two addresses, never one

The mock is reached through two different URLs depending on who is calling:

| Calling side | URL | Example |
|---|---|---|
| Runner / test code (control plane, wire export, direct asset fetch, latency measurement) | `runner_url` | `http://127.0.0.1:30090` |
| Product containers (config/runtime outbound params, model records, tool configuration) | `product_url` | `http://ext-knowledge:30090` |

The published port binds to `127.0.0.1` only; the product side reaches the
service through the product network overlay by its compose DNS name. Test
helpers pick the side explicitly (`test-e2e/infra/automation/shared/ext_knowledge.py`);
self-referential URLs (Dify `download_url`) are derived from the request's
own Host header, so a URL handed to the product is product-reachable and a
URL fetched by the runner is runner-reachable. Do not "fix" one by
mechanically replacing the host.

## Base URL conventions per service

Every product configuration points at the plain service **root**:

| Product configuration | Value |
|---|---|
| `AIDP_SERVER_URL` (env) | `http://<product-host>:30090` |
| ind-AIDP tool `server_url` | `http://<product-host>:30090` (tenant `aidp`, key `mock-aidp-key`) |
| DataMate `server_url` / tool config | `http://<product-host>:30090` (root — the retrieval tool drops base paths) |
| Dify `dify_api_base` | `http://<product-host>:30090` (service appends `/v1/datasets`) |
| Dify dify_search tool `server_url` | `http://<product-host>:30090/v1` (tool appends `/datasets/...`; both path variants are served) |
| RAGFlow base / tool | `http://<product-host>:30090` |
| iData `idata_api_base` / tool | `http://<product-host>:30090` |
| Haotian `list_url` / `retrieve_url` | `http://<product-host>:30090/haotian/api/knowledge-sets` / `.../api/retrieve` (no product-side path contract; stable choice) |
| Arbitrary asset URLs | `http://<runner-or-product-host>:30090/assets/<name>` |
| Fault-model `base_url` (LLM record) | `http://<product-host>:30090/v1` |

### Fault model API base — read this before "fixing" it

The fault route set serves exactly one endpoint, `POST /v1/chat/completions`
(plus SSE when `stream: true`). OpenAI-compatible clients append
`/chat/completions` to the configured API base, so a model record created
with `base_url = http://<product-host>:30090/v1` produces real wire requests
at `/v1/chat/completions`. Earlier documentation suggested configuring the
plain gateway root (`http://<host>:30090`) as the model API base — that
convention belongs to *service roots* like AIDP/DataMate, not to
OpenAI-compatible API bases, and is corrected here. There is no
`/chat/completions` alias at the root, no `/fault` or `/unavailable` prefix
(that scheme belonged to the retired test-assets fault provider), and no
doubled `/v1/v1` — any of those would land on 404 by design.

## Driving it from the product UI (agent tools + seed catalog)

What a human enters in the agent editor when binding these services as
tools: **工具管理 → 选择工具 → the 本地工具 tab → the tool's gear (配置)
action**. Base URLs use the product-side address from the table above
(`http://<product-host>:30090`; `ext-knowledge` is the compose DNS name in
the bundled deployment). Credentials are credential *shapes*, never
secrets: the route sets accept any Bearer string, so enter realistic-looking
values.

| Service | Tool (`source: local`) | Configuration fields | Runtime input | Notes |
|---|---|---|---|---|
| DataMate | `datamate_search` | `server_url` = root; pick KBs in the picker (`index_names`) | `query` | No auth header is validated |
| Dify | `dify_search` | `server_url` = root **+ `/v1`** (official shape); `api_key` = any Bearer; pick datasets (`dataset_ids`) | `query` | Both `/v1/datasets` and `/datasets` are served and the product proxy strips a trailing `/v1`, so the official form works across every path |
| RAGFlow | `ragflow_search` | `server_url` = root; `api_key` = any Bearer; pick datasets (`dataset_ids`) | `query` | |
| iData | `idata_search` | `server_url` = root; `api_key` = any Bearer; `user_id` = any value (not validated); `knowledge_space_id` (e.g. `space-alpha`); `rerank_model_id` = **required by the tool**; pick KBs (`dataset_ids`) | **`question`** | The tool's runtime input is `question`, not `query` |
| Haotian | `haotian_search` | `list_url` = root + `/haotian/api/knowledge-sets`; `retrieve_url` = root + `/haotian/api/retrieve`; `authorization` = any non-empty value; pick KBs (`dataset_ids`) | `query` | The connector forwards the raw header, so no `Bearer ` prefix is required |
| AIDP (managed) | — | Use the agent's 知识库管理 section; the deployment wires `AIDP_SERVER_URL` | — | Nothing to type |
| AIDP (independent) | `ind_aidp_search` | `server_url` = root; `api_key` = `mock-aidp-key` (exact, like a real issued key); `tenant_id` = `aidp`; pick KBs (`kds_list`) | `query` | |

The built-in test panel submits the tool's runtime inputs verbatim;
`query` / `question` is required. A validation error of the form
`forward() missing 1 required positional argument: 'query'` means the test
request carried no query — refill the 查询词 field and submit again
(interacting with the KB picker after typing can reset the field in some
builds).

### Seed catalog

What the pickers list and the retrieval returns. `POST /_reset` restores
all of it.

| Service | Seeded selections | Worth picking |
|---|---|---|
| DataMate | `datamate-kb-001` 运行手册知识库, `datamate-kb-002` 产品文档库, `datamate-kb-003`…`021` (empty page fillers), `datamate-kb-graph` | 001/002 carry retrievable chunks |
| Dify | `dify-ds-handbook` (Nexent Product Handbook), `dify-ds-faq` 常见问题 FAQ, plus `dify-ds-empty` / `-archive` / `-legacy` / `-unicode` (empty) | handbook / faq carry chunks |
| RAGFlow | `ragflow-ds-main` (Main Corpus, 25 docs), `ragflow-ds-legal` 合规语料库 (8), `ragflow-ds-faq` (3), `ragflow-ds-legacy` (1), `ragflow-ds-empty` | main / legal / faq carry chunks |
| iData | `space-alpha` → `idata-kb-alpha-1` 设备维护手册, `idata-kb-alpha-2` Safety Regulations; `space-beta` → `idata-kb-beta-1` 民航规章库 | All three carry chunks |
| Haotian | 军事知识集 → `ht-ds-001` 装备手册 (+ a `null` entry the product maps to a default UUID), 民用知识集 → `ht-ds-101` 民航规章 | Both carry chunks |
| AIDP | 25 KBs in the catalog (`aidp-kb-product` AIDP Product Handbook, `aidp-kb-api`, `aidp-kb-faq`, `aidp-kb-04`…`25`); the product lists only KBs registered in its own permission table, so register the ones a journey needs | `aidp-kb-product` carries the retrieval oracle (`AIDP产品介绍.pdf`); `aidp-kb-faq` is renamed at startup into the 政务服务与城市治理知识库 demo with 8 Chinese files |

Two AIDP seed behaviors worth knowing before a hand-run: the Chinese demo
rename/files are applied when the mock **starts**, so a later `/_reset`
restores the plain seeds (restart the mock to get the demo back); and the
permission-table registration above is product state, cleared by a fresh
product database, not by this service.


`GET /v1/models` is deliberately absent (404): LLM model creation performs
no connectivity probe, so no consumer needs it. Extend the provider only
when a suite case actually calls a new endpoint.

## Control plane

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness; reports per-service status incl. AIDP (top-level `status` stays `ok` even when a service is degraded — readiness rules must check `services.*` individually, as deployment.json does) |
| `POST /_reset` | `{"services": ["dify", ...]}` or empty body → reset all (route sets + AIDP) back to seeds |
| `POST /_mock/fail-next` | `{"service", "count", "status"}` — next N requests to that route set fail; `service: "aidp"` proxies to the AIDP sub-app (scoped to `/KnowledgeBase` paths only) |
| `POST /_mock/fail-reset` | `{"service": ...}` or empty → clear failure plan |
| `POST /_mock/latency` | `{"service", "delay_ms"}` (prefixed route sets only) |
| `POST /_mock/assets` | `{"assets": [{name, content_type, size?, content_b64?, filename?, support_ranges?, status?, redirect_to?, latency_ms?}]}` — runtime asset declaration |
| `GET /_mock/identity` | Deployment metadata (`run_id`, `source_revision`, `build_manifest_sha256`) from the container environment; no secrets. An empty `run_id` marks an unowned instance — runners must refuse write control-plane operations on it |
| `GET /_mock/state` | Failure-plan snapshot plus identity, for evidence export |
| `GET /_wire-log?service=&limit=` | Request log for evidence, with `retained`/`dropped` counters to detect ring-buffer truncation |
| `POST /_wire-log/clear` | Clear the wire log (bound: 2000 records) |

State persists per route set under `_state/` and survives restarts; `/_reset`
restores seeds. Failure counters and latency are in-memory only.

### AIDP reset is more than the sub-app's own `/_reset`

The AIDP sub-app's `/_reset` only clears KB/document state. The unified
`POST /_reset` (and `{"services": ["aidp"]}`) additionally drives the sub-app
through its public control endpoints to restore failure counters and every
runtime knob — `processing-seconds=0`, `history-page-size=10`,
`upload-seconds=0`, `file-faults query_seconds=0 query_fail=false
delete_fail=false` — and checks each response code. A half-completed AIDP
reset surfaces as HTTP 502, never as a silent success. This is what makes
per-case isolation real: cases that tune knobs or schedule failures cannot
leak them into the next case.

## Running

Standalone (local dev / AIDP-minimal profile; the AIDP mock is loaded from
the repository checkout):

```bash
python test-e2e/infra/mock-services/ext-knowledge-mock/server.py --port 30090
```

Through the mock-services dispatcher (builds the image from a packed,
batch-owned context, waits for readiness — all eight services — and attaches
the product network; the product must already be deployed):

```bash
python test-e2e/infra/mock-services/ext-knowledge-mock/build_context.py --output <context-dir>
export EXT_KNOWLEDGE_BUILD_CONTEXT=<context-dir>
export EXT_KNOWLEDGE_MOCK_RUN_ID=<owning-run-id>
# ...plus the SOURCE_REVISION / BUILD_MANIFEST_SHA256 values the packer prints
python test-e2e/infra/mock-services/deploy.py up ext-knowledge
python test-e2e/infra/mock-services/deploy.py status ext-knowledge
python test-e2e/infra/mock-services/deploy.py stop ext-knowledge
```

The published port is fixed at `30090` (the readiness registry probes a
literal localhost URL); confirm the port is free before `up`. `stop` only
stops the registered service — no `down`, no volume deletion. Run a single
uvicorn worker — all state lives in-process.

Runner-side integration: cases declare `required_mock_services` in
`execution.yaml` (logical IDs: `knowledge-provider`, `http-fixture`,
`model-provider`). The suite starts this mock as a private controlled process
on a free port for the case, exactly like the `test-assets` and `test-mcp`
servers, and `test-e2e/infra/tools/ext_attach.py` validates health and resets
per-case state over HTTP. **No machine-local YAML, identity handshake or
cross-batch lock is required.** The Compose dispatcher above remains available
for an optional external shared instance; only that mode uses
`config/ext-knowledge.yaml`.

Profile-selected cases were removed together with the mock/real split:
PW-KB-AIDP-01 attaches through its plain `knowledge-provider` dependency, and
there is no machine-local journey file to create.

## Deliberate quirks (do not "fix" without checking the adapters)

- Dify retrieve/upload-file are registered under both `/datasets/...`
  and `/v1/datasets/...`: the backend datasets proxy strips a trailing
  `/v1` while the SDK tool's `server_url` conventionally includes it — a
  real Dify host serves both path variants.
- DataMate routes are root-mounted (`/api/knowledge-base/...`,
  `/api/data-management/...`) like a real DataMate, and MUST stay that way:
  `DataMateSearchTool._parse_server_url` rebuilds its base URL from
  scheme+host+port only, silently dropping any base path — a prefixed base
  makes the retrieval tool 404 while the sync chain (plain concatenation)
  keeps working, a confusing half-broken state.
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
  (`POST /v1/chat/completions`), two markers
  (`force-regenerate-name-failure` -> 503, `provider 429` -> first two calls
  per marker 429 then recover), fixed recovery content, SSE variant.
  `/v1/models`, the `failure probe` / `forced fault` markers and usage stats
  are deliberately absent because no suite case consumes them — extend only
  when a case does (pinned by test_models_endpoint_intentionally_absent).

## Fidelity tests

`test/ext_components/ext_knowledge/` drives the **real product adapters**
(DataMateClient, dify/idata/ragflow/haotian services) against a live
instance of this service — assembled from a per-session temporary copy so
the source tree and any deployed instance are never touched — so
adapter-contract drift turns into a red test in CI instead of a late E2E
failure:

```bash
pytest test/ext_components/ext_knowledge -v
```

Starting the in-process server binds a listener on 127.0.0.1; run it only
in environments where local test listeners are permitted.
