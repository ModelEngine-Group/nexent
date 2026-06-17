# W7: Full Session Lifecycle APIs

## Objective

Expose durable, authorized, auditable session operations for compact, flush_snapshot,
restore, reset, and context inspection over immutable execution history.

## API Surface

W7 owns authorized lifecycle orchestration and public/backend API behavior. It does not
rewrite W5 history, implement P2 internals, or define compaction algorithms; it
coordinates those services and records their outcomes.

Provide backend APIs and matching SDK methods:

| Operation | Required behavior |
| --- | --- |
| `compact` | Create a governed compacted representation, optionally using focused instructions |
| `flush_snapshot` | Flush in-memory state as a `compression.snapshot` event to W5 |
| `restore` | Append lifecycle events that make a compression.snapshot the new active derived-state baseline without deleting later history |
| `reset_context` | Reset selected derived state without deleting source history |
| `inspect_context` | Return authorized items, representations, budgets, and decision reasons |
| `resolve_ambiguous_effect` | Record an explicit `retry`, `skip`, or `confirm_completed` decision for one blocked tool call |

Add authorized Working Memory inspect/edit and memory-decision inspect operations.
Edits append events; they do not rewrite source history. Every operation is idempotent
when supplied an idempotency key and emits pre/post lifecycle events.

## Behavioral Rules

- Initial lifecycle APIs operate only on W4 single-owner sessions. W7 exposes no
  conversation-sharing, membership-management, or ownership-transfer operation.
- Shared agents, tenant-shared memories, and administrator/operator capabilities do not
  change session ownership. Any separately authorized operator action is explicitly
  audited and scoped to that operation.
- The initial release permits one active run per durable session. `restore`,
  `reset_context`, manual `compact`, Working Memory edits, and other mutating lifecycle
  operations return `operation_conflicts_with_active_run` while a run is active.
- Waiting for or cancelling a run does not make a conflicting operation safe until the
  run reaches a committed terminal/recovery state and clears W5 `active_run_id`.
- If a parent session has pending subagent sessions (subagent sessions linked by
  `parent_session_id` that have not reached a committed terminal state), mutating
  lifecycle operations return `operation_conflicts_with_active_subagent`. This is
  distinct from the active-run check: a parent run may complete its current execution
  step while an async subagent is still running, creating a window where
  `active_run_id` is cleared but subagent results have not yet been written back.
- Read-only `inspect_context` may run concurrently. Runtime-internal compaction executed
  as part of the active run is not a W7 manual lifecycle mutation.
- Restore and reset cannot silently destroy dirty state; a `compression.snapshot` event is appended to W5 first.
- Restore and reset change derived active state through new lifecycle events; they do
  not delete or rewrite later source events.
- A `restore.applied` event records the restored covered `event_seq` and may reference
  a `compression.snapshot` event. Projectors can rebuild the source prefix from W5
  when the compression.snapshot is unavailable, then apply events after the restore
  event; events between the restored boundary and restore event remain auditable but
  inactive.
- Manual compaction instructions are untrusted user input governed by P3/P5.
- Inspect responses redact sensitive payloads and reveal no hidden chain-of-thought.
- Inspect, restore, and resume responses expose session `replay_status`. A
  `partial_after_erasure` session must never be reported as completely replayable.
- Restore/resume may continue from rebuilt remaining state only when projection and
  policy checks establish that it is safe. Otherwise they fail with
  `recovery_unsafe_after_erasure`.
- Lifecycle hooks have deadlines and cannot leave operations half-committed.
- Resume, restore, and reset must not automatically invoke a tool call whose committed
  W5 history has a start event but no terminal result. The session remains blocked
  until an authorized user or operator records `retry`, `skip`, or
  `confirm_completed`. A `retry` response must warn that duplicate external effects are
  possible.
- `retry` permits a new linked tool-call attempt; `skip` continues without invoking the
  unresolved call; `confirm_completed` records the actor's assertion and continues
  without invoking the tool. Every choice is an append-only W5 event.

## API and Operation Contract

Every mutation request contains `conversation_id`, idempotency key, expected lifecycle
or Working Memory version where relevant, and typed operation options. The backend
resolves W4 identity and W5 `agent_session_id`; clients never authorize themselves by
supplying internal IDs.

Responses contain operation ID, lifecycle status, committed W5 event IDs/sequences,
compression.snapshot/version references, and typed warnings. Required errors include
`access_denied`, `session_not_found`, `version_conflict`, `dirty_state_flush_failed`,
`snapshot_invalid`, `operation_in_progress`, `hook_failed`, and `operation_timeout`.
An active-run conflict returns `operation_conflicts_with_active_run`.
Unsupported sharing or ownership-transfer requests return
`shared_conversation_unsupported` or `ownership_transfer_unsupported`; ordinary
non-owner access continues to return non-disclosing `access_denied`/`session_not_found`.
Unresolved tool-effect state returns `ambiguous_effect_resolution_required`.
Erasure-related responses may return `partial_after_erasure` warning status or
`recovery_unsafe_after_erasure`.

## Lifecycle State Machine

Mutations progress through `requested`, `validating`, `flushing`, `applying`,
`committed`, or `failed`. State transitions and pre/post hook outcomes append W5 events.
Retrying an idempotency key returns the existing operation. Inspection is read-only and
may run concurrently. Mutating lifecycle operations are serialized per agent session
and are rejected, not queued or applied, while an active run exists.

## Required Deliverables and Phases

- Deliver API/SDK schemas, lifecycle service/state machine, operation store,
  authorization matrix, hooks, W5/P2 integration, UI/operator controls, and runbooks.
- Phase through inspect/flush_snapshot, resolve_ambiguous_effect, restore/reset,
  Working Memory edits, compact, then frontend controls after contract and
  failure-path stabilization.

## Implementation Plan

1. Define request/response/error schemas and authorization matrix.
2. Add lifecycle service orchestrating W5 events, compression snapshots, and P2 validation.
3. Enforce W5 single-active-run checks for every mutating lifecycle operation.
4. Implement flush_snapshot and inspect first, then resolve_ambiguous_effect, then
   restore/reset, then compact.
5. Add `resolve_ambiguous_effect` with authorization, idempotency, and durable W5 events.
6. Add Working Memory edit operations with optimistic version checks.
7. Add pre/post hooks and typed lifecycle events.
8. Add frontend/operator controls only after API contracts stabilize.
9. Publish SDK examples and operational runbooks.

## Repository Touchpoints

- New session lifecycle service and database modules
- `backend/apps/conversation_management_app.py`
- `backend/services/conversation_management_service.py`
- `backend/agents/agent_run_manager.py`
- New SDK session client methods
- Subagent session query (for debugging and conflict checking)
- Monitoring/operator UI

## Tests and Definition of Done

- Restore reproduces the compression.snapshot's effective active-context view.
- Erasure tests expose `partial_after_erasure`, never reuse invalidated derived state,
  and reject restore/resume when safe reconstruction is impossible.
- Reset preserves immutable events and handles dirty-state writeback.
- Active-run conflict tests prove restore, reset, manual compact, and Working Memory
  mutation are rejected until the active run reaches a committed terminal/recovery state.
- Subagent conflict tests prove mutating lifecycle operations are rejected with
  `operation_conflicts_with_active_subagent` when the parent session has pending
  subagent sessions, even after the parent run's `active_run_id` is cleared.
- Crash-after-tool-start tests prove resume is blocked, no automatic tool invocation
  occurs, and each explicit resolution choice is durable, authorized, and idempotent.
- Authorization, redaction, idempotency, concurrency, and hook-failure tests pass.
- Single-owner tests prove no lifecycle API shares or transfers a session, shared
  resources grant no session access, and audited operator actions leave ownership
  unchanged.
- Inspection explains inclusion, exclusion, reduction, budget, and provenance decisions.
- W7 is done when all lifecycle operations are durable, authorized, replayable,
  observable, and usable through backend API plus SDK.
