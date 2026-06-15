# Findings Registry

This registry is authoritative for the production-readiness review. Severity reflects
the risk to the capability claim affected by the finding, not necessarily the entire
program. `Delivery classification` prevents a valid architectural risk from becoming
an over-engineered release-one requirement:

- `Required guardrail`: implement the smallest safe contract in the initial applicable release.
- `Claim-gated`: required only before enabling the named capability or production claim.
- `Measure-triggered`: do not build the advanced mechanism until evidence crosses an approved threshold.
- `Scope-exclusion`: reject or omit the unsupported behavior instead of building it.

| ID | Severity | Delivery classification | Affected documents | Description | Minimum non-over-engineered response |
| --- | --- | --- | --- | --- | --- |
| CM-001 | Critical | Required guardrail | W5, W6, W7, W9 | State replay is described strongly enough to be mistaken for safe automatic resume, but external tool effects have no durable intent, ambiguity, or reconciliation contract. | Stop on ambiguous effects. Build reconciliation only if automatic side-effect-safe resume is approved. |
| CM-002 | High | Required guardrail | W5, W6, W8, W14 | Append-only replay and physical erasure conflict; after deletion, historical replay may be partial or semantically different. | Mark replay partial after erasure, invalidate derived state, and record proof; do not build a general erasure-replay engine. |
| CM-003 | Critical | Required guardrail | W7, W9, W13 | CAS protects checkpoint writes but does not fence active workers or lifecycle mutations from continuing after restore/reset/ownership change. | Serialize or reject conflicts. Add fencing only before concurrent lifecycle mutation is enabled. |
| CM-004 | Low | Measure-triggered | W5 | A single session sequence row and the event index/data join may become expensive under unusually high-volume sessions, but CM-003 removes same-session active-run concurrency and no current evidence shows a bottleneck. | Keep the simple design and measure append latency, sequence lock wait, events per session, and replay latency under CM-009 workloads. Optimize only after approved thresholds are crossed. |
| CM-005 | High | Claim-gated | W5, W6 | Event schema versions are named, but the supported compatibility window, reader behavior, and mixed-version deployment rules are incomplete. | Support the current and immediately previous durable schema with simple reader upcasters before the first production upgrade. |
| CM-006 | High | Required guardrail | W5, W7 | Multi-record event/projection and checkpoint/lifecycle-event publication lacks complete transaction, visibility, retry, and repair ownership contracts. | Atomically create each source record with its path-owned outbox, publish derived/audit records asynchronously and idempotently, and assign repair ownership per path; do not build a universal saga platform. |
| CM-007 | Medium | Scope-exclusion | W4, W5, W9 | The architecture is single-owner, but ambiguous wording could be interpreted as support for shared conversations or ownership transfer. | Make conversation/session ownership immutable in release one; reject sharing, membership, and transfer explicitly, and keep shared resources/operator policy separate from ownership. |
| CM-008 | High | Required guardrail | W3, W10, W11, W12, W13 | W3 is a blocker but its full stage list depends on later workstreams, creating an implementation and readiness cycle. | Ship a minimal fit gateway first; defer richer reduction quality to W10-W13. |
| CM-009 | High | Claim-gated | W5-W8, W12, W15 | No representative workload model defines session length, event rate, payload size, concurrency, retention, or retrieval profile. | Define a small number of supported workload envelopes before a production-scale claim. |
| CM-010 | Medium | Claim-gated | W7, W12, W14, W15 | No numeric availability, RPO/RTO, rebuild-time, queue-lag, or storage-capacity objectives exist for production-scale claims. | Set topology-specific targets only for the deployment being approved; not required for an initial bounded pilot. |
| CM-011 | Medium | Required guardrail | Parent plan, W15 | Aggressive calendar milestones can be interpreted as readiness gates despite unresolved migrations, security review, load evidence, and SLO targets. | Label dates as planning targets and use a short claim-scoped exit checklist. |
| CM-012 | Critical | Required guardrail | W5, W12, W14 | Redaction/classification failure behavior is not uniformly fail-closed before sensitive payload persistence. | Reject or restrict persistence when classification/redaction fails; never persist raw fallback content. |
| CM-013 | Critical | Required guardrail | W2, W3, W4, W10, W14 | Bypass prevention is asserted, but the trusted enforcement boundary and untrusted SDK/client behavior are not explicit. | Restrict production model dispatch and governed persistence to trusted server-side boundaries that fail closed on invalid authorization, policy, budget/fit, or governance inputs. |
| CM-014 | Medium | Claim-gated | W7, W8 | Checkpoint payload/schema migration and compatibility with historical event/projection versions are not defined. | Invalidate and rebuild old checkpoints initially; add checkpoint upcasters only when rebuild cost or compatibility requirements justify them. |
| CM-015 | Low | Measure-triggered | W8 | Complete-prefix hashing can become O(history) per checkpoint and targeted invalidation can become expensive. | Use append-time incremental hashing; do not add Merkle/segment structures without measured need. |
| CM-016 | High | Required guardrail | W1, W2, W3, W16 | Provider/model capabilities such as hard capacity, exact token counting, reasoning-window behavior, and prompt caching are assumed discoverable and stable. | Maintain a small approved versioned capability profile for supported deployments; reject unknown hard capacity, apply a 10% context-window uncertainty reserve for incomplete required behavior, and disable unknown cache capabilities. |
| CM-017 | Medium | Scope-exclusion | W6, W10, W14 | The authority ordering does not define behavior for every incomparable and multi-source conflict. | Support a finite initial conflict set and return an explicit unresolved result for all others. |
| CM-018 | High | Required guardrail | W3, W10, W11, W13 | “Minimum fidelity” and summary coverage imply semantic guarantees that cannot be generally validated deterministically. | Enforce structural invariants only; measure semantic quality instead of building a semantic proof system. |
| CM-019 | High | Required guardrail | W12, W5 | Artifact offload says publication is atomic, but object storage and relational event commits cannot generally share a transaction. | Use staged upload/finalize, idempotent publication, and orphan cleanup for this path only. |
| CM-020 | High | Claim-gated | W14, W5-W12 | Deletion propagation across event DB, object storage, checkpoints, caches, and memory lacks a concrete consistency/repair model. | Before claiming complete deletion, track per-store completion and retry incomplete destinations; no generic workflow platform is required. |
| CM-021 | Medium | Required guardrail | W13 | Summary source coverage and required-information retention are treated as validation rules without specifying enforceable checks. | Validate references, schema, and reduction structurally; move semantic retention to W15 measurement. |
| CM-022 | Low | Measure-triggered | W5, W6, W15 | Decision traces for every inclusion/exclusion can create high volume, sensitive data duplication, and label-cardinality risk. | Start with bounded reason codes and sampled detail; expand only for demonstrated diagnostic need. |
| CM-023 | High | Required guardrail | W3, W16 | W16 assembles a prompt then passes it to W3, while W3 owns final assembly and may change it, risking cache fingerprints that do not match dispatched bytes. | Compute cache metadata from the exact final dispatched payload through one serializer. |
| CM-024 | Low | Required guardrail | Parent plan | “Production-ready” is used broadly while several capabilities are explicitly conditional or unsupported. | Keep a lightweight release capability checklist; do not create a separate governance platform. |
| CM-025 | Medium | Scope-exclusion | W4, W12 | Isolated subagents and delegated work lack identity propagation, delegated authorization, mutation, and parent/child ownership rules. | Limit release-one delegated work to bounded/read-only behavior; add delegated mutation capabilities only if approved. |
| CM-026 | Low | Scope-exclusion | W3, W12, W15 | Multimodal testing is required without a modality contract for token accounting, artifacts, projection, redaction, or supported providers. | Remove unsupported modalities from release gates; add contracts only when a modality enters scope. |

## Severity Summary

| Severity | Count |
| --- | ---: |
| Critical | 4 |
| High | 10 |
| Medium | 7 |
| Low | 5 |
| **Total** | **26** |

## Reviewed Finding Decisions

This table is the authoritative progress view for the finding-by-finding review.
`Completed` means the decision was accepted and all listed specification, parent-plan,
and review-artifact updates were written and consistency-checked.

| ID | Decision | Review status | Document update status | Approved treatment | Updated documents |
| --- | --- | --- | --- | --- | --- |
| CM-001 | Retain as Critical / Required guardrail | Accepted | Completed | Classify started tool calls without a terminal result as `ambiguous_effect`; block automatic invocation and require durable authorized resolution. No general effect-reconciliation platform. | W5, W6, W7, W9, parent plan, review artifacts |
| CM-002 | Retain as High / Required guardrail | Accepted | Completed | Require queryable source-event lineage; after physical erasure mark replay partial, invalidate affected derived objects, and reject unsafe recovery. No global lineage graph. | W5-W9, W11, W12, W14, parent plan, review artifacts |
| CM-003 | Retain as Critical / Required guardrail | Accepted | Completed | Permit one active run per durable session and reject conflicting lifecycle mutations. No fencing or concurrent same-session mutation. | W5, W7, W9, W13, parent plan, review artifacts |
| CM-004 | Lower to Low / Measure-triggered | Accepted | Completed | Keep simple per-session sequencing and normalized event storage; measure before optimizing. Does not block initial implementation. | W5, parent plan, review artifacts |
| CM-005 | Retain as High / Claim-gated | Accepted | Completed | Before the first production event-schema upgrade, support current and previous versions through one W5 canonical reader/upcaster and reader-first deployment. | W5, W6, parent plan, review artifacts |
| CM-006 | Retain as High / Required guardrail | Accepted | Completed | W5 and W7 atomically create their source record with path-owned outbox work, then own idempotent retry and repair. No universal saga or distributed transaction platform. | W5, W7, parent plan, review artifacts |
| CM-007 | Retain as Medium / Scope-exclusion | Accepted | Completed | Use immutable single-owner conversations/sessions and reject sharing, membership, and ownership transfer. Shared resources and operator policy do not change ownership. | W4, W5, W7, W9, parent plan, review artifacts |
| CM-008 | Retain as High / Required guardrail | Accepted | Completed | Ship an independent minimal W3 hard-fit gateway first; W10-W13 later improve retained quality without becoming hard-fit prerequisites. | W3, parent plan, review artifacts |
| CM-011 | Retain as Medium / Required guardrail | Accepted | Completed | Treat every schedule date as a planning target; a reached date cannot override failed or insufficient-evidence mandatory gates. Reuse W15 evidence with one lightweight claim-scoped release checklist. No new governance platform. | W15, parent plan, review artifacts |
| CM-012 | Retain as Critical / Required guardrail | Accepted | Completed | Classification/redaction failure forbids raw governed persistence, fallback, logs, and traces; allow only retry, ephemeral handling, failure, and sanitized reason-coded records. | W5, W12, W14, parent plan, review artifacts |
| CM-013 | Retain as Critical / Required guardrail | Accepted | Completed | Use two trusted server-side boundaries: production model dispatch verifies W4/W10/W2/W3 inputs, and governed persistence verifies W4/W10/W14 inputs. Treat SDK/client assertions as untrusted and deny direct paths. No separate enforcement platform. | W2, W3, W4, W10, W14, parent plan, review artifacts |
| CM-016 | Retain as High / Required guardrail | Accepted | Completed | Use a small approved versioned capability profile for supported deployments. Reject unknown hard capacity; when required behavior is incomplete, reserve an additional 10% of the context window; disable unknown cache directives. | W1, W2, W3, W16, parent plan, review artifacts |
| CM-019 | Retain as High / Required guardrail | Accepted | Completed | Use W12-specific governed staging, one pending-artifact/event/finalize-outbox transaction, idempotent finalize, ready-only reads, retry/repair, and orphan cleanup. No distributed transaction or general saga platform. | W5, W12, parent plan, review artifacts |
| CM-020 | Retain as High / Claim-gated | Accepted | Completed | Tombstones immediately block reads; W14 coordinates a fixed destination registry with per-store status, idempotent retry, verification, and completion only after every required destination succeeds. No generic workflow platform. | W5-W12, W14, parent plan, review artifacts |
| CM-023 | Retain as High / Required guardrail | Accepted | Completed | W16 supplies a cache partition plan; W3 alone produces final payload, serialization, token count, and fingerprints, and trusted dispatch cannot modify prompt/cache content. | W3, W16, parent plan, review artifacts |
| CM-018 | Retain as High / Required guardrail | Accepted | Completed | Split validation: structural (schema, source refs, mandatory presence, tool pairs, representation tier) blocks commit; semantic quality (retention, coverage, equivalence) routes to W15 SLO measurement. No semantic proof system. | W11, W13, W15, parent plan, review artifacts |
| CM-021 | Retain as Medium / Required guardrail | Accepted | Completed | Structural validation blocks commit: source lineage (CM-002 contract), source existence, mandatory ContextItem presence, schema validity. Semantic coverage routes to W15 SLO. No independent summary quality platform. | W6, W13, W15, parent plan, review artifacts |
| CM-024 | Retain as Low / Required guardrail | Accepted | Completed | Reuse CM-011 claim-scoped release checklist. Use "claim-scoped production readiness" in documentation. No new governance platform. | Parent plan, W15, review artifacts |
| CM-017 | Retain as Medium / Scope-exclusion | Accepted | Completed | Declare finite initial conflict set in W10. Same-tier conflicts take higher specificity or recency. Incomparable conflicts return `authority_conflict_unresolved`. No exhaustive conflict ontology. | W10, parent plan, review artifacts |
| CM-025 | Retain as Medium / Scope-exclusion | Accepted | Completed | Subagent is a normal agent with independent `agent_session_id`, own W5 event log, own W1/W2 budget, and permissions from its agent config. Inherits parent `conversation_id` with `parent_session_id` and `delegation_type = 'subagent'`. Triggered via async built-in tool. Only final answer exposed to parent. Recursive delegation prohibited. Memory scope follows ordinary agent rules. No W14 re-governance on transfer. | W4, W5, W12, parent plan, review artifacts |
| CM-026 | Retain as Low / Scope-exclusion | Accepted | Completed | Remove unsupported modalities from Release 1 gates. W15 SLO covers text only. Add modality contracts only when a modality enters scope. No Release 1 multimodal context contracts. | W15, W3, parent plan, review artifacts |

| CM-009 | Retain as High / Claim-gated | Accepted | Completed | Do not pre-define workload envelopes. After W1-W16 implementation, use W15 measurement infrastructure to collect real performance data and define envelopes based on observed data. No production-scale claim until envelopes are defined. | W5, W15, parent plan, review artifacts |
| CM-010 | Retain as Medium / Claim-gated | Accepted | Completed | Do not pre-define numeric targets. After W1-W16 implementation, use W15 measurement infrastructure to collect real recovery/availability data per topology. Define targets based on observed data. No production-scale claim until targets are defined. | W15, parent plan, review artifacts |
| CM-014 | N/A — obsolete | Resolved | Completed | W7 retired; checkpoint functionality merged into W5 as `compression.snapshot` events. Schema migration fully covered by CM-005 event-schema compatibility contract. | W5, W6, W8, W9, W13, parent plan, README, review artifacts |

### Review Progress Summary

| Progress state | Count | Findings |
| --- | ---: | --- |
| Accepted and document updates completed | 24 | CM-001-CM-014, CM-016-CM-021, CM-023-CM-026 |
| Pending individual review | 2 | CM-015, CM-022 |
| **Total** | **26** | **CM-001-CM-026** |

## Delivery Classification Summary

| Delivery classification | Count |
| --- | ---: |
| Required guardrail | 14 |
| Claim-gated | 5 |
| Measure-triggered | 3 |
| Scope-exclusion | 4 |
| **Total** | **26** |
