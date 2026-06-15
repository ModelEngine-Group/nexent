# Finding Review Decisions

This log records the user-approved decision for each finding as the review proceeds.
The implementation specifications and parent plan are updated immediately after each
accepted decision.

## CM-001: Ambiguous External Tool Effects

- **Decision:** Accepted as `Critical / Required guardrail`.
- **Approved minimum:** Any committed tool-call start without a committed terminal
  result becomes `ambiguous_effect` during recovery. Resume performs no automatic tool
  invocation. An authorized user or operator must durably choose `retry`, `skip`, or
  `confirm_completed`; retry explicitly accepts possible duplicate effects.
- **Explicitly out of scope:** Tool side-effect taxonomy, general effect-intent model,
  automatic external-system reconciliation, and cross-tool transaction coordination.
- **Updated documents:** W5, W6, W7, W9, parent production plan, findings registry.

## CM-002: Physical Erasure and Derived-State Lineage

- **Decision:** Accepted as `High / Required guardrail`.
- **Approved minimum:** Every persisted derived object exposes queryable source-event
  lineage using explicit source IDs or a complete source range. Physical erasure marks
  the session `partial_after_erasure`, invalidates affected derived objects as whole
  objects, rebuilds only from remaining authorized history when safe, and rejects
  unsafe restore/resume.
- **Explicitly out of scope:** Global lineage graph, field- or word-level attribution,
  editing generated summaries in place, and a general erasure-replay engine.
- **Updated documents:** W5, W6, W7, W8, W9, W11, W12, W14, parent production plan,
  findings registry.

## CM-003: Active Runs and Lifecycle Mutation

- **Decision:** Accepted as `Critical / Required guardrail`.
- **Approved minimum:** Permit exactly one active run per durable session. Reject a
  second run and reject restore, reset, manual compact, Working Memory mutation, and
  other conflicting lifecycle mutations until the active run reaches a committed
  terminal/recovery state. Read-only inspection remains allowed. Runtime-internal
  compaction remains part of its owning active run.
- **Explicitly out of scope:** Distributed fencing tokens, running-state restore, and
  concurrent same-session lifecycle mutation.
- **Updated documents:** W5, W7, W9, W13, parent production plan, findings registry.

## CM-004: Per-Session Sequence and Replay-Join Scale

- **Decision:** Lowered to `Low / Measure-triggered`.
- **Approved minimum:** Keep the simple per-session sequence allocation and normalized
  event index/data join. Measure append latency, session-sequence lock wait, events per
  session, and replay latency under representative CM-009 workloads. CM-004 does not
  block the initial production implementation.
- **Explicitly out of scope:** Sequence batching or preallocation, session-internal
  partitioning, a distributed sequence service, speculative event-table
  denormalization/materialization, and other optimization without threshold evidence.
- **Updated documents:** W5, parent production plan, findings registry, W5 review,
  goal coverage, impact analysis, architecture assessment, over-engineering secondary
  review.

## CM-005: Durable Event-Schema Compatibility

- **Decision:** Retained as `High / Claim-gated`.
- **Approved minimum:** Before the first production event-schema upgrade, W5 readers
  support the current and immediately previous event versions. One W5 canonical reader
  upcasts the previous version to the current internal representation for all
  consumers. Deploy compatible readers before enabling the new writer; after new-
  version writes begin, rollback is allowed only to releases that can read them. A
  later upgrade must not remove reader support for versions still present in retained
  events; migration or an expanded window requires separate approval.
- **Explicitly out of scope:** Arbitrary historical-version compatibility, rewriting
  stored events, reverse/down-casting, consumer-specific event upcasters, and an
  independent schema-evolution platform. Checkpoint compatibility remains CM-014.
- **Updated documents:** W5, W6, parent production plan, findings registry, W5/W6
  reviews, cross-workstream review, goal coverage, impact analysis, and architecture
  assessment.

## CM-006: Multi-Record Publication and Repair Ownership

- **Decision:** Retained as `High / Required guardrail`, with scope narrowed from
  generic cross-store consistency to the W5 and W7 multi-record publication paths.
- **Approved minimum:** W5 commits each source event and required compatibility-
  projection outbox row in one relational transaction, then owns idempotent projection
  retry and operator repair. W7 commits each checkpoint and required publication-
  outbox row in one transaction; its W5 lifecycle event is asynchronous audit
  publication, and a committed W8-valid checkpoint remains loadable while publication
  is pending. W7 owns retry and repair for that path.
- **Explicitly out of scope:** Universal saga/workflow platforms, distributed
  transactions, two-phase commit, and one shared repair framework for all storage
  paths. Object-storage publication and deletion propagation are separately governed
  by the accepted CM-019/CM-020 path-specific contracts.
- **Updated documents:** W5, W7, parent production plan, findings registry, W5/W7
  reviews, cross-workstream review, impact analysis, goal coverage, and architecture
  assessment.

## CM-007: Single-Owner Conversation and Session Scope

- **Decision:** Retained as `Medium / Scope-exclusion`.
- **Approved minimum:** Release one gives every conversation and W5 session one
  immutable tenant/user owner. Reject sharing, membership, and ownership-transfer
  requests explicitly; ordinary non-owner access remains non-disclosing. Shared agents
  and tenant-shared memories do not grant session access. Separately authorized
  operator actions are audited and do not change ownership.
- **Explicitly out of scope:** Conversation membership/roles, shared-session read or
  write, ownership migration, resource permission migration, and revocation workflows.
  An independent copy for another user creates a new conversation/session.
- **Updated documents:** W4, W5, W7, W9, parent production plan, findings registry,
  W4/W7/W9 reviews, cross-workstream review, impact analysis, goal coverage, and
  architecture assessment.

## CM-011: Calendar Targets and Claim-Scoped Readiness

- **Decision:** Retained as `Medium / Required guardrail`.
- **Approved minimum:** Treat every implementation schedule and milestone date as a
  planning target. Reaching a date never overrides a failed or `insufficient_evidence`
  mandatory gate. Before release approval, record one lightweight checklist listing
  enabled capability claims, linked mandatory gates/evidence versions, excluded or
  disabled unsupported claims, and release approval identity/time.
- **Explicitly out of scope:** Separate release-governance platform, new project-
  management workflow, calendar-based approval service, and treating all claim-gated
  production-scale evidence as a blocker for initial implementation or bounded pilots.
- **Updated documents:** W15, parent production plan, findings registry, W1/W9/W15
  reviews, cross-workstream review, goal coverage, impact analysis, and architecture
  assessment.

## CM-013: Trusted Model Dispatch and Governed Persistence Boundaries

- **Decision:** Retained as `Critical / Required guardrail`.
- **Approved minimum:** Use two trusted server-side enforcement boundaries. Production
  model dispatch requires current W4 authorization, immutable W10 policy decision,
  server-resolved or verified W2 budget, and the exact final W3 fit result. Governed
  persistence requires current W4 authorization, applicable W10 policy decision, and
  complete W14 governed payload metadata. SDK/client assertions are untrusted; missing,
  stale, mismatched, caller-expanded, or incomplete inputs fail closed, and direct
  production dispatch/raw-persistence paths are denied.
- **Explicitly out of scope:** Separate policy-enforcement microservice, service mesh or
  OPA requirement, cryptographically signed decision tokens, distributed capability
  platform, and repeated full policy/authorization resolution at every internal
  function call.
- **Updated documents:** W2, W3, W4, W10, W14, parent production plan, findings
  registry, W2/W3/W4/W10/W14 reviews, cross-workstream review, goal coverage, impact
  analysis, and architecture assessment.

## CM-016: Supported Provider/Model Capability Profiles

- **Decision:** Retained as `High / Required guardrail`.
- **Approved minimum:** Maintain a small approved versioned capability profile only for
  supported production provider/model deployments. Provider discovery is unverified
  candidate metadata and cannot silently change production behavior. Unknown hard
  capacity returns `provider_capability_unknown` and blocks production dispatch. When
  hard capacity is known but required tokenizer, reasoning-window, or provider-overhead
  behavior is incomplete, W2 reserves an additional 10% of `context_window_tokens`,
  separate from requested output capacity. Unknown prompt-cache capability disables
  cache directives and unknown cache metrics are never reported as hits.
- **Explicitly out of scope:** General provider capability discovery, automatic
  documentation scraping/probing, profiles for unsupported models, and separate
  unknown reasoning/overhead/estimation reserve configuration in release one.
- **Updated documents:** W1, W2, W3, W16, parent production plan, findings registry,
  W1/W2/W3/W16 reviews, cross-workstream review, goal coverage, impact analysis, and
  architecture assessment.

## CM-008: Independent Minimal Hard-Fit Gateway

- **Decision:** Retained as `High / Required guardrail`.
- **Approved minimum:** Ship W3's independent minimal hard-fit gateway first. It may
  reject, use existing bounded representations, remove or deterministically truncate
  optional content, preserve complete tool pairs, and fail on mandatory overflow.
  W10-W13 later improve retained quality but cannot become prerequisites for hard fit.
- **Explicitly out of scope:** Blocking W3 on the complete policy/reducer/artifact/
  compaction stack or building a separate fit orchestration platform.
- **Updated documents:** W3, parent production plan, findings registry, W3 review,
  cross-workstream review, goal coverage, impact analysis, and architecture assessment.

## CM-012: Fail-Closed Governance Processing

- **Decision:** Retained as `Critical / Required guardrail`.
- **Approved minimum:** Unknown classification or classification/redaction failure
  forbids raw governed persistence, inline fallback, logs, and traces. Callers may
  retry, retain content only as ephemeral process-local state, fail the operation, or
  append a sanitized reason-coded failure record without the rejected payload.
- **Explicitly out of scope:** A new DLP platform, temporary raw persistence for later
  cleanup, and raw diagnostic/proof records.
- **Updated documents:** W5, W12, W14, parent production plan, findings registry,
  W5/W12/W14 reviews, goal coverage, impact analysis, and architecture assessment.

## CM-019: Path-Specific Artifact Publication

- **Decision:** Retained as `High / Required guardrail`.
- **Approved minimum:** W12 uploads governed bytes to non-readable staging, then one
  relational transaction creates the pending artifact, W5 reference event, and
  finalize outbox. A W12-owned worker idempotently finalizes the immutable object and
  marks it ready; only ready artifacts are readable. Retry/repair and orphan cleanup
  remain W12-owned.
- **Explicitly out of scope:** Distributed transactions, two-phase commit, universal
  saga/workflow platforms, and one repair framework for every storage path.
- **Updated documents:** W5, W12, parent production plan, findings registry, W12
  review, cross-workstream review, goal coverage, impact analysis, and architecture
  assessment.

## CM-020: Fixed-Destination Deletion Propagation

- **Decision:** Retained as `High / Claim-gated`.
- **Approved minimum:** An authorized tombstone immediately blocks reads, restore,
  retrieval, and prompt injection. W14 coordinates a fixed initial destination
  registry; each storage adapter owns idempotent deletion and verification with
  `pending`, `completed`, and retryable `failed` status. The operation cannot report
  `completed` until every required destination verifies deletion.
- **Explicitly out of scope:** A generic workflow/orchestration platform, one universal
  storage adapter, and claiming immediate physical deletion from backups that instead
  enforce inaccessible-until-expiry handling.
- **Updated documents:** W8, W14, parent production plan, findings registry, W8/W14
  reviews, cross-workstream review, goal coverage, impact analysis, and architecture
  assessment.

## CM-023: Single Final Payload Owner

- **Decision:** Retained as `High / Required guardrail`.
- **Approved minimum:** W16 produces only a deterministic cache partition plan. W3
  alone assembles and serializes the final provider payload, verifies fit, and computes
  stable-prefix/full-prompt fingerprints from that exact payload. Trusted dispatch
  sends it unchanged except for transport-only metadata.
- **Explicitly out of scope:** A second serializer, pre-fit prompt fingerprints, and a
  separate prompt-assembly service.
- **Updated documents:** W3, W16, parent production plan, findings registry, W3/W16
  reviews, cross-workstream review, goal coverage, impact analysis, and architecture
  assessment.

## CM-018: Minimum-Fidelity Semantic Validation

- **Decision:** Retained as `High / Required guardrail`.
- **Approved minimum:** Split validation into two layers. Structural validation
  (blocks commit): schema validity, source-event reference existence, measurable token
  reduction, mandatory ContextItem presence, tool-call/result pair integrity, and
  representation tier not below declared minimum fidelity. Semantic quality
  (measured, does not block commit): information retention, constraint/decision/goal
  coverage, and semantic equivalence are all routed to W15 SLO measurement. W13's
  `summary_invalid` failure is triggered only by structural validation. W11's
  `minimum_fidelity_violation` checks only representation tier, not content semantics.
- **Explicitly out of scope:** Semantic proof system, LLM-based automatic semantic
  equivalence validation as a commit gate, and semantic quality metrics as hard
  blockers.
- **Updated documents:** W11, W13, W15, parent production plan, findings registry.

## CM-021: Summary Source Coverage Validation

- **Decision:** Retained as `Medium / Required guardrail`.
- **Approved minimum:** Structural validation (blocks commit): every compression or
  summary result must include `source_event_range` or `source_event_ids` (reusing the
  CM-002 lineage contract), referenced source events must exist and not be deleted,
  mandatory ContextItems must have a corresponding representation after compression
  (tier may degrade but cannot disappear), and schema must be valid. Semantic
  coverage (measured, does not block): key decision/constraint/goal retention rate
  and source-to-summary information-loss classification are routed to W15 SLO.
- **Explicitly out of scope:** Field-level information retention verification,
  automatic semantic coverage scoring as a hard gate, and an independent summary
  quality validation platform.
- **Updated documents:** W6, W13, W15, parent production plan, findings registry.

## CM-024: Claim-Scoped Production Readiness Terminology

- **Decision:** Retained as `Low / Required guardrail`.
- **Approved minimum:** Reuse the lightweight claim-scoped release checklist
  established by CM-011. Use "claim-scoped production readiness" rather than
  unconditional "production-ready" in documentation. The checklist lists each enabled
  capability claim, linked mandatory gates and evidence versions, explicitly excluded
  or disabled unsupported claims, and release approval identity and time. No new
  governance platform is introduced.
- **Explicitly out of scope:** Separate release-governance platform, new project-
  management workflow, and removing "production-ready" from all documents (only
  qualifying its usage is required).
- **Updated documents:** Parent production plan, W15, findings registry.

## CM-017: Authority Conflict Taxonomy

- **Decision:** Retained as `Medium / Scope-exclusion`.
- **Approved minimum:** Declare a finite initial conflict set in W10. Cross-tier
  conflicts are resolved by authority ordering (already defined). Same-tier conflicts
  take higher specificity or more recent time. Incomparable conflicts return
  `authority_conflict_unresolved` and do not silently select either side. Multi-source
  memory conflicts are handled by W10 global retrieval resolution for deduplication,
  lifecycle filtering, and contradiction detection; unresolvable conflicts are excluded
  from injection. All unresolved conflicts emit a reason code visible through W9
  inspection and W15 measurement.
- **Explicitly out of scope:** Exhaustive conflict-resolution ontology, automatic
  conflict arbitration framework, and cross-tenant authority merging.
- **Updated documents:** W10, parent production plan, findings registry.

## CM-025: Subagent Identity and Delegation Model

- **Decision:** Retained as `Medium / Scope-exclusion`, with the scope expanded from
  "read-only delegation" to "independent agent with restricted delegation."
- **Approved minimum:** A subagent is a normal agent whose trigger mechanism differs.
  It runs as an independent agent with its own `agent_session_id` (UUID), its own W5
  execution event log, its own W1/W2 capacity and budget, and its own permissions
  defined by its agent configuration. The subagent's `agent_session` inherits the
  parent's `conversation_id` and records `parent_session_id` pointing to the parent
  agent's session, plus `delegation_type = 'subagent'`. Subagent delegation is
  implemented as a special built-in tool (`delegate_task`) that executes
  asynchronously and returns a session ID to the parent agent. The framework notifies
  the parent agent when subagent execution completes; the parent agent retrieves the
  subagent's final answer through a query mechanism. The parent agent is free to
  continue other work or wait during subagent execution. Only the final answer is
  exposed to the parent agent; intermediate execution history remains in the
  subagent's own session. Recursive delegation is prohibited: subagents cannot create
  sub-subagents or delegate tasks. Memory write scope follows the same rules as
  ordinary agents, determined by the subagent's agent configuration. W14 governance
  is not reapplied during subagent-to-parent result transfer; W10 policy selection in
  the parent agent naturally handles permission differences.
- **Explicitly out of scope:** Recursive delegation (sub-subagents), delegated
  mutation capability-token framework, subagent independent identity separate from
  parent tenant/user, and subagent access to parent session history unless explicitly
  passed in the delegation task.
- **Updated documents:** W4, W5, W12, parent production plan, findings registry.


