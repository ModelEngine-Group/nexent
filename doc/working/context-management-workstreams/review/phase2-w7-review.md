# Phase 2: W7 Review

## Assessment

Checkpoints as disposable recovery optimizations are correct. CAS prevents stale
checkpoint overwrite but does not alone guarantee lifecycle or worker ownership safety.

## Findings and Risks

- **CM-003 (Critical):** No fencing prevents an old worker from appending or flushing
  after restore, reset, or handoff.
- **CM-006 (High):** The accepted W7 path atomically creates the checkpoint and its
  publication outbox; W5 lifecycle publication is asynchronous audit and never gates
  recovery.
- **CM-010 (Medium):** No RPO/RTO, rebuild-time, or storage availability targets exist.
- **CM-014 (Medium):** Checkpoint schema upcasting and compatibility are undefined.

## Recommendations

- Initially serialize or reject conflicting lifecycle operations.
- Add fencing before advertising concurrent worker ownership/handoff modes; conversation
  ownership transfer is excluded by CM-007.
- Define checkpoint compatibility and recovery objectives; implement W7-owned
  lifecycle-publication retry, repair tooling, and failure drills.

**Readiness:** Ready for serialized lifecycle scope; not for concurrent mutation claims.
