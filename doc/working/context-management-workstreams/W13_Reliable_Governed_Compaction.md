# W13: Reliable Governed Compaction

## Objective

Make semantic compaction a bounded, observable, independently governed service that
cannot take down or indefinitely delay the main agent run.

## Compaction Policy

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

## Execution State Machine

Use explicit states such as requested, running, succeeded, retryable-failure,
fallback-running, deterministic-fallback, cancelled, and failed. Persist lifecycle
events through W5 and checkpoints through W7. A successful result must validate schema,
token reduction, required-information retention, and source coverage before commit.

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
- Concurrent compactions cannot corrupt checkpoint order.
- W13 is done when compaction-provider degradation cannot cause uncontrolled run
  failure, latency, retries, or spend, and every outcome is durable and observable.

