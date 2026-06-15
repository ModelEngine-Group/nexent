# W8: Complete Cache Validation and Versioning

## Objective

Prevent stale summaries, Working Memory, retrieval results, and checkpoints from being
reused after any relevant history, model, policy, schema, prompt, branch, or lifecycle
change.

## Validity Contract

Replace boundary-only fingerprints in `sdk/nexent/core/agents/agent_context.py` with a
complete canonical fingerprint. A checkpoint is valid only when all inputs match:

- Hash of the complete covered event range using canonical serialization.
- Covered start/end event sequence and branch identity.
- Context policy and memory policy versions.
- Summary prompt and output schema versions.
- Agent/configuration version and model ID.
- Tokenizer family/version and capacity-calculation version.
- Projection/representation schema versions.
- Relevant redaction, authority, and lifecycle-state versions.

Use an explicit hash algorithm and canonical JSON rules. Store components separately
as well as in one final digest so invalidation reasons remain observable.

## Invalidation Rules

Any covered event mutation, legal redaction, deletion, branch operation, model switch,
prompt/schema change, authority-policy change, or memory lifecycle update invalidates
affected derived state. New events after the covered end do not invalidate the covered
prefix; they trigger incremental projection. History is normally immutable, so edits
are represented by events and invalidation metadata.

## Implementation Plan

1. Define canonical serialization and version registry in an ADR.
2. Implement streaming complete-prefix hashing over W5 events.
3. Extend W7 checkpoint records with digest inputs and invalidation reason.
4. Centralize validation in `CheckpointValidator`; callers cannot bypass it.
5. Add targeted invalidation events/jobs for deletion, redaction, and policy changes.
6. Emit hit, miss, invalid, rebuild, and reason-code metrics.
7. Provide an operator tool to explain why a checkpoint was accepted or rejected.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_cache.py`
- W5 event-log and W7 checkpoint repositories
- Policy/version registries from W10 and W14
- Monitoring and lifecycle services

## Tests and Definition of Done

- Mutation tests change each covered event field and every version input.
- Branch and model/prompt switch tests prove invalidation.
- Append-only incremental tests prove valid prefixes remain reusable.
- Deletion/redaction tests invalidate all affected projections and checkpoints.
- Canonicalization tests are stable across processes and supported runtime versions.
- W8 is done when no checkpoint or derived cache can be used without centralized
  complete validation and every invalidation is observable by stable reason code.

