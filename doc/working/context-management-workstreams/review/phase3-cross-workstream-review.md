# Phase 3: Cross-Workstream Consistency Report

## Executive Result

W1-W16 form a coherent target architecture, but the integration contracts are not yet
uniformly production-ready. The highest-risk gaps are at boundaries: external effects,
lifecycle concurrency, cross-store publication/deletion, durable schema evolution, and
the exact final prompt assembly path.

## Interface Mismatches

| Area | Mismatch | Findings | Required resolution |
| --- | --- | --- | --- |
| Final prompt | W3 owns final assembly/serialization; W16 also assembles and fingerprints. | CM-023 | One exact-dispatched-payload contract. |
| Validation | W11/W13 imply semantic admissibility/coverage; W15 treats quality as measured. | CM-018, CM-021 | Separate structural validation from semantic evidence. |
| Provider behavior | CM-016 now uses small approved versioned profiles for supported deployments, rejects unknown hard capacity, applies a 10% uncertainty reserve for incomplete required behavior, and disables unknown cache directives. | CM-016 | Keep profiles small and versioned; do not trust unverified discovery as production authority. |
| Trusted execution | CM-013 now defines two server-side boundaries: model dispatch verifies W4/W10/W2/W3 inputs, and governed persistence verifies W4/W10/W14 inputs. | CM-013 | Treat SDK/client assertions as untrusted and deny direct production dispatch/raw-write paths. |
| Durable versions | W5 event compatibility is now bounded to current plus previous through one canonical reader; checkpoint compatibility remains unresolved. | CM-005, CM-014 | Keep the accepted W5 reader-first/writer-later contract; resolve checkpoint rebuild/upcast behavior under CM-014. |
| Artifact publication | W12 calls publication atomic across stores; W5 uses transactional outbox semantics. | CM-019 | Staged cross-store publication and repair. |

## Responsibility Conflicts and Gaps

| Area | Problem | Findings |
| --- | --- | --- |
| External effects | No owner for durable effect intent, ambiguity, and reconciliation. | CM-001 |
| Active ownership | CAS owner exists for checkpoints, but no fencing owner spans W7/W9/W13. | CM-003 |
| Shared/delegated identity | CM-007 now excludes shared conversations and ownership transfer; delegated mutation remains unresolved. | CM-007, CM-025 |
| Publication and repair ownership | CM-006 now assigns W5 event/projection repair to W5 and checkpoint/lifecycle-publication repair to W7; object-storage and deletion paths remain unresolved. | CM-006, CM-019, CM-020 |
| Production topology | W15 measures outcomes, but no topology owner defines numeric recovery/capacity objectives. | CM-009, CM-010 |

## Lifecycle Inconsistencies

- Restore/reset can change active lineage while an old worker continues producing
  events or checkpoints. **CM-003**
- Physical erasure can make previously replayable source history partial. **CM-002**
- W5/W7 multi-record publication now has path-owned outbox and repair semantics;
  deletion propagation remains unresolved. **CM-006, CM-020**
- Automatic resume is unsafe when a tool effect is ambiguous. **CM-001**
- W5 event upgrades use the accepted current-plus-previous canonical-reader contract;
  checkpoint upgrades can still make historical checkpoints unusable until CM-014 is
  resolved. **CM-005, CM-014**

## Memory Architecture Consistency

The source-of-truth split is coherent:

- W5 events are durable source history.
- W6 projections and Working Memory are rebuildable derived state.
- W7 checkpoints are disposable recovery accelerators.
- W10 governs selection and memory operations.
- W14 governs trust and lifecycle.

Remaining gaps:

- Authority order needs a supported conflict taxonomy. **CM-017**
- Minimum-fidelity claims need structural/semantic separation. **CM-018**
- Deletion and supersession must repair every derived/store path. **CM-020**
- Decision traces must be bounded and governed. **CM-022**

## Cross-Workstream Decisions

1. Ship a minimal W3 gateway before the complete W10-W13 quality stack. **CM-008**
2. Reject ambiguous external-effect resume unless an optional reconciliation package is approved. **CM-001**
3. Serialize conflicting lifecycle operations until fencing is implemented. **CM-003**
4. Use path-specific publication and cross-store contracts, not an assumed universal
   transaction. **CM-006, CM-019, CM-020**
5. Use W5's accepted current-plus-previous event window; define checkpoint
   rebuild/upcast behavior separately under CM-014. **CM-005, CM-014**
6. Treat dates as planning targets and make production claims capability-specific and
   evidence-gated through the accepted lightweight release checklist.
   **CM-009-CM-011, CM-024**
7. Enforce the accepted trusted model-dispatch and governed-persistence boundaries;
   bypass detection is diagnostic, not authorization. **CM-013**
