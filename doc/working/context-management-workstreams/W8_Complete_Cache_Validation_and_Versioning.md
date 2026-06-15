# W8: Complete Cache Validation and Versioning

## Objective

Prevent stale summaries, Working Memory, retrieval results, and checkpoints from being
reused after any relevant history, model, policy, schema, prompt, restore/reset, or
lifecycle change.

## Validity Contract

W8 owns canonical fingerprints, validation, and invalidation delivery. It does not
create projections/checkpoints or decide policy content; W6, W7, W10, and W14 provide
the versioned inputs that W8 validates.

Replace boundary-only fingerprints in `sdk/nexent/core/agents/agent_context.py` with a
complete canonical fingerprint. A checkpoint is valid only when all inputs match:

- Hash of the complete covered event range using canonical serialization.
- W5 session identity and covered start/end event sequence.
- Context policy and memory policy versions.
- Summary prompt and output schema versions.
- Agent/configuration version and model ID.
- Tokenizer family/version and capacity-calculation version.
- Projection/representation schema versions.
- Relevant redaction, authority, and lifecycle-state versions.

Use an explicit hash algorithm and canonical JSON rules. Store components separately
as well as in one final digest so invalidation reasons remain observable.

## Invalidation Rules

Any covered event mutation, legal redaction, deletion, restore/reset operation, model
switch, prompt/schema change, authority-policy change, or memory lifecycle update
invalidates affected derived state. New events after the covered end do not invalidate
the covered prefix; they trigger incremental projection. History is normally
immutable, so edits are represented by events and invalidation metadata.

Physical erasure or irreversible redaction additionally sets the owning session replay
status to `partial_after_erasure`. Derived objects located through explicit source IDs
or covered source ranges are invalidated as whole objects; W8 does not attempt
field-level removal from summaries or other generated content.

## Validator Contract

```text
validate_derived_state(candidate, current_inputs) -> ValidationResult
```

`ValidationResult` is `valid`, `invalid`, or `error` and includes the compared
fingerprint components plus stable reasons. Required invalid reasons include
`event_content_changed`, `event_range_changed`, `policy_version_changed`,
`model_or_agent_changed`, `prompt_or_schema_changed`, `tokenizer_changed`,
`projection_version_changed`, `lifecycle_changed`, `governance_changed`, and
`source_erased`.
Validation errors never degrade to cache hits.

## Canonicalization and Invalidation Delivery

- Define one canonical JSON/byte serialization, hash algorithm, and registry version.
- Store component digests separately so operators can explain invalidation.
- Direct read paths must call the centralized validator; bypasses are test failures.
- Deletion/redaction/policy changes publish targeted invalidation work with durable
  retries; lazy validation remains the correctness backstop.

## Required Deliverables and Phases

- Deliver canonical serializer/hasher, version registry, `CheckpointValidator`,
  invalidation publisher/worker, explain tool, metrics, and migration for old caches.
- Phase through shadow validation, reject-invalid/read-rebuild behavior, targeted
  invalidation, then deletion of boundary-only validation paths.

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
- Restore/reset and model/prompt switch tests prove invalidation.
- Append-only incremental tests prove valid prefixes remain reusable.
- Deletion/redaction tests invalidate all affected projections and checkpoints.
- Erasure tests prove range- and explicit-ID lineage locate affected derived objects
  and prevent their reuse after payload deletion.
- Canonicalization tests are stable across processes and supported runtime versions.
- W8 is done when no checkpoint or derived cache can be used without centralized
  complete validation and every invalidation is observable by stable reason code.
