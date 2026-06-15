# W11: Progressive Component Reduction

## Objective

Preserve critical capabilities under token pressure by progressively reducing each
component to an admissible minimum representation instead of dropping it whole.

## Representation Model

Each W6 `ContextItem` may have versioned representations:

| Representation | Use |
| --- | --- |
| `full` | Complete content when budget permits |
| `compressed` | Semantically reduced content |
| `structured` | Minimal typed fields needed for correct behavior |
| `pointer` | Resolvable reference plus enough metadata to decide whether to load |

Each item declares a minimum-fidelity invariant. A reducer may only produce admissible
representations and must refuse a downgrade that violates the invariant. Representation
generation records source fingerprint, generator version, token count, loss metadata,
and staleness status.

## Component Reducers

- Tools: retain name, purpose, and minimal schema; load full schema on demand.
- Skills: shorten descriptions, retain likely matches, and defer full instructions.
- Memory/knowledge: globally rerank, deduplicate, summarize, cap, and preserve attribution.
- Working Memory: always retain active goals, explicit constraints, confirmed decisions,
  and unresolved work.
- Agent definitions: retain routing metadata; load full cards only after selection.
- System instructions: preserve mandatory security and behavior sections.
- History/observations: preserve recent complete steps and tool-call/result integrity.

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

