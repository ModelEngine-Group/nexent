# W10: Guaranteed Context Fit

## Objective

Make request fit a mandatory runtime invariant: every serialized main-model and
compaction-model request is within its W2 safe input budget before provider dispatch.

## Current State and Scope

`sdk/nexent/core/agents/agent_context.py` can warn after compression while still
returning oversized context. W10 replaces that best-effort behavior with a deterministic
`ContextFitPipeline`. It owns final assembly and emergency degradation; richer
component reducers and artifact offloading arrive through W8 and P4. The initial
gateway does not depend on those richer stages: hard fit is delivered first, and later
workstreams may improve retained quality without weakening or replacing the invariant.

### Current Dispatch Path Analysis

All production model calls already converge on a single chokepoint:
`openai_llm.py:186` (`self.client.chat.completions.create(stream=True)`). Nine call
paths flow through this chokepoint: agent main loop, max-steps handler, VLM
image/audio/video analysis, long-context analysis, and three compression paths.

However, two production bypass paths exist that skip the chokepoint:

| ID | File | Issue |
|----|------|-------|
| B1 | `backend/utils/llm_utils.py:100` | System prompt generation manually constructs completion kwargs and calls `client.chat.completions.create` directly, bypassing `OpenAIModel.__call__` |
| B2 | `backend/services/conversation_management_service.py:282` | Title generation calls `llm.generate(messages)` which routes to the smolagents parent class `generate` method, bypassing nexent's `__call__` override |

Non-production direct calls (health checks in `openai_llm.py:350` and
`openai_vlm.py:72`, benchmark code in `eval_utils.py:169`) are low-risk and out of
scope for bypass elimination.

## Pipeline Contract

Input: capacity snapshot, safe input budget, policy version, mandatory `ContextItem`
minimums, optional representations, and complete recent tool-call/result pairs.

Output: serialized provider request, token accounting, selected representation IDs,
loss/reduction decisions, and a fit status. The pipeline must either return a fitting
request or a typed `mandatory_context_overflow` failure. It must never dispatch an
unverified request.

Production dispatch requires a W1 snapshot with known hard capacity. Unknown hard
capacity fails with `provider_capability_unknown`; W10 cannot claim guaranteed fit by
guessing a total window. When exact counting behavior is unknown but hard capacity is
known, W10 verifies against the W2 budget that already includes the mandatory 10%
uncertainty reserve and records that the count is estimated rather than exact.

Deterministic stages:

1. Remove expired, invalid, or non-required items.
2. Use already-available bounded summaries, pointers, or lower-fidelity representations.
3. Remove or deterministically truncate optional content while preserving complete
   tool-call/result pairs.
4. Apply explicit emergency truncation and emit a context-loss event.

P3-W6 may later add policy-guided selection, progressive component reduction,
artifact offload, and governed compaction as quality-enhancing stages. Those stages
cannot become prerequisites for hard fit or dispatch safety.

Selection is two phase: install every mandatory minimum representation, then spend
remaining tokens on higher-fidelity upgrades by deterministic policy utility.

## Gateway Interface and Failure Contract

```text
fit_and_serialize(request_intent, capacity_snapshot, budget_snapshot, context_items,
                  policy_version) -> FitResult
```

`FitResult` contains the final provider payload, verified serialized count, selected
representations, stage decisions, loss metadata, stable-prefix fingerprint, full-prompt
fingerprint, W1 capacity fingerprint, W2 budget fingerprint, and status. Required
failures include
`mandatory_context_overflow`, `serialization_failed`, `tokenizer_unavailable`,
`provider_capability_unknown`, `invalid_representation`, and
`provider_limit_inconsistent`, plus `capacity_snapshot_mismatch` and
`budget_snapshot_mismatch`.

Each stage is deterministic, idempotent, independently testable, and unable to dispatch
requests. After every material change, canonical serialization and counting rerun. A
provider overflow triggers one request-local limit correction and at most one retry.

## Final Assembly and Cache Metadata Boundary

W3 provides a deterministic `CachePartitionPlan` containing partition assignments,
ordering rules, and allowed provider cache directives. W10 alone owns final provider
payload assembly, canonical serialization, token counting, fit verification, and the
stable-prefix/full-prompt fingerprints calculated from that exact final payload.

The trusted dispatch boundary sends the W10 `FitResult` payload unchanged. It may add
transport-only authentication, tracing, and retry metadata, but it cannot modify prompt
content or cache directives. W3 never fingerprints a pre-fit payload or dispatches a
request.

## Trusted Model Dispatch Boundary

Production provider credentials and dispatch capability are available only to the
trusted server-side dispatch path. Immediately before dispatch, it requires an
authorized W4 identity, an immutable P3 policy decision, a server-resolved or verified
W2 budget snapshot, and the exact final W10 `FitResult`. SDK/client assertions and
ordinary internal callers are untrusted and cannot mark a payload authorized, governed,
or fit.

Missing, stale, mismatched, or caller-expanded decisions fail closed before provider
dispatch. Required failures include `dispatch_not_authorized`,
`policy_decision_invalid`, `budget_snapshot_invalid`, and `fit_result_invalid`.
Bypass detection remains diagnostic; direct production provider-dispatch paths are
removed or denied rather than merely monitored.

The trusted path verifies that the W2 snapshot references the active W1 fingerprint
and that the final `FitResult` references both active W1 and W2 fingerprints. It also
verifies provider/model identity and requested output match the final provider request.
W10 may reduce input content but cannot re-resolve capacity, recalculate reserve, or
increase the W2 hard input budget.

## Required Deliverables and Phases

- Deliver the fit gateway, canonical serializers/counters, stage interface, typed
  outcomes/events, mandatory installer, optional-upgrade selector, trusted dispatch
  enforcement, and bypass detection.
- First deliver the independent minimal hard-fit gateway. Then phase through shadow
  counting, compaction-call enforcement, main-call enforcement, P3-W6 quality-stage
  integration, and deletion/blocking of every direct provider-dispatch path.

## Implementation Plan

1. Add a canonical provider-request serializer and tokenizer/count verification step.
2. Define typed fit outcomes, fault codes, and reduction/loss event payloads.
3. Implement the minimal independent stages behind a common stage interface.
4. Route all main and compaction calls through one fit gateway.
5. Add a single provider-overflow recovery retry using provider-reported limits.
6. Refuse safely when mandatory minimums cannot fit; include actionable diagnostics.
7. Accept W3 cache partition plans and compute cache metadata only from the final
   serialized payload.
8. Connect P3-W6 quality-enhancing stages without weakening the hard invariant.
9. Eliminate production dispatch bypasses and restrict provider credentials to the
   trusted path:
   - **9a. Fix B1** (`backend/utils/llm_utils.py:100`): Replace manual
     `_prepare_completion_kwargs` + direct `client.chat.completions.create` with a
     call to `llm(messages)` so it flows through `OpenAIModel.__call__`. This also
     gains monitoring, observer, and extra_body integration for free.
   - **9b. Fix B2** (`backend/services/conversation_management_service.py:282`):
     Replace `llm.generate(messages)` with `llm(messages)` to route through the
     trusted `__call__` path instead of the smolagents parent `generate` method.
   - **9c. Credential isolation** (architecture layer): Ensure only requests that
     have passed W10 fit verification can access production provider API keys.
     Options include injecting credentials at the trusted dispatch layer rather than
     storing them on `OpenAIModel` instances, or adding a fit-verification gate in
     `__call__`. This is a broader architectural change to be designed alongside
     the W10 gateway implementation.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/models/openai_llm.py` — primary chokepoint (line 186)
- `sdk/nexent/core/utils/token_estimation.py`
- `sdk/nexent/monitor/agent_observability.py`
- `backend/utils/llm_utils.py` — bypass B1 (step 9a)
- `backend/services/conversation_management_service.py` — bypass B2 (step 9b)

## Tests

- Property-test arbitrary item combinations, budgets, representations, and ordering.
- Verify serialized, not pre-serialization, token counts fit the hard budget.
- Prove unknown hard capacity blocks production dispatch and unknown exact-counting
  behavior uses the W2 10% uncertainty reserve without claiming exact token counts.
- Test mandatory-only overflow, emergency truncation, and stable reason codes.
- Test tool-call/result pair integrity under every reduction stage.
- Simulate provider context-length errors and prove one deterministic retry without loops.
- Prove the minimal gateway guarantees fit before P3-W6 integrations are available.
- Prove W3 plans cannot change fit decisions and fingerprints match the exact final
  payload dispatched by the trusted boundary.
- Run multilingual, multimodal, and large-schema fixtures. Release 1 multimodal
  fixtures cover only text modality; add modality-specific fixtures when a modality
  enters product scope. **Finding:** CM-026.
- Negative integration tests prove SDK/client and ordinary internal callers cannot
  dispatch without valid W4, P3, W2, and W10 decisions.
- Bypass elimination tests prove that all production `chat.completions.create` calls
  flow through the single chokepoint (`openai_llm.py:186`). Specifically:
  - System prompt generation (`llm_utils.py`) routes through `OpenAIModel.__call__`.
  - Title generation (`conversation_management_service.py`) routes through
    `OpenAIModel.__call__` and does not invoke the smolagents parent `generate` method.
  - Static analysis or repository search confirms no remaining direct production
    provider dispatch paths outside the chokepoint and health-check exceptions.

## Rollout and Definition of Done

Start with the minimal hard-fit gateway, shadow evaluation, and fault telemetry, then
enforce on compaction calls and finally main calls. Integrate P3-W6 quality stages
afterward. Maintain a temporary kill switch only for diagnosis; it must not permit
unverified production dispatch. W10 is done when all model-call paths use the trusted
server-side gateway, direct production provider access is denied, property tests pass,
and preventable context-length provider errors meet the W9 release target.
