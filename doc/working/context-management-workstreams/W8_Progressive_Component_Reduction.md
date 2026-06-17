# W8: Progressive Component Reduction

## Objective

Preserve critical capabilities under token pressure by progressively reducing each
component to an admissible minimum representation instead of dropping it whole.

## Representation Model

W8 owns admissible lower-fidelity representations and reduction validation. It does
not choose policy priority, final prompt membership, artifact authorization, or
compaction scheduling; W13, W10, P4, and W6 own those decisions.

Each W12 `ContextItem` may have versioned representations:

| Representation | Use |
| --- | --- |
| `full` | Complete content when budget permits |
| `compressed` | Semantically reduced content |
| `structured` | Minimal typed fields needed for correct behavior |
| `pointer` | Resolvable reference plus enough metadata to decide whether to load |

Each item declares a minimum-fidelity invariant. A reducer may only produce admissible
representations and must refuse a downgrade that violates the invariant. Representation
generation records source fingerprint, queryable source-event lineage inherited from
the source `ContextItem`, generator version, token count, loss metadata, and staleness
status.

## Component Reducers

- Tools: retain name, purpose, and minimal schema; load full schema on demand.
- Skills: shorten descriptions, retain likely matches, and defer full instructions.
- Memory/knowledge: globally rerank, deduplicate, summarize, cap, and preserve attribution.
- Working Memory: always retain active goals, explicit constraints, confirmed decisions,
  and unresolved work.
- Agent definitions: retain routing metadata; load full cards only after selection.
- System instructions: preserve mandatory security and behavior sections.
- History/observations: preserve recent complete steps and tool-call/result integrity.

## Reducer Contract

```text
reduce(context_item, target_representation, budget, policy_version) -> ReductionResult
```

`ReductionResult` contains the representation, source fingerprint, token count,
generator/version, admissibility result, loss metadata, and stable decisions. Required
failures include `unsupported_item_type`, `minimum_fidelity_violation`,
`reducer_failed`, `representation_stale`, `pointer_unresolvable`, and
`target_budget_impossible`.

Reducers never select which items enter the prompt; W13/W10 request admissible
representations. Semantic reducers may call models only through W6/W10-governed paths.
Deterministic structured/pointer fallbacks must exist for every mandatory item type.

Validation of reduction results is split into two layers. Structural validation
(blocks commit): schema validity, source-event reference existence, mandatory
ContextItem presence (item may degrade in tier but cannot disappear), tool-call/result
pair integrity, and representation tier not below the item's declared minimum fidelity.
W8's `minimum_fidelity_violation` checks only representation tier, not content
semantics. Semantic quality (measured, does not block commit): information retention,
constraint/decision/goal coverage, and semantic equivalence are routed to W9 SLO
measurement. A semantic proof system or LLM-based automatic semantic equivalence
validation as a commit gate is explicitly out of scope. **Finding:** CM-018.

## Subagent Reducer Independence

Subagent sessions use their own reducer chain based on their agent configuration.
The parent agent's reducers do not apply to the subagent's internal context
reduction. When a subagent returns its final answer to the parent, the parent's
W13/W8 pipeline governs how that result is represented in the parent's context.

## Representation Lifecycle

- A representation is valid only for its source fingerprint and generator/policy versions.
- Updating or deleting source content invalidates descendants through P2/P5.
- Physical source erasure invalidates each affected representation as a whole; reducers
  do not attempt field-level deletion from generated text.
- Cached representations are immutable; regeneration creates a new version.
- Loss metadata identifies omitted categories and whether they are recoverable.

## Required Deliverables and Phases

- Deliver representation schema/store, reducer registry/interface, admissibility
  validator, reducers per component type, pointer integration, inspection, and metrics.
- Phase through deterministic structured/pointer forms, semantic compressed forms,
  W13/W10 integration, then precomputation/caching based on measured demand.

## Implementation Plan

1. Define reducer interface, representation schema, admissibility checks, and reason codes.
2. Add deterministic reducers for each component type.
3. Generate lower-fidelity forms on demand for deterministic reducers (structured,
   pointer). Cache lower-fidelity forms for semantic reducers (compressed) at
   creation or material update, since regeneration involves LLM calls.
4. Integrate representation selection into W13 policy and W10 final-fit pipeline.
5. Add pointer resolution and fault handling with P4.
6. Emit reduction decisions, lost-content metadata, generation cost, and staleness.
7. Add operator inspection for representation chains.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- W12 context-item/projector modules
- Tool, skill, knowledge, memory, and agent-definition assembly paths

## Tests and Definition of Done

- Oversized fixtures for every component retain their mandatory minimum.
- Tests reject invalid downgrades and stale representations.
- Round-trip pointer tests recover full content when authorized.
- Quality tests measure retained constraints, decisions, tool capability, and attribution.
- Determinism and token-accounting tests cover each reducer.
- Performance baseline tests measure reducer latency for each component type
  (lower priority, after functional implementation is stable).
- W8 is done when every supported component type has an admissible reduction chain,
  no mandatory minimum is silently dropped, and W10 can consume reducer outputs.
