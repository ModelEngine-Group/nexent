# Phase 3: Cross-Workstream Consistency Report

## Executive Result

W1-W16 form a coherent target architecture, but the integration contracts are not yet
uniformly production-ready. The highest-risk gaps are at boundaries: external effects,
lifecycle concurrency, cross-store publication/deletion, durable schema evolution, and
the exact final prompt assembly path.

## Interface Mismatches

| Area | Mismatch | Findings | Required resolution |
| --- | --- | --- | --- |
| Final prompt | CM-023 now makes W3 produce a cache partition plan and W4 alone assemble, serialize, count, and fingerprint the exact final payload. | CM-023 | Keep trusted dispatch from modifying prompt/cache content. |
| Validation | P5/W9 imply semantic admissibility/coverage; W10 treats quality as measured. | CM-018, CM-021 | Separate structural validation from semantic evidence. |
| Provider behavior | CM-016 now uses small approved versioned profiles for supported deployments, rejects unknown hard capacity, applies a 10% uncertainty reserve for incomplete required behavior, and disables unknown cache directives. | CM-016 | Keep profiles small and versioned; do not trust unverified discovery as production authority. |
| Trusted execution | CM-013 now defines two server-side boundaries: model dispatch verifies W5/P4/W2/W4 inputs, and governed persistence verifies W5/P4/W3 inputs. | CM-013 | Treat SDK/client assertions as untrusted and deny direct production dispatch/raw-write paths. |
| Durable versions | P1 event compatibility is now bounded to current plus previous through one canonical reader; checkpoint compatibility remains unresolved. | CM-005, CM-014 | Keep the accepted P1 reader-first/writer-later contract; resolve checkpoint rebuild/upcast behavior under CM-014. |
| Artifact publication | CM-019 now defines governed non-readable staging, one pending-artifact/event/finalize-outbox transaction, idempotent finalize, ready-only reads, and W6-owned repair. | CM-019 | Keep this path-specific; do not add distributed transactions or a general saga platform. |

## Responsibility Conflicts and Gaps

| Area | Problem | Findings |
| --- | --- | --- |
| External effects | No owner for durable effect intent, ambiguity, and reconciliation. | CM-001 |
| Active ownership | CAS owner exists for checkpoints, but no fencing owner spans W7/W8/W9. | CM-003 |
| Shared/delegated identity | CM-007 now excludes shared conversations and ownership transfer; delegated mutation remains unresolved. | CM-007, CM-025 |
| Publication and repair ownership | P1 owns event/projection repair, W7 owns checkpoint/lifecycle publication repair, W6 owns artifact finalize/cleanup, and W3 coordinates fixed-destination deletion status while each adapter deletes/verifies its store. | CM-006, CM-019, CM-020 |
| Production topology | W10 measures outcomes, but no topology owner defines numeric recovery/capacity objectives. | CM-009, CM-010 |

## Lifecycle Inconsistencies

- Restore/reset can change active lineage while an old worker continues producing
  events or checkpoints. **CM-003**
- Physical erasure can make previously replayable source history partial. **CM-002**
- P1/W7/W6 publication paths now have path-owned outbox/repair semantics; W3
  immediately tombstones deletion targets and coordinates fixed-destination retry and
  verification. **CM-006, CM-019, CM-020**
- Automatic resume is unsafe when a tool effect is ambiguous. **CM-001**
- P1 event upgrades use the accepted current-plus-previous canonical-reader contract;
  checkpoint upgrades can still make historical checkpoints unusable until CM-014 is
  resolved. **CM-005, CM-014**

## Memory Architecture Consistency

The source-of-truth split is coherent:

- P1 events are durable source history.
- P2 projections and Working Memory are rebuildable derived state.
- W7 checkpoints are disposable recovery accelerators.
- P4 governs selection and memory operations.
- W3 governs trust and lifecycle.

Remaining gaps:

- Authority order needs a supported conflict taxonomy. **CM-017**
- Minimum-fidelity claims need structural/semantic separation. **CM-018**
- Deletion now uses immediate tombstone read blocking plus a fixed per-store completion
  registry; complete-deletion claims remain evidence-gated. **CM-020**
- Decision traces must be bounded and governed. **CM-022**

## Cross-Workstream Decisions

1. Ship an independent minimal W4 hard-fit gateway before the complete P4-W9 quality
   stack; later stages improve quality but cannot become hard-fit prerequisites.
   **CM-008**
2. Reject ambiguous external-effect resume unless an optional reconciliation package is approved. **CM-001**
3. Serialize conflicting lifecycle operations until fencing is implemented. **CM-003**
4. Use path-specific publication and cross-store contracts, not an assumed universal
   transaction. **CM-006, CM-019, CM-020**
5. Use P1's accepted current-plus-previous event window; define checkpoint
   rebuild/upcast behavior separately under CM-014. **CM-005, CM-014**
6. Treat dates as planning targets and make production claims capability-specific and
   evidence-gated through the accepted lightweight release checklist.
   **CM-009-CM-011, CM-024**
7. Enforce the accepted trusted model-dispatch and governed-persistence boundaries;
   bypass detection is diagnostic, not authorization. **CM-013**
8. W3 supplies only a cache partition plan; W4 owns the exact final payload,
   serialization, token count, and fingerprints. **CM-023**
9. Fail closed before governed persistence, use W6-specific staged artifact
   publication, and use W3's fixed-destination deletion coordinator without creating
   general DLP, saga, or workflow platforms. **CM-012, CM-019, CM-020**
