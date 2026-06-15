# W13: Reliable Governed Compaction

## Objective

Make semantic compaction a bounded, observable, independently governed service that
cannot take down or indefinitely delay the main agent run.

## Compaction Policy

W13 owns semantic-compaction execution, validation, bounded retries, fallback, and
operation lifecycle. It does not define context authority, representation
admissibility, or checkpoint truth; W10, W11, W7, and W8 provide those contracts.

Define a versioned `CompactionPolicy` containing:

- Primary and fallback compaction models.
- W1/W2 capacity and reserve settings for compaction calls.
- Deadline, cancellation propagation, and provider-aware retry limits.
- Rate-limit handling, concurrency limit, and circuit-breaker thresholds.
- Per-operation and per-session cost ceilings.
- Summary prompt/schema versions and validation rules.
- Deterministic fallback behavior when semantic compaction is unavailable.

The main execution model is not implicitly the compaction model. All compaction calls
pass W3 final fit. Invalid or non-progress summaries are rejected and cannot trigger
unbounded retry loops.

Runtime-internal compaction may execute as part of the one active run. A user/operator
manual compaction request is a W9 lifecycle mutation and is rejected while any run is
active. The initial release does not support concurrent manual compaction or
same-session lifecycle mutation and therefore does not require fencing tokens.

## Execution State Machine

Use explicit states such as requested, running, succeeded, retryable-failure,
fallback-running, deterministic-fallback, cancelled, and failed. Persist lifecycle
events through W5 and checkpoints through W7. A successful result must validate schema,
token reduction, required-information retention, and source coverage before commit.

## Service Contract

```text
request_compaction(identity, agent_session_id, source_range, policy_version,
                   requested_target) -> CompactionOperation
get_compaction_status(operation_id) -> CompactionStatus
```

The operation records source range/fingerprint, model/prompt/schema versions, deadline,
attempts, cost, state, output representation, validation, and W5 event IDs. Required
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
minimum fidelity. W13's `summary_invalid` failure is triggered only by structural
validation. Semantic quality (measured, does not block commit): information retention,
constraint/decision/goal coverage, and source-to-summary equivalence are routed to W15
SLO measurement. **Findings:** CM-018, CM-021.

- Retry/fallback counts and total deadline are hard bounded.
- Deterministic W11 fallback is always available and records explicit loss metadata.
- Failed compaction cannot overwrite a newer W7 checkpoint or block the run indefinitely.

## Required Deliverables and Phases

- Deliver policy/schema, operation store/state machine, service/executor, validators,
  model adapters, retry/fallback/circuit breaker, cost accounting, W5/W7 integration,
  inspection, dashboards, and runbooks.
- Phase through observe-only validation, isolated service execution, bounded fallback,
  lifecycle/API integration, then automated compaction triggers.

## Implementation Plan

1. Define policy, state machine, failure taxonomy, and cost-accounting contract.
2. Extract compaction execution behind a dedicated service interface.
3. Add timeout, cancellation, bounded retries, fallback model, and circuit breaker.
4. Validate summary schema, source coverage, and measurable progress.
5. Implement deterministic hard reduction using W11 representations.
6. Persist lifecycle events and expose status through W9 inspection.
7. Add dashboards for latency, retries, fallback, failures, cost, and reduction.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/summary_cache.py`
- Model provider and monitoring layers
- W5 event writer, W7 checkpoint writer, and W9 lifecycle hooks

## Tests and Definition of Done

- Fault injection covers timeout, cancellation, rate limit, malformed summary, provider
  outage, circuit open, cost ceiling, and no-progress output.
- Tests prove retry counts and latency are bounded.
- Deterministic fallback always fits and emits explicit loss metadata.
- Duplicate or concurrent compaction attempts are rejected or serialized and cannot
  corrupt checkpoint order.
- Manual compaction requests are rejected with `operation_conflicts_with_active_run`
  while a session run is active; runtime-internal compaction remains owned by that run.
- W13 is done when compaction-provider degradation cannot cause uncontrolled run
  failure, latency, retries, or spend, and every outcome is durable and observable.
