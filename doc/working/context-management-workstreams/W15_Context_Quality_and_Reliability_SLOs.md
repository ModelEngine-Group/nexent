# W15: Context Quality and Reliability SLOs

## Objective

Turn context quality, safety, durability, and efficiency into measured product contracts
with release-blocking CI gates, production dashboards, alerts, and replayable evidence.

## SLO Framework

W15 owns measurement definitions, evidence, release gates, dashboards, alerts, and
diagnostic replay. It does not silently change runtime policy or implementation;
measured regressions create reviewed work for the owning W-ID.

Each SLO must define metric, population, target, error budget, measurement method,
minimum sample size, owner, dashboard, alert, and release-gate behavior. Separate
correctness/safety gates from optimization targets. Safety gates such as tenant
isolation, secret persistence, and request fit have zero-tolerance test expectations.

## Required Metric Families

- Fit success, mandatory-minimum overflow, and provider overflow recovery.
- Summary/category retention and complete tool-pair retention.
- Compression ratio, latency, cost, and prompt-cache reuse.
- Restart, failover, replay, compression snapshot concurrency, restore, and reset correctness.
- Tenant isolation, redaction, retention, and deletion propagation.
- Memory-write precision, confirmation compliance, retrieval recall/reranking, stale
  rejection, and correction/conflict handling.
- Working Memory retention through compression and lifecycle operations.
- Minimum-fidelity violations, bootstrap restoration failures, and dirty-state flush misses.
- Recall outcomes by no-match, denied, backend error, and pointer-resolution failure.
- Duplicate equivalent calls, avoidable refetches, and context-thrash rate.
- Multilingual and multimodal quality.

Release 1 SLO gates cover only text modality and any explicitly supported modalities.
Unsupported modalities are excluded from release gates. When a modality enters product
scope, its token accounting, artifact handling, projection, redaction, and provider
support contracts must be defined before adding its SLO gates. **Finding:** CM-026.

## Evidence Pipeline

Run fixed LongMemEval, EventQA, and manual-case baselines in CI. Add generated property,
load, chaos, security, multilingual, and multimodal suites. Persist benchmark inputs,
policy/model versions, and results so regressions are reproducible.
Production metrics use bounded-cardinality labels and tenant-safe aggregation.

Decision trace output from W6 (projection decisions), W10 (policy/memory decisions),
and W3 (fit/reduction decisions) uses OpenTelemetry-style spans, attributes, and
events. Traces are collected and stored by external observability infrastructure, not
by product-internal data persistence. In normal production operation, traces are
either disabled or emit only summary-level spans with reason codes. Detailed traces
(including content snippets) are enabled only during active debugging or benchmark
runs. A unified telemetry/observability specification document consolidates all
decision trace requirements; this document is low priority, to be implemented after
core functionality. **Finding:** CM-022.

## SLO Definition Contract

Every SLO is stored as a versioned record containing:

```text
name, owner, population, metric_query, unit, target, comparison,
error_budget, minimum_sample_size, evaluation_window, exclusions,
dashboard, alert_policy, release_gate, evidence_version
```

Correctness/security gates fail closed when evidence is missing. Optimization targets
may warn before blocking according to approved policy. Metric labels must be
bounded-cardinality and tenant-safe; raw prompt/event content is never a label.

## Gate and Evidence Behavior

- CI produces a signed/versioned evidence bundle containing inputs, configuration,
  model/policy versions, results, and regressions.
- Release evaluation returns `pass`, `fail`, or `insufficient_evidence`; the last is a
  failure for mandatory gates.
- Calendar dates and delivery milestones are planning targets only; reaching them never
  overrides a `fail` or `insufficient_evidence` mandatory gate.
- Production alerts link to runbooks and replayable authorized traces.
- Baseline updates require review and cannot be performed automatically by the code
  change being evaluated.

## Claim-Scoped Release Checklist

Before approving a release, record one lightweight checklist that:

1. Lists the capability claims enabled by the release.
2. Links each claim to its mandatory gates and evidence version.
3. Confirms no mandatory gate is `fail` or `insufficient_evidence`.
4. Explicitly disables or excludes every unsupported or insufficient-evidence claim.
5. Records the release approver and approval time.

This checklist reuses W15 evidence and the existing release process. Release one does
not require a separate release-governance platform, project-management workflow, or
calendar-based approval service.

Use "claim-scoped production readiness" rather than unconditional "production-ready"
in release documentation. This checklist reuses W15 evidence and the existing release
process; no separate release-governance platform is required. **Finding:** CM-024.

## Required Deliverables and Phases

- Deliver SLO registry/schema, metric/reason registries, benchmark orchestrator,
  evidence store, baseline comparator, gate service, dashboards, alerts, replay/trace
  inspection, and runbooks.
- Phase through current baselines, non-blocking CI evidence, approved release gates,
  production alerts, then recurring incident drills and SLO review.
- W15 coordinates performance baseline tests across W5, W6, W10, W11, W12, W13, and
  W14. These baselines are lower priority (after functional implementation is stable)
  but W15 defines the measurement standards and targets.

## Implementation Plan

1. Establish baseline measurements of current system behavior before W1-W14
   implementation starts. This baseline is required to quantify improvement after
   W1-W14 implementation.
2. Approve SLO definitions, targets, owners, and release policy.
3. Standardize metrics, trace schemas, and reason-code registry.
4. Add CI benchmark orchestration and baseline comparison.
5. Add production dashboards, alerts, and incident runbooks.
6. Implement deterministic replay and decision-trace inspection.
7. Require workstream PRs to attach relevant SLO evidence.
8. Add the lightweight claim-scoped checklist to release approval.

## Repository Touchpoints

- `sdk/benchmark/longmemeval_eval/`
- `sdk/benchmark/eventqa_eval/`
- `sdk/benchmark/manual_cases/`
- `sdk/ctx_debugger/`
- `sdk/nexent/monitor/`
- `backend/utils/monitoring.py`
- `backend/apps/monitoring_app.py`
- Frontend monitoring UI and CI configuration
- New unified telemetry/observability specification document (low priority, post-core)

## Tests and Definition of Done

- Gate-behavior tests prove qualifying regressions fail releases.
- Metrics schema tests enforce units, labels, and privacy.
- Replay tests reproduce selection/writeback decisions from recorded evidence.
- Dashboard/alert smoke tests and incident drills are documented.
- Gate tests prove a reached planning date cannot override a failed or
  insufficient-evidence mandatory gate.
- W15 is done when agreed SLOs are measured in CI and production, regressions block
  release as designed, claim-scoped release checklists are recorded, and operators can
  diagnose failures from authorized traces.
