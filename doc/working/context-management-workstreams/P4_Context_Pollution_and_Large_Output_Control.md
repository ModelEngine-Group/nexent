# P4: Context Pollution and Large Output Control

## Objective

Keep large tool outputs, logs, files, search results, and delegated exploration out of
the main prompt while preserving reliable, authorized retrieval when details are needed.

## Artifact Contract

P4 owns artifact offload, bounded summaries/pointers, and authorized retrieval. It
does not decide final context selection, retention policy, or secret-handling policy;
P3/W10, P5, and shared redaction services govern those decisions.

Large or binary output is stored as `agent_artifact`; the event log and active context
retain a bounded summary, metadata, content hash, authorization scope, retention policy,
and deterministic artifact pointer. Inline-size and token thresholds are policy-driven.
Artifacts are immutable; updates create new versions.

Pointer resolution must validate W4 identity, authorization, lifecycle status, hash,
and backend availability. Failures emit distinct typed faults: denied, deleted/expired,
not found, hash mismatch, and backend error. Raw secrets are redacted before artifact
storage under P5. If classification or redaction fails, raw content is never stored as
an artifact or inline fallback.

## Runtime Behavior

- Enable safe observation limits by default.
- Preserve complete tool-call/result pairs even when raw results are offloaded.
- Summaries state what was omitted and how to retrieve it.
- Agent retrieval of artifact slices is budgeted and audited.
- Delegated work runs as an independent subagent with its own `agent_session`,
  execution event log, and capacity budget. Subagent delegation is implemented as
  a special built-in tool that executes asynchronously and returns a session ID to
  the parent agent. The framework notifies the parent agent when subagent execution
  completes; the parent retrieves the subagent's final answer through a query
  mechanism. Only the subagent's final answer is exposed to the parent agent's
  context; intermediate execution history remains in the subagent's own session. The
  parent agent is free to continue other work or wait during subagent execution.
  Concurrent subagent execution is supported; the parent agent may delegate multiple
  tasks in parallel. P5 governance is not reapplied during subagent-to-parent
  result transfer; P3 policy selection in the parent agent naturally handles
  permission differences. **Finding:** CM-025.
- Duplicate equivalent retrieval/tool calls are detected for W9 measurement.

## Subagent Artifact Isolation

Subagent artifacts are scoped to the subagent's `agent_session`. The parent agent
cannot directly access subagent artifacts; only the subagent's final answer (which
may reference subagent artifacts) is exposed to the parent context. If the parent
agent needs details from a subagent's artifacts, the subagent must include the
relevant information in its final answer or provide artifact pointers that the
parent can resolve through authorized retrieval.

## Artifact and Retrieval Contracts

```text
offload_output(identity, source_event, content, policy) -> ArtifactReference
resolve_artifact(identity, artifact_reference, slice_request) -> ArtifactSliceResult
```

An artifact record contains immutable ID/version, owner scope, source event, media
type, size, content hash, storage location, bounded summary, retention/lifecycle state,
and redaction metadata. References expose no storage credentials. Required failures
include `artifact_denied`, `artifact_deleted_or_expired`, `artifact_not_found`,
`artifact_not_ready`, `artifact_hash_mismatch`, `slice_invalid`,
`artifact_governance_failed`, and `artifact_backend_error`.

The artifact's bounded summary and references retain queryable source-event lineage.
Physical erasure of a source event or artifact invalidates the associated bounded
summary and pointers as whole derived objects; no deleted payload is retained in proof
metadata.

## Offload Publication and Failure Behavior

- Evaluate byte/token/type thresholds before content enters W5 inline detail or active context.
- First obtain a complete P5 `GovernedPayload`. Governance failure permits only a
  sanitized reason-coded failure event, retry, ephemeral process-local handling, or run
  failure; it never permits raw persistence.
- Upload governed bytes with an idempotency key and content hash to a non-readable
  staging object.
- In one relational transaction, create a `pending` artifact record, append the W5
  source/reference event, and create an artifact-finalize outbox row.
- A P4-owned worker idempotently finalizes the immutable object and marks the artifact
  `ready`; only `ready` artifacts are readable.
- Failed finalize leaves an explicit `pending` or `failed` result for retry/repair.
  Orphan and expired staging objects are cleaned by a P4-owned job.
- Failed offload follows typed per-policy behavior: governed bounded inline fallback,
  retryable failure, or run failure; raw oversized content is never silently injected.
- Retrieval is range-limited, budgeted, audited, and returns bounded slices.

The initial artifact lifecycle is `pending -> ready`, `pending -> failed`, and
`ready -> deleted`. This is a path-specific outbox/finalize contract; distributed
transactions, two-phase commit, and a general saga/workflow platform are out of scope.

## Required Deliverables and Phases

- Deliver artifact schema/repository, object-storage adapter, offload decider, bounded
  summarizer, pointer format, retrieval API/tool, lifecycle jobs, and dashboards.
- Phase through shadow threshold measurement, tool-result offload, retrieval/pointers,
  delegated-output isolation, then default-safe observation limits.

## Implementation Plan

1. Define artifact schemas/status, staging/final storage adapter, pointer format, and
   lifecycle policy.
2. Add artifact offloading at tool-result ingestion before active-context insertion.
3. Implement deterministic bounded summarization and metadata extraction.
4. Add artifact-finalize outbox worker, retry/repair status, and staging-orphan cleanup.
5. Add authorized pointer-resolution API/tool with range/slice support.
6. Configure offload thresholds per tool type via agent configuration. Outputs
   exceeding the threshold are stored as artifacts with pointers; the original
   content is preserved for retrieval. This is an offload decision, not a
   truncation — full content remains accessible through the artifact pointer.
   Context space decisions (whether to include full content, pointer only, or
   summary) are made by P3 policy selection and W10 final fit, not by P4.
7. Add isolated subagent-result contract and parent-context boundary.
8. Integrate pointers with W8 representations and W10 fit stages.

## Repository Touchpoints

- W5 event/artifact persistence
- Tool execution and observer paths in `sdk/nexent/core/`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- Managed-agent and external A2A execution paths
- Backend artifact API/service and object storage adapter

## Tests and Definition of Done

- Multi-megabyte outputs have bounded active-context impact.
- Authorized agents retrieve exact offloaded details and slices.
- Pointer denial, expiry, missing backend, and corruption emit distinct faults.
- Publication fault tests prove staging/upload, database commit, finalize, and cleanup
  retries cannot expose a non-ready artifact or lose repair work.
- Governance-failure tests prove raw content is absent from artifacts, events,
  fallbacks, logs, and repair records.
- Tool-call/result pairs remain complete through offloading and compaction.
- Subagent isolation tests prove parent prompts receive bounded outputs only.
- Subagent delegation tests prove delegated work runs as an independent session with
  its own event log.
- Concurrent subagent tests prove multiple subagents can execute in parallel under
  one parent run.
- Final answer isolation tests prove only the subagent's final answer enters the
  parent context.
- Recursive delegation tests prove subagents cannot delegate further tasks.
- Performance baseline tests measure artifact offload latency at tool-result ingestion
  and artifact retrieval latency during context assembly (lower priority, after
  functional implementation is stable).
- P4 is done when large output is artifact-first by default, retrieval is reliable and
  governed, and prompt-growth/cost targets meet W9 thresholds.

## Codebase Gap Analysis (2026-06-17)

**Verdict: Real pollution gaps exist; artifact system deferred, quick fixes justified.**

### Current safeguards
- smolagents `truncate_content()`: 20K char head+tail truncation for code execution output
- ContextManager pre-truncation: `max_observation_length` (exists but **defaults to 0 = disabled**)
- Component token budgets: 7 types with individual limits
- Compression: 3-level fallback (L1 full → L2 trimmed → L3 hard truncation)

### Uncontrolled pollution sources
- **`terminal_tool.py`**: ZERO output size limits — `cat` of large file returns unbounded output
- **`read_file_tool.py`**: warns at 10MB but returns entire file content
- **`max_observation_length` defaults to 0**: pre-truncation layer exists but is disabled
- **No artifact offload mechanism**: cannot store large results externally
- **Subagent output not budget-capped**: subagent can return up to 20K chars consuming parent context

### Quick fixes (do now)
1. Set `max_observation_length` default to 4000-8000 chars
2. Add output size caps to `terminal_tool.py` and `read_file_tool.py`
3. Add configurable budget cap on subagent return strings

### Why artifact system is deferred
Full artifact offload requires W5 event log (for artifact records) and P5 governance (for redaction before storage). No customer-reported large-output incidents yet.
