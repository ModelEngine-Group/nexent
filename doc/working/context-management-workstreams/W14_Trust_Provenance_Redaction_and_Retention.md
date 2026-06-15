# W14: Trust, Provenance, Redaction, and Retention

## Objective

Make persisted and retrieved context safe for production by enforcing source trust,
provenance, redaction, retention, temporal memory lifecycle, confirmation, and deletion
propagation across all context stores and derived state.

## Metadata Contract

W14 owns governance metadata, classification, redaction, confirmation, retention,
deletion propagation, and validated writeback. It does not decide context relevance or
token fit; W10 and W3 consume W14-governed inputs.

Every context item, event, artifact, compression snapshot, and memory carries source, owner,
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
depth. Store redaction metadata, never the removed secret. Unknown classification or
classification/redaction failure fails closed: raw content cannot enter any governed
durable store, log, trace, artifact, or fallback path. The caller may retry, retain the
content only as ephemeral process-local state, or fail the operation. A sanitized
reason-coded failure record may identify the destination and source reference but never
contain the rejected payload.

Deletion creates an auditable
tombstone and propagates to events where legally permitted, projections, compression snapshots,
artifacts, caches, and long-term memory; derived state becomes invalid immediately.
The W5 runtime role remains append-only. Physical event deletion or redaction uses a
separate privileged governance path that produces an auditable proof record without
granting ordinary event writers update/delete access.

### Erasure-Lineage Contract

Every persisted derived object must expose queryable lineage to its source W5 events:
explicit `source_event_ids` for sparse or selected inputs or a `source_event_range` for
a complete contiguous range. A simple reverse-reference table or indexed range lookup
is sufficient; a global lineage graph and field-level attribution are not required.

For physical erasure or irreversible redaction:

1. Erase or irreversibly redact the governed payload without copying it into proof metadata.
2. Mark the owning session `partial_after_erasure`.
3. Locate every persisted derived object whose lineage includes the erased event.
4. Invalidate each affected summary, compression snapshot, Working Memory version,
   representation, artifact summary/pointer, cache, and long-term memory as a whole.
5. Rebuild from remaining authorized events when safe; otherwise keep the object
   unavailable and reject unsafe restore/resume.

Deletion proof records contain target identity, affected scope, timestamps, actor,
reason code, and per-destination result only. They never retain the erased content.

### Deletion Propagation Contract

After an authorized deletion request creates its tombstone, every governed read,
restore, retrieval, and prompt-injection path must treat the target and located
descendants as unavailable immediately, even while physical deletion is in progress.
The operation reports `in_progress`, not `completed`, until all required destinations
are verified.

W14 coordinates a fixed initial destination registry: W5 event payloads, conversation
projections, compression snapshots, W8 caches/derived state, W12 artifacts/object storage,
long-term memory, and explicitly declared persistent log/search/backup destinations.
For each destination, a simple durable status record progresses from `pending` to
`completed`, or to `failed` and back through idempotent retry. The owning storage
adapter performs and verifies its deletion; W14 aggregates status and proof.

Backup destinations that cannot delete immediately must be inaccessible to normal
restore/read paths and report their expiry/purge deadline. A deletion operation becomes
`completed` only after every required destination is verified. This fixed registry and
retry contract does not require a general workflow/orchestration platform.

## Validated Writeback Journal

Lifecycle writeback stages typed append, merge, and set-with-version operations. Before
commit, validate schema, provenance, scope, authority, policy, version, and
non-destructiveness. Commit deterministically or reject with a stable reason code.
Dirty state cannot be discarded at compaction, reset, restore, shutdown, eviction, or
worker handoff before journal resolution.

## Governance Service Contracts

```text
classify_and_redact(identity, payload, destination, policy_version) -> GovernedPayload
request_deletion(identity, target, reason, idempotency_key) -> DeletionOperation
commit_writeback(expected_version, staged_operations) -> WritebackResult
```

`GovernedPayload` contains sanitized content, classification, provenance, retention,
redaction proof metadata, and policy version. Required failures include
`classification_required`, `redaction_failed`, `write_prohibited`,
`confirmation_required`, `scope_violation`, `stale_version`, and
`deletion_propagation_incomplete`.

## Governed Persistence Boundary

Events, memories, summaries, artifacts, compression snapshots, projections, caches, and other
governed durable state are written only through trusted server-side persistence
interfaces. Each write requires a current W4 authorization decision, applicable W10
policy decision, and W14 `GovernedPayload` with classification, redaction, provenance,
lineage, retention, and policy metadata required for that destination.

SDK/client claims that content is authorized, classified, redacted, or governed are
untrusted. Missing, stale, mismatched, or incomplete governance inputs fail closed
before persistence. This boundary is an interface and permission contract within the
existing storage paths; release one does not require a separate policy-enforcement
microservice, service mesh, or signed capability-token platform.

## Deletion and Writeback State Machines

- Deletion progresses through requested, authorized, tombstoned, propagating,
  invalidating, rebuilding, verified, and completed/failed; every fixed-registry
  destination produces `pending`, `completed`, or retryable `failed` proof status.
- Writeback progresses through staged, validated, committed, or rejected. Partial
  commits are repaired or rolled back according to an ADR; they are never hidden.
- Ordinary runtime roles cannot physically mutate W5 events. Privileged deletion paths
  are separately authorized, audited, and verified.

## Required Deliverables and Phases

- Deliver classification/provenance schemas, redaction service, secret fixtures,
  confirmation flows, fixed-destination deletion coordinator/proof report, writeback
  journal, retention jobs, policy integration, dashboards, and incident runbooks.
- Phase through classify/redact-before-write, confirmation/no-write enforcement,
  lifecycle filtering, deletion propagation, then retention/expiry automation.

## Implementation Plan

1. Approve classification, trust, retention, and temporal-memory schemas.
2. Implement shared authorization/provenance and redaction services.
3. Apply redaction before W5 events, W12 artifacts, compression snapshots, memory, logs, and traces.
4. Add confirmation/no-write flows to W10 Memory Policy Engine.
5. Add lifecycle filtering, supersession, and conflict metadata to memory retrieval.
6. Implement the fixed-destination deletion coordinator, per-destination status,
   idempotent retry, read blocking, and proof report.
7. Add queryable source-lineage lookup and `partial_after_erasure` session state.
8. Implement validated writeback journal and retention/expiry jobs.
9. Restrict governed storage writes to trusted persistence interfaces and remove or
   deny raw/direct write paths.

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
- Fault tests prove tombstoned targets are unavailable immediately, incomplete
  destinations are retried, and `completed` is impossible before every required
  destination verifies deletion.
- Erasure tests locate all persisted descendants by source lineage, invalidate whole
  objects, rebuild only from remaining authorized history, and reject unsafe recovery.
- Writeback tests reject stale-version, unauthorized, destructive, and invalid operations.
- Negative integration tests prove SDK/client and ordinary internal callers cannot
  persist raw or self-declared-governed payloads.
- W14 is done when governance metadata and policy apply end to end, secret tests pass,
  direct raw persistence is denied, and deletion/retention/writeback behavior is
  demonstrably complete.
