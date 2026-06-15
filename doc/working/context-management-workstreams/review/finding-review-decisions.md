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
