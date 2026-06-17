# W1: Correct Model Token-Capacity Configuration

## Objective

Replace the ambiguous `max_tokens` contract with explicit model capacity fields and
a single resolver that supplies trustworthy capacity data to every model request.
This is a blocker for correct compression, output reservation, and final-fit checks.

## Current State and Scope

`backend/database/db_models.py` describes `ModelRecord.max_tokens` as total available
tokens, while `sdk/nexent/core/agents/agent_model.py` and
`sdk/nexent/core/models/openai_llm.py` use it as the completion output cap.
`backend/agents/create_agent_info.py` also uses the database value as a context
threshold. W1 fixes chat/LLM capacity semantics across database, backend APIs,
provider discovery, SDK configuration, frontend model forms, and monitoring.
Embedding-model dimensions that currently reuse `max_tokens` are out of scope and
must retain their behavior until separately migrated.

## Target Contract

Add these optional fields to the model record and SDK `ModelConfig`:

| Field | Database / SDK type | Contract |
| --- | --- | --- |
| `context_window_tokens` | nullable positive integer | Combined input/output window, when applicable |
| `max_input_tokens` | nullable positive integer | Provider hard input limit when distinct |
| `max_output_tokens` | nullable positive integer | Provider-supported or operator-configured output cap |
| `default_output_reserve_tokens` | nullable positive integer | Default output allowance reserved per request |
| `tokenizer_family` | nullable string, maximum 100 characters | Tokenizer/counting adapter identifier |
| `capacity_source` | nullable enum/string: `operator`, `profile`, `provider_candidate`, `legacy`, `unknown` | Source of the persisted or resolved capacity value |
| `capability_profile_version` | nullable string, maximum 100 characters | Version of the approved provider/model capability profile used by the request |

Keep `max_tokens` as a deprecated API/database alias for `max_output_tokens` during
migration. It must never feed `ContextManagerConfig.token_threshold`.

## Design

Create a `ModelCapacityResolver` in the SDK model layer backed by a small versioned
capability profile for each formally supported provider/model or deployment ID. The
profile contains only capabilities required by W1-W10 and W3: hard capacity fields,
token-counter mode/tokenizer family, reasoning-window behavior, provider-overhead
behavior, prompt-cache mode, and cache-metric availability.

Resolution precedence is approved operator override, approved versioned capability
profile, provider discovery as unverified candidate metadata, then unknown. Provider
discovery never changes production behavior until it is approved into a profile
version. Every request records the selected profile version and field sources.

Reject impossible values: non-positive capacities, output cap larger than a combined
window, input limit larger than the combined window without an explicit provider
exception, or reserve larger than available capacity. Unknown hard capacity is not
allowed for production dispatch and returns `provider_capability_unknown`. When hard
capacity is known but any required tokenizer, reasoning, or provider-overhead behavior
is unknown, W2 applies the approved unified uncertainty reserve.

This initial profile is configuration, not a general provider capability discovery
platform. It covers only supported production models and does not automatically scrape,
probe, or trust all provider/model capabilities.

Nexent continues to allow users to configure models that are not in the platform-
maintained profile catalog. The catalog is a source of approved defaults, not a model
allowlist. For an uncataloged model, authorized model configuration supplies the hard
capacity fields. Production dispatch is allowed when those fields resolve to a valid
known hard capacity; otherwise it fails with `provider_capability_unknown`. Incomplete
tokenizer, reasoning-window, or provider-overhead behavior uses W2's uncertainty rule.

## Runtime Contract

```text
resolve_capacity(model_id, provider, operator_overrides, requested_output_tokens)
  -> ModelCapacitySnapshot
```

`ModelCapacitySnapshot` is an immutable/frozen SDK model containing:

| Field | Type / rule |
| --- | --- |
| `model_record_id` | nullable integer |
| `provider`, `model_name` | required strings identifying the selected deployment |
| `context_window_tokens`, `max_input_tokens`, `max_output_tokens`, `default_output_reserve_tokens` | nullable positive integers |
| `requested_output_tokens` | required positive integer resolved for this request |
| `provider_input_limit_tokens` | required positive derived hard input limit |
| `tokenizer_family` | nullable string |
| `counting_mode` | `exact` or `estimated` |
| `unknown_capabilities` | bounded list of capability reason codes |
| `field_sources` | bounded map from capacity field to source enum |
| `capability_profile_version`, `resolver_version` | nullable/required strings respectively |
| `warnings` | bounded list of stable reason codes |
| `fingerprint` | required deterministic string over the resolved contract |

The snapshot is passed unchanged to W2, W10, W3, monitoring, and provider dispatch.
Typed failures include `invalid_capacity_configuration`,
`provider_capability_unknown`, `uncertainty_reserve_basis_unknown`,
`requested_output_exceeds_cap`, and `provider_metadata_invalid`.

## Database Migration Contract

Follow the repository's existing SQL migration convention:

- Add the nullable capacity columns and comments to both fresh-install schemas:
  `docker/init.sql` and `k8s/helm/nexent/charts/nexent-common/files/init.sql`.
- Add one version-prefixed, idempotent upgrade SQL file under `docker/sql/` using
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and column comments.
- Do not overload the new chat/LLM capacity columns for embedding dimensions.
- Keep existing rows valid with null new fields; backfill approved known models
  separately, and resolve legacy `max_tokens` only as the temporary output-cap alias.
- Rollback may restore legacy readers, but must not reinterpret `max_tokens` as context
  capacity.

## Migration, Deliverables, and Phases

- Additive fields ship before readers change; chat `max_tokens` is only a temporary
  output-cap alias, while embedding dimensions retain current behavior until separately migrated.
- Deliver the ADR, migrations, API/SDK models, resolver, small approved capability-
  profile catalog, provider adapters, tokenizer registry, frontend fields, backfill
  report, and telemetry dashboard.
- Phase through shadow resolution, known-model backfill, consumer cutover,
  invalid-config enforcement, then removal of legacy chat-model writes.
- Rollback may restore legacy reads but must never restore `max_tokens` as context capacity.

## Implementation Plan

1. Add an ADR defining field semantics, capability-profile precedence, unknown behavior,
   and migration.
2. Add nullable database columns and update model-management CRUD/service schemas.
3. Update provider discovery adapters to return explicit capacity metadata.
4. Extend SDK `ModelConfig`; rename internal LLM output-cap use to `max_output_tokens`.
5. Add `ModelCapacityResolver` and a tokenizer adapter registry.
6. Stop assigning legacy `max_tokens` to context thresholds in `create_agent_info.py`.
7. Update frontend add/edit forms and labels; show capacity source and warnings.
8. Add monitoring fields for the resolved snapshot on every request.

## W1 to W2/W10 Handoff

- W1 creates exactly one immutable `ModelCapacitySnapshot` for a model request after
  resolving the selected model and requested output.
- W2 consumes that snapshot and returns a budget snapshot that records the W1
  fingerprint; W2 never mutates or independently re-resolves capacity.
- W10 consumes both snapshots and rejects a missing or mismatched W1 fingerprint before
  fit/serialization or dispatch.
- Provider dispatch verifies the selected provider/model, requested output, and W1
  fingerprint still match the final request.

## Repository Touchpoints

- `backend/database/db_models.py`
- `backend/database/model_management_db.py`
- `backend/services/model_management_service.py`
- `backend/services/model_provider_service.py`
- `backend/agents/create_agent_info.py`
- `backend/apps/model_managment_app.py`
- `frontend/app/[locale]/models/`
- `frontend/types/modelConfig.ts`
- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/models/openai_llm.py`
- `sdk/nexent/core/utils/token_estimation.py`

## Tests and Release Evidence

- Unit-test precedence and validation for combined-window and separate-input providers.
- Keep stable fixture cases for a combined-window model, a separate-input-limit model,
  an uncataloged operator-configured model, unknown hard capacity, and incomplete
  required behavior.
- Test that unverified provider discovery cannot silently change production profiles
  and unknown hard capacity blocks production dispatch.
- Migration-test legacy records, null fields, overrides, and rollback compatibility.
- Contract-test backend, frontend, and SDK serialization.
- Assert no runtime context threshold is sourced from legacy `max_tokens`.
- Dashboard evidence must show total window, hard input limit, output cap, reserve,
  tokenizer family, capability-profile version/source, unknown-capability rate, and
  provider context-length errors.

## Rollout and Definition of Done

Deploy additive columns first, dual-read legacy records, backfill catalog-known
models, then switch reads to the resolver. Remove legacy writes only after all clients
have migrated. W1 is done when every chat model request has a validated capacity
snapshot and repository search finds no use of legacy `max_tokens` as context capacity.
