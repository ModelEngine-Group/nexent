# P1: Raw History and Active Context Separation

## Objective

Build deterministic, versioned, purpose-specific projections from W5 execution events.
The W5 event log remains the durable source of truth; P1 produces the different views
needed by the chat UI, agent resume, model requests, Working Memory, long-term memory,
and audit without sending all durable history to every consumer.

P1 is successful when adding more tool details, lifecycle events, and audit metadata to
W5 does not automatically increase model-prompt size or change current chat behavior.

## Scope and Non-Goals

P1 owns:

- Reading an authorized, session-ordered range of W5 events.
- Applying restore/reset lifecycle semantics to determine active-state lineage.
- Transforming events into rebuildable, purpose-specific records and `ContextItem`s.
- Explaining every inclusion, transformation, and exclusion with stable reason codes.
- Providing backend-owned chat and resumable-history views during migration.

P1 does not:

- Append or mutate W5 events.
- Decide final token budgets or representation upgrades; P3 and W10 own selection.
- Generate compressed representations; W8 and W6 own reduction and compaction.
- Persist recovery compression snapshots; W5 owns compression snapshots.
- Persist long-term memories; P3 and memory services decide and perform writes.

## Source and Derived-State Invariants

1. W5 events are the source of truth. Projections and materialized caches are disposable.
2. Events are read in ascending `event_seq`; UUIDs and timestamps never define order.
3. A projector never changes source events or hides an event from authorized audit.
4. The same event prefix, projector version, policy version, and authorization scope
   produce the same projection and fingerprint.
5. `model_context_projection` is not the complete model prompt. It supplies eligible
   history/context candidates to P3/W10 for policy selection and final fit.
6. Restore/reset changes active-state lineage through lifecycle events, while
   `audit_projection` continues to expose the complete authorized event sequence.
7. Hidden/private chain-of-thought is neither required nor reconstructed.

## Terminology

| Term | Meaning |
| --- | --- |
| Raw history | Authorized W5 events ordered by `event_seq`. |
| Active-state lineage | Events currently effective after applying restore/reset lifecycle semantics. |
| Projection | Rebuildable transformation of raw history for one declared purpose. |
| Projection record | Purpose-specific output record, such as one chat message or resume action. |
| `ContextItem` | Stable typed candidate that may be selected or reduced for model context. |
| Materialized projection | Optional cached projection that can always be rebuilt from W5. |

## Projection Request and Result Contract

Create one shared `HistoryProjector` service. Public callers resolve
`ContextIdentity` and authorization before projection; internal execution uses the
resolved W5 `agent_session_id`.

```text
project(
  identity,
  agent_session_id,
  through_event_seq,
  purpose,
  projection_version,
  policy_version,
  authorization_scope,
  options
) -> ProjectionResult
```

Request rules:

- `through_event_seq` is inclusive. Omitted means the latest committed event.
- `purpose` is a closed registry value, not arbitrary caller text.
- `projection_version` identifies transformation behavior and schema.
- `policy_version` controls governance/filtering behavior, not source-event parsing.
- `authorization_scope` is resolved by trusted backend code.
- `options` uses a typed per-purpose schema and cannot bypass authorization or policy.

`ProjectionResult` must contain:

| Field | Meaning |
| --- | --- |
| `agent_session_id` | Projected W5 session. |
| `through_event_seq` | Last source sequence considered. |
| `active_baseline_seq` | Checkpoint/event baseline selected by the latest applicable restore/reset lifecycle event. |
| `purpose` | Projection registry key. |
| `projection_version` | Transformation implementation/schema version. |
| `policy_version` | Governance policy version used. |
| `records` | Ordered typed projection records. |
| `context_items` | Stable candidate items, empty for projections that do not produce them. |
| `source_ranges` | Source event ranges consumed, including excluded inactive ranges when relevant. |
| `decisions` | Inclusion, exclusion, redaction, grouping, and transformation decisions with reason codes. |
| `token_estimates` | Optional estimates by record/item and total; never treated as final W10 counts. |
| `fingerprint` | Canonical digest of source ranges, relevant event content, versions, and options. |
| `replay_status` | `complete` or `partial_after_erasure`; projections never hide loss of source evidence. |

Required failure types:

- `identity_not_found`
- `access_denied`
- `invalid_event_range`
- `unsupported_event_schema`
- `unsupported_projection_version`
- `invalid_projection_options`
- `artifact_unavailable`
- `projection_invariant_violation`

## Shared Projection Pipeline

Every projection runs the same ordered stages:

1. **Resolve identity and boundary:** authorize `ContextIdentity`, resolve
   `agent_session_id`, and validate `through_event_seq`.
2. **Read canonical events:** stream W5 index/data rows ordered by `event_seq`; the W5
   canonical reader validates event schemas, upcasts the immediately previous version
   to the current internal representation, and validates parent/session relationships.
3. **Apply governance:** enforce P5 redaction, deletion, retention, and authorization.
4. **Resolve active lineage:** interpret `restore.applied`, `reset.applied`, and related
   lifecycle events for projections that represent current state.
5. **Transform by purpose:** group, select, and transform events using the registered
   projector implementation.
6. **Build `ContextItem`s:** when required, produce stable typed candidates and source
   provenance without selecting final prompt representations.
7. **Record decisions:** emit stable reason codes for every excluded, transformed,
   inactive, or policy-denied source record.
8. **Fingerprint and return:** canonicalize the result inputs and compute the digest.

### Active-Lineage Rules

- `audit_projection` reads all authorized events and ignores active-lineage exclusion.
- `chat_projection` shows the user-visible linear transcript by default. Restore/reset
  lifecycle markers may be shown as metadata, but prior visible messages remain visible
  unless product policy explicitly hides them.
- Resume, model-context, and Working Memory projections apply active lineage.
- A `restore.applied` event records the restored covered `event_seq` and may reference
  a W5 `compression.snapshot` event. Current state is reconstructed from the active source prefix through
  that sequence, then events after the restore event are applied. The checkpoint may
  accelerate reconstruction but is never required. Events between the restored
  boundary and restore event remain audit history but are excluded from active state
  with reason `inactive_after_restore`.
- A `reset.applied` event declares which derived-state categories reset. Later events
  rebuild those categories; unaffected categories remain active.

## Minimum Event-to-Projection Mapping

The event taxonomy ADR must define mapping rules for every registered W5 event type.
The initial registry must cover at least:

| Event type or family | Chat | Resume | Model context | Working Memory | Memory candidate | Audit |
| --- | --- | --- | --- | --- | --- | --- |
| `user.input` | User message | Active objective/input | Recent-turn candidate | Goal/constraint evidence | Possible explicit fact | Full authorized event |
| `run.started` | Usually hidden | Run/config state | Agent/config metadata only when needed | Active run state | Excluded | Full authorized event |
| model action/visible progress | Policy-visible unit | Action status | Recent complete-step candidate | Open/completed action | Usually excluded | Full authorized event |
| `tool.call.*` | Usually hidden | Pending/completed tool action | Paired with result when relevant | Tool state | Excluded | Full authorized event |
| `tool.result.*` | Optional visible unit/source | Result status and pointer | Paired result summary/pointer | Tool state/evidence | Verified evidence candidate when eligible | Full authorized event |
| `run.failed` / cancellation / retry | Optional status | Recovery/retry state | Include only when relevant | Blocker/tool state | Excluded | Full authorized event |
| `final.answer` | Assistant message | Completed outcome | Recent-turn candidate | Goal/action completion evidence | Possible explicit fact only | Full authorized event |
| Working Memory update/edit | Hidden | Active state | Structured candidate | Apply typed update | Excluded | Full authorized event |
| memory candidate/decision/write | Hidden | Usually excluded | Only if relevant and retrieved by policy | Optional decision state | Candidate/decision record | Full authorized event |
| artifact event | Attachment/reference | Artifact state | Authorized pointer/summary | Entity/evidence reference | Possible verified evidence | Full authorized event |
| `restore.applied` / `reset.applied` | Optional lifecycle marker | Apply lineage/state change | Apply lineage/state change | Apply lineage/state change | Apply lineage when relevant | Full authorized event |
| deletion/redaction/tombstone | Hide or mark according to policy | Remove/invalidate affected state | Remove/invalidate affected candidates | Remove/invalidate affected fields | Remove/invalidate candidate | Retain authorized proof metadata |

Unknown registered event types must never be silently ignored. A projector must either
handle the type, explicitly exclude it with a registered reason, or fail with
`unsupported_event_schema`.

P1 projectors consume only W5 canonical current-form events and never implement
event-schema upcasters independently. W5 events outside the approved `current +
previous` compatibility window fail with `unsupported_event_schema`; P1 does not guess,
silently exclude, or rewrite them.

### Projection Implementation Priority

Not all projections are required for Release 1. Prioritize by consumer dependency:

- **Release 1 required:** `chat_projection` (UI compatibility), `resume_projection`
  (restart recovery), `model_context_projection` (P3/W10 input).
- **Release 1 optional:** `working_memory_projection` (can defer if compression
  snapshots carry Working Memory directly), `memory_candidate_projection` (depends
  on P3 Memory Policy Engine), `audit_projection` (can implement after core
  projections are stable).
- **Deferred:** `memory_projection` (compatibility flow, low priority).

## Required Projections

### `chat_projection`

**Consumer:** Existing conversation APIs and chat UI.

**Produces:** Ordered user-facing message records and attachment/citation references.

Include:

- User inputs accepted for durable runs.
- Assistant final answers.
- Explicitly user-visible progress units supported by current UI policy.
- Feedback, title, deletion, and lifecycle metadata required by the UI.

Exclude by default:

- Internal tool arguments/results.
- Retry bookkeeping, checkpoints, policy decisions, and private operational metadata.
- Hidden/private reasoning.

Required compatibility mapping:

- Derive `message_index` and `unit_index` from committed event order, never caller
  history length.
- Preserve current message/unit/source response shapes until the UI migrates.
- Make projection writes idempotent using source `event_id`.

### `resume_projection`

**Consumer:** Run preparation after restart, worker handoff, or a later user turn.

**Produces:** Typed records sufficient to continue unfinished work without replaying
every raw observation into the model.

Include:

- Latest active user objective and accepted explicit constraints.
- Completed and pending actions.
- Tool-call/result status, including interrupted, ambiguous, resolved, and retryable operations.
- Confirmed decisions, unresolved questions, relevant artifacts, and lifecycle state.
- Latest compatible checkpoint reference when available.

An unresolved `ambiguous_effect` is a blocking resume record. The projection must not
represent the associated tool call as safely retryable or completed. After a W5
resolution event, it projects the explicit `retry`, `skip`, or `confirm_completed`
decision and its actor.

Exclude:

- Superseded/inactive state.
- Completed low-value detail that does not affect continuation.
- Raw large outputs when a governed artifact pointer or summary exists.

### `model_context_projection`

**Consumer:** P3 policy selection and W10 final-fit assembly for the next model request.

**Produces:** Ordered eligible `ContextItem` candidates, not a final serialized prompt.

Include:

- Recent complete user/assistant turns.
- Active goals, constraints, decisions, unresolved items, and required tool state.
- Complete tool-call/result pairs when they remain relevant.
- Authorized artifact pointers and already-valid compacted representations.

Rules:

- Never split a required tool-call/result pair.
- Mark mandatory/minimum-fidelity metadata, but let P3 decide policy priority.
- Do not automatically include all chat or audit records.
- Increasing raw event detail must not increase this projection unless transformation
  rules intentionally produce a new candidate.

### `working_memory_projection`

**Consumer:** Agent runtime, W5 compression snapshots, W7 inspection/editing, and P3.

**Produces:** One versioned structured state object plus source-linked `ContextItem`s.

Minimum state schema:

| Category | Required content |
| --- | --- |
| `goal` | Current explicit task objective and status. |
| `constraints` | Active explicit constraints and their authority/source. |
| `decisions` | Confirmed decisions, rationale summary, and supersession state. |
| `open_items` | Unresolved questions, blockers, and planned actions. |
| `entities` | Active files, resources, identifiers, and relevant state. |
| `tool_state` | Pending, ambiguous, explicitly resolved, completed, failed, and retryable tool operations. |

Rules:

- State is derived from events and explicit W7 edit events, never mutated silently.
- Conflicting updates resolve deterministically by authority, lifecycle, and event order.
- Every field links to source event IDs and exposes a last-updated sequence.

### `memory_candidate_projection`

**Consumer:** P3 Memory Policy Engine.

**Produces:** Sanitized candidate facts/corrections/evidence for review; it never writes
long-term memory directly.

Include only:

- Stable user facts/preferences explicitly stated or confirmed.
- Corrections and supersession relationships.
- Verified tool-derived evidence allowed by policy.

Each candidate includes source events, confidence/evidence type, proposed scope,
retention classification, sensitivity classification, and rejection/confirmation
requirements.

### `memory_projection`

**Consumer:** Memory inspection and compatibility flows requiring event-derived memory.

**Produces:** Policy-approved memory records derived from W5 memory decision/write
events. It does not perform retrieval from external memory stores and does not bypass
P3 lifecycle filtering.

### `audit_projection`

**Consumer:** Authorized operators, debugging, compliance, and W9 evidence.

**Produces:** Complete authorized event records plus projection/governance decisions.

Rules:

- Preserve canonical event order and inactive-lineage events.
- Redact or deny payloads according to P5; audit access is not automatic full access.
- Include stable reason codes for unavailable, deleted, or physically redacted detail.

## `ContextItem` Contract

Not all projections produce full `ContextItem` objects. Only `model_context_projection`
and `working_memory_projection` produce complete `ContextItem` candidates with all
fields. Other projections (`chat_projection`, `resume_projection`, `audit_projection`)
produce simpler purpose-specific record structures without the full `ContextItem`
schema.

Use a stable item identity so an item can be selected, reduced, checkpointed, inspected,
and rebuilt without relying on array position.

```text
ContextItem {
  context_item_id,
  agent_session_id,
  item_type,
  scope,
  source_event_ids,
  source_event_range,
  content_or_reference,
  provenance,
  authority_tier,
  lifecycle_status,
  mandatory,
  minimum_fidelity,
  dirty_state,
  recompute_cost,
  last_updated_event_seq,
  schema_version
}
```

Rules:

- `context_item_id` is deterministic for the logical item where practical.
- Source provenance is mandatory; an item with no resolvable source is invalid.
- Items contain canonical semantic content or a governed reference, not UI formatting.
- Representations such as `full`, `compressed`, `structured`, and `pointer` are separate
  W8 records linked to the item.
- P1 may mark an item mandatory or declare minimum fidelity from source semantics, but
  P3 validates and resolves final policy.

## Storage and Materialization

Start with on-demand projection from W5 plus `compression.snapshot` acceleration. Do not create a
database table for every projection before profiling.

Materialize only when a measured latency/load requirement justifies it:

- `chat_projection` may be materialized into existing conversation tables through the
  W5 compatibility projector.
- `working_memory_projection` is persisted inside W5 `compression.snapshot` events and rebuilt from W5 when missing or invalid.
- Other projections default to on-demand or short-lived cache.

Every materialized result stores `agent_session_id`, `through_event_seq`,
`projection_version`, `policy_version`, fingerprint, creation time, and invalidation
status. A cache hit is accepted only through P2 validation.

Every persisted derived object must expose queryable source lineage. Use explicit
`source_event_ids` for sparse or selected inputs and `source_event_range` for complete
contiguous ranges. A simple reverse-reference table or indexed range lookup is
sufficient; a global lineage graph and field-level word attribution are not required.

Compression and summary validation uses a two-layer approach. Structural validation
(blocks commit): every compression result must include `source_event_range` or
`source_event_ids` (reusing the CM-002 lineage contract), referenced source events
must exist and not be deleted, mandatory ContextItems must have a corresponding
representation after compression (tier may degrade but cannot disappear), and schema
must be valid. Semantic coverage (measured, does not block commit): key
decision/constraint/goal retention rate and source-to-summary information-loss
classification are routed to W9 SLO measurement. **Finding:** CM-021.

When a source event is physically erased or irreversibly redacted, every persisted
derived object whose lineage includes that event is invalidated as a whole. Rebuild
from remaining authorized history when safe. If safe reconstruction is not possible,
return the object as unavailable rather than preserving or editing old derived content.

## Runtime Integration

### New Durable Run

1. W5 appends `user.input` and `run.started`.
2. P1 builds resume/Working Memory/model-context candidates through the committed head.
3. P3/W10 select, reduce, and fit the final model request.
4. Runtime events append to W5.
5. P1 chat projection updates compatibility tables; W5 appends `compression.snapshot` events at configured boundaries.

### Resume or Worker Restart

1. W5 locates the latest `compression.snapshot` event for the session.
2. P1 loads the snapshot payload (summary, Working Memory, token accounting) and
   replays events after the snapshot's covered range through the requested event head.
3. P1 returns reconstructed Working Memory, resume state, and model-context candidates.
4. Runtime continues without trusting frontend-provided history.

### Stateless or Non-Durable Run

Stateless requests may use caller-provided history, but must be explicitly classified.
They do not silently modify a durable agent session or become authoritative history.

## Current Chat-History Migration

Current `AgentRequest.history` is supplied by the caller and flattened to role/content
before each run. Migrate in phases:

1. **Observe:** Build `chat_projection` in shadow mode and compare it with existing
   conversation tables and caller history. Emit mismatch reason codes and no behavior
   change.
2. **Project:** Append W5 events first and populate current conversation tables through
   the compatibility projector. Existing read APIs still use current tables.
3. **Authoritative backend history:** Run preparation reads backend projections.
   Caller history is ignored for durable sessions except validated fallback.
4. **Projection-native reads:** Conversation APIs may read `chat_projection` directly;
   legacy tables remain optional materialized compatibility views.

Never append caller-provided history as duplicate source events. Historical
conversation rows predating W5 may be imported once using explicit migration events or
kept as a legacy prefix with a documented boundary.

## Stable Decision Reason Codes

At minimum define:

- `included_by_projection_rule`
- `excluded_for_purpose`
- `inactive_after_restore`
- `reset_category_inactive`
- `superseded_by_later_event`
- `policy_denied`
- `redacted`
- `deleted_or_expired`
- `replaced_by_artifact_pointer`
- `collapsed_into_group`
- `legacy_history_mismatch`
- `unsupported_event_schema`

## Required Deliverables

- Projection request/result and per-purpose record schemas.
- Projection registry and event-to-projection mapping registry.
- Authorized canonical W5 event reader.
- Restore/reset active-lineage resolver.
- Deterministic fingerprint and decision-reason implementation.
- Seven required projector implementations.
- `ContextItem` schema and builder.
- Chat shadow comparator and mismatch dashboard.
- Backend-history adapter for durable run preparation.
- Golden fixtures, replay fixtures, and migration fixtures.

## Implementation Plan

### Phase 1: Contracts and Shared Reader

1. Approve projection request/result, record, decision, and `ContextItem` schemas.
2. Define projection and reason-code registries plus their schema/version evolution rules.
3. Integrate the authorized W5 canonical event-range reader; do not duplicate W5 event
   upcasters in projectors.
4. Implement active-lineage resolver for restore/reset lifecycle events.
5. Implement deterministic fingerprinting and shared invariant checks.

### Phase 2: Chat Compatibility

1. Implement `chat_projection` against golden W5 fixtures.
2. Build shadow comparison with current conversation tables and `AgentRequest.history`.
3. Integrate W5 compatibility projector using source-event idempotency.
4. Define/import the pre-W5 legacy-history boundary.
5. Cut over compatibility writes only after mismatch targets pass. "Zero semantic
   mismatch" means: message order is identical, message content is identical,
   attachment/citation references match, and search sources match. Allowed
   differences: `message_index` derivation source (event order vs. history length)
   and any explicitly approved UI behavior changes.

### Phase 3: Resumable Runtime State

1. Implement `working_memory_projection` and its conflict/supersession rules.
2. Implement `resume_projection`, including interrupted tool/run handling.
3. Integrate W5 `compression.snapshot` load/replay: after loading a snapshot, call
   P2 `validate_derived_state(snapshot, current_events)` to confirm validity before
   using the snapshot payload for state reconstruction.
4. Change durable run preparation to use backend projections instead of caller history.
5. Validate restart and cross-worker continuation.

### Phase 4: Context and Memory Candidates

1. Implement `model_context_projection` producing `ContextItem` candidates.
2. Integrate candidate output with P3/W8/W10 without duplicating policy logic.
3. Implement `memory_candidate_projection` and `memory_projection`.
4. Implement authorized `audit_projection`.
5. Add materialization only for measured bottlenecks.
6. Performance tests measure projection latency for sessions with 100, 1000, and
   10000 events to establish baselines before production deployment.

## Repository Touchpoints

- New backend projection registry (projection registration, reason-code registry,
  event-to-projection mapping), event reader, lineage resolver, and projector modules
- W5 event-log repository and compatibility projector
- W5 compression snapshot events and P2 validator
- `backend/services/conversation_management_service.py`
- `backend/services/agent_service.py`
- `backend/agents/create_agent_info.py`
- `backend/agents/agent_run_manager.py`
- `backend/database/conversation_db.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_cache.py`
- `sdk/nexent/memory/`

## Tests

- Golden event fixtures validate every projection and decision reason.
- Determinism tests reproduce byte-equivalent canonical results and fingerprints.
- Restore/reset fixtures prove correct active lineage while audit retains full history.
- Current and immediately previous W5 event-version fixtures produce the same canonical
  projector input; versions outside the W5 compatibility window fail explicitly rather
  than being silently dropped.
- Authorization/redaction tests prove projections cannot leak tenant or restricted data.
- Chat shadow tests compare projected messages, units, attachments, and sources with
  current UI behavior.
- Legacy-history migration tests prevent duplicate messages and define the migration boundary.
- Restart and cross-worker tests reconstruct the same Working Memory and resume state.
- Interrupted tool-call tests preserve status and required call/result relationships.
- Ambiguous-effect fixtures prove resume remains blocked until an explicit durable
  resolution event exists.
- Prompt-growth tests prove additional audit/tool detail does not automatically increase
  `model_context_projection`.
- Cache rebuild tests reproduce materialized results from W5 after deletion or corruption.
- Erasure-lineage tests locate affected persisted projections, Working Memory,
  summaries, checkpoints, and memory candidates by source event; invalidate each whole
  object; and mark rebuilt results `partial_after_erasure`.

## Definition of Done

P1 is complete when:

- Every required projection has an approved typed schema, version, deterministic
  implementation, golden fixtures, and stable reason codes.
- Every registered W5 event type has an explicit mapping or exclusion rule for every
  required projection; no event type is silently dropped.
- W5-backed `chat_projection` produces zero semantic message/order/attachment/source
  mismatches against approved compatibility fixtures. Any intentionally changed UI
  behavior is separately approved and versioned.
- Durable run preparation and restart recovery use backend projections rather than
  trusting caller-provided history.
- Working Memory and resume state rebuild from W5 alone, optionally accelerated by a
  valid W5 `compression.snapshot` event.
- P3/W10 receive bounded `ContextItem` candidates instead of raw complete history.
- Audit can reconstruct the complete authorized event sequence, including inactive
  restore/reset history.
- All materialized projections are disposable and demonstrably rebuildable from W5.
- Determinism, authorization, restore/reset lineage, restart, and migration test suites
  pass with no known projection-invariant violations.
