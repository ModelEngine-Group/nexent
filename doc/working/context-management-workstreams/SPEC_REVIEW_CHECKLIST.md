# Workstream Spec Review Checklist

> Derived from the W1 post-acceptance retrospective (2026-06-16). Apply to
> every new workstream spec **before** it is marked Accepted. Apply again
> to every existing spec **before** implementation begins. Each item has
> concrete sub-questions; "OK" requires an affirmative answer to **all**
> sub-questions, not just the main one.

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
adoption, frontend UX, and operations. Every issue would have been
caught by one of the six items above. This checklist is the smallest
formalization of that lesson.
