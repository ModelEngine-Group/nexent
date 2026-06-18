# W13: Unified Context and Memory Policy

## Objective

Replace distributed, partially enforced context and memory behavior with one
validated, versioned policy engine used by context selection, memory operations,
projection consumers, reducers, and model requests.

W13 is the implementation workstream promoted from P3. It is scheduled after W5/W12
because it needs durable events and bounded `ContextItem` inputs, and before W8/W10
because reducers and final fit need enforceable policy decisions.

W13 is successful when context and memory behavior is determined by server-resolved
policy decisions rather than scattered prompt text, duplicated helper logic, or
caller-supplied assertions.

## Scope and Non-Goals

W13 owns:

- `ContextPolicy` and nested `MemoryPolicy` schemas.
- Policy merge, validation, versioning, and resolution.
- Deterministic authority and conflict decisions.
- Context selection decisions over W12 `ContextItem`s.
- Memory read/write/update/delete permission decisions.
- Routing automatic memory flow and memory tools through one policy service.
- Stable decision reason codes and inspection data.
- Bypass detection at trusted model-dispatch and governed-persistence boundaries.

W13 does not:

- Serialize final provider payloads or perform final token counting. W10 owns final
  assembly and fit.
- Generate lower-fidelity representations. W8 owns reducers.
- Persist W5 events or long-term memories. W5 and memory services execute approved
  writes.
- Implement full P5 governance, deletion propagation, redaction, retention, or temporal
  memory lifecycle.
- Implement P4 artifact offload.
- Solve every possible conflict ontology. Release 1 supports a finite, explicit
  conflict set.

## Dependencies

| Dependency | Required contract |
| --- | --- |
| W4 | Trusted identity and ownership resolution. |
| W5 | Durable event/session identity and source references. |
| W12 | `ContextItem` candidates and projection metadata. |
| W2 | Safe input budget used during selection planning. |
| W7 | Inspection surfaces and lifecycle operations that expose policy decisions. |
| W8 | Consumes policy decisions for representation downgrade and upgrade requests. |
| W10 | Consumes selected candidates and rejects stale/missing policy decisions before dispatch. |

P5 remains deferred. W13 must define extension points for P5 metadata without requiring
P5 to be complete in Release 1.

## Policy Domains

Define `ContextPolicy` with nested `MemoryPolicy`.

`ContextPolicy` covers:

- Component injection flags.
- Mandatory status and minimum fidelity.
- Total and per-component budgets.
- Allowed representation tiers.
- Deterministic selection and degradation rules.
- Utility-per-token scoring inputs.
- Authority tiers and conflict behavior.
- Scope and privacy constraints available in Release 1.

`MemoryPolicy` covers:

- Retrieval scopes.
- Global reranking and deduplication behavior.
- Memory write destination and eligibility.
- Update and no-write rules.
- Confirmation requirements where supported.
- Conflict handling for retrieved memories.

Invalid policy is rejected during configuration or run preparation, not during a live
model dispatch.

## Authority Contract

W13 resolves supported conflicts in code before prompt assembly using this order:

1. System security and platform policy.
2. Authorized tenant policy.
3. Explicit current-user instruction or correction.
4. Confirmed Working Memory or active-task state when available.
5. Recent verified W5 events and tool results.
6. Valid retrieved long-term memory.
7. Compressed summaries.
8. Unverified agent inference.

Relevance never grants authority. Retrieved content remains attributed and below
authoritative instructions. Conflicts and exclusions emit reason-coded decisions.

Release 1 conflict rules:

- Cross-tier conflicts are resolved by the authority order above.
- Same-tier conflicts use higher specificity.
- If specificity is equal, more recent evidence wins.
- Incomparable conflicts return `authority_conflict_unresolved`.
- Unresolvable memory conflicts are excluded from prompt injection.
- All unresolved conflicts are visible through W7 inspection and W9 metrics.

## Selection Contract

Selection runs in two phases:

1. Install every mandatory item at its minimum admissible representation.
2. Spend remaining budget deterministically on admissible upgrades.

Total and per-component budgets are hard constraints. If mandatory minima cannot fit,
selection fails with `mandatory_budget_impossible`; W10 may then reject dispatch or
apply only its explicitly allowed emergency behavior.

W13 selection produces decisions, not final messages.

## Policy Service Contracts

```text
resolve_policy(identity, agent_config, request_overrides) -> ResolvedPolicy
select_context(resolved_policy, context_items, safe_input_budget) -> SelectionDecision
decide_memory_operation(resolved_policy, candidate_or_query) -> MemoryDecision
validate_policy_decision(operation, decision, identity, resource, policy_version) -> ValidationResult
```

`ResolvedPolicy` contains immutable merged rules, sources, version, validation report,
and fingerprint.

`SelectionDecision` contains:

- Selected and excluded `ContextItem` IDs.
- Required representation tier per selected item.
- Budget allocations and remaining budget.
- Conflict decisions.
- Mandatory-minimum failures.
- Stable reason codes.
- Policy version and decision fingerprint.

`MemoryDecision` contains:

- Operation type: retrieve, write, update, delete, no-write, confirm-required.
- Allowed scopes and destinations.
- Excluded candidates or query results.
- Conflict and authority decisions.
- Required confirmation details when applicable.
- Stable reason codes.

Required failures:

- `policy_invalid`
- `override_not_permitted`
- `mandatory_budget_impossible`
- `authority_conflict_unresolved`
- `memory_operation_denied`
- `policy_decision_missing`
- `policy_decision_stale`
- `policy_decision_identity_mismatch`
- `policy_decision_resource_mismatch`

## Merge and Bypass Rules

- Merge precedence is platform, tenant, agent, user configuration, then permitted
  request override.
- Lower layers cannot weaken higher-layer security, privacy, or mandatory-context
  rules.
- Selection and memory decisions are pure and deterministic for identical inputs.
- Runtime callers receive immutable decisions, not mutable policy objects.
- Every context strategy, automatic memory flow, `store_memory`, and `search_memory`
  path must call W13.
- SDK/client-supplied policy decisions are untrusted.
- Trusted dispatch and governed persistence boundaries require a current server-resolved
  decision bound to identity, resource, operation, and policy version.
- Missing, stale, or mismatched decisions fail closed.

## Subagent Policy Independence

Subagent sessions resolve their own W13 policy based on their agent configuration.
The parent agent's policy does not govern the subagent's internal context selection or
memory operations. When a subagent's final answer enters the parent context, the
parent's W13 policy governs how that result is selected and represented.

## Codebase Gap Analysis

Current centralization:

- `ContextManager` handles compression, component registry, strategy selection, and
  system prompt assembly.
- Component budgets and injection flags exist but are not consistently enforced at one
  trusted boundary.

Current scattered behavior:

- Memory search before run bypasses `ContextManager`.
- Memory level filtering is duplicated in `create_agent_info.py`,
  `store_memory_tool.py`, and `search_memory_tool.py`.
- End-of-run automatic memory write is outside the context policy path.
- Conflict resolution is expressed as prompt instructions rather than enforced code.
- Some observation and time-injection logic is hardcoded in agent runtime paths.

W13 should consolidate this behavior behind one policy service rather than only
deduplicating helper functions.

## Required Deliverables and Phases

- Deliver policy schemas, merge precedence, validators, resolver, authority/conflict
  engine, context selection engine, Memory Policy Engine, decision validator, reason
  code registry, metrics, and W7 inspection integration.
- Phase through shadow decisions, context-selection enforcement, memory-read
  enforcement, memory-write/confirmation enforcement, and bypass removal.

## Implementation Plan

1. Define policy schemas, default policy, merge precedence, validation, and versioning.
2. Extract duplicated memory-level filtering into a shared W13-owned helper.
3. Implement `resolve_policy` and deterministic authority/conflict resolution.
4. Implement `select_context` over W12 `ContextItem`s and W2 safe input budgets.
5. Route runtime context strategies through `select_context`.
6. Route `search_memory` tool and pre-run memory search through `decide_memory_operation`.
7. Route `store_memory` tool and end-of-run automatic memory writes through
   `decide_memory_operation`.
8. Emit policy decision events/telemetry and expose authorized inspection through W7.
9. Enforce policy-decision validation at W10 dispatch and governed persistence
   boundaries.
10. Remove or fail release tests for bypass paths.

## Repository Touchpoints

- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/agent_model.py`
- `backend/agents/create_agent_info.py`
- `backend/services/agent_service.py`
- `sdk/nexent/core/tools/store_memory_tool.py`
- `sdk/nexent/core/tools/search_memory_tool.py`
- `sdk/nexent/memory/`
- `backend/services/memory_config_service.py`
- W12 projector modules
- W7 lifecycle inspection service
- W10 final-fit and dispatch boundary

## Metrics and Reason Codes

Required metrics:

- Policy resolution latency.
- Context selection latency.
- Number of selected/excluded items by component type.
- Mandatory-budget failure count.
- Memory operation allow/deny/confirm counts.
- Conflict counts by authority tier and resolution reason.
- Bypass detection count.
- Stale or mismatched policy-decision rejection count.

Required reason-code families:

- `selected_mandatory_minimum`
- `selected_budget_upgrade`
- `excluded_budget`
- `excluded_policy_disabled`
- `excluded_lower_authority`
- `authority_conflict_resolved`
- `authority_conflict_unresolved`
- `memory_operation_allowed`
- `memory_operation_denied`
- `confirmation_required`
- `policy_decision_stale`
- `policy_decision_missing`

## Tests and Definition of Done

- Matrix tests cover every strategy, injection flag, budget, authority tier, conflict,
  confirmation requirement, scope, and no-write classification supported in Release 1.
- Determinism tests produce identical decisions for identical inputs and policy version.
- Bypass tests prove every context and memory path invokes W13.
- Negative integration tests prove caller-supplied, stale, or mismatched decisions
  cannot authorize dispatch or persistence.
- Invalid policy fixtures fail before run start with actionable errors.
- Memory tests prove pre-run search, tool search, tool write, and automatic write use
  the same policy service.
- W8 integration tests prove reducers receive representation requirements from W13.
- W10 integration tests prove dispatch requires a current W13 decision.
- Performance baseline tests measure policy resolution and context selection latency.
- W13 is done when one versioned policy explains and enforces every Release 1 context
  selection and memory operation path, and bypass paths fail tests.
