# W2: Output and Safety Capacity Reserve

## Objective

Derive and enforce a per-request safe input budget that preserves room for model
output, provider framing, reasoning behavior, and token-estimation error.

## Dependencies and Scope

W2 depends on W1's capacity snapshot and tokenizer contract. It owns budget
calculation and reserve policy. It does not own component selection or truncation;
W15, W8, and W9 consume the resulting budget. SDK/client calculations are advisory
only; the trusted server-side model dispatch boundary resolves or verifies the W2
snapshot used for production dispatch.

## Budget Contract

For each request:

```text
provider_input_limit =
  min(max_input_tokens, context_window_tokens - requested_output_tokens)
  using only limits that are defined

safe_input_budget =
  provider_input_limit
  - uncertainty_reserve

uncertainty_reserve =
  context_window_tokens * 10%
  when any required tokenizer, reasoning-window, or provider-overhead behavior is unknown;
  otherwise use the approved profile-specific reserve
```

The 10% basis is the resolved `context_window_tokens` supplied by W1 model
configuration or an approved capability profile. When the 10% rule is required but
`context_window_tokens` is absent, W2 does not guess from `max_input_tokens`; it fails
with `uncertainty_reserve_basis_unknown`. A separate-input-limit model can therefore
operate without `context_window_tokens` only when its approved profile supplies a
specific reserve and verifies the relevant behavior.

`requested_output_tokens` is bounded by `max_output_tokens`; it defaults to
`default_output_reserve_tokens` and may be overridden per agent or request.
All reserve decisions and their sources are included in request telemetry.

## Policy Model

Introduce a validated `CapacityReservePolicy` with provider defaults and bounded
operator overrides:

- Output reserve: expected maximum answer size.
- Uncertainty reserve: exactly 10% of `context_window_tokens` when any required
  tokenizer, reasoning-window, or provider-overhead behavior is unknown.
- Approved profile-specific reserve: may replace the 10% uncertainty reserve only when
  the relevant behavior is verified in the selected W1 capability profile.
- Soft-limit ratio: point at which proactive compaction begins.

Invalid or negative remaining budgets fail configuration before a model call. Requests
may not lower the configured default output reserve in release one. A request may
increase `requested_output_tokens` up to `max_output_tokens`, which narrows the
available input budget. Lowering the default reserve requires the existing authorized
model/agent configuration update path and must record the decision.
Request/operator overrides cannot reduce the required 10% uncertainty reserve.

The 10% uncertainty reserve is additional to `requested_output_tokens`; it does not
replace output capacity. Hard capacity must be known before it can be calculated.
Release one does not separately configure unknown reasoning, provider-overhead, and
estimation-error reserves.

## Input and Output Contract

```text
calculate_safe_input_budget(capacity_snapshot, reserve_policy, request_overrides)
  -> SafeInputBudgetSnapshot
```

`CapacityReservePolicy` is an immutable/frozen SDK model containing
`soft_limit_ratio` as a decimal in `(0, 1]` and an optional non-negative
`approved_profile_reserve_tokens`. `request_overrides` contains only an optional
positive `requested_output_tokens`.

`SafeInputBudgetSnapshot` is immutable/frozen and contains the W1 capacity fingerprint,
provider hard input limit, requested output, uncertainty or approved profile-specific
reserve, soft and hard input limits, sources, warnings, and its own deterministic
fingerprint.
Typed failures include `invalid_reserve_policy`, `requested_output_exceeds_capacity`,
`uncertainty_reserve_basis_unknown`, `reserve_exceeds_capacity`, and
`no_safe_input_capacity`.

## Resolution, Deliverables, and Phases

- Request overrides narrow limits unless policy explicitly permits expansion; undefined
  provider limits are omitted from `min(...)`, never treated as zero.
- In release one, request overrides can only increase output reservation and therefore
  narrow input capacity. Existing authorized model/agent configuration may lower the
  configured default; no new override permission system is introduced.
- Deliver the validated policy schema, pure calculator, unified 10% unknown-capability
  reserve, approved profile-specific reserve support, configuration/UI fields, and
  reserve telemetry.
- Phase through observe-only comparison, soft-limit shaping, hard-budget/output-cap
  enforcement through W15, then removal of direct `token_threshold` decisions.
- All callers consume the same snapshot; local reserve recalculation is prohibited.
- Caller-supplied budget snapshots, reserve values, and output caps are untrusted and
  cannot authorize or expand a production model call.

## Implementation Plan

1. Add reserve-policy fields and validation to context/model configuration.
2. Implement a pure `SafeInputBudgetCalculator` using W1 capacity snapshots.
3. Resolve per-request output allowance before context assembly begins.
4. Replace `token_threshold` usage with the calculated soft and hard input budgets.
5. Pass requested output tokens to the provider call consistently.
6. Emit budget snapshots to logs, traces, and monitoring.
7. Surface an operator warning whenever the unified 10% uncertainty reserve is active.
8. Require the trusted server-side dispatch path to resolve or verify the immutable
   budget snapshot and reject caller-expanded limits.

## W2 to W15 Handoff

- W2 calculates exactly one `SafeInputBudgetSnapshot` from the immutable W1 snapshot.
- The W2 snapshot records the W1 fingerprint, selected requested output, reserve
  breakdown, hard input budget, soft input budget, and its own fingerprint.
- W15 rejects a W2 snapshot whose W1 fingerprint, provider/model identity, or requested
  output does not match the active W1 snapshot.
- W15 may reduce selected input content but cannot increase the W2 hard input budget or
  independently recalculate reserves.
- Trusted dispatch verifies the final W15 result references the active W1 and W2
  fingerprints.

## Repository Touchpoints

- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/models/openai_llm.py`
- `sdk/nexent/core/utils/token_estimation.py`
- `backend/agents/create_agent_info.py`
- `backend/utils/monitoring.py`
- Agent/model configuration APIs and frontend forms

## Tests

- Table-driven unit tests for combined windows, separate input limits, known profiles,
  uncataloged configured models, missing uncertainty-reserve basis, and the unified 10%
  uncertainty reserve.
- Property tests assert `safe_input_budget + all reserves` never exceeds a hard limit.
- Tests prove requested output is reserved separately from the 10% uncertainty reserve
  and overrides cannot reduce that reserve.
- Integration tests verify long-answer tasks retain the requested output allowance.
- Regression tests prove compaction starts at the soft limit, not the hard boundary.
- Telemetry tests verify every request records reserve values and source.
- Negative integration tests prove SDK/client-supplied or locally recalculated budgets
  cannot expand the limits enforced at production dispatch.

## Rollout and Definition of Done

Ship in observe-only mode first and compare calculated budgets with current prompt
sizes. Then enforce soft limits, followed by hard budget rejection. W2 is done when
every request reports a reserve breakdown, the provider output cap matches the
reserved allowance, no context builder can consume reserved capacity, and no
caller-supplied budget can weaken server-side enforcement.
