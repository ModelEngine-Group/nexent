# Phase 2: P1 Review

## Assessment

P1 is the strongest foundational specification, but it is also the largest operational
risk. It enables state reconstruction, not automatically safe continuation of external
effects.

## Findings and Risks

- **CM-001 (Critical):** Tool side effects can be ambiguous after crash or timeout.
- **CM-002 (High):** Physical erasure makes historical replay partial.
- **CM-004 (Low):** Per-session sequence allocation is a measure-triggered scale
  observation; CM-003 removes same-session active-run concurrency and no current
  evidence justifies an advanced allocation mechanism.
- **CM-005 (High, claim-gated):** The accepted minimum supports current and immediately
  previous event versions through one P1 canonical reader/upcaster before the first
  production event-schema upgrade.
- **CM-006 (High):** The accepted P1 path atomically creates source events and required
  compatibility-projection outbox rows, then uses P1-owned idempotent retry and repair.
- **CM-009 (High):** Event rates, session size, retention, and replay workload are absent.
- **CM-012 (Critical):** The accepted fail-closed boundary forbids raw persistence,
  fallback, logs, and traces after classification/redaction failure.
- **CM-022 (Low):** Lifecycle and decision event volume may be excessive.

## Recommendations

- State explicitly that ambiguous effects stop unless reconciliation is approved.
- Implement the accepted P1 canonical event upcaster before the first production event-
  schema upgrade; implement the accepted P1 event/projection-outbox repair path and
  post-erasure replay status.
- Benchmark simple session serialization before adding more complex storage structures.
- Bound payloads, traces, and retention by workload class.

**Readiness:** Implementation-ready for the accepted contracts; production-scale claims
still depend on CM-009 and bounded trace governance.
