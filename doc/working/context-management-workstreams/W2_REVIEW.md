# W2 Spec Review

| Field | Value |
| --- | --- |
| Workstream | W2: Output and Safety Capacity Reserve |
| Source | `W2_Output_and_Safety_Capacity_Reserve.md` |
| Reviewer date | 2026-06-16 |
| Method | Spec Review Checklist (`SPEC_REVIEW_CHECKLIST.md`) + four spec-reader concerns surfaced during checklist application |
| Status of W2 | Spec Accepted, implementation pending |

## Summary

| Item | Status | Required action |
| --- | --- | --- |
| 1. User Journey | 🔴 | Add "Operator-Visible Effects" section; add "Configuration Path" section |
| 2. Frontend Decomposition | 🔴 | Either add full frontend plan OR explicitly mark as no-frontend-in-W2 and define the configuration UX deferral |
| 3. End-to-End Demo | 🟡 | Concrete demo script with named values; include negative path |
| 4. Operational Dependencies | 🟡 | Spell out which containers rebuild; clarify ops nothing-to-do is intentional |
| 5. Sibling Components | 🔴 | Enumerate current local-reserve sites; specify W2→compaction-model handoff (see Issue C) |
| 6. Reverse Test | 🟡 | Operator must be able to know W2 is active and tune `soft_limit_ratio` |
| **Reader Issue A** | 🔴 | `soft_limit_ratio` default value missing |
| **Reader Issue B** | 🔴 | `requested_output_tokens` per-agent/request override mechanism unspecified |
| **Reader Issue C** | 🔴 | W2 ↔ W13 compaction-model relationship undefined |
| **Reader Issue D** | 🟡 | Step 5 "consistent" semantics unclear: rename only or new wiring? |

**Verdict:** W2 spec is not Ready to Implement as written. **7 of 10** checklist
items require updates. None of the gaps invalidate the architecture — they
are under-specifications that would reproduce W1-style post-acceptance
surprises if shipped to implementation as-is.

## Detailed Findings

### Item 1. User Journey 🔴

**What spec says:** Pure technical description of `SafeInputBudgetSnapshot` +
calculator + policy fields.

**What is missing:**
- Who is the operator persona? (Tenant admin? Per-agent owner? Oncall?)
- What does the operator **see change** when W2 ships? Today they see
  `token_threshold` driving compaction. Tomorrow they see... what?
- When W2 rejects a request with `no_safe_input_capacity` or
  `reserve_exceeds_capacity`, where does the error surface to the operator?
- The 10% uncertainty reserve will make some previously-accepted requests
  fail. Which operator gets the notification?

**Required action:** Add **"Operator-Visible Effects"** section enumerating:
1. Compaction now triggers at `soft_limit_ratio × provider_input_limit`
   instead of at `model_record_t.max_tokens` — visibly earlier
2. Requests that pass W1 capacity may fail W2 budget; new typed failure
   surfaces as `HTTPException` mapped from `LimitExceededError` or similar
3. Monitoring rows get new fields (already in step 8 via reserve breakdown
   — confirm cross-link)
4. The 10% uncertainty reserve is conservatively safe; first deployment
   may see ~10% reduction in usable input for unverified profiles

### Item 2. Frontend Decomposition 🔴

**What spec says:** Nothing. The spec assumes pure backend.

**What is missing:** The W2 policy has at least three operator-tunable
values:
- `default_output_reserve_tokens` (already in W1 column)
- `soft_limit_ratio` (new in W2)
- `approved_profile_reserve_tokens` (new in W2)
- Per-agent/request `requested_output_tokens` override (Reader Issue B)

None of these have a configuration path. The spec implicitly says
"existing model/agent configuration" but doesn't name UI elements.

**Required action:** Decide and document one of:
- **(a) No new UI in W2**: explicitly state "configuration is via direct
  `model_record_t` / `ag_tenant_agent_t` writes; no UI in W2 scope; UI
  added later under W18 if demand emerges"
- **(b) UI in W2**: split frontend out as W2 sub-step with the six
  sub-questions from checklist item 2

Without this decision, implementation has no answer to "where does the
operator change `soft_limit_ratio`".

### Item 3. End-to-End Demo 🟡

**What spec says:** "Every request reports a reserve breakdown" and
"Long-answer tasks retain the requested output allowance."

**What is missing:** Concrete, copy-pasteable script.

**Required action:** Add to `Tests` section:

```text
Demo script:
1. Configure model gpt-4o (catalog-known, context=128000, output_cap=16384)
2. Send chat with requested_output=8192
3. Verify monitoring row contains:
   - provider_input_limit_tokens = 128000 - 8192 = 119808
   - reserve_breakdown = {output: 8192, uncertainty: 0}  # known profile
4. Configure uncataloged model my-custom (no overrides)
5. Send same chat
6. Verify monitoring row contains:
   - reserve_breakdown.uncertainty = 12800  (= 10% × 128000)
   - safe_input_budget = 119808 - 12800 = 107008
   - warning surfaced: "unified_10pct_uncertainty_reserve_active"
7. Negative path: send chat with requested_output > max_output_tokens
   → expect 400 with error.code = "requested_output_exceeds_cap"
```

### Item 4. Operational Dependencies 🟡

**What spec says:** Nothing explicit.

**What is reality:** W2 is code-only (no DB columns, no env vars, no new
services). But spec should still name this explicitly so deployers don't
wonder.

**Required action:** Add **"Operational Dependencies"** section:

| Component | Action |
| --- | --- |
| `nexent-runtime` / `nexent-northbound` / `nexent-config` / `nexent-mcp` | Image rebuild (流程 A) — W2 lives in SDK + backend agent paths |
| `nexent-web` | No change (no UI in W2 if Option a from Item 2) |
| `nexent-postgresql` | No change |
| Env vars | None |
| Feature flag | None — W2 is unconditional once shipped |

### Item 5. Sibling Components 🔴

**What spec says:** "All callers consume the same snapshot; local reserve
recalculation is prohibited."

**What is missing:** Which callers?

**Required action:** Enumerate every current site that derives a reserve
or threshold locally:

```text
Current local-reserve / threshold sites (confirmed via grep, 2026-06-16):
- sdk/nexent/core/agents/agent_context.py:373    pair budget
- sdk/nexent/core/agents/agent_context.py:415    action budget
- sdk/nexent/core/agents/agent_context.py:753    summary input
- sdk/nexent/core/agents/agent_context.py:764    summary reduce
- sdk/nexent/core/agents/agent_context.py:845    safe actions
- sdk/nexent/core/agents/agent_context.py:860    reduced actions
- backend/agents/create_agent_info.py:_resolve_input_budget  (W1 wiring;
  W2 must subtract uncertainty reserve from this result)
```

Each must either be migrated to consume the W2 snapshot or be explicitly
exempted (and the exemption justified).

### Item 6. Reverse Test 🟡

**What spec says:** Snapshots are recorded in monitoring.

**What is missing:** How does an operator answer "is W2 active for my
tenant right now? what reserve did this request use?"

**Required action:**
- A monitoring query (SQL) the operator can run to see the reserve
  breakdown for a recent request.
- A documented log line emitted when the 10% uncertainty reserve fires,
  so oncall can grep `journalctl` / Langfuse for it.
- If `soft_limit_ratio` is tunable via DB, document the SQL operators run.

## Reader-Surfaced Issues (deeper than checklist alone)

### Issue A. `soft_limit_ratio` default value 🔴

**Problem:** Spec defines `soft_limit_ratio` as decimal in `(0, 1]` but
gives no default. This decides when compaction proactively triggers.

**Risk:** Too high (e.g. 0.95) → compaction starts late, requests fail
the hard limit before W3 final-fit can act. Too low (e.g. 0.5) →
compaction churns even on small contexts, latency + cost balloon.

**Recommendation:** Default `0.8` (80%). Rationale:
- Leaves 20% headroom for compaction work itself (which can grow
  context briefly during the compaction LLM call)
- Conservative enough that hard-limit rejection should be rare
- Matches the heuristic used by similar systems (Anthropic agent SDK
  defaults to 80% trigger; OpenCode and Codex use 0.75-0.85 range)

**Required action:** Add to spec § Policy Model:
> Default `soft_limit_ratio = 0.8`. Operators may override per-tenant via
> `tenant_config_t.soft_limit_ratio` (key already exists in W14 governance
> domain, or add it). Per-agent override deferred to future workstream.

### Issue B. `requested_output_tokens` per-agent override 🔴

**Problem:** Spec says values "may be overridden per agent or request"
but doesn't say where or how.

**Two distinct contracts buried in one sentence:**

1. **Per-agent override**: persisted on agent config row. Operator sets it
   when creating/editing an agent. Used as the default `requested_output_tokens`
   for every request that agent makes.
2. **Per-request override**: sent in the chat API request body. Overrides
   the agent default for one call. Used by callers who know they need a
   long answer (or a short one).

These need different code + UX:

| Path | Where | How configured | Frontend impact |
|---|---|---|---|
| Per-agent | `ag_tenant_agent_t.requested_output_tokens` column | Agent edit dialog | New input field in agent editor |
| Per-request | `POST /api/v1/agent/run` body field | Programmatic only | None (API caller's responsibility) |

**Required action:** Add to spec § Policy Model two subsections:

> **Per-agent override**: persisted on agent config (new column on
> `ag_tenant_agent_t`); migration required. Agent edit UI gains a numeric
> input "Requested output tokens" with placeholder showing the resolved
> model-level default. Validates `≤ max_output_tokens` from resolved
> capacity. Frontend touchpoint: `frontend/app/[locale]/agents/.../*.tsx`
> (to enumerate during implementation).
>
> **Per-request override**: optional integer field on agent-run request
> body. Same validation. Documented in OpenAPI spec but no UI.

### Issue C. W2 ↔ W13 compaction-model relationship 🔴

**Problem:** W13 (governed compaction) calls a separate compaction model
(typically a smaller/cheaper LLM). That model is a `model_record_t` row
with its own capacity. **The compaction call itself needs its own W1→W2
chain** — W2 spec doesn't say this.

**Why it matters:**
- Main model: gpt-4o, context=128k, requested_output=8k → safe input = 107k
- Compaction model: gpt-4o-mini, context=128k, requested_output=4k →
  safe input = different value
- If W13 uses the **main model's** W2 snapshot for the compaction call,
  it will misjudge compaction's own budget
- This is also the same defect that W1 had — assuming one model's
  parameters apply to all calls

**Required action:** Add to spec § "W2 to W3 Handoff" (or new section):

> **Compaction calls and W2:** When W13 invokes the compaction model, that
> call goes through the same W1→W2 chain as a primary model call, with
> the compaction `model_record_t` as input. The main run's W2 snapshot is
> NOT reused for the compaction call. W2 explicitly states: every model
> dispatch (primary, compaction, summary) gets its own W1 capacity
> snapshot + W2 budget snapshot. Snapshots are NOT shared across model
> identities.
>
> This also means W13 cannot use a `gpt-4o-mini` compaction model for
> uncataloged main models without verifying the compaction model itself
> is cataloged (or has operator overrides). Compaction config UX should
> warn operators if the chosen compaction model is uncataloged.

### Issue D. Step 5 "Pass requested output tokens" semantics 🟡

**Problem:** Step 5 reads "Pass requested output tokens to the provider
call consistently." Current code already passes `max_tokens` to OpenAI's
`chat.completions.create` (renamed to `max_output_tokens` internally by
W1 step 4).

**Two interpretations:**

(a) Step 5 = verify the existing pass-through uses W2's
    `requested_output_tokens` value, not a separate local value. Code change
    is one line per call site.

(b) Step 5 = add new wiring that the snapshot's `requested_output_tokens`
    is the value sent, AND that no other code path can override it. May
    require trusted-dispatch boundary work (CM-013 in findings).

**Required action:** Clarify in spec § Implementation Plan step 5:

> Step 5 is **interpretation (b)**: the W2 snapshot's
> `requested_output_tokens` MUST be the value sent to
> `chat.completions.create` as `max_tokens`. The trusted server-side
> dispatch boundary (per CM-013) verifies this on every call. Local
> overrides — for example a caller passing a `max_tokens` kwarg directly
> to `OpenAIModel.__call__` — are rejected or coerced to the snapshot
> value. Add a server-side assertion in the dispatch wrapper.

This is more than rename — it's the enforcement contract.

## Recommended Next Steps

1. **Update W2 spec** with the changes specified in each finding above.
   Single commit; mirror Chinese version if it exists.
2. **Open follow-up question for agent-edit UI**: per-agent
   `requested_output_tokens` field is a UX addition that may want its
   own decision (separate ticket or fold into a W2 sub-step).
3. **Cross-link W13**: when W13 spec is reviewed, item 5 should
   explicitly call back to the W2 "snapshots are per-model, not shared"
   rule documented in Issue C.
4. **After W2 spec updates merge**: run the checklist again from a clean
   read of the spec to confirm all 🔴 became 🟢.

## Open Questions for User

- Issue B: should per-agent override be in W2 scope, or defer to a follow-up?
  The frontend work is non-trivial.
- Issue C: should W13 also be re-reviewed against this checklist + the
  same "per-model snapshot" rule, before W13 implementation begins?
- Default `soft_limit_ratio = 0.8` acceptable, or override?
