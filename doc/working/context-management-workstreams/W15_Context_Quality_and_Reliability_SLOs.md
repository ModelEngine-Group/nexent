# W15: Context Quality and Reliability SLOs

## Objective

Turn context quality, safety, durability, and efficiency into measured product contracts
with release-blocking CI gates, production dashboards, alerts, and replayable evidence.

## SLO Framework

Each SLO must define metric, population, target, error budget, measurement method,
minimum sample size, owner, dashboard, alert, and release-gate behavior. Separate
correctness/safety gates from optimization targets. Safety gates such as tenant
isolation, secret persistence, and request fit have zero-tolerance test expectations.

## Required Metric Families

- Fit success, mandatory-minimum overflow, and provider overflow recovery.
- Summary/category retention and complete tool-pair retention.
- Compression ratio, latency, cost, and prompt-cache reuse.
- Restart, failover, replay, checkpoint concurrency, restore, and fork correctness.
- Tenant isolation, redaction, retention, and deletion propagation.
- Memory-write precision, confirmation compliance, retrieval recall/reranking, stale
  rejection, correction/conflict handling, and decision trace completeness.
- Working Memory retention through compression and lifecycle operations.
- Minimum-fidelity violations, bootstrap restoration failures, and dirty-state flush misses.
- Recall outcomes by no-match, denied, backend error, and pointer-resolution failure.
- Duplicate equivalent calls, avoidable refetches, and context-thrash rate.
- Multilingual and multimodal quality.

## Evidence Pipeline

Run fixed LongMemEval, EventQA, and manual-case baselines in CI. Add generated property,
load, chaos, security, multilingual, and multimodal suites. Persist benchmark inputs,
policy/model versions, decision traces, and results so regressions are reproducible.
Production metrics use bounded-cardinality labels and tenant-safe aggregation.

Add an authorized decision trace showing candidates, writes, retrieval selections,
exclusions, conflicts, reductions, final assembly, lifecycle writeback, and stable
reason codes. Add deterministic trace replay and an optional offline oracle that
classifies policy-controllable versus physically unavoidable faults.

## Implementation Plan

1. Baseline current behavior before W1-W14 changes.
2. Approve SLO definitions, targets, owners, and release policy.
3. Standardize metrics, trace schemas, and reason-code registry.
4. Add CI benchmark orchestration and baseline comparison.
5. Add production dashboards, alerts, and incident runbooks.
6. Implement deterministic replay and decision-trace inspection.
7. Require workstream PRs to attach relevant SLO evidence.

## Repository Touchpoints

- `sdk/benchmark/longmemeval_eval/`
- `sdk/benchmark/eventqa_eval/`
- `sdk/benchmark/manual_cases/`
- `sdk/ctx_debugger/`
- `sdk/nexent/monitor/`
- `backend/utils/monitoring.py`
- `backend/apps/monitoring_app.py`
- Frontend monitoring UI and CI configuration

## Tests and Definition of Done

- Gate-behavior tests prove qualifying regressions fail releases.
- Metrics/trace schema tests enforce units, labels, reason codes, and privacy.
- Replay tests reproduce selection/writeback decisions from recorded evidence.
- Dashboard/alert smoke tests and incident drills are documented.
- W15 is done when agreed SLOs are measured in CI and production, regressions block
  release as designed, and operators can diagnose failures from authorized traces.

