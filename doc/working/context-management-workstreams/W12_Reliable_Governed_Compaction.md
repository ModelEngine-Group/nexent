# W12: Reliable Governed Compaction

## Objective

Make semantic compaction a bounded, observable, independently governed service that
cannot take down or indefinitely delay the main agent run.

## Current State and Gap Analysis

The current implementation in `sdk/nexent/core/agents/agent_context.py` provides a
functional but incomplete compression system. This section maps the current
capabilities against W12 requirements to identify gaps.

### Current Architecture

```
CoreAgent._step_stream()
  → ContextManager.compress_if_needed(model, memory, ...)
    → [Trigger: _effective_tokens > token_threshold]
    → [Two-phase: Previous (60%) + Current (40%)]
    → [Compression path: L1 Full → L2 Trimmed → L3 Hard truncation]
    → [Error handling: context-length retry (1 attempt) → fallback to L3]
    → [Cache: PreviousSummaryCache / CurrentSummaryCache with anchor fingerprint]
```

### Current Strengths (Already Aligned with W12)

| Capability | Current Implementation | W12 Alignment |
|-----------|----------------------|---------------|
| Deterministic fallback | L3 hard truncation (no LLM call) | ✅ W9 deterministic fallback |
| Incremental compression | Cache-valid path compresses only new content | ✅ Reduces LLM calls |
| Cache mechanism | Anchor fingerprint matching | ⚠️ Partial (not W6-style) |
| Cost tracking | `CompressionCallRecord` (input/output tokens, chars, cache hit) | ⚠️ No latency measurement |
| Two-phase compression | Previous/Current separation | ✅ Avoids single-pass overload |

### Critical Gaps

| W12 Requirement | Current Status | Gap Severity |
|----------------|---------------|-------------|
| Independent compaction model | ❌ Uses main execution model | Critical |
| CompactionPolicy strategy object | ❌ No policy object | Critical |
| W1/W2 capacity settings | ❌ Direct `token_threshold` usage | Critical |
| Deadline/timeout | ❌ No timeout mechanism | Critical |
| Cancellation propagation | ❌ No cancellation mechanism | Critical |
| Provider-aware retry limits | ❌ Only retries on context-length error (1 attempt) | Critical |
| Rate-limit handling | ❌ No rate-limit handling | Critical |
| Concurrency limit | ❌ No concurrency control | Critical |
| Circuit breaker | ❌ No circuit breaker | Critical |
| Per-operation cost ceiling | ❌ No cost ceiling | Critical |
| Per-session cost ceiling | ❌ No cost ceiling | Critical |
| Summary prompt/schema versioning | ✅ Has `summary_system_prompt` and `summary_json_schema` | Partial |
| Validation rules | ⚠️ JSON parse only, no schema validation | Partial |
| W15 final fit integration | ❌ Not integrated | Critical |
| Invalid/no-progress summary rejection | ❌ No progress check | Critical |
| Unbounded retry loop prevention | ⚠️ Only 1 retry on context-length error | Partial |
| Execution state machine | ❌ No state machine | Critical |
| W4 lifecycle event persistence | ❌ Not persisted | Critical |
| Source fingerprint revalidation | ⚠️ Uses anchor fingerprint, not W6-style | Partial |
| Structural validation (CM-018, CM-021) | ❌ No structural validation | Critical |
| Semantic quality measurement (W13) | ❌ No measurement | Critical |

### Migration Strategy

The current `ContextManager` class is the primary refactoring target. W12 should:

1. Extract `_generate_summary` and `_do_generate_summary` into a dedicated compaction
   service with timeout, cancellation, and circuit breaker.
2. Replace direct `token_threshold` usage with W1/W2 capacity snapshots.
3. Add `CompactionPolicy` configuration object to `ContextManagerConfig`.
4. Integrate W15 final fit for all compaction model calls.
5. Add execution state machine around the compression pipeline.
6. Persist compression results as W4 `compression.snapshot` events.

## Compaction Policy

W12 owns semantic-compaction execution, validation, bounded retries, fallback, and
operation lifecycle. It does not define context authority, representation
admissibility, or compression snapshot truth; W8, W9, and W6 provide those contracts.

Define a versioned `CompactionPolicy` containing:

- Primary and fallback compaction models.
- W1/W2 capacity and reserve settings for compaction calls.
- Deadline, cancellation propagation, and provider-aware retry limits.
- Rate-limit handling, concurrency limit, and circuit-breaker thresholds.
- Per-operation and per-session cost ceilings.
- Summary prompt/schema versions and validation rules.
- Deterministic fallback behavior when semantic compaction is unavailable.

The main execution model is not implicitly the compaction model. All compaction calls
pass W15 final fit. Invalid or non-progress summaries are rejected and cannot trigger
unbounded retry loops.

### Compression Trigger Conditions

W12 executes compaction but does not define when to trigger it. Trigger conditions are
defined by W2 `CapacityReservePolicy.soft_limit_ratio`. The current implementation uses
two-phase thresholds:

- Previous phase: `prev_tokens > token_threshold * 0.6`
- Current phase: `curr_tokens > token_threshold * 0.4`

W12 should respect the W2 soft-limit ratio as the primary trigger, with the two-phase
thresholds as implementation details within the compaction service.

### Fallback Model Selection Strategy

When the primary compaction model fails, W12 uses a fallback model before falling back
to deterministic W9 hard reduction. Fallback model selection:

1. If primary model fails with `provider_unavailable` or `rate_limited`, use the
   configured fallback model from `CompactionPolicy`.
2. If fallback model also fails, use deterministic W9 hard reduction.
3. Fallback model should be a cheaper/faster model than the primary (e.g., smaller
   context window, lower cost per token, faster response time).
4. The fallback model is configured in `CompactionPolicy.fallback_model` and validated
   at policy resolution time.

Runtime-internal compaction may execute as part of the one active run. A user/operator
manual compaction request is a W7 lifecycle mutation and is rejected while any run is
active. The initial release does not support concurrent manual compaction or
same-session lifecycle mutation and therefore does not require fencing tokens.

## Execution State Machine

Use explicit states such as requested, running, succeeded, retryable-failure,
fallback-running, deterministic-fallback, cancelled, and failed. Persist lifecycle
events and compression results through W4. A successful result must validate schema,
token reduction, required-information retention, and source coverage before commit.

## Service Contract

```text
request_compaction(identity, agent_session_id, source_range, policy_version,
                   requested_target) -> CompactionOperation
get_compaction_status(operation_id) -> CompactionStatus
```

The operation records source range/fingerprint, model/prompt/schema versions, deadline,
attempts, cost, state, output representation, validation, and W4 event IDs. Required
failures include `deadline_exceeded`, `cancelled`, `provider_unavailable`,
`rate_limited`, `cost_limit_exceeded`, `summary_invalid`, `no_progress`,
`source_changed`, and `circuit_open`.

## Commit and Fallback Rules

- Source fingerprint is revalidated before committing a result.
- Success requires schema validity, source coverage, minimum-fidelity retention, and
  measurable token reduction.

Compaction validation is split into structural and semantic layers. Structural
validation (blocks commit): schema validity, source-event reference existence (reusing
the CM-002 lineage contract), mandatory ContextItem presence, tool-call/result pair
integrity, measurable token reduction, and representation tier not below declared
minimum fidelity. W12's `summary_invalid` failure is triggered only by structural
validation. Semantic quality (measured, does not block commit): information retention,
constraint/decision/goal coverage, and source-to-summary equivalence are routed to W13
SLO measurement. **Findings:** CM-018, CM-021.

- Retry/fallback counts and total deadline are hard bounded.
- Deterministic W9 fallback is always available and records explicit loss metadata.
- Failed compaction cannot overwrite a newer `compression.snapshot` or block the run indefinitely.

## Subagent Compression Independence

Subagent sessions can trigger their own compaction through W12 using their own
`CompactionPolicy`. The parent agent's compaction does not affect subagent sessions.
Each subagent session maintains its own compression state, cache, and cost accounting
independently. When a subagent session produces a `compression.snapshot` event, it is
scoped to the subagent's `agent_session` and does not interact with the parent
session's compression state.

## Required Deliverables and Phases

- Deliver policy/schema, operation store/state machine, service/executor, validators,
  model adapters, retry/fallback/circuit breaker, cost accounting, W4 integration,
  inspection, dashboards, and runbooks.
- Phase through observe-only validation, isolated service execution, bounded fallback,
  lifecycle/API integration, then automated compaction triggers.

## Implementation Plan

1. Define policy, state machine, failure taxonomy, and cost-accounting contract.
2. Extract compaction execution behind a dedicated service interface.
3. Add timeout, cancellation, bounded retries, fallback model, and circuit breaker.
4. Validate summary schema, source coverage, and measurable progress:
   - Schema validity: summary must conform to `summary_json_schema`.
   - Source coverage: summary must reference source events via CM-002 lineage contract.
   - Measurable progress: compressed output token count must be strictly less than
     source token count. If compression produces equal or greater token count, reject
     with `no_progress` and trigger deterministic W9 fallback.
5. Implement deterministic hard reduction using W9 representations.
6. Persist lifecycle events and expose status through W7 inspection.
7. Add dashboards for latency, retries, fallback, failures, cost, and reduction.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/summary_cache.py`
- Model provider and monitoring layers
- W4 event writer and W7 lifecycle hooks

## Tests and Definition of Done

- Fault injection covers timeout, cancellation, rate limit, malformed summary, provider
  outage, circuit open, cost ceiling, and no-progress output.
- Tests prove retry counts and latency are bounded.
- Deterministic fallback always fits and emits explicit loss metadata.
- Duplicate or concurrent compaction attempts are rejected or serialized and cannot
  corrupt checkpoint order.
- Manual compaction requests are rejected with `operation_conflicts_with_active_run`
  while a session run is active; runtime-internal compaction remains owned by that run.
- Performance baseline tests measure compaction trigger latency, compression execution
  latency (LLM call duration), and validation latency (lower priority, after
  functional implementation is stable).
- W12 is done when compaction-provider degradation cannot cause uncontrolled run
  failure, latency, retries, or spend, and every outcome is durable and observable.

## Codebase Gap Analysis (2026-06-17)

**Verdict: Compaction engine functional but reliability gaps are real production risks.**

### Current architecture
```
CoreAgent._step_stream()
  → ContextManager.compress_if_needed(self.model, memory, ...)
    → [Same model as agent — no separate compaction model]
    → [No timeout on LLM calls]
    → [Only context-length errors get 1 retry]
    → [No circuit breaker]
    → [No cancellation support]
    → L3 hard truncation fallback
```

### Critical reliability gaps
- **No timeout**: `_do_generate_summary()` calls model with no timeout — model hang = infinite step block
- **No transient-error retry**: network timeout, 429, 500 → immediate `return None` → L3 fallback
- **No circuit breaker**: every step attempts compaction regardless of prior failures
- **No cancellation**: `stop_event` not checked during compression
- **No separate compaction model**: GPT-4o agent uses GPT-4o for summarization
- **Unhandled exception propagation**: `compress_if_needed()` called without try/except at `core_agent.py:308`

### Priority actions
1. Add `compaction_timeout_seconds` config (default 30s)
2. Add retry with exponential backoff for transient errors (max 2 retries)
3. Add defensive try/except wrapper (fall back to original messages on unexpected errors)
4. Add circuit breaker (skip compaction for M steps after N consecutive failures)
5. Add `compaction_model` config field (allow cheaper model for summarization)
