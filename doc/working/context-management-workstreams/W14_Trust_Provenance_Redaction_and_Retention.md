# W14: Trust, Provenance, Redaction, and Retention

## Objective

Make persisted and retrieved context safe for production by enforcing source trust,
provenance, redaction, retention, temporal memory lifecycle, confirmation, and deletion
propagation across all context stores and derived state.

## Metadata Contract

Every context item, event, artifact, checkpoint, and memory carries source, owner,
permissions, trust level, timestamps, expiry/retention class, lifecycle status, and
policy version. Long-term memory additionally includes source event IDs, source type,
confidence, created/confirmed time, validity interval, supersession link, and approval.

Untrusted retrieved content is attributed and placed below authoritative instructions.
Stale, rejected, superseded, expired, and deleted memories are filtered before prompt
injection. Sensitive, tenant-shared, high-impact, or low-confidence writes require
confirmation. Explicit ephemeral and no-write classifications are supported.

## Redaction and Deletion

Redaction occurs before persistence and before logs/traces. Use structured field-aware
redactors for tool arguments and headers plus secret-pattern detection as defense in
depth. Store redaction metadata, never the removed secret. Deletion creates an auditable
tombstone and propagates to events where legally permitted, projections, checkpoints,
artifacts, caches, and long-term memory; derived state becomes invalid immediately.

## Validated Writeback Journal

Lifecycle writeback stages typed append, merge, and set-with-version operations. Before
commit, validate schema, provenance, scope, authority, policy, version, and
non-destructiveness. Commit deterministically or reject with a stable reason code.
Dirty state cannot be discarded at compaction, reset, fork, shutdown, eviction, or
worker handoff before journal resolution.

## Implementation Plan

1. Approve classification, trust, retention, and temporal-memory schemas.
2. Implement shared authorization/provenance and redaction services.
3. Apply redaction before W5 events, W12 artifacts, checkpoints, memory, logs, and traces.
4. Add confirmation/no-write flows to W10 Memory Policy Engine.
5. Add lifecycle filtering, supersession, and conflict metadata to memory retrieval.
6. Implement deletion-propagation orchestrator and proof report.
7. Implement validated writeback journal and retention/expiry jobs.

## Repository Touchpoints

- W5-W12 storage and policy modules
- `sdk/nexent/memory/`
- `sdk/nexent/core/tools/store_memory_tool.py`
- `sdk/nexent/core/tools/search_memory_tool.py`
- `backend/services/memory_config_service.py`
- Conversation deletion, monitoring, and object-storage paths

## Tests and Definition of Done

- Secret fixtures never appear in any persisted event, summary, artifact, memory, or trace.
- Authority/prompt-injection tests keep untrusted retrieval below instructions.
- Temporal tests cover stale, superseded, corrected, rejected, and expired memories.
- Deletion tests prove complete propagation and produce an auditable report.
- Writeback tests reject stale-version, unauthorized, destructive, and invalid operations.
- W14 is done when governance metadata and policy apply end to end, secret tests pass,
  and deletion/retention/writeback behavior is demonstrably complete.

