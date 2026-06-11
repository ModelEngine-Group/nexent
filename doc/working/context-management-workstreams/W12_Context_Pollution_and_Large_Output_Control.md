# W12: Context Pollution and Large Output Control

## Objective

Keep large tool outputs, logs, files, search results, and delegated exploration out of
the main prompt while preserving reliable, authorized retrieval when details are needed.

## Artifact Contract

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

