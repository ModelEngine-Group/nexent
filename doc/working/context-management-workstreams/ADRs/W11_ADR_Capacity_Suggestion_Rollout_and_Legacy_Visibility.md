# W11 ADR: Capacity Suggestion Rollout and Legacy Visibility

| Field | Value |
| --- | --- |
| Status | Proposed |
| Owners | Model integration squad, Frontend model-management owner, Agent authoring owner |
| Affects | [W11](../W11_Capacity_Suggestion_On_Model_Add.md), [W1](./W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md), [W2](./W2_ADR_Budget_Snapshot_Overrides_and_Dispatch_Enforcement.md) |
| Related findings | CM-031, CM-032 |
| Date | 2026-06-18 |
| Accepted on | Pending |
| Supersedes | None |

## Signoff Status

| Item | Status | Notes |
| --- | --- | --- |
| Decision 1: capacity suggestion flag and user switch | Confirmed | `CAPACITY_SUGGESTION_ENABLED` controls user-facing capacity suggestions. Add/Edit capacity surfaces also expose a user-visible suggestion switch, default on. |
| Decision 2: legacy bare-capacity visibility | Confirmed | Old LLM/VLM rows missing capacity are surfaced by default-on warnings independent of the suggestion flag. |
| Decision 3: no automatic legacy data repair | Confirmed | W11 shows legacy `max_tokens` as evidence and guidance only. It does not infer or write capacity values without an operator save. |
| Decision 4: catalog suggestion save semantics | Pending | Need final signoff on whether accepted catalog suggestions save capacity fields as operator-visible values in addition to canonical provider/model fields. |
| Decision 5: provider discovery phase boundary | Confirmed | Provider discovery is deferred to Version 2. Version 1 ships catalog exact/fuzzy suggestions only. |
| Decision 6: visibility permissions and navigation | Confirmed | Administrators get repair navigation. Ordinary agent authors see only a non-blocking warning and contact-admin copy. |

## Context

W11 exists because the default manual model-add path commonly persists
`model_factory = 'OpenAI-API-Compatible'`, which misses W1's exact
`(provider, model_name)` catalog lookup. This makes approved W1 catalog
capacity unreachable for many manually added LLM/VLM models and leaves
operators without an obvious way to fill the new capacity fields.

W11 now covers two related but separate user experiences:

1. **Capacity suggestions** during Add/Edit flows. These suggestions can come
   from deterministic catalog/provider inference and later from a dedicated
   provider-capacity interface. Suggestions are non-mutating until accepted.
2. **Legacy bare-capacity visibility** for old LLM/VLM rows whose
   `context_window_tokens` or `max_output_tokens` are still null. These rows
   need visible remediation prompts even when capacity suggestion is disabled.

The decisions below separate those two experiences so implementation can start
without accidentally introducing automatic data repair or provider-network
behavior before owners sign off.

## Decision 1: Capacity Suggestion Flag and Add/Edit Switch

**Decision:** `CAPACITY_SUGGESTION_ENABLED` controls only user-facing capacity
suggestions. It does not control legacy bare-capacity warnings.

Every single-model capacity surface must include a user-visible Add/Edit switch:

- Normal single-model Add dialog.
- Normal single-model Edit dialog.
- Per-model configuration opened from batch provider flows.

The global flag and the frontend switch both default to **on**.

### Rationale

Suggestions are safe to enable by default because they do not write data until
the operator accepts or edits the fields and saves. The suggestion UI shows
source and confidence, so operators can reject bad matches. A visible switch
preserves local control for tenants or operators who prefer manual entry.

### Consequences

- `CAPACITY_SUGGESTION_ENABLED=false` is still the global rollback path.
- Turning off the Add/Edit switch suppresses suggestion calls and suggestion
  chips in that dialog.
- Turning off suggestions must not hide bare-capacity warnings.

## Decision 2: Legacy Bare-Capacity Visibility Is Default-On and Separate

**Decision:** LLM/VLM rows where `context_window_tokens IS NULL OR
max_output_tokens IS NULL` are surfaced through default-on warnings independent
of `CAPACITY_SUGGESTION_ENABLED`.

The default-on visibility surfaces are:

- Model Management list badge.
- Agent-edit model selector warning and selected-model notice.
- Operator dashboard capacity-coverage widget.

### Rationale

Legacy bare-capacity rows disable W2 output-token enforcement and the W1 to W2
dispatch consistency check. That risk exists even when capacity suggestions are
disabled, so the visibility path must not be tied to the suggestion feature.

### Consequences

- The visibility path may expose a "fill capacity now" affordance, but it does
  not itself generate or persist capacity values.
- The backend `/capacity-coverage` endpoint remains read-only.
- Embedding, speech-to-text, text-to-speech, and rerank rows stay out of scope
  for this warning because they do not participate in the W1/W2 dispatch path.

## Decision 3: No Automatic Legacy Data Repair

**Decision:** W11 does not automatically repair old rows. It does not infer
capacity from legacy `max_tokens`, does not add `capacity_source =
'legacy_inferred'`, and does not write capacity values from the model loader or
any other runtime path.

For old rows, W11 may show the legacy `max_tokens` value when present and
positive, with guidance that this value may have been entered as the provider's
context window before W1 separated capacity fields. Operators must review the
value and manually save capacity fields.

### Rationale

`max_tokens` had ambiguous historical semantics. Automatically copying it into
`context_window_tokens` would silently reinterpret user data and could create
wrong capacity records. Explicit operator review is slower but preserves
ownership and avoids hidden data mutation.

### Consequences

- No DB migration is required for a new `legacy_inferred` source value.
- Existing `capacity_source` comments and init SQL do not need a new enum-like
  label for W11.
- The UI should show copy similar to: "Legacy max_tokens is `<max_tokens>`. If
  this value is the provider context window, enter it as Context Window and
  save."

## Decision 4: Catalog Suggestion Save Semantics

**Status:** Pending.

### Question

When an operator accepts a catalog exact/fuzzy suggestion, should the save
payload persist only the canonical `model_factory` / `model_name`, or should it
also save the suggested capacity fields as operator-visible values?

### Current Proposed Direction

Save the canonical provider/model fields required for W1 exact lookup. Also
allow saving the visible capacity fields as operator-confirmed values so the row
is understandable in Model Management. At runtime, W1 exact lookup remains the
authority for profile capacity; monitoring should report `capacity_source =
'profile'` only when the saved provider/model actually match the catalog.

### Decision Needed From

Model integration owner and monitoring owner.

## Decision 5: Provider Discovery Phase Boundary

**Status:** Confirmed.

### Question

Should W11 Phase 1/2 include provider discovery, or should they ship catalog
exact/fuzzy suggestions only and wait for the future provider-capacity
interface?

### Decision

Ship Phase 1/2 with catalog exact/fuzzy suggestions only. Defer provider
discovery to Version 2, gated by explicit owner signoff on:

- Supported providers.
- Timeout budget.
- Rate limits.
- Credential handling.
- Logging and tracing redaction.
- Test fixtures proving chat/completions token usage is not treated as hard
  capacity metadata.

### Consequences

- Version 1 must not call provider discovery or upstream provider-capacity
  network paths.
- Version 1 tests focus on catalog exact/fuzzy matching and no-suggestion
  behavior.
- Provider discovery tests, timeout budgets, and credential-handling evidence
  belong to Version 2.

## Decision 6: Visibility Permissions and Navigation

**Status:** Confirmed.

### Question

Who can see each bare-capacity visibility surface, and what navigation should
be available when the current user cannot manage models?

### Decision

- Model Management list badge: visible to users who can view/manage models.
- Dashboard widget: visible only to platform admins or model-management admins.
- Agent-edit selector warning: visible to every user who can select the model.
- Agent-edit remediation link: shown only when the user has model-management
  permission; otherwise show "Ask a model administrator to configure capacity
  for `<model_name>`."
- Dashboard "View all" opens Model Management with a local bare-capacity filter.

### Consequences

- Administrators see actionable navigation to repair capacity.
- Ordinary agent authors see only a non-blocking warning and contact-admin
  guidance.
- Selecting or saving an agent with a bare-capacity model remains allowed.

## Definition of Done for This ADR

This ADR can move to Accepted when:

- [x] Decisions 1-3 are recorded in the W11 English and Chinese specs.
- [ ] Decision 4 is accepted or explicitly deferred with an implementation
  fallback.
- [x] Decision 5 is accepted or provider discovery is explicitly moved out of
  the first W11 implementation slice.
- [x] Decision 6 is accepted with concrete permission and navigation behavior.
- [ ] W11 English and Chinese specs are updated to match accepted Decision 4.

## Implementation Guidance While Pending

Implementation may start on low-risk pieces that do not depend on pending
decisions:

- Pure catalog exact/fuzzy matcher.
- Read-only `POST /api/v1/models/suggest-capacity` route for catalog matches.
- Frontend Add/Edit suggestion switch skeleton.
- Bare-capacity warning, administrator repair navigation, and ordinary
  agent-author contact-admin copy.

Implementation should wait for ADR acceptance before:

- Provider discovery or any upstream provider-capacity network calls.
- Final save semantics that decide catalog vs operator persistence details.
