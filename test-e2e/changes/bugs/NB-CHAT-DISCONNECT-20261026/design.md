# Persisted chat execution after subscriber disconnect

## Scope and design

User requirement: read the `conversation_id` response header from `/nb/v1/chat/run`, close the response without consuming SSE, and let the admitted Agent finish and persist its result. This owns F-146 / F-146-RULE-01. HTTP routes, payloads and SSE event contracts stay unchanged. This is process-local execution, not durable scheduling across server restarts.

The Northbound service forwards to the runtime, where ordinary frontend chats and Northbound runs share `management.services.agent.subscription.run_agent_stream`. Persisted runs already use a buffered channel and detached producer. Starting that producer inside the response generator tied startup to body iteration. Releasing its reservation from the subscriber's `finally` also let early disconnect invalidate preparation before run registration.

Create the response and start its producer before returning it. The producer owns the preparation reservation and deferred worker cleanup; subscriber close only detaches channel consumption. Producer completion/failure/cancellation releases its resources, including cancellation before its first iteration. Debug/A2A direct streams keep response-owned cancellation. Explicit `/agent/stop/{run_id}` continues through the existing run manager and cancellation scope. Existing resume/replay logic precedes this branch and remains unchanged.

## Existing proof and remaining gaps

| Behavior | Existing assertions | Action |
| --- | --- | --- |
| Disconnect after first produced SSE chunk | `test_non_debug_producer_survives_sse_disconnect` checks second chunk and completion | Reuse UT |
| No response-body iteration | No existing UT starts producer before iteration | Add focused UT |
| Disconnect before preparation registers the run | Existing mocked stream does not validate reservation ownership | Add UT with the real reservation manager and controlled stream preparation |
| Error and cancellation cleanup | Producer error, generator-close and shutdown tests exist | Reuse and add pre-start cancellation/reservation assertions |
| Normal new/existing Northbound SSE | AGT-064 consumes the stream and checks conversation_created/header consistency | Reuse D3 unchanged |
| Headers-only disconnect through proxy/runtime/model/persistence | AGT-064 never closes early | Add NB-CHAT-DISCONNECT-001, D3, real provider |
| Frontend explicit stop and debug disconnect | Existing stop/direct-stream tests | Reuse UT; no frontend code changes |

No new D1 is needed: isolated lifecycle decisions belong in UT; the extra formal evidence requires the deployed HTTP/runtime/model boundary. D2 adds no separate proof beyond this D3. D4 UI and D5 restart/load acceptance are outside this fix. All existing Cases and scripts are preserved. The unrelated broad legacy acceptance gaps in AGT-064 are deferred.

## Current acceptance and traceability

| AC | Observable behavior | Code | Proof | Result |
| --- | --- | --- | --- | --- |
| AC-001 | An admitted producer runs without body iteration | subscription.run_agent_stream | New lifecycle UT and NB-CHAT-DISCONNECT-001 | UT PASS; D3 BLOCKED |
| AC-002 | Disconnect while preparing cannot release the reservation or allow a duplicate run | subscriber finally and producer ownership | New lifecycle UT with real AgentRunManager | PASS |
| AC-003 | Producer completion/error/cancellation releases reservation and any unbound worker | producer done callback | New lifecycle UT and existing producer shutdown tests | PASS |
| AC-004 | Normal SSE, debug disconnect and explicit stop retain their contracts | unchanged direct-stream branch, run manager | Existing targeted UT and AGT-064 | UT PASS; D3 BLOCKED |

## Verification evidence — 2026-10-26

Tested working-tree source is based on `5336b7719266b4e010299eff4c6bb9717042fddb`. The final product change is limited to `backend/management/services/agent/subscription.py` (45 added / 20 removed lines, including moved producer setup). No frontend or public API definitions change. Producer cleanup only cancels an unfinished worker when it can still release the preparation reservation; a worker already bound to a run retains its own cleanup/capacity lifetime.

Traditional UT uses the existing root `.venv` Python 3.11 environment. The backend environment's attempted collection failed because `jinja2` is missing; it is not counted as a pass. No dependencies were changed.

```text
.venv/bin/python -m pytest test/backend/services/test_agent_subscription_lifecycle.py test/backend/services/test_agent_service.py -q --disable-warnings -k 'subscription_lifecycle or run_agent_stream or non_debug_producer or cancelled_producer or debug_stream or stop_agent_tasks or poll_runtime_cancel_signal or shutdown_agent_stream_tasks'
50 passed, 449 deselected

.venv/bin/python -m pytest test/backend/services/test_runtime_proxy_service.py test/backend/services/test_streaming_channel.py -q --disable-warnings
66 passed
```

The eight new lifecycle tests assert producer execution before body iteration and history replay; valid reservation and duplicate rejection during preparation; sanitized failure with released worker/capacity; no premature cancellation of a bound worker; cancellation both before and after producer startup; direct debug disconnect; and explicit stop after subscriber detach. The existing service selection also covers admission rejection, queue timeout, SSE delivery and request-owned task shutdown. Proxy/channel tests cover upstream closure and buffered streaming.

Negative detection used an uncommitted temporary pytest harness to load only the original `run_agent_stream` AST from the base commit into the test process. Product files were never replaced. Selecting `headers_only_response or disconnect_during_preparation` produced **2 expected failures**: no producer exists before body iteration, and subscriber close removes the reservation so duplicate admission no longer raises. Both selectors pass with the fixed source.

Formal checks are separate:

- Design and implementation validation pass with `--generate --require-ut-change NB-CHAT-DISCONNECT-20261026 --require-acceptance-case NB-CHAT-DISCONNECT-001`. Generated F-146 associations include the new Case; registry/Excel remain generated local views.
- Collection of the new Case reports both `new` and `existing` parameter variants. Collection used an external temporary home containing only `features: {}` for the collection hook, with no service credentials. It is not runtime evidence.
- `.venv/bin/python test-e2e/infra/tools/run_cases.py NB-CHAT-DISCONNECT-001 AGT-064` is **BLOCKED**: `NEXENT_TEST_HOME` is unset and no runtime test home was supplied. Neither Case was executed. The initial collection attempt without that configuration also failed at the existing collection hook.
- Copyright validation of all three changed Python files and `git diff --check` pass.

Independent assertion review: `detached_run` submits one POST and exits the HTTP stream context after reading only status/headers, preserving the existing ID and journaling new IDs for cleanup. `assert_persisted_answer` polls history plus real PostgreSQL status/counts, requires a completed assistant answer with the unique marker, rejects stopped/failed messages and requires exactly one persisted user and assistant message. Its only HTTP action after detach is GET; no retry POST or stop is present. The parameterized test runs this path for both variants using the same identity as the Northbound key. Both acceptance bindings name the actual collected test. These assertions are implemented; live provider/persistence behavior remains unverified.

SHA-256 evidence for reviewed artifacts:

```text
4b1ddcf2649b1566d274d94940db15df9d9eb3a4fa9a88cca2b818435f308416  backend/management/services/agent/subscription.py
a339511b00b26522e11ae40534853089657015ccf1f7e2d48c331fc0367d3862  test-e2e/cases/NB-CHAT-DISCONNECT-001/case.yaml
b783c709e46a453d5bebc9df36348f7bee71ad820e1374c09fa6b96bb5d91550  test-e2e/cases/NB-CHAT-DISCONNECT-001/test.py
```

## Hotfix transplant verification — 2026-10-27

Cherry-picked `555306ea7ac8477872f43f46121bfd16ed4b5c54` onto `hotfix/v2.8.1` at `11f516b60` without conflicts. The product, UT and formal Case files match the original fix; no develop merge or develop-specific lifecycle fixture adaptation is included.

The same targeted commands above pass on this baseline: **50 passed, 449 deselected** for lifecycle/service UT and **66 passed** for proxy/channel UT. Copyright checks for all three changed Python files and `git diff --check` pass.

Implementation asset validation with `--generate --require-ut-change NB-CHAT-DISCONNECT-20261026 --require-acceptance-case NB-CHAT-DISCONNECT-001` fails on one pre-existing baseline issue: `CHAT-AGENT-DETAIL-20261026` references missing `frontend/tests/workbench/ConversationResumeBranch.test.tsx`. The reference already exists and the file is absent in `11f516b60`; this transplant changes neither. Real D3 remains blocked by the runtime prerequisites described above.

## Verification limits

Both documented sibling SPEC directories (`nexent-doc`, `nexent_SPEC`) are absent. The formal assets and actual UT/scripts in this repository were inspected; this is a delivery record, not a replacement external SPEC. Record UT, static validation and real runtime results separately. Missing runtime configuration or credentials blocks D3 acceptance and never counts as a pass.
