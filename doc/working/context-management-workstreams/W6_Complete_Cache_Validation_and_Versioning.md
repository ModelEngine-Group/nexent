# W6: Complete Cache Validation and Versioning

## Objective

Prevent stale summaries, Working Memory, and retrieval results from being
reused after any relevant history, model, policy, schema, prompt, restore/reset, or
lifecycle change.

## Validity Contract

W6 owns canonical fingerprints, validation, and invalidation delivery. It does not
create projections or decide policy content; W5, W8, and W11 provide
the versioned inputs that W6 validates.

Replace boundary-only fingerprints in `sdk/nexent/core/agents/agent_context.py` with
metadata-based validation. A derived view or cached projection is valid only when all
metadata inputs match:

- W4 session identity and covered start/end event sequence.
- `partial_after_erasure` flag (one-time mark for physical erasure propagation).
- Context policy and memory policy versions.
- Summary prompt and output schema versions.
- Agent/configuration version and model ID.
- Tokenizer family/version and capacity-calculation version.
- Projection/representation schema versions.
- Relevant redaction, authority, and lifecycle-state versions.
- Event count since last compression snapshot (for W5 materialized projections).

Content hashing (traversing event payloads to compute a digest) is removed from W6.
Storage-layer integrity is handled by database checksums, not by W6. Store validation
components separately so invalidation reasons remain observable. **Finding:** CM-015.

## Invalidation Rules

Any covered event mutation, legal redaction, deletion, restore/reset operation, model
switch, prompt/schema change, authority-policy change, or memory lifecycle update
invalidates affected derived state. New events after the covered end do not invalidate
the covered prefix; they trigger incremental projection. History is normally
immutable, so edits are represented by events and invalidation metadata.

Physical erasure or irreversible redaction additionally sets the owning session replay
status to `partial_after_erasure`. Derived objects located through explicit source IDs
or covered source ranges are invalidated as whole objects; W6 does not attempt
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

## Validation and Invalidation Delivery

- Define one version registry and validation component schema.
- Store validation components separately so operators can explain invalidation.
- Direct read paths must call the centralized validator; bypasses are test failures.
- Deletion/redaction/policy changes publish targeted invalidation work with durable
  retries; lazy validation remains the correctness backstop.
- An authorized W11 deletion tombstone makes matching read candidates immediately
  invalid even while destination-specific physical deletion remains in progress.
- Physical erasure propagates through the one-time `partial_after_erasure` flag on
  `agent_session`; all historical compression snapshots are invalidated without
  per-snapshot hash computation. **Finding:** CM-015.

## Required Deliverables and Phases

- Deliver canonical serializer/hasher, version registry, `DerivedStateValidator`,
  invalidation publisher/worker, explain tool, metrics, and migration for old caches.
- Phase through shadow validation, reject-invalid/read-rebuild behavior, targeted
  invalidation, then deletion of boundary-only validation paths.

## Implementation Plan

1. Define version registry and validation component schema in an ADR.
2. Implement O(1) metadata-based validation:
   - compression.snapshot: `partial_after_erasure` flag + version field comparison
     (policy_version, model_version, projection_version).
   - W5 materialized projections: snapshot validity + event count since snapshot +
     version fields.
   - Physical erasure: one-time `partial_after_erasure` flag that invalidates all
     historical snapshots without per-snapshot hash computation.
3. Extend derived-state records with validation inputs and invalidation reason.
4. Centralize validation in `DerivedStateValidator`; callers cannot bypass it.
5. Add targeted invalidation events/jobs for deletion, redaction, and policy changes.
6. Emit hit, miss, invalid, rebuild, and reason-code metrics.
7. Provide an operator tool to explain why derived state was accepted or rejected.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_cache.py`
- W4 event-log repository
- Policy/version registries from W8 and W11
- Monitoring and lifecycle services

## Tests and Definition of Done

- Mutation tests change each covered event field and every version input.
- Restore/reset and model/prompt switch tests prove invalidation.
- Append-only incremental tests prove valid prefixes remain reusable.
- Deletion/redaction tests invalidate all affected projections and compression snapshots.
- Erasure tests prove range- and explicit-ID lineage locate affected derived objects
  and prevent their reuse after payload deletion.
- Canonicalization tests are stable across processes and supported runtime versions.
- W6 is done when no derived view or cached projection can be used without centralized
  complete validation and every invalidation is observable by stable reason code.
