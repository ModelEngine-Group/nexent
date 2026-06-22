# Workstream Spec Review Checklist

> Items 1-6 derived from the W1 post-acceptance retrospective (2026-06-16).
> Items 7-10 added after the W1/W2 follow-up retrospective (2026-06-22) —
> end-to-end testing of the W2 PR plus six weeks of cleanup surfaced four
> additional bug categories, most damaging being a layer-interaction bug
> that silently dropped operator capacity edits and soft-deleted the user's
> freshly-added catalog rows. Apply this checklist to every new workstream
> spec **before** it is marked Accepted. Apply again to every existing spec
> **before** implementation begins. Each item has concrete sub-questions;
> "OK" requires an affirmative answer to **all** sub-questions, not just
> the main one.

## How to Use

1. Copy this file into a per-workstream review (e.g. `W2_REVIEW.md`).
2. For each of the six items, fill in answers in plain text.
3. Mark an item ❌ if any sub-question is unanswered or unclear.
4. The spec is not Ready to Implement until every item is ✅ or has an
   explicit "deferred to follow-up workstream W_NN" with the follow-up open.

## The Six Items

### 1. User Journey Section

**Main question:** Does the spec describe how a real operator or developer
encounters this workstream's behavior, end to end?

Sub-questions:
- [ ] Who is the user persona affected? (operator, end-user, integrator, oncall)
- [ ] What does the user see / type / click as a direct consequence of this workstream?
- [ ] What does the user **not** see that they used to see, or now sees differently?
- [ ] If a value moves from "operator-typed" to "system-derived", who knows the
      derivation rule and how do they correct it when wrong?

> **W1 lesson**: ADR Decision 1 modeled the catalog data, runtime contract,
> and fingerprint. But never modeled "how does the operator get capacity
> values into a `model_record_t` row" — and the default `model_factory =
> 'OpenAI-API-Compatible'` made every standard add path silently miss the
> catalog. Spec passed evaluation; users couldn't actually reach the feature.

### 2. Frontend Step Decomposition

**Main question:** If the workstream has a frontend impact, is it broken
into ≥ 3 concrete sub-items covering distinct concerns?

Sub-questions:
- [ ] **State**: is the new form state machine described? (initial value,
      transitions, required vs optional fields)
- [ ] **Visual**: which existing UI element is replaced/removed/added?
      What does the layout look like (sketch / row arrangement)?
- [ ] **Service layer**: which `*.service.ts` / API call sites need new
      camelCase ↔ snake_case mapping?
- [ ] **Validation**: client-side validation rules (which fields required,
      which combinations rejected, error message keys)
- [ ] **Migration of existing data**: when an existing row has legacy field
      X but no new field Y, what happens on edit-load? on save?
- [ ] **Sibling components**: which other dialogs / pages share state or
      semantic with the changed one and must be updated in lockstep?

> **W1 lesson**: W1 spec step 7 said "Update frontend add/edit forms and
> labels; show capacity source and warnings". One sentence → 8 distinct
> bugs (B1–B8 in the retrospective) because each of the 6 sub-concerns
> above had no answer in the spec.

### 3. End-to-End Demo Script in Acceptance

**Main question:** Does the acceptance section include a concrete,
copy-pasteable demo script that a human can execute against a live
deployment to prove the workstream works?

Sub-questions:
- [ ] Does the script start from a clean state and produce a verifiable
      artifact (DB row, monitoring record, UI screenshot)?
- [ ] Are the **specific values** (model name, provider, request body) named,
      not just types ("an LLM model" — too vague)?
- [ ] Is there a **negative path** demo too? ("Add a model with no catalog
      match → expect fallback to X and warning Y")
- [ ] Does the script reference verification SQL / curl / log lines
      reviewers can paste?

> **W1 lesson**: "Tests cover combined-window and separate-input-limit
> providers" and "Monitoring reports total window, output reserve, safe
> input budget, actual input usage, and capacity source" — both abstract.
> CM-031 wasn't found until ~10 days post-acceptance when a human manually
> ran a real model addition. A demo script in acceptance would have surfaced
> CM-031 on day 1.

### 4. Operational Dependencies

**Main question:** What does deployment need to do beyond `git pull` for
this workstream to take effect?

Sub-questions:
- [ ] Which containers need image rebuild? (which Dockerfile, which
      `compose up --force-recreate <service>`)
- [ ] Which DB migrations need to run manually? (which SQL files in
      `docker/sql/`)
- [ ] Which env vars / `consts.const` entries need to be set?
- [ ] Which feature flags exist and what's their default? Per-tenant
      override mechanism?
- [ ] Is there a runbook step for staged rollout? Rollback procedure?
- [ ] Which monitoring dashboards/alerts need updating?

> **W1 lesson**: W1 step 2 shipped three SQL files in `docker/sql/`. Nobody
> applied them in the running environment for ~24 hours, until the user
> tried to add a model and got a SQL "column does not exist" error
> mis-translated by the frontend as "无法连接到 ModelEngine". The spec
> never said the files must be applied manually because there's no
> migration runner — and didn't flag the absence of a runner as a
> dependency. (See `nexent 代码改动生效流程.md` 坑 6.)

### 5. Sibling Components Enumerated

**Main question:** For every component, file, table, or call site
mentioned, are its near-siblings explicitly listed (even just to say
"intentionally out of scope")?

Sub-questions:
- [ ] If a dialog/page is modified, is every other dialog that shares the
      same form state or model-record schema named?
- [ ] If a function is modified, are all callers listed (`grep` evidence
      or file:line references)?
- [ ] If a DB column is added, are all ORM/Pydantic/SQL mirror files named?
- [ ] If a Python module is loaded under one sys.modules key, is the other
      key (e.g. `backend.services.X` vs `services.X`) named?

> **W1 lesson**: Step 7 named `ModelEditDialog` but not its sibling
> `ProviderConfigEditDialog`. Both rendered capacity fields after the fix,
> but only one got the fix. Same dialog file, two exported components —
> easy to miss when grepping by feature name.

### 6. Reverse-Test: "Can the User Actually Use This Feature?"

**Main question:** Pretend you are an operator/developer who needs the
feature this workstream enables. Walk through the steps end to end. Do
you hit a dead-end, ambiguous default, or invisible failure?

Sub-questions:
- [ ] Without reading source code, can the user know **whether the feature
      is active** for their request? (visible status, monitoring row, etc.)
- [ ] Are all the values the feature depends on **reachable from the UI**
      (not just from SQL UPDATE)?
- [ ] If the feature silently falls back, is the fallback **observable**?
      (log line, monitoring field, UI badge)
- [ ] If the workstream is invisible (pure backend), what would let an oncall
      engineer answer "is W_N healthy right now?" in <60 seconds?

> **W1 lesson**: glm-5.1 was added successfully, "connectivity check
> passed", and the user had no signal that the catalog was missed. The
> only way to find out was to query `model_monitoring_record_t` directly.
> A reverse-test review during spec evaluation would have caught this.

## Post-W1/W2 Follow-up Additions (2026-06-22)

> Items 7–10 capture lessons from the W2 PR's end-to-end testing window.
> Where Items 1–6 focus on spec completeness, these focus on
> implementation contracts that are easy to miss when fixing one reported
> bug at a time — particularly when the same concept has multiple
> frontend surfaces, multiple backend constructor sites, or multiple
> key-derivation halves that must agree.

### 7. Frontend Configuration Surface Matrix

**Main question:** For every form/dialog this workstream modifies, has
the **complete matrix** of configuration surfaces been enumerated, and
has each surface's contract (state, validation, save handler, wire
payload) been verified?

The matrix is at least four surfaces and often six:
- single-add (`ModelAddDialog`, single-row form)
- single-edit (`ModelEditDialog`)
- batch-add top-level defaults (`ModelAddDialog` batch-import panel)
- batch-add per-row gear modal (`ModelAddDialog` Settings Modal)
- batch-edit per-row gear modal (`ProviderConfigEditDialog` from
  `ModelDeleteDialog`)
- batch-edit Confirm / "修改配置" bulk-apply (`ModelDeleteDialog`
  footer Confirm + `ProviderConfigEditDialog` with
  `hideCapacityFields=true`)

Sub-questions:
- [ ] Does the spec **list** every surface in the matrix that lets an
      operator configure this concept? Even just to say "intentionally
      out of scope for this workstream — follow-up W_NN".
- [ ] For each surface, is the form state initialization documented?
      (which fields prefill from where; what happens with NULL or empty
      existing values; what happens with the backend's
      `DEFAULT_LLM_MAX_TOKENS` sentinel)
- [ ] For each surface, is the validation contract documented? (which
      fields are required; whether the Save button is `disabled` only,
      or the handler also re-checks — see Item 9)
- [ ] For each surface, is the **save handler's wire payload format**
      documented? (camelCase vs snake_case; provider-prefix format;
      numeric model_id vs name; what gets included when fields are
      optional)
- [ ] For each batch-mode surface, are the **destructive semantics**
      called out? ("Confirm in batch-edit deletes existing models not in
      the incoming list" is the kind of contract that must be visible in
      the spec, not buried in `batch_create_models_for_tenant`.)
- [ ] If a fix is applied to one surface, has it been **explicitly
      replicated** to every other surface that shares the same concept?
      Or is a follow-up opened for each remaining surface?

> **W1/W2 follow-up lesson**: W1 step 7 named `ModelEditDialog` and the
> spec acknowledged `ProviderConfigEditDialog` as a sibling. Six weeks
> later we discovered the same class of fix was missing from FOUR more
> surfaces: `ModelAddDialog` batch-import per-row gear (commit
> `4f770de1c`), `ModelAddDialog` single-add payload hygiene (`5985d4ba4`),
> `ModelEditDialog` defensive isFormValid guard (`60655efbb`), and
> `ModelDeleteDialog` Confirm gate + provider-level bulk-apply panel
> (`6dd735162`). The "4-quadrant" view of frontend model config
> (`add`/`edit` × `single`/`batch`) was never written down, so each
> single-bug fix shipped while the other three quadrants kept the bug.
> The capstone incident (commit `67a75f014`) was an interaction between
> two of those quadrants: batch-edit gear save silently dropping
> capacity edits, then batch-edit Confirm soft-deleting freshly-added
> catalog rows on every confirm.

### 8. Pydantic Optional Silent Drop in Constructor Sites

**Main question:** When a new `Optional[X] = None` field is added to a
request or response schema, has every site that **explicitly constructs**
that schema been audited and updated to thread the new field through?

Sub-questions:
- [ ] `grep -rn "ClassName(" backend/ sdk/` produces a finite list. Has
      every callsite been audited? Are the constructor sites using
      `**dict` passthrough (safe — new fields flow automatically) or
      explicit kwargs (unsafe — silent absorption to default)?
- [ ] For sites using explicit kwargs, is there a test that pins the
      constructor's `call_args` (not just the return dict — mocking
      `model_dump` trivially satisfies a return-dict assertion regardless
      of what the constructor received)?
- [ ] Is there a regression test where the schema field's intended
      operator value reaches the DB column, not just the schema default?
- [ ] If the spec adds a "marker" field (e.g., `capacity_source` with
      `operator` vs `provider_candidate` semantics), is the
      operator-vs-marker contract enforced at the constructor site, not
      just hoped-for at the caller?

> **W1/W2 follow-up lesson**: W1 added W1/W2 capacity fields
> (`context_window_tokens`, `max_output_tokens`, etc.) to the
> `ModelRequest` Pydantic schema. The single-add and single-edit service
> paths used dict passthrough (`dict(model_data) → create_model_record`),
> so the new fields landed automatically. But `prepare_model_dict` (the
> batch-create path in `backend/services/model_provider_service.py`,
> introduced 2025-08-06 and never touched by W1/W2 commits) used
> `ModelRequest(model_factory=..., model_name=..., max_tokens=...)` —
> explicit kwargs, no `**`. The new W2 fields were `Optional[int] = None`,
> so the constructor silently used `None` for them. Every batch-fetched
> LLM landed with `context_window_tokens=NULL`; only the legacy
> `max_tokens` mirror persisted (the glm-5.1 / glm-5.2 incident, commit
> `8bbd6075a`). Worse, the existing test
> `test_prepare_model_dict_does_not_persist_provider_capacity_candidates`
> only asserted "the dumped result dict doesn't contain W2 fields" — but
> the result was controlled by the mocked `model_dump`, so the assertion
> was trivially satisfied no matter what the constructor received.
> Strengthening the test to also pin `mock_model_request.call_args`
> (commit `70d231b2d`) is what now blocks regressions.

### 9. Defensive Save Handler Guards

**Main question:** For every Save / Submit handler whose button is gated
by `disabled={!isValid()}`, does the handler **also** re-check
`if (!isValid()) return` at the top of its body?

Sub-questions:
- [ ] Can the handler be invoked from non-click paths? (Modal `onOk`,
      form submit, keyboard Enter, programmatic dispatch, third-party
      component callbacks)
- [ ] React's `disabled` attribute can lag one tick behind state updates
      — does the handler tolerate being invoked while it would have been
      disabled?
- [ ] If validation fires for required fields, does the handler bail
      before sending an incomplete payload, or does it send and rely on
      backend rejection?
- [ ] Is the same guard pattern applied symmetrically across sibling
      dialogs? (If one dialog has the guard and a sibling doesn't, the
      sibling will trip on the same edge case.)

> **W1/W2 follow-up lesson**: `ModelEditDialog.handleSave` had
> `disabled={!isFormValid()}` on its Save button but no defensive guard
> inside the handler. A user opened the dialog for glm-5.2 (whose W2
> columns were NULL in DB because of Item 8), saw empty required fields,
> somehow triggered save (likely Modal `onOk` firing or a fast-click
> before the disabled state propagated), and the row landed with
> `context_window_tokens=NULL, max_output_tokens=NULL` persisted via a
> partial payload. The Save button being disabled is a hint, not an
> enforcement. `ProviderConfigEditDialog` already had `if (!valid())
> return` in its handler — making both dialogs symmetric (commit
> `60655efbb`) closed the gap.

### 10. Wire-Format Key Consistency Across Halves

**Main question:** For every backend route that does both a "lookup
existing by key" pass and a "delete-not-in-list by key" pass, do both
halves compute the **same key** from the same row, by the same helper?
And does the frontend's outbound payload match what the backend expects?

Sub-questions:
- [ ] Does every place that builds the key use the **same helper**
      function (e.g., `add_repo_to_name`)? Or does one half use raw
      concatenation while the other uses the helper?
- [ ] If a row field is empty/None, does the key-building helper omit the
      separator? Does the raw concatenation also omit it? (Inconsistent
      handling of empty `model_repo` was the glm-4.7 incident.)
- [ ] Is there a test where one row has an empty key component and the
      membership check returns the expected result?
- [ ] Does the frontend's outbound `model_id` (or whatever the lookup
      handle is) match what the backend's lookup expects? (`{factory}/{name}`
      vs bare `{name}` vs numeric primary key)
- [ ] When a frontend silent no-op (Item A) interacts with a backend
      destructive default (Item B), the failure mode is invisible to the
      user until it destroys data. Is the layer interaction explicitly
      tested?

> **W1/W2 follow-up lesson** (commit `67a75f014`):
> `batch_create_models_for_tenant` built `existing_model_map` keyed by
> `add_repo_to_name(model_repo, model_name)` — which returns `"glm-4.7"`
> when `model_repo` is empty. The delete loop ten lines above used
> `model["model_repo"] + "/" + model["model_name"]` — which returns
> `"/glm-4.7"`. For DashScope rows (catalog returns bare names like
> `glm-4.7`; persisted rows have `model_repo=""`), the delete loop's key
> never matched the catalog id, so every existing row got soft-deleted
> on every batch_create call. Independently, the frontend gear modal in
> `ModelDeleteDialog` constructed `model_id = selectedSingleModel.model_name
> || selectedSingleModel.id`, sending bare `"glm-4.7"` instead of
> `"dashscope/glm-4.7"`; the backend split on "/" and got no model_factory,
> so `get_model_by_name_factory(model_name="glm-4.7", model_factory=None)`
> returned None and logged a warning instead of erroring. The frontend
> received HTTP 200 with no diff, so the gear modal closed and the user
> thought their capacity edit landed. The two bugs combined to make gear
> saves invisible AND the next "Confirm" click soft-delete the user's
> freshly-added rows. Either bug alone would have been noticed quickly;
> the interaction is what made the failure mode silent.

## Severity Calibration

When applying the checklist:

- **🟢 OK**: all sub-questions answered, evidence inlined (file:line, SQL,
  exact values).
- **🟡 Partial**: main question yes, ≥1 sub-question unanswered.
- **🔴 Gap**: main question no, or contradictory answer.

A workstream with even one 🔴 should not move to Accepted. A workstream
with all 🟡 should have follow-ups opened and tracked before
implementation begins.

## Output Format

A per-workstream review writes a table like:

| Item | Status | Evidence / Gap | Required action |
| --- | --- | --- | --- |
| 1. User Journey | 🟡 | Operator visible effects partially described; no UI section | Add "Operator-Visible Effects" + "Configuration Path" sections |
| 2. Frontend Decomposition | N/A | No frontend in scope (pure backend) | N/A |
| 3. End-to-End Demo | 🔴 | Acceptance is abstract metrics, no script | Add concrete script in §Tests |
| ... | ... | ... | ... |

Each Required action either becomes a spec edit or an explicit follow-up.

## Why This Exists

The W1 workstream passed a 26-finding formal review, three rounds of
implementation PRs, and was marked Accepted. Within 24 hours of
end-to-end testing, ~17 distinct issues surfaced across catalog
adoption, frontend UX, and operations. Items 1–6 are the smallest
formalization of that lesson.

Six weeks later, the W2 PR's end-to-end testing surfaced ~20 more
issues, several of them silent data-loss bugs (gear-save no-op +
batch_create soft-delete cascade) that destroyed an operator's
freshly-added catalog rows. Each had at least one of these patterns:

- The same concept had multiple frontend configuration surfaces
  (`add`/`edit` × `single`/`batch` × `per-row`/`provider-level`); one
  surface got the fix and the others kept the bug.
- A new schema field was Optional with default None; one constructor
  site used `**dict` passthrough and another used explicit kwargs;
  the kwargs site silently dropped the new field.
- A save handler relied on `disabled={!isValid()}` alone; the handler
  fired anyway through a non-click path and persisted a partial row.
- A backend route built the same row's lookup key two different ways
  in two adjacent loops; the key inconsistency manifested as cascading
  soft-deletes on every Confirm click.

Items 7–10 cover those patterns. The combined checklist is what every
spec should pass before implementation and every PR should answer in
its description.
