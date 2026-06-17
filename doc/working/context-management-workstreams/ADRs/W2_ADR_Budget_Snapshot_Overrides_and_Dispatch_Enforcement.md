# W2 ADR: SafeInputBudgetSnapshot, Override Precedence, and Dispatch Enforcement

| Field | Value |
| --- | --- |
| Status | Accepted |
| Owners | Agent runtime squad (W2 lead), AI Agent squad (SDK boundary), Model integration squad (W1 lead, fingerprint compatibility) |
| Affects | [W2](../W2_Output_and_Safety_Capacity_Reserve.md), [W3](../W3_Guaranteed_Context_Fit.md), [W13](../W13_Reliable_Governed_Compaction.md), [W16](../W16_Prompt_Cache_Aware_Assembly.md) |
| Related findings | CM-013, CM-027, CM-028, CM-029, CM-030 |
| Date | 2026-06-16 |
| Accepted on | 2026-06-16 |
| Supersedes | None |

## Signoff Status

| Item | Status | Notes |
| --- | --- | --- |
| Decision 1: W2 fingerprint field set and algorithm | Confirmed | W3 can use the W2 snapshot fingerprint algorithm and field set for validation. |
| Decision 2: override precedence chain | Confirmed | The precedence chain and frontend-facing agent override behavior are accepted. |
| Decision 3: reject-on-mismatch at SDK dispatch | Confirmed | AI Agent squad / SDK boundary owner accepts reject-on-mismatch and SDK-wrapper enforcement. |
| Type skeleton PR | Completed | Interface/type skeleton work is included in the W2 skeleton commit; calculator body, migration, and dispatch enforcement remain separate W2 implementation work. |

## Context

The W2 spec body now reflects CM-027–CM-030 (per the 2026-06-16 phase 6
review and today's spec edits). This ADR was opened to pin three
implementation-detail couplings, each with two reasonable choices that
downstream W3, W13, and the SDK boundary will hard-depend on:

1. **`SafeInputBudgetSnapshot` field set and fingerprint algorithm.** The
   W1 ADR Decision 3 explicitly defers this to a sibling ADR:
   > *"The W2 fingerprint uses the same algorithm with its own field set
   > (defined in a sibling W2 ADR if needed) and includes the W1
   > fingerprint as one input."*
   W3 verifies W1 and W2 fingerprints at the trusted dispatch boundary;
   without an exact algorithm here, that verification cannot be written.
2. **Override precedence and DB column shapes for CM-027/CM-028.** The W2
   spec lists the per-tenant `soft_limit_ratio` override, the per-agent
   `requested_output_tokens` column, and the per-request API body field
   as in-scope but does not pin who-wins, column constraints, key strings,
   or migration ordering.
3. **CM-030 trusted-dispatch enforcement: reject vs coerce, SDK vs
   backend.** The W2 spec says caller `max_tokens` kwargs are
   "rejected or coerced" by an assertion in "the SDK or backend dispatch
   wrapper." Both pairs are binary choices with different security and
   layer-rule implications.

Resolving the three together avoids spec drift across W2, W3, W13, the
SDK, and `tenant_config_t` storage. As of the signoff status above,
Decisions 1-3 are confirmed, and the type skeleton has been completed.
This ADR is accepted as of 2026-06-16.

## Decision 1: SafeInputBudgetSnapshot Field Set and Fingerprint Algorithm

**Decision:** Mirror W1 ADR Decision 3 (SHA-256 over canonical JSON,
hex-encoded, truncated to 32 characters / 128 bits). The W2 fingerprint
includes the W1 fingerprint as one of its inputs, so a W1 change cascades
into a W2 change by construction.

### Algorithm (binding)

```python
import hashlib
import json
from typing import Mapping, Sequence

def compute_w2_fingerprint(
    *,
    w2_resolver_version: str,
    w1_fingerprint: str,                              # from ModelCapacitySnapshot
    provider: str,
    model_name: str,
    requested_output_tokens: int,
    output_reserve_source: str,                       # "model_default" | "agent" | "request"
    uncertainty_reserve_tokens: int,
    uncertainty_reserve_basis: str,                   # "context_window_10pct" | "approved_profile" | "none"
    approved_profile_reserve_tokens: int | None,
    soft_limit_ratio: float,                          # resolved post-precedence
    soft_limit_ratio_source: str,                     # "code_default" | "tenant_config"
    soft_input_budget_tokens: int,
    hard_input_budget_tokens: int,
    field_sources: Mapping[str, str],
    warnings: Sequence[str],                          # excluded from fingerprint, see below
) -> str:
    payload = {
        "v": 1,
        "w2_resolver_version": w2_resolver_version,
        "w1_fingerprint": w1_fingerprint,
        "provider": provider,
        "model_name": model_name,
        "requested_output_tokens": requested_output_tokens,
        "output_reserve_source": output_reserve_source,
        "uncertainty_reserve_tokens": uncertainty_reserve_tokens,
        "uncertainty_reserve_basis": uncertainty_reserve_basis,
        "approved_profile_reserve_tokens": approved_profile_reserve_tokens,
        "soft_limit_ratio": soft_limit_ratio,
        "soft_limit_ratio_source": soft_limit_ratio_source,
        "soft_input_budget_tokens": soft_input_budget_tokens,
        "hard_input_budget_tokens": hard_input_budget_tokens,
        "field_sources": dict(sorted(field_sources.items())),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]
```

### Field set rationale

| Included | Reason |
| --- | --- |
| `w2_resolver_version` | Bumped when the calculator's own logic changes; prevents stale fingerprints across logic versions |
| `w1_fingerprint` | A W1 change must invalidate every dependent W2 snapshot; including it makes the dependency cryptographic |
| `provider`, `model_name` | Identity of the dispatch target; redundant with W1 fingerprint but kept for greppable logs |
| `requested_output_tokens` + `output_reserve_source` | Three override paths produce the same number from different provenance; sources must affect fingerprint per CM-028 |
| Three reserve fields (`uncertainty_reserve_tokens`, `_basis`, `approved_profile_reserve_tokens`) | Different reserves under CM-016/CM-027 must produce different fingerprints |
| `soft_limit_ratio` + `_source` | Per-tenant override produces a different operating envelope; W3 must reject snapshots whose ratio source no longer matches the active tenant config |
| Derived `soft_input_budget_tokens`, `hard_input_budget_tokens` | Included so a calculator bug that changes derivation cannot silently match |
| Sorted `field_sources` | Two configurations with the same numbers but different provenance are not interchangeable for audit |

| Excluded | Reason |
| --- | --- |
| `warnings` | Informational; may legitimately differ across identical resolutions (e.g., observability side effects) |
| `fingerprint` itself | Trivially excluded |
| Time/clock fields | Determinism requires the fingerprint to be a pure function of the resolved contract |

### W2 resolver version policy

- `W2_RESOLVER_VERSION = "1.0.0"` constant inside `sdk/nexent/core/models/capacity_resolver.py`
  (or a new sibling module — see Open Item 1).
- Bump rules identical to W1 ADR Decision 3.
- Included as a tag in W2 monitoring.

## Decision 2: Override Precedence and DB Column Shapes

**Decision:** Pin a single precedence chain per overridable field and ship
the two DB-side additions in one migration. **Per-request beats per-agent
beats per-tenant beats model default**, evaluated independently for each
field.

### Override precedence per field

| Field | Layer 1 (lowest) | Layer 2 | Layer 3 | Layer 4 (highest) | Notes |
| --- | --- | --- | --- | --- | --- |
| `requested_output_tokens` | W1 `model_record_t.default_output_reserve_tokens` | — | `ag_tenant_agent_t.requested_output_tokens` | API body `requested_output_tokens` | Per-tenant override **not** introduced for this field in release one (CM-028 scope) |
| `soft_limit_ratio` | Code default `0.8` (in `CapacityReservePolicy`) | `tenant_config_t` key `context.soft_limit_ratio` | — | — | Per-agent and per-request ratio overrides explicitly out of scope (CM-027) |

Resolution evaluates the chain from highest defined layer downward; the
first defined value wins. Each non-default resolution emits the matching
`output_reserve_source` / `soft_limit_ratio_source` enum into the
fingerprint (Decision 1).

### DB column shapes

```sql
-- v2.2.0_0616_add_requested_output_tokens_to_ag_tenant_agent_t.sql
ALTER TABLE nexent.ag_tenant_agent_t
  ADD COLUMN IF NOT EXISTS requested_output_tokens INTEGER NULL;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.requested_output_tokens IS
  'Per-agent override for W2 requested_output_tokens. NULL means inherit '
  'the resolved model-level default. Must satisfy 0 < value <= '
  'max_output_tokens from the resolved W1 capacity at save time.';
```

- **Type:** `INTEGER NULL`. Positivity is enforced by service-layer
  validation (saves below 1 or above resolved `max_output_tokens` raise
  `requested_output_exceeds_capacity`), not a DB `CHECK` constraint —
  the upper bound depends on the linked model row and must be resolved
  via lookup, not a static constraint.
- **Fresh-install schemas:** identical `ADD COLUMN` lines appended to
  `docker/init.sql` and `k8s/helm/nexent/charts/nexent-common/files/init.sql`
  per the repository's standard migration convention.
- **Frontend:** the agent-edit form gains a numeric input bound to this
  column. Placeholder text shows the resolved model-level default; an
  empty input persists `NULL`. The Form.Item carries a conditional max
  rule equal to the currently selected model's `max_output_tokens` so
  the upper-bound violation is caught at save time, not only at agent
  run time; switching the selected model re-runs validation so an
  already-filled value that exceeds the new ceiling is flagged
  immediately. The backend `_validate_requested_output_tokens_for_agent`
  check remains as defense-in-depth.

### `tenant_config_t` storage for `soft_limit_ratio`

`tenant_config_t` is the existing key/value store; no migration needed.

- `config_key`: `"context.soft_limit_ratio"` (dotted namespace consistent
  with other context-management keys to be added by W10/W14).
- `config_value`: decimal string in `(0, 1]`, parsed at read time. Values
  outside the range raise `invalid_reserve_policy` at policy load; the
  request does not silently fall back to the code default.
- `value_type`: `"single"`.
- No frontend control in release one; tenant operators set this through
  the existing tenant-config admin path.

### Migration ordering

1. Ship the column + fresh-install schema edits (no readers behind a flag yet).
2. Resolver reads the column behind a feature flag `w2.use_agent_override`
   defaulting to `false`. With the flag off, behavior is identical to
   today's "model default only" path.
3. After observe-only telemetry confirms reads work, flip the flag to
   `true` per environment.
4. Same staged-flag pattern (`w2.use_tenant_soft_limit_override`) applies
   to the `tenant_config_t` read.

The flags exist to satisfy W2 Implementation Plan's "observe-only" phase,
not as long-lived configuration. They are removed once Phase 3 (hard
budget enforcement) ships.

## Decision 3: CM-030 Enforcement — Reject + SDK Wrapper

**Decision:** *Reject* (not coerce) caller-supplied `max_tokens` kwargs.
The assertion lives in the *SDK* dispatch wrapper, immediately before the
`chat.completions.create` call. **Signoff:** confirmed by AI Agent squad /
SDK boundary owner.

### Reject vs coerce: choose reject

| | Reject | Coerce |
| --- | --- | --- |
| Caller bug visibility | Loud (typed failure, surfaces in tests) | Silent (call succeeds with surprise behavior) |
| Backward compatibility | Existing callers that pass `max_tokens` break and are fixed | Existing callers keep "working" but bypass intent is hidden |
| CM-013 alignment | Fail-closed | Silent-correct, which CM-013 explicitly excludes for budget/policy inputs |
| Diagnostic cost | Stable typed failure `caller_max_tokens_override_forbidden` | Requires correlating snapshot vs. actual sent value in logs |

CM-013's accepted minimum is to fail closed on "missing, stale, mismatched,
caller-expanded, or incomplete inputs"; a caller-supplied `max_tokens` is
exactly the *caller-expanded* case. Coercion would re-introduce the
silent-pass behavior CM-013 was written to remove.

### Production frontend exposure

In the normal Nexent production flow, end users interact through the web
frontend and do not directly pass `max_tokens`. A `max_tokens` mismatch is
therefore expected to indicate an internal caller bug, test/script misuse,
future integration bug, or an unintended kwargs pass-through inside backend
or SDK code rather than an ordinary user action.

For ordinary frontend users, the mapped error should be generic and
actionable without exposing budget internals, for example "model request
budget configuration is invalid; contact an administrator." The typed
exception and structured logs/traces must include `snapshot_value`,
`caller_value`, W1/W2 fingerprints, provider, and model identity for
operators and developers. External API clients may receive the stable
reason code `caller_max_tokens_override_forbidden`; exposing the exact
`requested_output_tokens` value in API error details is allowed only for
authorized developer/admin-facing diagnostics, not required for the
consumer chat UI.

### SDK vs backend wrapper: choose SDK

The actual `chat.completions.create` call is made from
`sdk/nexent/core/models/openai_llm.py`. Putting the assertion in the SDK
boundary makes it the unmodifiable chokepoint: every dispatch path —
backend services, scripts, tests, and any future caller — goes through
the same check.

Per `CLAUDE.md`'s SDK layer rule, the SDK takes the W2 snapshot as a
**parameter**; it does not read tenant config, env, or DB. The assertion
operates purely on its parameters:

```python
# sdk/nexent/core/models/openai_llm.py — illustrative shape
def _dispatch_chat_completion(
    *,
    snapshot: SafeInputBudgetSnapshot,
    messages: list[dict],
    **kwargs,
) -> ChatCompletion:
    if "max_tokens" in kwargs and kwargs["max_tokens"] != snapshot.requested_output_tokens:
        raise CallerMaxTokensOverrideForbidden(
            snapshot_value=snapshot.requested_output_tokens,
            caller_value=kwargs["max_tokens"],
        )
    kwargs["max_tokens"] = snapshot.requested_output_tokens
    return client.chat.completions.create(messages=messages, **kwargs)
```

`CallerMaxTokensOverrideForbidden` is a new typed SDK error mapped to
HTTP 400 by `apps/` boundary code per `CLAUDE.md` app-layer rules.

### Backend still owns the snapshot-resolution boundary

The SDK assertion does **not** replace W2's trusted-dispatch resolution —
backend services still resolve or verify the snapshot before constructing
the SDK call, per CM-013. The SDK assertion is a defense-in-depth check
that catches the residual class of "caller passes a stray kwarg through."

## Consequences

- **W3 can write fingerprint verification today.** The exact W2 field set
  and algorithm are pinned; `capacity_fingerprint_mismatch` becomes
  implementable.
- **One migration, two new override paths.** The per-agent column ships
  alone; the per-tenant `soft_limit_ratio` reuses existing
  `tenant_config_t` rows.
- **Loud caller-bug failures during rollout.** Any existing call site
  passing `max_tokens` to the SDK chat path will break in the first
  Phase-2 dry-run; that breakage is intentional and surfaces CM-013 gaps
  early.
- **SDK stays pure.** The assertion operates on parameters only; no
  env/config reads added to the SDK.
- **W2 can start implementation once this ADR is accepted.** Its
  remaining dependency is W1 (already accepted) plus W3's trusted-dispatch
  integration, which consumes this ADR's fingerprint contract.
- **Type skeleton can start before acceptance.** The skeleton may add
  frozen model types, calculator signatures, and dispatch wrapper
  signatures while final ADR acceptance is still pending. It must not merge
  calculator behavior, migrations, or production dispatch enforcement
  before this ADR is accepted.

## Open items

| # | Item | Owner | Resolution required before |
| --- | --- | --- | --- |
| 1 | New SDK module name for `SafeInputBudgetCalculator` (sibling to `capacity_resolver.py`) vs adding to the existing module | W2 lead | Type-skeleton PR |
| 2 | Exact wire spelling of the API body field — `requested_output_tokens` (matches DB/SDK) vs a shorter alias | W2 lead, frontend reviewer | API contract PR |
| 3 | Whether `w2.use_agent_override` / `w2.use_tenant_soft_limit_override` flags live in `tenant_config_t` or `consts/const.py` | W2 lead | Migration PR |

These three items do not change Decisions 1–3 above. They are routing
decisions that can be made during the type-skeleton PR.

## Definition of done for this ADR

This ADR is accepted when:

- [x] **Decision 1 fingerprint field set signed off by W3 lead** — W3
      verification code can be written against it.
- [x] **Decision 2 precedence chain signed off by W2 lead and frontend
      reviewer** — the agent-edit UI behavior is unambiguous.
- [x] **Decision 3 reject-on-mismatch signed off by AI Agent squad
      (SDK boundary owner)** — `CallerMaxTokensOverrideForbidden` is added
      to the SDK error taxonomy.
- [x] **Type skeleton PR merged or explicitly approved for parallel
      development** adding `SafeInputBudgetSnapshot`,
      `CapacityReservePolicy`, `SafeInputBudgetCalculator`, and the
      `_dispatch_chat_completion` wrapper signature into the SDK. Calculator
      body, migration, and dispatch enforcement are separate W2
      implementation work.
- [x] **Status flipped to Accepted.**

With this ADR accepted, W2 implementation may proceed. Calculator body,
migration, and dispatch enforcement should still land as explicit W2
implementation changes with the tests required by the W2 spec.
