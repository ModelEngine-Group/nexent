# W7: Durable Multi-Worker Context State

## Objective

Persist versioned context checkpoints so effective context and Working Memory survive
restart, failover, and load-balancer routing. Multiple workers may process different
sessions, but the initial release does not permit concurrent active runs or lifecycle
mutation within one durable session.

## Checkpoint Contract

W7 owns durable recovery snapshots, concurrency, and checkpoint loading/commit. It does
not replace W5 source history, define W6 projections, or decide W8 validity rules.

A checkpoint is a recovery optimization tied to an immutable W5 event boundary, not a
new source of truth. Store:

- Full W4 `ContextIdentity`, W5 `agent_session_id`, and covered event sequence.
- Queryable source event range and any explicitly selected source event IDs used by
  checkpointed derived state.
- Summary text and structured summary payload.
- Working Memory version and structured payload.
- Selected `ContextItem` representation references.
- Token counts and capacity snapshot reference.
- Complete validity fingerprint and policy/model/schema/prompt versions.
- `checkpoint_version`, creation reason, lifecycle status, and retention metadata.

Database storage is authoritative. Redis may cache serialized checkpoints but cannot be
the only copy. A cache miss falls back to the database; a corrupt or invalid checkpoint
falls back to W5/W6 replay.

### Checkpoint Publication Contract

The committed W7 database checkpoint is the authoritative checkpoint record and may be
loaded after W8 validation without waiting for a W5 checkpoint lifecycle event. Any W5
`checkpoint.created` or related lifecycle event is audit/observability publication; it
does not make the checkpoint valid and is never a recovery prerequisite.

When such a lifecycle event is required, the checkpoint commit creates a W7-owned
publication-outbox row in the same database transaction. The outbox uses
`(checkpoint_id, lifecycle_event_type)` as its idempotency key and retries W5
publication independently. It records pending, completed, or failed-with-retry state
plus bounded error metadata and attempt timestamps. A missing or delayed lifecycle
event is visible and repairable but does not invalidate a committed checkpoint. W7
owns retry and operator repair for this path.

This contract does not make Checkpoint a W5 source event, require atomic commit across
W7 and W5 services, or introduce a general saga/workflow platform.

## Concurrency and Ownership

Writes use compare-and-swap on `(identity, checkpoint_version, event_seq)`. A writer
may commit only if the session event head and expected checkpoint version still match.
Conflicts return a typed result and force reload/reprojection; they never silently
overwrite. Distributed locks may reduce contention but do not replace CAS.

For the initial release, W5's single-active-run contract is the ownership guardrail.
Restore, reset, manual compact, and other conflicting W9 lifecycle mutations are
rejected while an active run exists. They may proceed only after the run reaches a
committed terminal/recovery state. Checkpoint CAS remains required, but distributed
fencing tokens are explicitly out of scope until concurrent same-session lifecycle
mutation is approved.

Dirty context state must be staged, validated, and committed before worker handoff,
shutdown, reset, restore, eviction, or compaction can discard the only in-memory copy.
Conversation/session ownership transfer is outside the initial release.

## Checkpoint Schema and Service Contract

```text
load_latest(identity, agent_session_id) -> CheckpointLoadResult
commit_checkpoint(expected_version, expected_event_seq, checkpoint_payload)
  -> CheckpointCommitResult
```

The durable record includes `checkpoint_id`, `agent_session_id`, covered `event_seq`,
`checkpoint_version`, W6 projection/Working Memory payloads, representation references,
W8 fingerprint components, policy/model/schema versions, lifecycle status, retention,
and timestamps. Required outcomes include `committed`, `conflict`, `invalid`,
`not_found`, and `storage_error`; conflicts never auto-overwrite.

## Recovery and Failure Behavior

- Load validates through W8 before exposing state; invalid/missing checkpoints replay W5/W6.
- A checkpoint affected by physical erasure is invalidated as a whole. Recovery may
  rebuild from remaining events, but the result remains `partial_after_erasure`; if
  safe reconstruction is impossible, recovery fails explicitly.
- Redis loss, stale cache, partial cache writes, and worker death never lose durable state.
- Checkpoint recovery never treats an in-flight tool call as completed or automatically
  reinvokes it. W6/W5 unresolved `ambiguous_effect` state blocks continuation until W9
  records an explicit resolution.
- Checkpoint commit and its required W7 publication-outbox row are atomic. W5
  checkpoint lifecycle events publish asynchronously and idempotently; missing or
  delayed audit publication is visible and repairable but never blocks checkpoint
  recovery.
- Dirty-state flush failure blocks destructive lifecycle actions and returns a typed fault.
## Required Deliverables and Phases

- Deliver migrations, repository/service, serializer, CAS logic, W8 integration,
  optional Redis adapter, retention jobs, repair tooling, and recovery dashboards.
- Phase through durable DB writes, read/replay integration, multi-worker CAS
  enforcement, Redis acceleration, then retention/archival automation.

## Implementation Plan

1. Add checkpoint schema, repository, composite indexes, and retention fields.
2. Implement serializer with explicit schema versions and size limits.
3. Add CAS create/update and typed conflict handling.
4. Load checkpoints during run creation; validate through W8 before use.
5. Flush at configured event boundaries and every destructive lifecycle boundary.
6. Add optional Redis read-through/write-through cache.
7. Add archival/TTL jobs and recovery fallback to event replay.

## Repository Touchpoints

- New checkpoint database/repository/service modules
- `backend/agents/agent_run_manager.py`
- `backend/agents/create_agent_info.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_cache.py`
- Runtime shutdown, cancellation, and worker-handoff paths

## Tests and Definition of Done

- Restart and cross-worker resume produce the same effective context.
- Concurrent writers prove stale versions cannot overwrite newer checkpoints.
- Active-run tests prove restore/reset/manual compact cannot proceed while a session
  run is active and can proceed after its committed terminal/recovery state.
- Crash tests cover each lifecycle boundary and dirty-state flush.
- Worker-death tests during a tool call prove checkpoint recovery surfaces
  `ambiguous_effect` and performs no automatic reinvocation.
- Redis loss/corruption falls back safely to durable storage or replay.
- Checkpoint-publication crash tests prove a committed, W8-valid checkpoint remains
  loadable while its W5 lifecycle event is pending, and W7 retry/operator repair
  publishes that event idempotently.
- Retention jobs never remove active or legally retained checkpoints.
- Erasure tests locate checkpoints by source lineage, invalidate them as whole objects,
  and reject recovery when remaining history is insufficient.
- W7 is done when context state is no longer process-dependent and recovery behavior is
  demonstrated under restart, failover, conflict, cache loss, and partial-write tests.
