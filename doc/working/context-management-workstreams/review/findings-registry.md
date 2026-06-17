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
| CM-001 | Critical | Required guardrail | P1, P2, W7, W8 | State replay is described strongly enough to be mistaken for safe automatic resume, but external tool effects have no durable intent, ambiguity, or reconciliation contract. | Stop on ambiguous effects. Build reconciliation only if automatic side-effect-safe resume is approved. |
| CM-002 | High | Required guardrail | P1, P2, P3, W3 | Append-only replay and physical erasure conflict; after deletion, historical replay may be partial or semantically different. | Mark replay partial after erasure, invalidate derived state, and record proof; do not build a general erasure-replay engine. |
| CM-003 | Critical | Required guardrail | W7, W8, W9 | CAS protects checkpoint writes but does not fence active workers or lifecycle mutations from continuing after restore/reset/ownership change. | Serialize or reject conflicts. Add fencing only before concurrent lifecycle mutation is enabled. |
| CM-004 | Low | Measure-triggered | P1 | A single session sequence row and the event index/data join may become expensive under unusually high-volume sessions, but CM-003 removes same-session active-run concurrency and no current evidence shows a bottleneck. | Keep the simple design and measure append latency, sequence lock wait, events per session, and replay latency under CM-009 workloads. Optimize only after approved thresholds are crossed. |
| CM-005 | High | Claim-gated | P1, P2 | Event schema versions are named, but the supported compatibility window, reader behavior, and mixed-version deployment rules are incomplete. | Support the current and immediately previous durable schema with simple reader upcasters before the first production upgrade. |
| CM-006 | High | Required guardrail | P1, W7 | Multi-record event/projection and checkpoint/lifecycle-event publication lacks complete transaction, visibility, retry, and repair ownership contracts. | Atomically create each source record with its path-owned outbox, publish derived/audit records asynchronously and idempotently, and assign repair ownership per path; do not build a universal saga platform. |
| CM-007 | Medium | Scope-exclusion | W5, P1, W8 | The architecture is single-owner, but ambiguous wording could be interpreted as support for shared conversations or ownership transfer. | Make conversation/session ownership immutable in release one; reject sharing, membership, and transfer explicitly, and keep shared resources/operator policy separate from ownership. |
| CM-008 | High | Required guardrail | W4, P4, P5, W6, W9 | W4 is a blocker but its full stage list depends on later workstreams, creating an implementation and readiness cycle. | Ship a minimal fit gateway first; defer richer reduction quality to P4-W9. |
| CM-009 | High | Claim-gated | P1-P3, W6, W10 | No representative workload model defines session length, event rate, payload size, concurrency, retention, or retrieval profile. | Define a small number of supported workload envelopes before a production-scale claim. |
| CM-010 | Medium | Claim-gated | W7, W6, W3, W10 | No numeric availability, RPO/RTO, rebuild-time, queue-lag, or storage-capacity objectives exist for production-scale claims. | Set topology-specific targets only for the deployment being approved; not required for an initial bounded pilot. |
| CM-011 | Medium | Required guardrail | Parent plan, W10 | Aggressive calendar milestones can be interpreted as readiness gates despite unresolved migrations, security review, load evidence, and SLO targets. | Label dates as planning targets and use a short claim-scoped exit checklist. |
| CM-012 | Critical | Required guardrail | P1, W6, W3 | Redaction/classification failure behavior is not uniformly fail-closed before sensitive payload persistence. | Reject or restrict persistence when classification/redaction fails; never persist raw fallback content. |
| CM-013 | Critical | Required guardrail | W2, W4, W5, P4, W3 | Bypass prevention is asserted, but the trusted enforcement boundary and untrusted SDK/client behavior are not explicit. | Restrict production model dispatch and governed persistence to trusted server-side boundaries that fail closed on invalid authorization, policy, budget/fit, or governance inputs. |
| CM-014 | Medium | Claim-gated | W7, P3 | Checkpoint payload/schema migration and compatibility with historical event/projection versions are not defined. | Invalidate and rebuild old checkpoints initially; add checkpoint upcasters only when rebuild cost or compatibility requirements justify them. |
| CM-015 | Low | Measure-triggered | P3 | Complete-prefix hashing can become O(history) per checkpoint and targeted invalidation can become expensive. | Use append-time incremental hashing; do not add Merkle/segment structures without measured need. |
| CM-016 | High | Required guardrail | W1, W2, W4, W3 | Provider/model capabilities such as hard capacity, exact token counting, reasoning-window behavior, and prompt caching are assumed discoverable and stable. | Maintain a small approved versioned capability profile for supported deployments; reject unknown hard capacity, apply a 10% context-window uncertainty reserve for incomplete required behavior, and disable unknown cache capabilities. |
| CM-017 | Medium | Scope-exclusion | P2, P4, W3 | The authority ordering does not define behavior for every incomparable and multi-source conflict. | Support a finite initial conflict set and return an explicit unresolved result for all others. |
| CM-018 | High | Required guardrail | W4, P4, P5, W9 | “Minimum fidelity” and summary coverage imply semantic guarantees that cannot be generally validated deterministically. | Enforce structural invariants only; measure semantic quality instead of building a semantic proof system. |
| CM-019 | High | Required guardrail | W6, P1 | Artifact offload says publication is atomic, but object storage and relational event commits cannot generally share a transaction. | Use staged upload/finalize, idempotent publication, and orphan cleanup for this path only. |
| CM-020 | High | Claim-gated | W3, P1-W6 | Deletion propagation across event DB, object storage, checkpoints, caches, and memory lacks a concrete consistency/repair model. | Before claiming complete deletion, track per-store completion and retry incomplete destinations; no generic workflow platform is required. |
| CM-021 | Medium | Required guardrail | W9 | Summary source coverage and required-information retention are treated as validation rules without specifying enforceable checks. | Validate references, schema, and reduction structurally; move semantic retention to W10 measurement. |
| CM-022 | Low | Measure-triggered | P1, P2, W10 | Decision traces for every inclusion/exclusion can create high volume, sensitive data duplication, and label-cardinality risk. | Start with bounded reason codes and sampled detail; expand only for demonstrated diagnostic need. |
| CM-023 | High | Required guardrail | W4, W3 | W3 assembles a prompt then passes it to W4, while W4 owns final assembly and may change it, risking cache fingerprints that do not match dispatched bytes. | Compute cache metadata from the exact final dispatched payload through one serializer. |
| CM-024 | Low | Required guardrail | Parent plan | “Production-ready” is used broadly while several capabilities are explicitly conditional or unsupported. | Keep a lightweight release capability checklist; do not create a separate governance platform. |
| CM-025 | Medium | Scope-exclusion | W5, W6 | Isolated subagents and delegated work lack identity propagation, delegated authorization, mutation, and parent/child ownership rules. | Limit release-one delegated work to bounded/read-only behavior; add delegated mutation capabilities only if approved. |
| CM-026 | Low | Scope-exclusion | W4, W6, W10 | Multimodal testing is required without a modality contract for token accounting, artifacts, projection, redaction, or supported providers. | Remove unsupported modalities from release gates; add contracts only when a modality enters scope. |
| CM-027 | Medium | Required guardrail | W2 | `soft_limit_ratio` policy field is defined as a decimal in `(0, 1]` but no default value is specified, leaving the compaction trigger point undefined at implementation time. | Set default `soft_limit_ratio = 0.8`; allow per-tenant override via `tenant_config_t`; do not introduce per-agent override in release one. |
| CM-028 | Medium | Required guardrail | W2 | Spec says `requested_output_tokens` may be overridden "per agent or per request" but does not specify location. Per-agent override implies a new DB column and agent-edit UI; per-request override implies a new request-body field. Treating one sentence as one task hides two distinct contracts. | Specify two contracts in the spec: per-agent on a new `ag_tenant_agent_t.requested_output_tokens` column with an agent-edit UI input; per-request as an optional integer on the agent-run API body. Decide which is in W2 scope vs deferred. |
| CM-029 | High | Required guardrail | W2, W9 | Every model dispatch — primary, compaction, summary — needs its own W1 capacity snapshot and W2 budget snapshot keyed on that model's identity. Spec does not state this rule, so W9 could reuse the main run's snapshot for the compaction model and misjudge the compaction budget. Same defect class as CM-031 (assuming one model's parameters apply to all calls). | Add an explicit rule to W2 spec: snapshots are per-model, never shared across model identities; W9 invokes the W1→W2 chain with the compaction model's `model_record_t` as input; reviewer of W9 must verify this. |
| CM-030 | High | Required guardrail | W2 | Implementation Plan Step 5 reads "Pass requested output tokens to the provider call consistently." The word "consistently" hides whether this is a one-line rename of the existing `max_tokens` parameter or the CM-013 trusted-dispatch enforcement contract that rejects caller-supplied overrides. The two interpretations have very different code scope and security implications. | Clarify in spec that Step 5 is CM-013 enforcement: trusted dispatch verifies the W2 snapshot's `requested_output_tokens` is the value sent to `chat.completions.create`; caller overrides via kwargs are rejected or coerced to the snapshot value; add server-side assertion in the dispatch wrapper. |
| CM-031 | Medium | Required guardrail | W1, W11 | Catalog lookup requires `(provider, model_name)` to exactly match an entry. The frontend "single model" add flow does not expose `model_factory` for LLM/VLM, so manual-add records keep the Pydantic default `'OpenAI-API-Compatible'` which lower-cases to `'openai-api-compatible'` and matches no catalog key. `_infer_model_factory` would convert dashscope URLs to `'dashscope'` but is only called inside the embedding branch, so LLM/VLM never benefit. Discovered post-acceptance on 2026-06-15 via end-to-end glm-5.1 test. | Open W11 to add `POST /api/v1/models/suggest-capacity` + fuzzy catalog match + extended `_infer_model_factory`. Until W11 ships, operators can directly update `model_record_t.model_factory` per-row; documented as a known workaround. |
| CM-032 | Low | Required guardrail | W1, W11 | Provider-level "Edit Config" batch dialog in the model-management UI cannot host per-model capacity controls because the dialog applies one configuration to every model from one provider, and capacity is per-model. The per-model gear icon path now exposes capacity (fix landed 2026-06-16), but operators who expected to batch-provision capacity from the provider-level panel have no path. | Hide capacity controls in the provider-level batch dialog (already done via `hideCapacityFields={true}`). Batch capacity provisioning, if desired, is a future workstream — not in W1 scope. |

## Severity Summary

| Severity | Count |
| --- | ---: |
| Critical | 4 |
| High | 12 |
| Medium | 10 |
| Low | 6 |
| **Total** | **32** |

## Reviewed Finding Decisions

This table is the authoritative progress view for the finding-by-finding review.
`Completed` means the decision was accepted and all listed specification, parent-plan,
and review-artifact updates were written and consistency-checked.

| ID | Decision | Review status | Document update status | Approved treatment | Updated documents |
| --- | --- | --- | --- | --- | --- |
| CM-001 | Retain as Critical / Required guardrail | Accepted | Completed | Classify started tool calls without a terminal result as `ambiguous_effect`; block automatic invocation and require durable authorized resolution. No general effect-reconciliation platform. | P1, P2, W7, W8, parent plan, review artifacts |
| CM-002 | Retain as High / Required guardrail | Accepted | Completed | Require queryable source-event lineage; after physical erasure mark replay partial, invalidate affected derived objects, and reject unsafe recovery. No global lineage graph. | P1-W8, P5, W6, W3, parent plan, review artifacts |
| CM-003 | Retain as Critical / Required guardrail | Accepted | Completed | Permit one active run per durable session and reject conflicting lifecycle mutations. No fencing or concurrent same-session mutation. | P1, W7, W8, W9, parent plan, review artifacts |
| CM-004 | Lower to Low / Measure-triggered | Accepted | Completed | Keep simple per-session sequencing and normalized event storage; measure before optimizing. Does not block initial implementation. | P1, parent plan, review artifacts |
| CM-005 | Retain as High / Claim-gated | Accepted | Completed | Before the first production event-schema upgrade, support current and previous versions through one P1 canonical reader/upcaster and reader-first deployment. | P1, P2, parent plan, review artifacts |
| CM-006 | Retain as High / Required guardrail | Accepted | Completed | P1 and W7 atomically create their source record with path-owned outbox work, then own idempotent retry and repair. No universal saga or distributed transaction platform. | P1, W7, parent plan, review artifacts |
| CM-007 | Retain as Medium / Scope-exclusion | Accepted | Completed | Use immutable single-owner conversations/sessions and reject sharing, membership, and ownership transfer. Shared resources and operator policy do not change ownership. | W5, P1, W7, W8, parent plan, review artifacts |
| CM-008 | Retain as High / Required guardrail | Accepted | Completed | Ship an independent minimal W4 hard-fit gateway first; P4-W9 later improve retained quality without becoming hard-fit prerequisites. | W4, parent plan, review artifacts |
| CM-011 | Retain as Medium / Required guardrail | Accepted | Completed | Treat every schedule date as a planning target; a reached date cannot override failed or insufficient-evidence mandatory gates. Reuse W10 evidence with one lightweight claim-scoped release checklist. No new governance platform. | W10, parent plan, review artifacts |
| CM-012 | Retain as Critical / Required guardrail | Accepted | Completed | Classification/redaction failure forbids raw governed persistence, fallback, logs, and traces; allow only retry, ephemeral handling, failure, and sanitized reason-coded records. | P1, W6, W3, parent plan, review artifacts |
| CM-013 | Retain as Critical / Required guardrail | Accepted | Completed | Use two trusted server-side boundaries: production model dispatch verifies W5/P4/W2/W4 inputs, and governed persistence verifies W5/P4/W3 inputs. Treat SDK/client assertions as untrusted and deny direct paths. No separate enforcement platform. | W2, W4, W5, P4, W3, parent plan, review artifacts |
| CM-016 | Retain as High / Required guardrail | Accepted | Completed | Use a small approved versioned capability profile for supported deployments. Reject unknown hard capacity; when required behavior is incomplete, reserve an additional 10% of the context window; disable unknown cache directives. | W1, W2, W4, W3, parent plan, review artifacts |
| CM-019 | Retain as High / Required guardrail | Accepted | Completed | Use W6-specific governed staging, one pending-artifact/event/finalize-outbox transaction, idempotent finalize, ready-only reads, retry/repair, and orphan cleanup. No distributed transaction or general saga platform. | P1, W6, parent plan, review artifacts |
| CM-020 | Retain as High / Claim-gated | Accepted | Completed | Tombstones immediately block reads; W3 coordinates a fixed destination registry with per-store status, idempotent retry, verification, and completion only after every required destination succeeds. No generic workflow platform. | P1-W6, W3, parent plan, review artifacts |
| CM-023 | Retain as High / Required guardrail | Accepted | Completed | W3 supplies a cache partition plan; W4 alone produces final payload, serialization, token count, and fingerprints, and trusted dispatch cannot modify prompt/cache content. | W4, W3, parent plan, review artifacts |
| CM-018 | Retain as High / Required guardrail | Accepted | Completed | Split validation: structural (schema, source refs, mandatory presence, tool pairs, representation tier) blocks commit; semantic quality (retention, coverage, equivalence) routes to W10 SLO measurement. No semantic proof system. | P5, W9, W10, parent plan, review artifacts |
| CM-021 | Retain as Medium / Required guardrail | Accepted | Completed | Structural validation blocks commit: source lineage (CM-002 contract), source existence, mandatory ContextItem presence, schema validity. Semantic coverage routes to W10 SLO. No independent summary quality platform. | P2, W9, W10, parent plan, review artifacts |
| CM-024 | Retain as Low / Required guardrail | Accepted | Completed | Reuse CM-011 claim-scoped release checklist. Use "claim-scoped production readiness" in documentation. No new governance platform. | Parent plan, W10, review artifacts |
| CM-017 | Retain as Medium / Scope-exclusion | Accepted | Completed | Declare finite initial conflict set in P4. Same-tier conflicts take higher specificity or recency. Incomparable conflicts return `authority_conflict_unresolved`. No exhaustive conflict ontology. | P4, parent plan, review artifacts |
| CM-025 | Retain as Medium / Scope-exclusion | Accepted | Completed | Subagent is a normal agent with independent `agent_session_id`, own P1 event log, own W1/W2 budget, and permissions from its agent config. Inherits parent `conversation_id` with `parent_session_id` and `delegation_type = 'subagent'`. Triggered via async built-in tool. Only final answer exposed to parent. Recursive delegation prohibited. Memory scope follows ordinary agent rules. No W3 re-governance on transfer. | W5, P1, W6, parent plan, review artifacts |
| CM-026 | Retain as Low / Scope-exclusion | Accepted | Completed | Remove unsupported modalities from Release 1 gates. W10 SLO covers text only. Add modality contracts only when a modality enters scope. No Release 1 multimodal context contracts. | W10, W4, parent plan, review artifacts |

| CM-009 | Retain as High / Claim-gated | Accepted | Completed | Do not pre-define workload envelopes. After W1-W16 implementation, use W10 measurement infrastructure to collect real performance data and define envelopes based on observed data. No production-scale claim until envelopes are defined. | P1, W10, parent plan, review artifacts |
| CM-010 | Retain as Medium / Claim-gated | Accepted | Completed | Do not pre-define numeric targets. After W1-W16 implementation, use W10 measurement infrastructure to collect real recovery/availability data per topology. Define targets based on observed data. No production-scale claim until targets are defined. | W10, parent plan, review artifacts |
| CM-014 | N/A — obsolete | Resolved | Completed | W7 retired; checkpoint functionality merged into P1 as `compression.snapshot` events. Schema migration fully covered by CM-005 event-schema compatibility contract. | P1, P2, P3, W8, W9, parent plan, README, review artifacts |

### Review Progress Summary

| Progress state | Count | Findings |
| --- | ---: | --- |
| CM-015 | Retain as Low / Measure-triggered | Accepted | Completed | Remove content hashing from P3. Replace with O(1) metadata-based validation: compression.snapshot validity via partial_after_erasure + version fields; P2 materialized cache via snapshot validity + event count + version fields; physical erasure via one-time partial_after_erasure flag. No Merkle trees or segmented hashing needed. | P3, parent plan, review artifacts |

### Review Progress Summary

| Progress state | Count | Findings |
| --- | ---: | --- |
| CM-022 | Retain as Low / Measure-triggered | Accepted | Completed | Consolidate decision trace requirements into a single unified telemetry spec (low priority). Use OpenTelemetry-style spans/attributes/events. External observability infrastructure collects and stores traces, not product database. Production: disabled or summary-level. Debug: detailed traces enabled on demand. | P1, P2, W10, parent plan, review artifacts |

### Review Progress Summary

| Progress state | Count | Findings |
| --- | ---: | --- |
| Accepted and document updates completed | 26 | CM-001-CM-026 |
| Pending individual review | 0 | — |
| **Total** | **26** | **CM-001-CM-026** |

## Delivery Classification Summary

| Delivery classification | Count |
| --- | ---: |
| Required guardrail | 14 |
| Claim-gated | 5 |
| Measure-triggered | 3 |
| Scope-exclusion | 4 |
| **Total** | **26** |
