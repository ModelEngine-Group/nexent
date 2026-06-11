# W3: Guaranteed Context Fit

## Objective

Make request fit a mandatory runtime invariant: every serialized main-model and
compaction-model request is within its W2 safe input budget before provider dispatch.

## Current State and Scope

`sdk/nexent/core/agents/agent_context.py` can warn after compression while still
returning oversized context. W3 replaces that best-effort behavior with a deterministic
`ContextFitPipeline`. It owns final assembly and emergency degradation; richer
component reducers and artifact offloading arrive through W11 and W12.

## Pipeline Contract

Input: capacity snapshot, safe input budget, policy version, mandatory `ContextItem`
minimums, optional representations, and complete recent tool-call/result pairs.

Output: serialized provider request, token accounting, selected representation IDs,
loss/reduction decisions, and a fit status. The pipeline must either return a fitting
request or a typed `mandatory_context_overflow` failure. It must never dispatch an
unverified request.

Deterministic stages:

1. Remove expired, invalid, or non-required items.
2. Replace large outputs with bounded summaries and artifact pointers.
3. Downgrade optional components through admissible representations.
4. Compact older history.
5. Reduce recent observations while preserving complete tool pairs.
6. Apply explicit emergency truncation and emit a context-loss event.

Selection is two phase: install every mandatory minimum representation, then spend
remaining tokens on higher-fidelity upgrades by deterministic policy utility.

## Implementation Plan

1. Add a canonical provider-request serializer and tokenizer/count verification step.
2. Define typed fit outcomes, fault codes, and reduction/loss event payloads.
3. Implement each pipeline stage behind a common stage interface.
4. Route all main and compaction calls through one fit gateway.
5. Add a single provider-overflow recovery retry using provider-reported limits.
6. Refuse safely when mandatory minimums cannot fit; include actionable diagnostics.
7. Connect W11 reducers and W12 artifact pointers without weakening the hard invariant.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/models/openai_llm.py`
- `sdk/nexent/core/utils/token_estimation.py`
- `sdk/nexent/monitor/agent_observability.py`

## Tests

- Property-test arbitrary item combinations, budgets, representations, and ordering.
- Verify serialized, not pre-serialization, token counts fit the hard budget.
- Test mandatory-only overflow, emergency truncation, and stable reason codes.
- Test tool-call/result pair integrity under every reduction stage.
- Simulate provider context-length errors and prove one deterministic retry without loops.
- Run multilingual, multimodal, and large-schema fixtures.

## Rollout and Definition of Done

Start with shadow evaluation and fault telemetry, then enforce on compaction calls and
finally main calls. Maintain a temporary kill switch only for diagnosis; it must not
permit unverified production dispatch. W3 is done when all model-call paths use the
gateway, property tests pass, and preventable context-length provider errors meet the
W15 release target.

