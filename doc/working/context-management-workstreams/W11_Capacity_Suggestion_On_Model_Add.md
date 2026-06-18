# W11: Capacity Suggestion on Model Add

## Objective

Make W1's capability profile catalog reachable from the default frontend
"single model" add flow without requiring operators to understand the
`model_factory` field, the catalog's exact provider keys, or the
`ProviderCapabilityUnknown` fallback path. Most production tenants add LLMs
through the manual form (URL + API key + model name) and currently bypass the
catalog entirely (see CM-031 / W1 ADR Known Limitations), defeating W1's purpose.

W11 also uses the existing connectivity-check moment to surface capacity
suggestions. Operators already must click connectivity validation before a model
can be added; that validation should return capacity suggestions when they can
be derived safely, while still treating unknown capacity as a non-blocking
suggestion miss.

## Current State and Scope

W1 ships a small approved day-one catalog in
`backend/consts/capability_profiles.py`. Resolution at request time succeeds
only when `(provider, model_name)` exactly matches a catalog key. The frontend
"single model" add form does not expose `model_factory`, so it ships as the
Pydantic default `'OpenAI-API-Compatible'` and matches no catalog key. The
backend helper `_infer_model_factory` only fires for embedding-type records.

W11 owns the user-facing "suggest defaults at add time" experience and the
connectivity-check integration that triggers it. It does **not** change the W1
resolver, the catalog data model, or the W1 fingerprint contract. The approved
catalog remains the trusted source for high-confidence profile defaults.

Out of scope:

- Replacing the W1 catalog with dynamic provider metadata.
- Weakening `ProviderCapabilityUnknown` semantics.
- Auto-persisting `provider_candidate` values without operator acceptance.
- Batch capacity provisioning from the provider-level `ProviderConfigEditDialog`
  path. Capacity remains per-model; provider-level batch config keeps capacity
  hidden per CM-032.

## User Journey

Persona: an operator adding or editing an LLM/VLM model.

1. The operator opens the single-model add dialog and enters `base_url`,
   `api_key`, and `model_name`.
2. The operator clicks the existing connectivity validation control. The add
   button remains gated by connectivity success exactly as it is today.
3. During the same backend validation request, W11 infers a provider candidate
   from `provider_hint` or `base_url`, then tries capacity suggestion in this
   order:
   - Approved W1 catalog exact/fuzzy match.
   - Version 2 only: provider discovery metadata, when the provider adapter and
     credentials can return model list or raw metadata with capacity hints.
   - No suggestion.
4. If a suggestion is found, the capacity fields populate in `suggested` state
   and an alert explains the source. Nothing is saved yet.
5. The operator can click "Use suggestion" or edit any suggested field. That
   promotes the affected fields to `operator` state.
6. On save, accepted suggestions are written through the existing model
   management endpoint as operator-confirmed configuration. For catalog matches,
   the save payload also writes `model_factory = suggested_provider` and the
   canonical catalog `model_name` when doing so is required for W1 exact lookup.
7. After the first model request, monitoring must show whether runtime capacity
   came from `profile`, `operator`, or fallback. A catalog match should produce
   the expected `capability_profile_version`; a provider-discovery suggestion
   accepted by the operator should produce `capacity_source = 'operator'` and
   no false profile claim.

Values that used to be invisible:

- Operators now see whether a capacity suggestion came from approved catalog
  data, and Version 2 may add lower-confidence provider discovery.
- Operators can correct a wrong suggestion before saving.
- A miss remains non-blocking but is observable through endpoint metrics and
  debug logs; the UI keeps the existing empty capacity form.

Capacity suggestion is controlled by `CAPACITY_SUGGESTION_ENABLED` and by a
frontend Add/Edit switch that is shown in every single-model capacity surface:
the normal Add/Edit dialogs and the per-model configuration path inside batch
provider flows. The switch controls whether W11 shows user-facing capacity
suggestions from deterministic inference and the future provider-capacity
interface. The recommended default is **on** because suggestions are
non-mutating, visibly attributed, and still require explicit operator
acceptance before persistence.

## Visibility for Existing Bare-Capacity Models

W11 also takes on the complementary mission of surfacing **existing**
model rows whose capacity columns are still NULL — the legacy rows
created before W1 step 7 made `context_window_tokens` and
`max_output_tokens` required in the Add/Edit forms. Without W11,
these rows silently disable W2 output-token enforcement and the W1→W2
dispatch consistency check, and the only signal today is a backend
WARNING that the model administrator and agent author never see.

### Problem Statement

The remediation path for a legacy bare-capacity row is identical to
the W11 add-time flow: open the model, fill in capacity, save. What is
missing is a way for the people who can take that action — model
administrators and agent authors — to **discover** which rows need it
without grepping backend logs. Today:

- The model management list page renders bare rows identically to
  configured rows; nothing in the UI says enforcement is off.
- The agent-edit "select model" dropdown ranks bare models the same as
  configured ones; an agent author can unknowingly attach an
  unprotected model to a high-traffic agent.
- The only log message is a backend WARNING aimed at platform
  operators who typically cannot edit per-tenant model records.

**Production evidence (2026-06-17, dev deployment):** a snapshot of
`model_record_t` on the active development cluster showed 7 non-deleted
rows total, of which 6 carried `model_factory = 'OpenAI-API-Compatible'`
— the manual-add default per CM-031. The W2 catalog-backfill migration
matched only one row (`glm-5.1` on `dashscope`), leaving the LLM the
operator was actively chatting with (`glm-5`) bare and silently
running without CM-030 enforcement. This is not an edge case: in the
absence of W11, the default-factory path is the dominant path, and
the bare-row population grows monotonically with normal usage.

### Scope: LLM and VLM Only

This visibility layer is scoped to rows where `model_type IN ('llm',
'vlm')`. Embedding, speech-to-text, and text-to-speech models share
the same `context_window_tokens` / `max_output_tokens` columns but do
not participate in the W1 capacity resolver or the W2 dispatch path,
so a NULL on those rows is not a missed enforcement and must not
surface as a warning. The badge, the agent-edit selector notice, the
dashboard widget, and the `/capacity-coverage` endpoint all apply the
`model_type IN ('llm', 'vlm')` filter at the data layer; downstream UI
treats this as an invariant rather than a runtime check.

### Solution Surfaces (Three UI Touchpoints)

#### 1. Model Management List Page Badge

In the LLM/VLM list view, render a small yellow warning badge next to
any row whose capacity is incomplete. The badge:

- Sits inline with the model name, not at the end of the row, so it
  is visible in narrow viewports and in dense lists.
- Uses the existing icon set (warning triangle); never red, because
  the model is still usable — only enforcement is off.
- Shows a tooltip on hover: "Output token cap is not enforced for
  this model. Click to fill capacity values now." (i18n keys below.)
- Clicking the badge opens the same `ModelEditDialog` that the
  existing pencil/gear control opens, with the capacity panel
  pre-expanded and (if W11 suggestion can match) the suggestion
  prefilled.

The badge and repair affordance are visible to administrators or users with
model-management permission. They are not exposed as a repair link to users who
cannot manage models.

The badge condition is `context_window_tokens IS NULL OR
max_output_tokens IS NULL`, matching the W1 resolver's
`ProviderCapabilityUnknown` gate. Both fields, not just one, because
either NULL produces `ProviderCapabilityUnknown` at request time.

#### 2. Agent-Edit Model Selector Warning

When an agent author opens the model dropdown on the agent-edit
page, items backed by bare-capacity rows render with the same
warning triangle and a one-line subtitle: "Output cap not enforced
— configure capacity in Model Management." Items remain selectable
(degraded behavior is preferable to blocking agent authorship).

If the author selects a bare-capacity model, the agent-edit form
shows a non-blocking inline notice above the save button: "The
selected model has no capacity configured. The agent will run, but
output-token enforcement and budget consistency checks are off
until capacity is set in Model Management." Ordinary agent authors
who lack model-management permission see no repair link; they only
see the non-blocking warning and: "Ask a model administrator to
configure capacity for `<model_name>`." Administrators or users with
model-management permission may see a link to the Model Management
repair entry.

#### 3. Dashboard Widget for Operators

In the system dashboard (the existing operator landing page used by
platform admins), add a small "Model capacity coverage" widget for
platform administrators or model-management administrators showing:

- Number of bare-capacity LLM/VLM rows / total rows.
- A "View all" link that opens Model Management filtered to bare
  rows.

The widget hides itself when the count is zero and is not shown to
ordinary agent authors. No alerting; the widget is observability, not
paging.

### Backend Endpoint Contract

```text
GET /api/v1/models/capacity-coverage
```

Read-only, idempotent. Tenant-scoped by the bearer token's tenant
claim. Returns:

| Field | Direction | Type | Notes |
| --- | --- | --- | --- |
| `total_llm_vlm` | out | integer | Count of non-deleted LLM/VLM rows in tenant |
| `bare_count` | out | integer | Count where `context_window_tokens IS NULL OR max_output_tokens IS NULL` |
| `bare_models` | out | array | Per-row identification |

Each `bare_models[]` entry:

| Field | Type | Notes |
| --- | --- | --- |
| `model_id` | integer | DB primary key |
| `model_name` | string | Raw display value |
| `model_factory` | string | Current value, often `OpenAI-API-Compatible` |
| `model_type` | string | `llm` or `vlm` |
| `suggestion_available` | boolean | Whether `/suggest-capacity` can prefill |

The endpoint is intentionally small. Frontend filters and sorts
locally. There is no pagination — at the row counts this endpoint
targets (typically < 100 per tenant), a simple list is sufficient
and operator filters are local-only.

`suggestion_available` is precomputed by a non-blocking call to the
W11 catalog matcher for each bare row. Provider-discovery suggestion
is **not** attempted from this endpoint (it would require credentials
and network calls scaled by row count); only catalog matching runs.
If the W11 feature flag is off, `suggestion_available` is always
`false` and the field is informational only.

### Frontend Implementation

Bare-capacity visibility is separate from capacity suggestion. It is a
default-on remediation prompt for old rows, not an automatic repair path and
not part of `CAPACITY_SUGGESTION_ENABLED`.

When `CAPACITY_SUGGESTION_ENABLED` is off:

- The list-page badge still renders because the badge depends only on the bare
  condition.
- The agent-edit dropdown warning still renders.
- The dashboard widget still renders.
- The "Click to fill" affordance opens the existing `ModelEditDialog`
  without suggestion prefill; the operator types values from scratch.

When `CAPACITY_SUGGESTION_ENABLED` is on, the same controls may additionally
prefill suggested values from W11's catalog match or later provider-capacity
interfaces. Suggestion UI is also controlled by a visible Add/Edit switch,
default on, across both normal single-model dialogs and per-model configuration
inside batch provider flows.

Files touched (new sub-list, not replacing the existing
Repository Touchpoints section):

- `frontend/app/[locale]/models/components/model/ModelList.tsx`
  (badge column)
- `frontend/app/[locale]/setup/components/agentInfo/AgentGenerateDetail.tsx`
  (selector subtitle and inline notice)
- `frontend/app/[locale]/dashboard/ModelCapacityCoverageWidget.tsx`
  (new)
- `frontend/services/modelService.ts`
  (`getCapacityCoverage()` method)
- `backend/apps/model_managment_app.py`
  (new GET route)
- `backend/services/model_management_service.py`
  (`get_capacity_coverage(tenant_id)` query)

### Localization Strings (Additional to the W11 Set Above)

- `model.list.capacityWarning.badgeTooltip`
- `model.list.capacityWarning.tooltipAction`
- `agent.modelSelector.bareCapacity.subtitle`
- `agent.modelSelector.bareCapacity.formNotice`
- `agent.modelSelector.bareCapacity.formNoticeNoPermission`
- `dashboard.capacityCoverage.title`
- `dashboard.capacityCoverage.subtitle`
- `dashboard.capacityCoverage.viewAll`

### Tests

Unit:

- `get_capacity_coverage` returns correct `bare_count` against a
  fixture with mixed configured/bare rows; `bare_models[]` excludes
  embedding/rerank rows; deleted rows excluded.
- `suggestion_available` is true for rows whose `model_name` and
  `model_factory` would catalog-match (or fuzzy-match) and false
  otherwise.

Integration:

- `GET /api/v1/models/capacity-coverage` with one configured
  `openai/gpt-4o` row and one bare row returns
  `bare_count = 1`, `total_llm_vlm = 2`, and the bare row's
  `model_id` in `bare_models[]`.
- Cross-tenant isolation: a bare row in tenant B does not appear in
  tenant A's response.

Frontend E2E:

- Model Management list page with one bare row: badge is visible
  inline with the model name. Clicking the badge opens
  `ModelEditDialog` with the capacity panel expanded.
- Agent-edit page selects a bare-capacity model: inline notice
  appears above save. Save still succeeds.
- Dashboard widget with `bare_count = 0` is not rendered; with
  `bare_count > 0` it shows the count and the "View all" link works.

### Phase Placement Within W11

This visibility work is **Phase 1.5** (between Phase 1 catalog match
and Phase 2 connectivity integration). It ships independently of the
suggestion-on-add UX because:

- It does not require connectivity validation changes.
- It does not require provider-discovery code.
- It directly addresses the existing-bare-rows problem regardless of
  whether the suggestion flag is on.

If Phase 1 ships in week N, Phase 1.5 should ship in week N+1 as a default-on
visibility feature. It can still be disabled by operators if needed, but it is
not gated by the capacity-suggestion switch because it does not propose or save
capacity values.

### Legacy `max_tokens` Guidance, Not Auto-Repair

When the W1 catalog backfill misses (CM-031: typically
`model_factory = 'OpenAI-API-Compatible'`) and no capacity suggestion is
available, the row stays bare and the dispatch path may run without CM-030
enforcement. W11 does **not** auto-repair these rows and never writes inferred
capacity values to `model_record_t`.

Instead, bare-capacity UI surfaces show the legacy `max_tokens` value when it is
present and positive. The prompt explains that old `max_tokens` values were
often entered as the model's context window before W1 separated capacity fields,
and instructs the operator to review that value and manually fill the
`context_window_tokens` field if it matches the provider documentation. The
operator may also fill `max_output_tokens`, `default_output_reserve_tokens`, and
other capacity fields manually or by accepting an explicit W11 suggestion.

Persistence semantics:

- W11 never mutates a bare row without an operator save action.
- The legacy `max_tokens` value is displayed as evidence only; it is not copied
  into `context_window_tokens` automatically.
- Accepted suggestions and manual edits continue to save through the existing
  model-management endpoints with `capacity_source = 'operator'`.
- Rows that remain incomplete continue to be shown by the default-on
  bare-capacity visibility surfaces.

UI copy:

- Bare-capacity tooltip/details include: "Legacy max_tokens is
  `<max_tokens>`. If this value is the provider context window, enter it as
  Context Window and save."
- If `max_tokens` is missing or non-positive, the UI omits the value and asks
  the operator to consult provider documentation.
- Agent-edit selector warnings stay non-blocking and do not attempt to infer a
  capacity value.

### Out of Scope for This Section

- Auto-fixing bare rows. The fix path is the operator opening the edit dialog,
  reviewing any legacy `max_tokens` evidence or W11 suggestion, and saving.
  Auto-write paths for catalog-matched rows remain governed by the catalog
  backfill SQL migration
  (`docker/sql/v2.2.0_0617_backfill_w2_capacity_from_w1_catalog.sql`), not by
  this UI work.
- Blocking agent save when a bare-capacity model is selected.
  Degraded behavior (warning + non-blocking) is the chosen UX so
  agent authoring is never gated on cross-team coordination.
- Email/Slack alerting from the dashboard widget. The widget is
  informational; integrators may add alerting downstream if desired.
- Surfacing the warning in the chat UI to end users. End users
  cannot edit model capacity; presenting the warning to them would
  create blame routing without recourse.

## Target Contract

Capacity suggestion is exposed two ways:

```text
POST /api/v1/models/suggest-capacity
```

and as an optional capacity-suggestion payload returned by the existing
connectivity validation flow after validation succeeds. The standalone endpoint
is useful for edit flows, provider browser flows, and tests; the add dialog
primarily uses the connectivity-check response to avoid a second visible step.

### Request

| Field | Direction | Type | Notes |
| --- | --- | --- | --- |
| `model_name` | in | string | Raw value typed by the operator |
| `base_url` | in | string | Optional; used to infer provider |
| `provider_hint` | in | string | Optional explicit provider, normally from provider browser or existing model record |
| `api_key` | in | string | Optional; only used by connectivity-check or provider-discovery paths, never logged |
| `model_type` | in | string | Optional; used to restrict suggestion to LLM/VLM paths and provider adapters |

The standalone `/suggest-capacity` endpoint accepts `api_key` only when provider
discovery is enabled. Catalog-only Phase 1 does not require it. The connectivity
check already has credentials in memory and may pass them to the same service
without persisting them.

### Response

| Field | Direction | Type | Notes |
| --- | --- | --- | --- |
| `suggestions` | out | object/null | Suggested capacity values in snake_case |
| `match_kind` | out | enum | `catalog_exact`, `catalog_fuzzy`, `provider_discovery`, `none` |
| `match_confidence` | out | enum | `high`, `medium`, `low` |
| `match_explanation` | out | string | Human-readable reason, e.g. `Matched approved catalog profile openai/gpt-4o@1` |
| `suggested_provider` | out | string/null | Provider key to persist when accepted, e.g. `openai` |
| `canonical_model_name` | out | string/null | Catalog/provider model id to persist when accepted |
| `capability_profile_version` | out | string/null | Present only for catalog matches |
| `capacity_source_on_accept` | out | enum/null | Always `operator` for accepted writes; null when `match_kind = none` |

The suggestion object includes only the model-record capacity fields that W11
can safely prefill:

- `context_window_tokens`
- `max_input_tokens`
- `max_output_tokens`
- `default_output_reserve_tokens`
- `tokenizer_family`

`capability_profile_version` is returned as response metadata for catalog
matches but is not blindly written as an operator value. W1 runtime resolution
must still prove a profile match from the saved `(model_factory, model_name)`.

The endpoint is read-only and idempotent. It never mutates the database and
never bypasses the operator. Accepting a suggestion is an explicit frontend
action that writes through the existing model-management endpoints with
`capacity_source = 'operator'`; the user took responsibility for the saved
capacity values. A catalog exact/fuzzy suggestion can still result in runtime
`capacity_source = 'profile'` after save, but only if the accepted provider and
canonical model name make W1's exact catalog lookup succeed.

## Design

W11 uses three capacity sources in strict trust order.

### 1. Approved Catalog Match

Read `backend/consts/capability_profiles.py` and match the operator input
against the approved W1 catalog.

Normalization:

- Lowercase for comparison only.
- Strip whitespace.
- Treat `-`, `_`, `.`, and `/` boundaries as comparable token separators.
- For namespaced catalog IDs, allow matching either the full provider model ID
  or the final segment when that final segment is unique inside the inferred
  provider's catalog entries.

Allowed examples:

- `gpt-4o` and `GPT-4o`.
- `glm-5.1` and `glm5.1`.
- `Deepseek V4 Flash` and `deepseek-ai/DeepSeek-V4-Flash`.
- `Kimi-K2.6` and `Pro/moonshotai/Kimi-K2.6`, only when unique for the inferred
  provider.

`catalog_exact` means the normalized provider and normalized model name already
identify the same catalog entry without dropping namespace segments.
`catalog_fuzzy` means one of the allowed normalization or unique-final-segment
rules was needed.

Catalog matches return high or medium confidence:

- `catalog_exact`: `high`, green UI treatment.
- `catalog_fuzzy`: `medium`, green UI treatment with a note that the saved
  canonical model name/provider will be used if accepted.

### 2. Provider Discovery During Connectivity Validation (Version 2)

Provider discovery is out of the first W11 implementation version. Version 1
ships catalog exact/fuzzy suggestions only. In Version 2, if the catalog does
not match and `base_url` host or `provider_hint` maps to a supported provider
adapter (`silicon`, `dashscope`, `tokenpony`, `modelengine`), W11 may call a
provider-capacity interface or existing provider discovery flow during
connectivity validation.

Provider discovery is deliberately lower trust than the approved catalog:

- It may use `get_provider_models` or provider-specific raw metadata returned
  by existing provider adapters.
- It may use `_extract_capacity_hints_from_raw` from W1 step 3.
- It may search for an exact provider model ID first, then a contains match
  only when the provider adapter marks the returned ID as unambiguous.
- It never changes W1's catalog or claims `capacity_source = 'profile'`.
- It returns `match_kind = provider_discovery`,
  `match_confidence = low`, and yellow UI treatment.

Plain chat/completions connectivity calls are not expected to reveal model hard
capacity. Token usage from a validation call is not sufficient to infer context
window, input limit, output limit, tokenizer family, reasoning-window behavior,
or provider overhead. Therefore connectivity validation can trigger discovery
metadata, but the single model call result itself is only connectivity evidence.

### 3. Operator Override

If neither catalog nor provider discovery returns a suggestion, the form remains
empty and the existing manual capacity path applies. If the operator accepts or
edits any suggestion, the saved capacity fields use `capacity_source =
'operator'`.

## Provider Inference and Save Rules

A shared helper picks the provider candidate:

- If `provider_hint` is set, use it.
- Else if `base_url` host matches a known map, use the mapped provider:
  - `api.openai.com` -> `openai`
  - hosts containing `dashscope` -> `dashscope`
  - known SiliconFlow hosts -> `silicon`
  - known TokenPony hosts -> `tokenpony`
  - known ModelEngine/open-router hosts -> `modelengine`
- Else if a catalog match is unique without a provider hint, use that entry's
  provider.
- Else return null and `match_kind = none`.

This helper also extends `_infer_model_factory` to LLM/VLM. Embedding records
continue to use the existing embedding behavior, but the host map must be
shared so LLM/VLM and embedding inference cannot drift.

Accepting a suggestion has these persistence rules:

| Match kind | Save `model_factory` | Save `model_name` | Save capacity fields | Runtime expectation |
| --- | --- | --- | --- | --- |
| `catalog_exact` | `suggested_provider` | Existing value if already canonical; otherwise `canonical_model_name` | Optional, as operator-confirmed visible values | W1 exact profile match should produce `capacity_source = profile` |
| `catalog_fuzzy` | `suggested_provider` | `canonical_model_name` unless the operator explicitly keeps the raw name | Yes, `capacity_source = operator` | Profile match only if canonical name is saved |
| `provider_discovery` | `suggested_provider` when known | Provider-returned exact model ID when known; otherwise existing value | Yes, `capacity_source = operator` | Operator-configured capacity, no profile claim |
| `none` | Existing behavior | Existing behavior | Existing manual input only | Existing fallback/override behavior |

If the operator keeps a raw fuzzy name that will not match W1's catalog, the UI
must show a warning: "Runtime will use operator capacity values, not the
approved catalog profile, unless the canonical model ID is saved."

## Runtime Contract

```text
suggest_capacity(
  model_name: str,
  base_url: Optional[str],
  provider_hint: Optional[str],
  model_type: Optional[str],
  api_key: Optional[str],
) -> SuggestCapacityResult
```

`SuggestCapacityResult` is a Pydantic model matching the response table above.
The catalog, provider adapters, host-to-provider map, and feature flags are
injected as parameters, following the same purity rule as W1 resolver.

Typed failures:

- `InvalidInput`: empty `model_name`, model name too long, unsupported
  `model_type`, or malformed URL. The endpoint returns 400 for invalid request
  shape.
- `ProviderDiscoveryFailed`: provider discovery HTTP/auth/timeout errors are
  caught and degrade to `match_kind = none` with an explanation. The endpoint
  still returns 200 because a missing suggestion is not a failed add flow.

Security and privacy:

- `api_key` is never logged, persisted, returned, or included in traces.
- Provider discovery obeys existing tenant authorization and rate-limit
  middleware.
- Connectivity validation may call suggestion logic only after the ordinary
  model-management authorization check succeeds.

## Database Migration Contract

None. W11 does not introduce schema. It reads the approved catalog and may make
optional upstream HTTP calls during provider discovery.

If per-tenant rollout is required, use existing `tenant_config_t` config storage
with key `capacity_suggestion_enabled`. This key defaults to unset, which means
the global env flag decides behavior.

## Migration, Deliverables, and Phases

- Phase 1: catalog exact/fuzzy match only. Ship behind
  `CAPACITY_SUGGESTION_ENABLED=true` by default, with the frontend Add/Edit
  suggestion switch defaulting on.
- Phase 2: integrate catalog suggestion output into connectivity validation
  response. No provider discovery in Version 1.
- Version 2: add provider discovery for supported adapters when credentials are
  available from connectivity validation or an explicit `/suggest-capacity`
  request, after the provider-capacity interface, timeout, rate-limit, and
  credential-handling contracts are accepted.
- Phase 4: extend `_infer_model_factory` to all LLM/VLM paths via the shared
  host-to-provider map; keep embedding behavior compatible.
- Phase 5: remove the feature flag once dogfood and SLO evidence passes.

## Implementation Plan

### Backend

1. Add `backend/services/model_capacity_suggestion_service.py` containing:
   - `suggest_capacity`
   - `_normalize_model_name`
   - `_pick_provider`
   - `_fuzzy_catalog_match`
   - `_suggest_from_provider_discovery`
   - shared host-to-provider map used by both W11 and `_infer_model_factory`
2. Add `POST /api/v1/models/suggest-capacity` route in
   `backend/apps/model_managment_app.py`.
3. Add `ModelCapacitySuggestionRequest`,
   `ModelCapacitySuggestionResponse`, and nested `CapacitySuggestionFields`
   Pydantic models in `backend/consts/model.py`.
4. Extend the existing connectivity validation response to optionally include
   `capacity_suggestion` after a successful validation. Failed suggestion does
   not fail connectivity validation.
5. Extend `backend/services/model_health_service.py::_infer_model_factory` to
   cover LLM/VLM using the shared host map.
6. Update model-save handling so accepting a catalog suggestion can save
   `model_factory = suggested_provider` and `model_name =
   canonical_model_name` when required for W1 catalog lookup.
7. Emit metrics:
   - `model_capacity_suggestion_requests_total{match_kind,model_type,provider}`
   - `model_capacity_suggestion_latency_ms{match_kind,provider}`
   - `model_capacity_suggestion_accept_total{match_kind,provider}`
   - `model_capacity_suggestion_dispatch_profile_hit_total{provider}`

### Frontend Service Layer

8. Add `modelService.suggestCapacity(...)` in
   `frontend/services/modelService.ts` returning a typed
   `SuggestCapacityResponse`. Request body is snake_case; response is mapped to
   camelCase, mirroring `mapCapacityFieldsFromApi`.
9. Extend the connectivity-check service response mapping to include
   `capacitySuggestion`.

### Frontend Form State Machine

10. In `ModelCapacityFields.tsx`, add three states per capacity input:
    `empty | suggested | operator`.
11. A `suggested` value renders with a small source chip near the field label:
    - catalog exact/fuzzy: green
    - provider discovery: yellow
12. User typing or clicking "Use suggestion" promotes affected fields to
    `operator`. Suggestion writes are rejected when a field is already
    `operator`, so user input is not overwritten by a delayed response.
13. The form keeps pending suggestion metadata:
    `matchKind`, `suggestedProvider`, `canonicalModelName`,
    `capabilityProfileVersion`, and `capacitySourceOnAccept`.
14. On save, accepted suggestion metadata is included in the existing save
    payload so backend can persist provider/model canonicalization and capacity
    fields according to the save rules above.
15. The capacity suggestion switch is rendered in every Add/Edit capacity
    surface, including normal single-model dialogs and per-model configuration
    opened from batch provider flows. Turning it off suppresses suggestion
    calls and suggestion chips for that dialog, but does not suppress
    bare-capacity warnings.
16. When no suggestion exists for `context_window_tokens`, render the context
    window control as a preset-capable selector instead of a plain numeric
    input. The selector must allow the operator to either choose a common preset
    or type a custom positive integer. Selecting or typing a value marks the
    field `operator`.
17. When no suggestion exists for `default_output_reserve_tokens`, render the
    output reserve control as a smaller preset-capable selector with the same
    custom positive-integer behavior.

Preset values:

```ts
const MAX_TOKEN_OPTIONS = [
  { value: "4096", label: "4K / 4,096" },
  { value: "8192", label: "8K / 8,192" },
  { value: "16384", label: "16K / 16,384" },
  { value: "32768", label: "32K / 32,768" },
  { value: "65536", label: "64K / 65,536" },
  { value: "131072", label: "128K / 131,072" },
  { value: "204800", label: "200K / 204,800" },
  { value: "262144", label: "256K / 262,144" },
  { value: "1048576", label: "1M / 1,048,576" },
];

const OUTPUT_RESERVE_OPTIONS = [
  { value: "256", label: "256" },
  { value: "512", label: "512" },
  { value: "1024", label: "1K / 1,024" },
  { value: "2048", label: "2K / 2,048" },
  { value: "4096", label: "4K / 4,096" },
  { value: "8192", label: "8K / 8,192" },
  { value: "16384", label: "16K / 16,384" },
];
```

The preset selectors are a fallback UX, not a capacity authority. Values chosen
from them save as `capacity_source = 'operator'`.

### Frontend Add/Edit Paths

18. `ModelAddDialog`: primary flow. Run suggestion after successful
    connectivity validation and also allow the standalone endpoint after
    `model_name` blur or `base_url` change when validation has already passed.
19. `ModelEditDialog`: if an existing custom OpenAI-compatible LLM/VLM has null
    capacity fields or `model_factory = OpenAI-API-Compatible`, show
    "Suggestion available" after validation or explicit check.
20. `ProviderConfigEditDialog` per-model gear path: reuse the same edit logic
    when invoked for one model. Provider-level batch config remains out of scope
    and keeps capacity fields hidden per CM-032.
21. `ModelDeleteDialog` provider browser flow: when enabling a provider model
    whose record is missing capacity values, surface the suggestion as an "Add
    capacity" prompt. Existing provider-sourced `model_factory` values are not
    overwritten unless the operator accepts a suggestion.

### Error and Fallback Handling

22. HTTP 5xx / network error from `/suggest-capacity`: log to console and fall
    back to existing empty-form behavior. Never block add/edit.
23. `match_kind = none`: no suggestion alert is shown. Capacity fields remain
    editable, and the context window / output reserve fields expose the preset
    selectors described above. Emit metric.
24. Provider discovery timeout/auth failure: show no user-facing error unless
    connectivity validation itself failed. Suggestion miss is diagnostic only.
25. Fuzzy catalog canonicalization warning: if the operator declines saving the
    canonical model name, show a warning that runtime will not claim profile
    capacity unless W1 exact lookup succeeds.

### Localization

26. Add locale strings to en/zh:
    - `model.dialog.capacity.suggestion.title`
    - `model.dialog.capacity.suggestion.matchExact`
    - `model.dialog.capacity.suggestion.matchFuzzy`
    - `model.dialog.capacity.suggestion.matchProviderDiscovery`
    - `model.dialog.capacity.suggestion.useSuggestion`
    - `model.dialog.capacity.suggestion.canonicalName`
    - `model.dialog.capacity.suggestion.candidateWarning`
    - `model.dialog.capacity.suggestion.profileMissWarning`
    - `model.dialog.capacity.suggestion.toggle`
    - `model.dialog.capacity.preset.custom`
    - `model.dialog.capacity.preset.contextWindow`
    - `model.dialog.capacity.preset.outputReserve`
    - `model.dialog.capacity.legacyMaxTokensHint`

## Repository Touchpoints

Backend:

- `backend/services/model_capacity_suggestion_service.py` (new)
- `backend/apps/model_managment_app.py` (new route and connectivity response)
- `backend/consts/model.py` (request/response Pydantic models)
- `backend/services/model_health_service.py` (`_infer_model_factory` shared
  host-map extension)
- `backend/services/model_management_service.py` (save accepted provider/model
  canonicalization and capacity fields)
- `backend/services/model_provider_service.py` and
  `backend/services/providers/*` (provider discovery input/metadata contract)

Frontend:

- `frontend/app/[locale]/models/components/model/ModelAddDialog.tsx`
- `frontend/app/[locale]/models/components/model/ModelEditDialog.tsx`
- `frontend/app/[locale]/models/components/model/ProviderConfigEditDialog`
  (per-model gear path only; provider-level batch capacity remains out of scope)
- `frontend/app/[locale]/models/components/model/ModelDeleteDialog.tsx`
- `frontend/app/[locale]/models/components/model/ModelCapacityFields.tsx`
- `frontend/services/modelService.ts`
- `frontend/public/locales/en/common.json`
- `frontend/public/locales/zh/common.json`

Call-site evidence to verify during implementation:

- `_infer_model_factory` is currently defined in
  `backend/services/model_health_service.py` and called from embedding-only
  model creation paths in `backend/services/model_management_service.py`.
- Model add/edit service mapping already has camelCase/snake_case capacity
  helpers in `frontend/services/modelService.ts`.
- Capacity UI is shared through `ModelCapacityFields.tsx`, rendered by add/edit
  and per-model provider config paths.

## Operational Dependencies

W11 requires a coordinated deploy across backend and web containers. There is
no DB migration.

| Component | Action | Trigger |
| --- | --- | --- |
| `nexent-runtime` / `nexent-northbound` / `nexent-config` / `nexent-mcp` | Image rebuild + `compose up --force-recreate` (flow A in `nexent 代码改动生效流程.md`) | Backend route, service, connectivity response, and suggestion changes |
| `nexent-web` | Image rebuild + `compose up --force-recreate` (flow D) | Frontend dialog, service, and i18n changes |
| `nexent-postgresql` | No change | No schema migration |
| `consts.const` | Add `CAPACITY_SUGGESTION_ENABLED`, default `true` | Global feature flag |
| Tenant config | Optional key `capacity_suggestion_enabled`; unset means inherit env flag | Staged tenant rollout |
| Monitoring | Add endpoint and acceptance metrics listed above | Phase 2 observation |

Rollout sequence:

1. Enable env var globally in staging.
2. Enable per-tenant for one internal tenant.
3. Measure one week of catalog exact/fuzzy accuracy and accepted-save profile
   hits.
4. Defer provider discovery to Version 2; enable it only after rate-limit and
   credential-handling evidence is reviewed.
5. Enable for paid tenants.
6. Measure one week.
7. Enable for all tenants and remove the flag only after definition of done
   passes.

Rollback:

- Set `CAPACITY_SUGGESTION_ENABLED=false`.
- Frontend hides suggestion UI and ignores `capacity_suggestion` from
  connectivity validation.
- Backend route returns disabled/no-op or is not called.
- No data migration is needed. Previously accepted operator capacity values
  remain ordinary operator configuration.

## Tests and Release Evidence

### Unit Tests

- `_normalize_model_name` covers all catalog entries and documented variants:
  `GPT-4o`, `glm5.1`, `Deepseek V4 Flash`, `Kimi-K2.6`, and namespaced
  Silicon entries.
- `_pick_provider` covers the host map and verifies unknown hosts return null.
- `_fuzzy_catalog_match` rejects ambiguous final-segment matches.
- Version 2 provider discovery tests verify chat/completions token usage is
  never treated as hard capacity metadata.

### Integration Tests

- `POST /api/v1/models/suggest-capacity` with
  `{"model_name":"gpt-4o","base_url":"https://api.openai.com/v1"}` returns
  `catalog_exact`, `suggested_provider = openai`,
  `canonical_model_name = gpt-4o`, and
  `capability_profile_version = openai/gpt-4o@1`.
- `POST /api/v1/models/suggest-capacity` with
  `{"model_name":"Deepseek V4 Flash","provider_hint":"silicon"}` returns
  `catalog_fuzzy`, canonical model name
  `deepseek-ai/DeepSeek-V4-Flash`, and medium confidence.
- `POST /api/v1/models/suggest-capacity` with
  `{"model_name":"unknown-local-model","base_url":"http://localhost:8000/v1"}`
  returns `match_kind = none` and no suggestions.
- Version 2 provider discovery mocked test: `qwen-some-experimental-model`
  against a DashScope provider response with capacity metadata returns
  `provider_discovery`, low confidence, and no `capability_profile_version`.

### Frontend E2E

- Add model with `https://api.openai.com/v1` + `gpt-4o`; click connectivity
  validation; capacity fields populate with green catalog suggestion; click
  "Use suggestion"; submit; saved row has `model_factory = openai`, model name
  canonical if needed, and operator-confirmed capacity fields.
- Add model with `provider_hint = silicon` + `Deepseek V4 Flash`; accept the
  canonical model name; submit; first runtime request monitoring shows
  `capability_profile_version = silicon/deepseek-v4-flash@1`.
- Add unknown model; click connectivity validation; validation can pass, no
  suggestion alert appears, add flow remains usable with manual capacity input.
- For that unknown model, open the context-window selector, choose
  `128K / 131,072`; open the output-reserve selector, choose `4K / 4,096`;
  submit; saved row has those values and `capacity_source = operator`.
- Disable feature flag; add/edit flows work exactly as before and W1 resolver
  tests still pass.

### Copy-Paste Demo Script

Catalog exact suggestion:

```bash
curl -sS -X POST http://127.0.0.1:5010/api/v1/models/suggest-capacity \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"model_name":"gpt-4o","base_url":"https://api.openai.com/v1","model_type":"llm"}'
```

Expected fields:

```json
{
  "match_kind": "catalog_exact",
  "match_confidence": "high",
  "suggested_provider": "openai",
  "canonical_model_name": "gpt-4o",
  "capability_profile_version": "openai/gpt-4o@1"
}
```

Catalog fuzzy suggestion:

```bash
curl -sS -X POST http://127.0.0.1:5010/api/v1/models/suggest-capacity \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"model_name":"Deepseek V4 Flash","provider_hint":"silicon","model_type":"llm"}'
```

Expected fields:

```json
{
  "match_kind": "catalog_fuzzy",
  "match_confidence": "medium",
  "suggested_provider": "silicon",
  "canonical_model_name": "deepseek-ai/DeepSeek-V4-Flash",
  "capability_profile_version": "silicon/deepseek-v4-flash@1"
}
```

Negative path:

```bash
curl -sS -X POST http://127.0.0.1:5010/api/v1/models/suggest-capacity \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"model_name":"unknown-local-model","base_url":"http://localhost:8000/v1","model_type":"llm"}'
```

Expected fields:

```json
{
  "match_kind": "none",
  "suggestions": null
}
```

Post-save verification SQL:

```sql
SELECT model_id, model_name, model_factory, context_window_tokens,
       max_output_tokens, default_output_reserve_tokens, tokenizer_family,
       capacity_source, capability_profile_version
FROM nexent.model_record_t
WHERE model_name IN ('gpt-4o', 'deepseek-ai/DeepSeek-V4-Flash')
ORDER BY model_id DESC
LIMIT 5;
```

First-dispatch monitoring verification:

```sql
SELECT model_name, model_factory, capability_profile_version, capacity_source,
       context_window_tokens, max_output_tokens, default_output_reserve_tokens
FROM nexent.model_monitoring_record_t
WHERE capability_profile_version IN ('openai/gpt-4o@1', 'silicon/deepseek-v4-flash@1')
ORDER BY created_at DESC
LIMIT 5;
```

## SLO and Definition of Done

SLOs during rollout:

- At least 70% of new manual-add LLM rows for catalog-supported models produce
  `match_kind != none` during connectivity validation.
- At least 95% of accepted catalog suggestions produce the expected runtime
  `capability_profile_version` on first dispatch.
- Version 2 provider discovery suggestion p95 latency stays under the approved
  model-add latency budget and timeout never blocks connectivity validation.
- Suggestion endpoint 5xx rate stays below 1% for enabled tenants.

Definition of done:

- Phase 1 and Phase 2 ship behind `CAPACITY_SUGGESTION_ENABLED`, default on,
  and every Add/Edit capacity surface includes the user-visible suggestion
  switch.
- Internal dogfood verifies exact and fuzzy suggestions for every approved
  catalog entry.
- Provider discovery is out of Version 1 and ships only in Version 2 after
  credential logging, rate-limit, and timeout tests pass.
- `_infer_model_factory` covers LLM/VLM add paths and preserves embedding
  behavior.
- All frontend sibling paths listed above are covered or explicitly out of
  scope in tests.
- Dogfood and SLO checks pass for two consecutive weeks.
- The feature flag is removed only after the rollback plan has been tested.

## Why This Is Not W1

W1's ADR was explicitly scoped to the catalog data model and the resolver
contract. The "how does the catalog get populated correctly from real user
behavior" question is a separate layer of the same problem. Moving the fix into
a fresh workstream keeps W1's invariants stable: catalog keys remain exact,
approved profiles remain reviewed data, and `provider_candidate` is never
authoritative without operator acceptance. W11 improves the operator path into
that contract without replacing the contract.

See `W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md` "Known Limitations"
section for the gap this workstream addresses.
