# W17: Capacity Suggestion on Model Add

## Objective

Make W1's capability profile catalog reachable from the default frontend
"single model" add flow without requiring operators to understand the
`model_factory` field, the catalog's exact provider keys, or the
`ProviderCapabilityUnknown` fallback path. Most production tenants add LLMs
through the manual form (URL + API key + model name) and currently bypass the
catalog entirely (see W1 ADR Known Limitation KL-1), defeating W1's purpose.

## Current State and Scope

W1 ships eight verified catalog entries in
`backend/consts/capability_profiles.py`. Resolution at request time succeeds
only when `(provider, model_name)` exactly matches a catalog key. The frontend
"single model" add form does not expose `model_factory`, so it ships as the
Pydantic default `'OpenAI-API-Compatible'` and matches no catalog key. The
backend helper `_infer_model_factory` only fires for embedding-type records.

W17 owns the user-facing "suggest defaults at add time" experience. It does
**not** change the resolver, the catalog data model, or the W1 fingerprint
contract; it adds a thin lookup layer between the frontend and the catalog,
plus a UX affordance to accept suggested values.

Out of scope: changing W1's catalog precedence; weakening
`ProviderCapabilityUnknown` semantics; auto-persisting `provider_candidate`
values (still gated through operator acceptance).

## Target Contract

A new endpoint surfaces capacity suggestions; the frontend optionally accepts
them as form placeholders.

```text
POST /api/v1/models/suggest-capacity
```

| Field | Direction | Type | Notes |
| --- | --- | --- | --- |
| `model_name` | in | string | Raw value typed by the operator |
| `base_url` | in | string | Optional; used to infer provider |
| `provider_hint` | in | string | Optional; explicit operator choice |
| `suggestions` | out | object | Suggested capacity values (snake_case) |
| `match_kind` | out | enum | `catalog_exact`, `catalog_fuzzy`, `provider_discovery`, `none` |
| `match_confidence` | out | enum | `high`, `medium`, `low` |
| `match_explanation` | out | string | Human-readable reason ("matched openai/gpt-4o@1 via tokenizer family") |
| `suggested_provider` | out | string | The provider key that would be persisted |

The suggestion object contains the same six capacity fields W1's
`CapabilityProfile` exposes: `context_window_tokens`, `max_input_tokens`,
`max_output_tokens`, `default_output_reserve_tokens`, `tokenizer_family`,
plus a derived `capacity_source` (`profile` for exact, `provider_candidate`
for fuzzy/discovery, omitted for `none`).

The endpoint is **read-only and idempotent**. It never mutates the database
and never bypasses the operator. Accepting a suggestion is an explicit
frontend action that writes through the existing model-management endpoints
with `capacity_source = 'operator'` (the user took responsibility).

## Design

Two layers of matching, evaluated in order:

1. **Catalog fuzzy match.** Normalize the user input (lowercase, strip
   namespace before final `/`, swap `-`/`/`/`.`/`_` boundaries) and the
   catalog keys, then exact-match. The fuzzy logic is bounded — it does not
   attempt semantic matching, only handles the well-known naming variants
   that surface from provider documentation versus user habit (`gpt-4o` vs
   `GPT-4o`, `deepseek-v4-flash` vs `deepseek-ai/DeepSeek-V4-Flash`,
   `glm-5.1` vs `glm5.1`). Match kind: `catalog_exact` (post-normalization
   identical) or `catalog_fuzzy` (one allowed transformation away).
2. **Provider discovery.** If `base_url` host or `provider_hint` maps to a
   supported provider adapter (silicon / dashscope / tokenpony / modelengine),
   call the existing `get_provider_models` flow once and search for a model
   whose ID contains the user-typed `model_name`. Use the
   `_extract_capacity_hints_from_raw` helper from W1 step 3 to surface any
   provider-published capacity. Match kind: `provider_discovery`.

If neither layer matches, return `match_kind: "none"` with no suggestions.
The frontend then shows the existing empty form.

A small inference helper picks `suggested_provider` for the response:

- If `provider_hint` is set, use it.
- Else if `base_url` host matches a known map (`api.openai.com` → `openai`,
  `dashscope.aliyuncs.com` → `dashscope`, etc.), use the mapping.
- Else if a catalog match was found, use that entry's provider.
- Else, return `OpenAI-API-Compatible` and `match_kind: "none"`.

This helper subsumes and replaces the LLM-only gap in
`_infer_model_factory`. Embedding records continue to use the existing
inference path; W17 does not refactor it.

## Runtime Contract

```text
suggest_capacity(model_name, base_url, provider_hint)
  -> SuggestCapacityResult
```

`SuggestCapacityResult` is a Pydantic model with the eight fields listed in
the contract table. The catalog, provider adapters, and host-to-provider map
are injected as parameters (same purity rule as W1 resolver).

Typed failures: `InvalidInput` (empty `model_name` or `model_name` too long),
`ProviderDiscoveryFailed` (HTTP errors during step 2 are caught and degrade
to `match_kind: "none"`; the endpoint still returns 200 with an explanation,
since a missing suggestion is not a request failure).

The endpoint is rate-limited per tenant via existing middleware (provider
discovery makes upstream API calls).

## Database Migration Contract

None. W17 does not introduce schema. It reads catalog + makes optional
upstream HTTP calls.

## Migration, Deliverables, and Phases

- Phase 1: catalog fuzzy match only, no provider discovery. Ship behind a
  feature flag.
- Phase 2: add provider discovery for the four supported adapters.
- Phase 3: extend `_infer_model_factory` to all model types via the same
  host-to-provider map used by suggest-capacity; deprecate the
  embedding-only path.
- Phase 4: remove feature flag once SLO evidence (see Tests) is collected.

## Implementation Plan

### Backend (items 1-3)

1. Add `backend/services/model_capacity_suggestion_service.py` containing
   `suggest_capacity` (pure) and `_normalize_model_name`, `_pick_provider`,
   `_fuzzy_catalog_match` helpers.
2. Add `POST /api/v1/models/suggest-capacity` route in
   `backend/apps/model_managment_app.py`.
3. Add `ModelCapacitySuggestionRequest` and `...Response` Pydantic models in
   `backend/consts/model.py`.

### Frontend service layer (item 4)

4. Add `modelService.suggestCapacity(model_name, base_url, provider_hint)`
   in `frontend/services/modelService.ts` returning a typed
   `SuggestCapacityResponse`. Snake-case body in, camelCase response out
   (mirror existing `mapCapacityFieldsFromApi` style).

### Frontend form state machine (items 5-7)

5. In `ModelCapacityFields.tsx`, add three states per capacity input:
   `empty | suggested | operator`. A `suggested` value renders with a small
   "suggested" chip next to the label and grey/dimmed text styling; user
   typing or clicking "Use suggestion" promotes the field to `operator`
   styling (existing). Reject suggestion writes when state is already
   `operator` to prevent overwriting user input.
6. In `ModelAddDialog.tsx` (and `ModelEditDialog.tsx` for the add-like
   flow if any), debounce 300 ms after `model_name` blur or `base_url`
   change; call `suggestCapacity`. On a non-`none` response, populate the
   fields as `suggested`. On `none`, leave form as-is and **do not** show
   an error — the empty path is the existing behavior.
7. Render `match_explanation` and `match_kind` as a small dismissable
   `Alert` ("Suggestion from openai/gpt-4o@1 catalog entry") above the
   capacity grid. Use existing i18n keys; add `model.dialog.capacity.suggestion.*`.

### Frontend coverage of all model-add paths (item 8)

8. **Apply suggestion logic to all three add paths**:
   - `ModelAddDialog` (single-model flow) — primary target
   - Provider browser flow (when user enables a model from
     `ModelDeleteDialog` provider list) — call suggestion when an
     existing model record is missing capacity values, surface as an
     "Add capacity" prompt
   - `ProviderConfigEditDialog` (per-model gear icon) — show
     "Suggestion available" badge if model_record has null capacity
     fields, click → fill in via the same API

### Error and fallback handling (item 9)

9. Suggestion endpoint failure modes:
   - HTTP 5xx / network error → log to console, **silently fall back** to
     existing empty-form behavior. Never block the add flow.
   - 200 with `match_kind: "none"` → no UI; identical to empty state.
   - 200 with `provider_discovery` match where capacity values are
     `provider_candidate` → render with yellow border (not green) so the
     operator knows it's lower-confidence than catalog matches.

### Localization (item 10)

10. Add locale strings to en/zh:
    - `model.dialog.capacity.suggestion.title`
    - `model.dialog.capacity.suggestion.matchExact`
    - `model.dialog.capacity.suggestion.matchFuzzy`
    - `model.dialog.capacity.suggestion.matchProviderDiscovery`
    - `model.dialog.capacity.suggestion.useSuggestion` (button text)
    - `model.dialog.capacity.suggestion.candidateWarning` (lower-confidence note)

## Repository Touchpoints

Backend:
- `backend/services/model_capacity_suggestion_service.py` (new)
- `backend/apps/model_managment_app.py` (new route)
- `backend/consts/model.py` (request/response Pydantic)
- `backend/services/model_health_service.py` (extend
  `_infer_model_factory` to cover LLM via shared host map)

Frontend — **all three model-management dialogs**, not just Add:
- `frontend/app/[locale]/models/components/model/ModelAddDialog.tsx`
  (primary suggestion flow)
- `frontend/app/[locale]/models/components/model/ModelEditDialog.tsx`
  (suggestion when editing custom OpenAI-API-Compatible model with no
  catalog match)
- `frontend/app/[locale]/models/components/model/ProviderConfigEditDialog`
  (suggestion when editing provider-categorized model via the gear icon —
  same dialog component sourced from `ModelEditDialog.tsx`)
- `frontend/app/[locale]/models/components/model/ModelDeleteDialog.tsx`
  (provider browser flow: when user enables a model from the provider
  list, surface suggestion if backend returns capacity hints)
- `frontend/app/[locale]/models/components/model/ModelCapacityFields.tsx`
  (suggested-placeholder rendering, `suggested` vs `operator` state)
- `frontend/services/modelService.ts` (add `suggestCapacity`)
- Locale files for explanation strings

## Operational Dependencies

W17 requires a coordinated deploy across backend + web containers. There
is no DB migration.

| Component | Action | Trigger |
| --- | --- | --- |
| `nexent-runtime` / `nexent-northbound` / `nexent-config` / `nexent-mcp` | Image rebuild + `compose up --force-recreate` (流程 A in `nexent 代码改动生效流程.md`) | Backend route + service added |
| `nexent-web` | Image rebuild + `compose up --force-recreate` (流程 D) | Frontend dialog + service changes |
| `nexent-postgresql` | No change | No schema migration |
| `consts.const` | Add `CAPACITY_SUGGESTION_ENABLED` env var | New feature flag |
| Tenant config | Optional: per-tenant override `capacity_suggestion_enabled` in `tenant_config_t` to support staged rollout by tenant | Phase 2/3 rollout |
| Monitoring | Add `match_kind` and latency metrics for the new endpoint to dashboards | Phase 2 observation |

**Rollout sequence**: enable env var globally for staging → enable per-tenant
for one internal tenant via `tenant_config_t` → measure 1 week → enable
globally for paid tenants → measure 1 week → enable for all.

**Rollback**: set `CAPACITY_SUGGESTION_ENABLED=false`. Frontend hides
suggestion UI; backend route stops being called. No data migration needed
since W17 never persists provider_candidate values automatically.

## Tests and Release Evidence

- Unit tests for `_normalize_model_name` covering all eight catalog entries
  and the documented variant patterns.
- Unit tests for `_pick_provider` against the host map.
- Integration test: POST /suggest-capacity with `gpt-4o` →
  `catalog_exact`; `Deepseek V4 Flash` →
  `catalog_fuzzy`; `qwen-some-experimental-model` against the dashscope URL
  → `provider_discovery` (mocked).
- Frontend Playwright (or Cypress) flow: add model with
  `https://api.openai.com/v1` + `gpt-4o` → see four fields auto-populate
  with `provider_candidate` badge; click "Use suggestion" → badge flips to
  `operator`; submit; verify monitoring record shows
  `capability_profile_version = 'openai/gpt-4o@1'`,
  `capacity_source = 'operator'`.
- SLO: at least 70% of new manual-add LLM rows during the rollout window
  produce a `match_kind != 'none'` response. (Measured by counting
  `capacity_source = 'operator'` rows with non-null
  `capability_profile_version` versus total new LLM rows.)
- No regression: removing the suggestion endpoint must still leave the
  resolver, monitoring, and existing edit flows working. Verified by
  disabling the feature flag and running the W1 end-to-end test.

## Rollout and Definition of Done

- Ship Phase 1 behind a flag, default off.
- Internal dogfood for one week; verify suggestion accuracy on the eight
  catalog entries.
- Phase 2 (provider discovery) gated on dogfood evidence and rate-limit
  budget approval.
- Phase 3 (extend `_infer_model_factory`) gated on Phase 2 ship + one week
  monitoring.
- W17 done when the dogfood and SLO checks pass for two consecutive weeks
  and the feature flag is removed.

## Why This Is Not W1

W1's ADR was explicitly scoped to the catalog data model and the resolver
contract. The "how does the catalog get populated correctly from real user
behavior" question is a separate layer of the same problem. Moving the fix
into a fresh workstream keeps W1's invariants stable (catalog keys remain
exact; `provider_candidate` is never authoritative) while letting W17
iterate on UX without renegotiating W1's CM-016 boundaries.

See `W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md` "Known
Limitations" section for the gap this workstream addresses.
