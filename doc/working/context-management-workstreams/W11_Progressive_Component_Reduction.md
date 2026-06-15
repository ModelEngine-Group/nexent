# W11: Progressive Component Reduction

## Objective

Preserve critical capabilities under token pressure by progressively reducing each
component to an admissible minimum representation instead of dropping it whole.

## Representation Model

W11 owns admissible lower-fidelity representations and reduction validation. It does
not choose policy priority, final prompt membership, artifact authorization, or
compaction scheduling; W10, W3, W12, and W13 own those decisions.

Each W6 `ContextItem` may have versioned representations:

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

Reducers never select which items enter the prompt; W10/W3 request admissible
representations. Semantic reducers may call models only through W13/W3-governed paths.
Deterministic structured/pointer fallbacks must exist for every mandatory item type.

## Representation Lifecycle

- A representation is valid only for its source fingerprint and generator/policy versions.
- Updating or deleting source content invalidates descendants through W8/W14.
- Physical source erasure invalidates each affected representation as a whole; reducers
  do not attempt field-level deletion from generated text.
- Cached representations are immutable; regeneration creates a new version.
- Loss metadata identifies omitted categories and whether they are recoverable.

## Required Deliverables and Phases

- Deliver representation schema/store, reducer registry/interface, admissibility
  validator, reducers per component type, pointer integration, inspection, and metrics.
- Phase through deterministic structured/pointer forms, semantic compressed forms,
  W10/W3 integration, then precomputation/caching based on measured demand.

## Implementation Plan

1. Define reducer interface, representation schema, admissibility checks, and reason codes.
2. Add deterministic reducers for each component type.
3. Generate/cache lower-fidelity forms at creation or material update where economical.
4. Integrate representation selection into W10 policy and W3 final-fit pipeline.
5. Add pointer resolution and fault handling with W12.
6. Emit reduction decisions, lost-content metadata, generation cost, and staleness.
7. Add operator inspection for representation chains.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- W6 context-item/projector modules
- Tool, skill, knowledge, memory, and agent-definition assembly paths

## Tests and Definition of Done

- Oversized fixtures for every component retain their mandatory minimum.
- Tests reject invalid downgrades and stale representations.
- Round-trip pointer tests recover full content when authorized.
- Quality tests measure retained constraints, decisions, tool capability, and attribution.
- Determinism and token-accounting tests cover each reducer.
- W11 is done when every supported component type has an admissible reduction chain,
  no mandatory minimum is silently dropped, and W3 can consume reducer outputs.
