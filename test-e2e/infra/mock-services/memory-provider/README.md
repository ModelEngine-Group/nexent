# External memory Mock (Mem0 protocol)

This service implements the HTTP subset used by the repository's existing
`backend/memory_provider_plugins/mem0/provider.py`. No product changes, Mem0
account, AI model, database, or Python package installation is required for the
Mock itself. This is a deterministic **integration fixture**, not evidence of
real Mem0 availability, semantic recall quality, or multi-provider compatibility.

## Deploy

Create a machine-local file outside Git, for example
`<test-home>/config/memory-mock.env`, from `.env.example`. Generate a dedicated
test-only credential, put it in `NEXENT_EXTERNAL_MEMORY_API_KEY`, and restrict
file permissions. Do not use a real Provider/model API key for the Mock.

Run from the repository root, using a verified interpreter:

```bash
# Ubuntu: python3. Windows: python or the test runtime's python.exe.
python3 test-e2e/infra/mock-services/deploy.py up memory --env-file <test-home>/config/memory-mock.env
python3 test-e2e/infra/mock-services/deploy.py status memory --env-file <test-home>/config/memory-mock.env
python3 test-e2e/infra/mock-services/deploy.py logs memory --env-file <test-home>/config/memory-mock.env
# Stop only this Mock, never product containers or A2A.
python3 test-e2e/infra/mock-services/deploy.py stop memory --env-file <test-home>/config/memory-mock.env
```

The default project is `nexent-mock-memory`; IDs `memory`, `memory-provider` and
`mem0` resolve to the same registration. Use the same `--project` and env file
for all operations. `--standalone` omits the product network; otherwise the
existing network is selected with `--product-network`. The host port is bound
to loopback, not to public interfaces. Readiness probes require no credential.

For a product container on the attached network, configure the **Mem0 plugin**:

| Existing configuration | Value |
| --- | --- |
| `NEXENT_EXTERNAL_MEMORY_PLUGIN` | `mem0` |
| `NEXENT_EXTERNAL_MEMORY_ENDPOINT` | `http://memory-provider:18120` |
| `NEXENT_EXTERNAL_MEMORY_API_KEY` | The dedicated credential from the local file |
| Mem0 plugin parameter `base_url` | Same container-reachable endpoint |
| Mem0 plugin parameter `api_key` | Same dedicated credential |

These three environment names already belong to `PW-MEMORY-PROVIDER-01`.
The deployment CLI does **not** edit `secrets.env`, product settings, the Daily
pipeline, or case definitions. Explicitly pass/load the local configuration
through the test runner before attempting that Journey. For a host-run product,
use `http://127.0.0.1:18120` instead; container loopback is not the host.

In the current UI the Mem0 endpoint field is labeled **API Base URL**. Do not
leave it at `https://api.mem0.ai` while using a Mock credential. A UI script
must require and fill that field, not silently ignore an unmatched locator.

Keep Mock execution receipts separate from real-service receipts. A passing
adapter smoke test is not a passing `PW-MEMORY-PROVIDER-01` result: the latter
also requires actual browser CRUD, enablement, chat retrieval, secret masking,
and cleanup. Chat evidence must establish an external-memory search result;
echoing a marker already present in the user's question is insufficient proof.

## Protocol and behavior

All endpoints except `/healthz` and `/readyz` require
`Authorization: Token <mock-credential>`. Optional `X-Org-Id` partitions data.
Never expose control endpoints to untrusted clients. The fixed host port is
18120; the Mock has no persistent volume or access to product data directories.

| Method and path | Behavior |
| --- | --- |
| `POST /v3/memories/add/` | Stores messages verbatim (`infer=false`), returns `event_id` |
| `GET /v1/event/{event_id}/` | Reports `SUCCEEDED` after the stored unit exists |
| `POST /v3/memories/search/` | Returns `{results:[{id,memory,score,metadata}]}` |
| `DELETE /v1/memories/{id}/?user_id=...` | Removes one scoped memory and its events |
| `POST /__control/fault` | Sets a user/org-scoped status or response delay |
| `GET /__control/observations?user_id=...` | Returns only add/search counts, no secrets or contents |
| `DELETE /__control/reset?user_id=...` | Clears that user/org's records, events, observations and fault |

Search accepts identity equality filters (`user_id`, `agent_id`, `run_id`) and
`AND`, with at least a user or agent identity. Unsupported/empty filters fail
closed. Matching is lexical, with no generated answers or embedding calls.
No stored matching item means an empty result. The product's own user-only
fallback is exercised by the smoke check, not implemented as a hidden shortcut
in the Mock. Event metadata supports scoped replay/upsert.

Fault body example (send with the same auth and org headers):

```json
{"user_id":"<isolated-test-user>","status":503,"delay_seconds":0}
```

Supported statuses: `200`, `401`, `403`, `429` (Retry-After: 1), `503`.
Delays range from 0 to 30 seconds. Restore with status 200/delay 0, or reset
only the isolated test user. There is no global reset or product shutdown.

Data expires after 24 hours, is bounded to 10,000 records/events, and disappears
on restart. Use unique test identities and delete/reset test-owned records;
do not clear a user shared by concurrent tests. Org isolation depends on the
client supplying a distinct org ID; the current plugin does not separately
send `tenant_id`, so this Mock must not be claimed to prove product tenant
isolation for deployments sharing the same org/key and user identities.

## Verification

Standard-library live HTTP regression tests (no dependency installation):

```bash
python3 -m unittest discover -s test-e2e/infra/mock-services/memory-provider/tests -v
python3 -m unittest discover -s test-e2e/infra/mock-services/tests -v
```

Using the existing test virtual environment, `smoke.py` invokes the unmodified
product `Mem0Provider` and its SDK models. It requires the dependencies already
needed by that plugin (`httpx`, SDK/Pydantic); missing imports fail, not skip.

```bash
# Ephemeral loopback server and random credential, both cleaned up automatically.
<test-python> test-e2e/infra/mock-services/memory-provider/smoke.py
# Verify the deployed Mock; only random smoke-owned users/organizations are cleared.
<test-python> test-e2e/infra/mock-services/memory-provider/smoke.py --url http://127.0.0.1:18120 --env-file <test-home>/config/memory-mock.env
```

Checks cover empty search, real ingest/event polling, marker retrieval,
user/org isolation, agent-to-user fallback, auth/403/429/503/timeout mapping,
recovery, wire counts, and cleanup. No credential, memory contents, or request
body is emitted by the Mock access logger or smoke report.
