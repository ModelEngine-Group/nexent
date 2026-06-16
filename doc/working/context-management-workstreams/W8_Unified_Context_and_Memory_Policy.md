# W8: Unified Context and Memory Policy

## Objective

Replace distributed, partially enforced context and memory behavior with one validated,
versioned policy engine used by every strategy, projection, memory operation, and model
request.

## Policy Domains

W8 owns policy resolution, authority/conflict decisions, selection decisions, and
memory-operation permission. It does not serialize final prompts, reduce content, or
persist events/memory; W15, W9-W10, W4, and memory services execute approved decisions.

Define `ContextPolicy` with a nested `MemoryPolicy`. The policy covers:

- Component injection, mandatory status, minimum fidelity, and total/per-type budgets.
- Deterministic selection, degradation, and utility-per-token rules.
- Source trust, authority tiers, scope, privacy, and allowed representations.
- Memory write destination, eligibility, confirmation, expiry, update, and no-write rules.
- Retrieval scopes, global reranking, deduplication, lifecycle filtering, and conflicts.

Reject invalid policy during configuration, not during a live run. Every resolved policy
has an immutable version and source metadata.

## Authority Contract

Resolve conflicts in code before prompt assembly using this order:

1. System security and platform policy.
2. Authorized tenant policy.
3. Explicit current-user instruction or correction.
4. Confirmed Working Memory for the active task.
5. Recent verified events and tool results.
6. Valid retrieved long-term memory.
7. Compressed summaries.
8. Unverified agent inference.

Relevance never grants authority. Retrieved content remains attributed and below
authoritative instructions. Conflicts and exclusions emit reason-coded decisions.

The initial release supports a finite conflict set. Cross-tier conflicts are resolved
by the authority ordering above. Same-tier conflicts take the rule with higher
specificity; when specificity is equal, the more recent rule wins. Incomparable
conflicts that cannot be resolved by these rules return `authority_conflict_unresolved`
and do not silently select either side. Multi-source memory conflicts are handled by
global retrieval resolution for deduplication, lifecycle filtering, and contradiction
detection; unresolvable conflicts are excluded from injection. All unresolved conflicts
emit a stable reason code visible through W7 inspection and W13 measurement. An
exhaustive conflict-resolution ontology is explicitly out of scope. **Finding:** CM-017.

## Selection Contract

All strategies must first install mandatory minimum representations. Remaining budget
is spent deterministically on admissible upgrades. Injection flags in
`sdk/nexent/core/agents/summary_config.py` are applied before selection. Total and
per-component budgets are hard constraints. The same memory policy governs automatic
and tool-driven writes, retrieval, update, expiry, and deletion.

## Policy Service Contracts

```text
resolve_policy(identity, agent_config, request_overrides) -> ResolvedPolicy
select_context(resolved_policy, context_items, safe_input_budget) -> SelectionDecision
decide_memory_operation(resolved_policy, candidate_or_query) -> MemoryDecision
```

`ResolvedPolicy` contains immutable merged rules, sources, version, validation report,
and fingerprint. Decisions contain selected/excluded IDs, conflicts, required
confirmation, target scope/destination, budgets, and stable reasons. Required failures
include `policy_invalid`, `override_not_permitted`, `mandatory_budget_impossible`,
`authority_conflict_unresolved`, and `memory_operation_denied`.

## Subagent Policy Independence

Subagent sessions resolve their own W8 policy based on their agent configuration.
The parent agent's policy does not apply to the subagent's internal context selection
or memory operations. When a subagent returns its final answer to the parent, the
parent's W8 policy governs how that result is integrated into the parent's context.

## Merge and Bypass Rules

- Merge precedence is platform, tenant, agent, user configuration, then permitted
  request override; lower layers cannot weaken higher-layer security/privacy rules.
- Selection and memory decisions are pure and deterministic for identical inputs.
- Runtime callers receive decisions, not mutable policy objects.
- Every context strategy, automatic memory flow, and memory tool call must pass through
  the service; bypass detection is release-blocking.
- SDK/client-supplied policy decisions are untrusted. The trusted model-dispatch and
  governed-persistence boundaries require a current immutable server-resolved decision
  bound to the operation, identity, resource, and policy version; missing or mismatched
  decisions fail closed.

## Required Deliverables and Phases

- Deliver schemas, version registry, resolver, validators, authority/conflict engine,
  selection engine, Memory Policy Engine, decision events/traces, and inspection API.
- Phase through shadow decisions, context-selection enforcement, memory-read
  enforcement, memory-write/confirmation enforcement, then removal of bypass paths.

## Implementation Plan

1. Define policy schemas, merge precedence, validation, and versioning ADR.
2. Implement policy resolver and deterministic authority/conflict resolver.
3. Route all context strategies through one selection interface.
4. Route `store_memory` and `search_memory` tools plus automatic memory flows through
   the Memory Policy Engine.
5. Add global cross-scope retrieval resolution.
6. Emit policy decisions and expose authorized inspection through W7.
7. Mark runtime paths that bypass policy as deprecated with a notice that they will
   be removed in the next version.
8. Enforce server-resolved policy decisions at model dispatch and governed persistence
   boundaries.

## Repository Touchpoints

- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/tools/store_memory_tool.py`
- `sdk/nexent/core/tools/search_memory_tool.py`
- `sdk/nexent/memory/`
- `backend/services/memory_config_service.py`

## Tests and Definition of Done

- Matrix tests cover every strategy, injection flag, budget, authority tier, conflict,
  confirmation requirement, scope, and no-write classification.
- Determinism tests produce identical decisions for identical inputs and policy version.
- Bypass tests prove every context and memory path invokes the engine.
- Negative integration tests prove caller-supplied, stale, or mismatched decisions
  cannot authorize dispatch or persistence.
- Invalid policy fixtures fail before run start with actionable errors.
- Performance baseline tests measure policy resolution and context selection latency
  to ensure W8 does not become a bottleneck on the model request hot path.
- W8 is done when one versioned policy explains and enforces every context selection
  and memory lifecycle decision.
