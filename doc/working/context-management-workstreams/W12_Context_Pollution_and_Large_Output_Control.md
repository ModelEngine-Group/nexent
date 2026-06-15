# W12: Context Pollution and Large Output Control

## Objective

Keep large tool outputs, logs, files, search results, and delegated exploration out of
the main prompt while preserving reliable, authorized retrieval when details are needed.

## Artifact Contract

W12 owns artifact offload, bounded summaries/pointers, and authorized retrieval. It
does not decide final context selection, retention policy, or secret-handling policy;
W10/W3, W14, and shared redaction services govern those decisions.

Large or binary output is stored as `agent_artifact`; the event log and active context
retain a bounded summary, metadata, content hash, authorization scope, retention policy,
and deterministic artifact pointer. Inline-size and token thresholds are policy-driven.
Artifacts are immutable; updates create new versions.

Pointer resolution must validate W4 identity, authorization, lifecycle status, hash,
and backend availability. Failures emit distinct typed faults: denied, deleted/expired,
not found, hash mismatch, and backend error. Raw secrets are redacted before artifact
storage under W14.

## Runtime Behavior

- Enable safe observation limits by default.
- Preserve complete tool-call/result pairs even when raw results are offloaded.
- Summaries state what was omitted and how to retrieve it.
- Agent retrieval of artifact slices is budgeted and audited.
- Exploratory or high-volume delegated work runs in isolated subagent context and
  returns a bounded result plus artifact references to the parent.
- Duplicate equivalent retrieval/tool calls are detected for W15 measurement.

## Artifact and Retrieval Contracts

```text
offload_output(identity, source_event, content, policy) -> ArtifactReference
resolve_artifact(identity, artifact_reference, slice_request) -> ArtifactSliceResult
```

An artifact record contains immutable ID/version, owner scope, source event, media
type, size, content hash, storage location, bounded summary, retention/lifecycle state,
and redaction metadata. References expose no storage credentials. Required failures
include `artifact_denied`, `artifact_deleted_or_expired`, `artifact_not_found`,
`artifact_hash_mismatch`, `slice_invalid`, and `artifact_backend_error`.

The artifact's bounded summary and references retain queryable source-event lineage.
Physical erasure of a source event or artifact invalidates the associated bounded
summary and pointers as whole derived objects; no deleted payload is retained in proof
metadata.

## Offload Decision and Failure Behavior

- Evaluate byte/token/type thresholds before content enters W5 inline detail or active context.
- Successful offload atomically publishes the artifact reference and source event/outbox.
- Failed offload follows typed per-policy behavior: bounded inline fallback, retryable
  failure, or run failure; raw oversized content is never silently injected.
- Retrieval is range-limited, budgeted, audited, and returns bounded slices.

## Required Deliverables and Phases

- Deliver artifact schema/repository, object-storage adapter, offload decider, bounded
  summarizer, pointer format, retrieval API/tool, lifecycle jobs, and dashboards.
- Phase through shadow threshold measurement, tool-result offload, retrieval/pointers,
  delegated-output isolation, then default-safe observation limits.

## Implementation Plan

1. Define artifact schemas, storage adapter, pointer format, and lifecycle policy.
2. Add artifact offloading at tool-result ingestion before active-context insertion.
3. Implement deterministic bounded summarization and metadata extraction.
4. Add authorized pointer-resolution API/tool with range/slice support.
5. Enable observation limits with per-tool override and explicit truncation metadata.
6. Add isolated subagent-result contract and parent-context boundary.
7. Integrate pointers with W11 representations and W3 fit stages.

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
- Tool-call/result pairs remain complete through offloading and compaction.
- Subagent isolation tests prove parent prompts receive bounded outputs only.
- W12 is done when large output is artifact-first by default, retrieval is reliable and
  governed, and prompt-growth/cost targets meet W15 thresholds.
