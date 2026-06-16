# W4: Structured Agent Execution Event Log

## Objective

Create an append-only, typed, replayable execution event log that becomes the durable
source of truth for agent runs while preserving the current conversation UI through a
compatibility projection.

## Scope and Non-Goals

W4 stores what happened: runs, model actions, tool calls/results, artifacts, errors,
answers, context-item lifecycle, Working Memory updates, and memory decisions. W5
decides what each consumer sees. W4 also persists `compression.snapshot` events for recovery acceleration. Hidden/private
chain-of-thought is explicitly not required and is not persisted by default. Branching
and forking execution history are not supported by this design.

## Core Entities

| Entity | Required responsibility |
| --- | --- |
| `agent_session` | Tenant/user ownership, status, lifecycle metadata, and next event sequence |
| `agent_event_index` | Ordered event envelope and run/step relationships |
| `agent_event_data` | Typed, schema-versioned event payload |
| `agent_artifact` | Large or binary output stored outside inline events |
| `compression.snapshot` | Event-boundary recovery record, stored as a W4 event type |

### Table Design

#### `agent_session`

| Field | Meaning |
| --- | --- |
| `agent_session_id UUID` | Globally unique durable agent-session identifier; distinct from the existing CAS/JWT authentication `session_id`. |
| `tenant_id` | Immutable tenant security and data-isolation owner, derived from trusted request context. |
| `user_id` | Immutable single user owner within the tenant, derived from trusted request context. |
| `conversation_id NULL` | Existing Nexent conversation referenced by the compatibility projection; unique within the tenant/user ownership scope when present. |
| `next_event_seq BIGINT` | Next sequence number allocated during an atomic append. |
| lifecycle fields | Status, creation/update timestamps, retention, and policy metadata. |

#### `agent_event_index`

| Field | Meaning |
| --- | --- |
| `event_id UUID` | Globally unique event identifier. UUID values never determine replay order. |
| `agent_session_id UUID` | Owning agent session; tenant and user are resolved through `agent_session`. |
| `event_seq BIGINT` | Monotonically increasing sequence within the session and the sole replay order. |
| `run_id BIGINT` | Session-scoped identifier for one user-triggered execution. |
| `step_id BIGINT NULL` | Run-scoped identifier grouping events from one logical execution step. |
| `parent_event_id UUID NULL` | Direct causal parent, such as a tool result's tool-call event. |
| `idempotency_key` | Caller-generated key preventing duplicate appends during retries. |
| `created_at` | Backend-assigned event creation timestamp for audit, not ordering. |

Required constraints:

- Primary key: `event_id`.
- Unique replay position: `(agent_session_id, event_seq)`.
- Unique retry identity: `(agent_session_id, idempotency_key)`.
- A referenced `parent_event_id` must belong to the same session.
- `run_id` increases within a session; `step_id` increases within a run.

#### `agent_event_data`

| Field | Meaning |
| --- | --- |
| `event_id UUID` | Primary key and foreign key to `agent_event_index`. |
| `event_type` | Stable registry key selecting the payload schema. |
| `schema_version` | Version of the schema used to validate and interpret `detail`. |
| `detail JSON/JSONB` | Validated event payload after required redaction. |
| policy fields | Redaction status, policy version, and other payload-governance metadata. |

The split between index and data keeps replay scans and relationship queries small.
Both rows must be inserted atomically, so an indexed event can never exist without its
typed payload. Large or binary payloads are stored in `agent_artifact` and referenced
from `detail`. Before this transaction, the trusted W11 governance boundary must return
a complete `GovernedPayload`. Classification or redaction failure cannot fall back to
raw event persistence; only a sanitized reason-coded failure event without the rejected
payload may be appended.

### Compatibility with Current Nexent Conversations

The existing integer `conversation_id` remains the public chat identifier and current
conversation APIs do not need to expose `agent_session_id`. W4 creates exactly one
internal `agent_session` for each owned Nexent conversation and enforces uniqueness on
`(tenant_id, user_id, conversation_id)` when `conversation_id` is present. Debug or
northbound runs without a conversation may receive standalone non-reusable agent
sessions. Existing conversations receive sessions lazily on their first W4-backed run
or through a migration job.

The initial release never changes an `agent_session` owner and does not attach multiple
users to one session. Sharing and ownership-transfer requests are rejected by W3/W7;
shared agents or tenant-shared memories do not grant access to W4 history.

Current conversation tables remain a compatibility projection during migration:

- User input and assistant output are appended to W4 first, then projected into
  `conversation_message_t`, `conversation_message_unit_t`, and source tables.
- Existing `message_index` and `unit_index` remain UI ordering fields; they do not
  replace W4 `event_seq`.
- Existing opinion updates, title changes, and soft deletion remain supported, but
  corresponding typed events must be appended so projections and audit state agree.
- `agent_id`, model configuration, and agent version are run properties stored in the
  typed `run.started` payload because the selected agent may differ between runs.

The main migration conflict is authority: current save paths write conversation tables
directly, while the target design makes W4 the source of truth. For every event that
requires a compatibility projection, the W4 event rows and its projection-outbox row
are created in the same relational transaction. The asynchronous projector is
idempotent, so an event commit may be temporarily absent from the compatibility view
but can never lose the durable work item needed to repair that view.

Additional current-mechanism conflicts and required resolutions:

| Current Nexent behavior | W4 migration requirement |
| --- | --- |
| Conversation rows identify their creator but do not store explicit `tenant_id`. | Backfill and enforce tenant ownership for each `agent_session`; never infer ownership from `conversation_id` alone. |
| `AgentRequest.conversation_id` is optional for debug and northbound paths. | Create a standalone agent session or explicitly classify the run as non-durable; do not silently append it to another conversation. |
| User and assistant messages are saved asynchronously and directly to conversation tables. | Append typed events synchronously at lifecycle boundaries, then project chat rows asynchronously with durable retries. |
| Active runs are registered by `user_id:conversation_id`, so a concurrent run overwrites the previous registry entry. | Initial durable-session scope permits exactly one active run per `agent_session`. A second run is rejected until the first reaches a committed terminal or recovery state. |
| UI `message_index` is computed from request history and may collide under concurrent runs. | Derive compatibility message order from committed W4 events rather than caller history length. |
| Conversation rows support opinion updates, title changes, and soft deletion. | Keep them as projections while appending corresponding feedback, metadata-change, and deletion/tombstone events. |

### Identity and Replay Contract

`tenant_id` and `user_id` are stored once on `agent_session`, not repeated on every
event. `run_id` and `step_id` are integer logical identifiers rather than globally
unique identities; their full scopes are `(agent_session_id, run_id)` and
`(agent_session_id, run_id, step_id)`. Events are replayed by joining index and data
rows, filtering by `agent_session_id`, and ordering by `event_seq`. UUID timestamps,
database row order, `run_id`, and `step_id` must never substitute for `event_seq`.

### Initial Active-Run Contract

The initial release permits exactly one active run per durable `agent_session`.
`agent_session` stores or references the current `active_run_id`; run start and terminal
state changes update it transactionally with the corresponding W4 lifecycle event.

A second run and conflicting W7 lifecycle mutations are rejected while `active_run_id`
is present. A cancelled, interrupted, or crashed run must first reach a committed
terminal/recovery state before the active-run marker is cleared. This deliberately
avoids concurrent same-session mutation and does not require fencing tokens.

### Append-Only Contract

`agent_event_index` and `agent_event_data` are immutable after their shared append
transaction commits. The normal application role may insert and read event rows but
may not update or delete them. Corrections, retries, cancellations, and logical
redactions are represented by new typed events. `agent_session.next_event_seq` and
session lifecycle fields are mutable coordination state and are not part of the
append-only event history. W11-governed legal deletion or physical redaction is the
only privileged exception; it must emit an auditable tombstone/proof record and
invalidate affected derived state. The owning `agent_session` is marked
`partial_after_erasure`; the system must no longer claim complete deterministic replay
for that session. The event index and non-sensitive envelope metadata may be retained
when policy permits, but erased payload content must not be copied into the proof.

## Event Taxonomy

Define a stable registry for user input, run lifecycle, model action, tool call, tool
result, artifact, error/retry/cancellation, final answer, Working Memory update,
memory candidate/write/conflict decision, context-item creation/representation/recall/
eviction/restoration, writeback stage/validation/commit/rejection,
compression.snapshot, and lifecycle boundary. The `run.started` payload stores
immutable model, agent, and configuration snapshots needed to replay that run without
a dedicated run table. Payload schemas use typed models and stable reason codes.

### `compression.snapshot` Event Type

A `compression.snapshot` event captures the result of context compression as a durable
event within the execution event log. It replaces the former independent checkpoint
subsystem (W7) and serves as the recovery acceleration point for restart, failover,
and worker handoff.

Payload schema:

| Field | Type | Meaning |
| --- | --- | --- |
| `summary_text` | string | Compressed history summary covering events before this snapshot |
| `working_memory` | structured object | Current Working Memory state (goal, constraints, decisions, open items, entities, tool state) |
| `covered_event_range` | `{start_seq, end_seq}` | Inclusive event sequence range covered by this snapshot |
| `token_accounting` | `{summary_tokens, working_memory_tokens, recent_events_tokens}` | Token counts at snapshot time |
| `selected_representations` | list | ContextItem representation references active at snapshot time |
| `policy_version` | string | Context/memory policy version used for compression |
| `model_version` | string | Model ID and version used for compression |
| `schema_version` | string | Follows CM-005 event-schema compatibility contract |
| `projection_version` | string | W5 projection version active at snapshot time |
| `creation_reason` | enum | `periodic`, `lifecycle_boundary`, `manual_compact`, `dirty_state_flush` |

A `compression.snapshot` event is appended like any other W4 event. It is immutable
after commit. Subsequent compression produces a new `compression.snapshot` event that
covers an extended range; old snapshots remain in the event log as audit history but
are superseded for recovery purposes by the latest snapshot.

If the snapshot payload exceeds the inline event size limit, large fields (e.g.,
Working Memory) are stored as W10 artifacts and referenced by pointer.

### Recovery from Compression Snapshot

Worker restart, failover, and load-balancer routing changes use the following
recovery flow:

1. **Find the latest `compression.snapshot` event** for the session by querying
   `agent_event_data` for the most recent event of type `compression.snapshot`.
2. **Load its payload**: summary text, Working Memory, token accounting, and
   covered event range.
3. **Replay events after the snapshot**: read all W4 events with `event_seq`
   greater than the snapshot's `covered_event_range.end_seq` and apply them to
   reconstruct the current state.
4. **Resume execution** from the reconstructed state.

If no `compression.snapshot` exists (e.g., first run, or all snapshots were erased),
recovery replays the entire event log from the beginning. This is always correct but
slower for long sessions.

Recovery never treats an in-flight tool call as completed or automatically reinvokes
it. Unresolved `ambiguous_effect` state blocks continuation until W7 records an
explicit resolution.

A `compression.snapshot` affected by physical erasure is invalidated as a whole.
Recovery falls back to the previous snapshot or full event replay. If safe
reconstruction is impossible, recovery fails explicitly with
`recovery_unsafe_after_erasure`.

### Dirty-State Flush

Dirty context state (in-memory Working Memory, pending compression results) must be
committed as a `compression.snapshot` event before worker handoff, shutdown, reset,
restore, eviction, or compaction can discard the only in-memory copy. Flush failure
blocks destructive lifecycle actions and returns a typed fault.

### Initial Event-Schema Compatibility Contract

CM-005 is claim-gated: this contract does not block the initial single-version
implementation or deployment, but it is required before the first production event-
schema upgrade.

For each event type, the W4 registry declares one enabled writer version and supports
reading that current version plus its immediately previous version. The W4 canonical
event reader owns the simple previous-to-current upcaster and returns the current
internal representation to W5, replay, projection, and audit consumers. Stored events
remain immutable; consumers do not implement their own event upcasters.

An event outside the declared `current + previous` read window fails explicitly with
`unsupported_event_schema`. The initial contract does not promise arbitrary historical
compatibility, database rewriting of old events, reverse/down-casting, or an independent
schema-evolution platform.

No upgrade may remove reader support for a schema version that still exists in retained
durable events. A later upgrade that would move retained events outside the
`current + previous` window requires an explicitly approved migration or expanded read
window before enabling its writer; this initial contract does not design that mechanism.

The first production schema upgrade uses a two-stage deployment:

1. Deploy readers that accept both the previous and new event version while writers
   continue emitting the previous version.
2. Enable the new writer version only after no instance that cannot read it remains in
   service.

After new-version writes begin, rollback is permitted only to a release that can read
the new version. A release that cannot read it must not receive traffic.

### Ambiguous Tool-Effect Guardrail

For the initial release, any committed `tool.call.started` event without a committed
terminal tool-result event is classified as `ambiguous_effect` during recovery. This
conservative rule does not require a tool side-effect taxonomy and applies even when
the tool may be read-only.

An ambiguous tool call must not be invoked automatically during resume. W4 records an
explicit operator/user resolution event selecting `retry`, `skip`, or
`confirm_completed`, including actor, timestamp, and optional rationale. Only that
resolution permits the run to continue. Selecting `retry` is an explicit acceptance
of possible duplicate external effects.

Automatic effect reconciliation, external-system status queries, and cross-tool
transaction coordination are outside W4's initial scope.

## Event Writer Interface and Failures

```text
append_event(identity, agent_session_id, run_id, step_id, parent_event_id,
             event_type, schema_version, detail, idempotency_key) -> AppendResult
```

`AppendResult` contains `event_id`, committed `event_seq`, duplicate status, and
projection-outbox status. Required failures include `session_not_found`,
`identity_not_authorized`, `event_schema_invalid`, `parent_session_mismatch`,
`payload_too_large`, `governance_processing_failed`, `sequence_conflict`, and
`append_storage_failed`. Retrying the same idempotency key returns the original
committed result.
Starting a second run for the session returns `active_run_conflict`.
The backend registry, not an untrusted caller, selects the enabled writer
`schema_version`; an append requesting another version returns `event_schema_invalid`.

## Required Deliverables and Phases

- Deliver schema/event registries, migrations, append repository/service, artifact
  integration, projection outbox, compatibility projector, replay reader, and operator tooling.
- Phase through schema/append foundations, shadow event emission, compatibility
  projection, event-first authority cutover, then removal of direct transcript writes.
- Each phase requires migration reports for missing sessions, duplicate messages,
  unmatched tool pairs, and projection lag.

## Write Path

The backend owns event creation. One transaction validates and redacts the typed
payload, atomically allocates the session's next `event_seq`, inserts
`agent_event_index` and `agent_event_data`, advances `next_event_seq`, and creates each
required compatibility-projection outbox row. If any required outbox insert fails, the
entire append transaction rolls back. Concurrent writers use row locking or optimistic
compare-and-swap on the session sequence.

The committed W4 event is immediately authoritative and readable; compatibility views
may lag until their outbox work completes. The outbox uses `(event_id,
projection_type)` as its idempotency key and records pending, completed, or failed-with-
retry state plus bounded error metadata and attempt timestamps. Projector retries and
operator replay of incomplete rows must be idempotent. Failed projection never loses
the source event or its repair work item.

This is a path-specific same-database transaction and asynchronous repair contract. It
does not require a general saga engine, distributed transaction, or shared repair
framework for unrelated storage paths.

The initial implementation keeps this simple per-session sequence allocation and the
normalized index/data join. It records append latency, session-sequence lock wait,
events per session, and replay latency. Batching, partitioning, materialization, or a
separate sequence service is considered only when representative CM-009 workload
measurements cross an approved threshold; this optimization does not block the initial
production implementation.

## Implementation Plan

1. Approve architecture decision records (ADRs) before the first production schema upgrade:
   - **1a. Event taxonomy and schema ADR:** Define event types (user.input,
     run.started, run.completed, tool.call.started, tool.call.completed,
     final.answer, error, cancellation, Working Memory update, memory decision,
     compression.snapshot, lifecycle boundary, etc.), payload schema for each event
     type, and schema versioning strategy.
   - **1b. Ordering and idempotency ADR:** Define event_seq as the sole ordering
     mechanism, idempotency_key usage and uniqueness constraints, run_id and step_id
     scoping rules, and concurrent writer conflict resolution.
   - **1c. Event schema evolution ADR:** Define current + previous version support
     policy, upcaster implementation requirements, and deployment/rollback procedures.
2. Add database entities, indexes, payload-size limits, and append repository.
3. Add session resolution and an event writer to each code path:
   - **3a. Agent main loop:** Emit `run.started` (with model/agent/config snapshots)
     and `run.completed`/`run.failed` events in `CoreAgent._run_stream`.
   - **3b. Tool execution:** Emit `tool.call.started` and `tool.call.completed`
     events around each tool invocation in the agent step loop.
   - **3c. Error and cancellation:** Emit `error` events on exceptions and
     `cancellation` events when `stop_event` is triggered.
   - **3d. Answer generation:** Emit `final.answer` events when the agent produces
     its final output.
4. Add context/memory lifecycle event APIs for W5-W11.
5. Implement redaction-before-persistence and artifact-reference behavior with W11.
6. Build compatibility projection into current conversation tables.
7. Migrate direct/asynchronous conversation saves to event-first projection in phases:
   - **7a. Shadow mode:** Dual-write to both W4 events and existing conversation
     tables; compare outputs and log mismatches without changing behavior.
   - **7b. Read switch:** Read conversation history from W4 event projections;
     keep dual-write for safety.
   - **7c. Write switch:** W4 events become authoritative; conversation table
     writes happen asynchronously through the compatibility projector.
   - **7d. Remove direct writes:** Remove legacy direct-write paths to
     conversation tables; all mutations go through W4 event append first.
8. Implement replay tooling that reconstructs a run after process restart.

## Repository Touchpoints

- `backend/database/db_models.py` and new event-log database module (event
  repository for index/data append and replay, session repository for
  agent_session CRUD and sequence allocation, projection outbox for
  compatibility projection work items)
- `backend/agents/create_agent_info.py`
- `backend/apps/agent_app.py`
- `backend/services/conversation_management_service.py`
- `backend/database/conversation_db.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/agents/agent_context.py`
- Tool execution and observer/monitoring paths

## Tests and Definition of Done

- Before the first production event-schema upgrade, schema contract tests prove the
  current and immediately previous event versions read through the W4 canonical
  upcaster, while versions outside the window fail explicitly.
- Before enabling a new production writer version, reader-first/writer-later deployment
  and rollback tests prove the writer cannot be enabled while an incompatible reader
  remains, no retained event version loses reader support, and rollback never routes
  traffic to a release unable to read committed new-version events.
- Atomic ordering, idempotent append, retry, and concurrent-writer tests.
- Active-run tests prove a durable session cannot start a second run until the first
  reaches a committed terminal or recovery state.
- Constraint tests prove event sequences are unique and parent events stay in-session.
- Atomicity tests prove index and data rows cannot be partially committed.
- Event/projection-outbox crash tests prove a required outbox row commits atomically
  with its W4 event, projection lag remains visible, and retry/operator replay
  idempotently repairs failed compatibility views.
- Replay test reconstructs a completed and interrupted run after restart.
- Physical-erasure tests retain only permitted envelope/proof metadata, mark the
  session `partial_after_erasure`, and prevent complete-replay claims.
- Crash tests at the tool-call boundary classify every started call without a committed
  terminal result as `ambiguous_effect`, block automatic invocation, and continue only
  after a durable `retry`, `skip`, or `confirm_completed` resolution event.
- Representative CM-009 workload tests report event-append latency, session-sequence
  lock wait, events per session, and replay latency without requiring speculative
  batching, partitioning, or materialization.
- Compatibility projection matches existing UI behavior.
- Migration tests cover conversation-backed, debug/non-conversation, and concurrent-run paths.
- Redaction fixtures prove secrets and hidden reasoning are absent.
- Performance baseline tests measure event-append latency, session-sequence lock
  contention, and projection lag under realistic workloads to establish benchmarks
  before production deployment.
- W4 is done when all production run paths emit typed events, replay is deterministic
  enough to rebuild state, ambiguous tool calls cannot auto-resume, and no UI
  transcript is treated as the execution source of truth.
