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

| Field | Contract |
| --- | --- |
| `context_window_tokens` | Combined input/output window, when applicable |
| `max_input_tokens` | Provider hard input limit when distinct |
| `max_output_tokens` | Provider-supported or operator-configured output cap |
| `default_output_reserve_tokens` | Default output allowance reserved per request |
| `tokenizer_family` | Tokenizer/counting adapter identifier |
| `capacity_source` | `provider`, `operator`, `catalog`, or `fallback` |

Keep `max_tokens` as a deprecated API/database alias for `max_output_tokens` during
migration. It must never feed `ContextManagerConfig.token_threshold`.

## Design

Create a `ModelCapacityResolver` in the SDK model layer. Input is model identity,
provider metadata, operator overrides, and requested output tokens. Output is an
immutable capacity snapshot containing resolved values, source metadata, warnings,
and a configuration version. Resolution precedence is operator override, trusted
provider discovery, versioned catalog, then conservative fallback.

Reject impossible values: non-positive capacities, output cap larger than a combined
window, input limit larger than the combined window without an explicit provider
exception, or reserve larger than available capacity. Unknown capacity is allowed
only through a conservative fallback with a warning metric.

## Implementation Plan

1. Add an ADR defining field semantics, precedence, fallback behavior, and migration.
2. Add nullable database columns and update model-management CRUD/service schemas.
3. Update provider discovery adapters to return explicit capacity metadata.
4. Extend SDK `ModelConfig`; rename internal LLM output-cap use to `max_output_tokens`.
5. Add `ModelCapacityResolver` and a tokenizer adapter registry.
6. Stop assigning legacy `max_tokens` to context thresholds in `create_agent_info.py`.
7. Update frontend add/edit forms and labels; show capacity source and warnings.
8. Add monitoring fields for the resolved snapshot on every request.

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
- Migration-test legacy records, null fields, overrides, and rollback compatibility.
- Contract-test backend, frontend, and SDK serialization.
- Assert no runtime context threshold is sourced from legacy `max_tokens`.
- Dashboard evidence must show total window, hard input limit, output cap, reserve,
  tokenizer family, capacity source, and fallback-warning rate.

## Rollout and Definition of Done

Deploy additive columns first, dual-read legacy records, backfill catalog-known
models, then switch reads to the resolver. Remove legacy writes only after all clients
have migrated. W1 is done when every chat model request has a validated capacity
snapshot and repository search finds no use of legacy `max_tokens` as context capacity.

