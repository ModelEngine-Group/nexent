# Over-Engineering Secondary Review

## Conclusion

The original findings are mostly valid risks, but the initial severity presentation
could cause over-engineering if teams interpret every finding as a release-one feature
requirement. The correct conclusion is:

- **No finding requires a new unconditional workstream.**
- **14 findings require a small correctness or safety guardrail.**
- **5 findings are required only before making a specific capability or production claim.**
- **3 findings should trigger advanced implementation only after measurement.**
- **4 findings are best handled by explicitly excluding unsupported scope.**

Therefore the findings are not generally “over-consideration,” but several proposed
full solutions would be over-engineering if implemented before their trigger.

## Review Test

Each finding was retested against four questions:

1. Does it prevent a concrete correctness, security, data-loss, or false-product-claim failure?
2. Is the triggering capability explicitly in W1-W16 or the parent target?
3. Can release one handle it safely through rejection, serialization, invalidation, or
   a narrower claim instead of a generalized subsystem?
4. Is there measured evidence that an advanced scalability or automation mechanism is needed now?

## Finding Disposition

| Disposition | Findings | Secondary confirmation |
| --- | --- | --- |
| Required minimal guardrail; not over-engineering | CM-001-CM-003, CM-006, CM-008, CM-011-CM-013, CM-016, CM-018-CM-019, CM-021, CM-023-CM-024 | These prevent incorrect behavior or false claims. The accepted response is deliberately small: stop, reject, serialize, fail closed, use one serializer, or narrow validation. |
| Valid but capability/claim-gated | CM-005, CM-009-CM-010, CM-014, CM-020 | Do not block a bounded pilot. Require them only before schema upgrades, production-scale approval, expensive historical checkpoint compatibility, or complete-deletion claims. |
| Valid risk; advanced implementation would be over-engineering now | CM-004, CM-015, CM-022 | Measure first. Do not build partitioning, Merkle structures, broad materialization, or exhaustive tracing now. |
| Valid ambiguity; exclude scope instead of building it | CM-007, CM-017, CM-025-CM-026 | Reject shared ownership, unsupported conflicts, delegated mutation, and unsupported modalities until explicitly approved. |

## Severity Corrections

The secondary review lowers severity where the risk is speculative, safely excludable,
or only relevant to a future capability:

- High to Medium: CM-007, CM-010, CM-011, CM-014, CM-017, CM-021, CM-025.
- High to Low after the accepted CM-004 review: CM-004. CM-003 removes
  same-session active-run concurrency, so this remains only a measured optimization
  trigger.
- Medium to Low: CM-015, CM-022, CM-024, CM-026.
- Critical and remaining High findings retain severity because they affect explicitly
  claimed correctness, security, durability, or production behavior.

The previous severity summary also contained a counting error: the registry had four,
not five, Critical findings.

## Mechanisms Explicitly Deferred

The following are not release-one requirements without a trigger:

- General effect-reconciliation platform.
- Concurrent lifecycle mutation with distributed fencing.
- Shared-conversation membership and ownership-transfer model.
- Event-log partitioning or generalized projection materialization.
- Universal saga/workflow platform for all cross-store operations.
- Advanced checkpoint upcasting across arbitrary historical versions.
- Merkle-tree or segmented hashing.
- Exhaustive conflict-resolution ontology.
- Semantic-proof system for summaries.
- Full-fidelity decision tracing for every item.
- Delegated mutation capability-token framework.
- Multimodal context contracts.

## Architecture Decision

Approve the findings after reclassification. Use the minimum responses in
`findings-registry.md`; treat any implementation beyond those responses as a separate
design decision requiring a claim, workload, incident, or measurement trigger.
