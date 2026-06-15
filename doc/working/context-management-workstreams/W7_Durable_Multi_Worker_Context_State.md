# W7: Durable Multi-Worker Context State

## Objective

Persist versioned context checkpoints so effective context and Working Memory survive
restart, failover, load-balancer routing, and concurrent workers.

## Checkpoint Contract

A checkpoint is a recovery optimization tied to an immutable W5 event boundary, not a
new source of truth. Store:

- Full W4 `ContextIdentity`, session, branch, and covered event sequence.
- Summary text and structured summary payload.
- Working Memory version and structured payload.
- Selected `ContextItem` representation references.
- Token counts and capacity snapshot reference.
- Complete validity fingerprint and policy/model/schema/prompt versions.
- `checkpoint_version`, creation reason, lifecycle status, and retention metadata.

Database storage is authoritative. Redis may cache serialized checkpoints but cannot be
the only copy. A cache miss falls back to the database; a corrupt or invalid checkpoint
falls back to W5/W6 replay.

## Concurrency and Ownership

Writes use compare-and-swap on `(identity, branch, checkpoint_version, event_seq)`.
A writer may commit only if the branch head and expected checkpoint version still
match. Conflicts return a typed result and force reload/reprojection; they never
silently overwrite. Distributed locks may reduce contention but do not replace CAS.

Dirty context state must be staged, validated, and committed before ownership transfer,
shutdown, reset, fork, eviction, or compaction can discard the only in-memory copy.

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
- Crash tests cover each lifecycle boundary and dirty-state flush.
- Redis loss/corruption falls back safely to durable storage or replay.
- Retention jobs never remove active or legally retained checkpoints.
- W7 is done when context state is no longer process-dependent and recovery behavior is
  demonstrated under restart, failover, conflict, cache loss, and partial-write tests.

