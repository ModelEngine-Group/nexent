# W2: Output and Safety Capacity Reserve

## Objective

Derive and enforce a per-request safe input budget that preserves room for model
output, provider framing, reasoning behavior, and token-estimation error.

## Dependencies and Scope

W2 depends on W1's capacity snapshot and tokenizer contract. It owns budget
calculation and reserve policy. It does not own component selection or truncation;
W3, W10, and W11 consume the resulting budget.

## Budget Contract

For each request:

```text
provider_input_limit =
  min(max_input_tokens, context_window_tokens - requested_output_tokens)
  using only limits that are defined

safe_input_budget =
  provider_input_limit
  - provider_overhead_reserve
  - reasoning_reserve
  - estimation_error_reserve
```

`requested_output_tokens` is bounded by `max_output_tokens`; it defaults to
`default_output_reserve_tokens` and may be overridden per agent or request.
All reserve decisions and their sources are included in request telemetry.

## Policy Model

Introduce a validated `CapacityReservePolicy` with provider defaults and bounded
operator overrides:

- Output reserve: expected maximum answer size.
- Provider overhead reserve: chat framing, tool schemas, and provider-added tokens.
- Reasoning reserve: only for providers/models where reasoning consumes the window.
- Estimation error reserve: fixed tokens, percentage, or the larger of both.
- Soft-limit ratio: point at which proactive compaction begins.

Invalid or negative remaining budgets fail configuration before a model call. Requests
may lower an output reserve only when policy permits and must record the decision.

## Implementation Plan

1. Add reserve-policy fields and validation to context/model configuration.
2. Implement a pure `SafeInputBudgetCalculator` using W1 capacity snapshots.
3. Resolve per-request output allowance before context assembly begins.
4. Replace `token_threshold` usage with the calculated soft and hard input budgets.
5. Pass requested output tokens to the provider call consistently.
6. Emit budget snapshots to logs, traces, and monitoring.
7. Surface an operator warning when fallback capacity or tokenizer estimates force a
   large safety margin.

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

- Table-driven unit tests for combined windows, separate input limits, missing values,
  provider overhead, reasoning reserve, and estimation margins.
- Property tests assert `safe_input_budget + all reserves` never exceeds a hard limit.
- Integration tests verify long-answer tasks retain the requested output allowance.
- Regression tests prove compaction starts at the soft limit, not the hard boundary.
- Telemetry tests verify every request records reserve values and source.

## Rollout and Definition of Done

Ship in observe-only mode first and compare calculated budgets with current prompt
sizes. Then enforce soft limits, followed by hard budget rejection. W2 is done when
every request reports a reserve breakdown, the provider output cap matches the
reserved allowance, and no context builder can consume reserved capacity.

