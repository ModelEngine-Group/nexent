# W16: Prompt-Cache-Aware Assembly

## Objective

Increase provider prompt-cache reuse by making stable prompt prefixes deterministic,
observable, and resistant to unnecessary per-request changes.

## Assembly Contract

Prompt assembly is partitioned into:

1. Stable authoritative prefix: system/security instructions and stable tool schemas.
2. Semi-stable policy/configuration context.
3. Dynamic Working Memory, retrieval, history, tool observations, and current input.

Within each partition, use canonical serialization and deterministic component ordering.
Do not place timestamps, request IDs, user-specific dynamic text, or unstable map
ordering in stable prefixes unless required for correctness. Cache optimization never
overrides W3 fit, W10 authority, W11 minimum fidelity, or W14 privacy.

## Observability

For providers that expose cache usage, record cached input tokens, uncached input
tokens, hit/reuse ratio, estimated savings, stable-prefix fingerprint, and the reason
the prefix changed. For providers without metrics, track deterministic prefix equality
as a proxy and label it clearly.

Define a prefix-change reason registry: system prompt version, tool schema version,
policy version, agent version, ordering change, provider serialization change, and
unexpected nondeterminism.

## Implementation Plan

1. Inventory current prompt assembly and identify stable/dynamic boundaries.
2. Define canonical serializer and ordering shared with W3 token verification.
3. Refactor assembly into explicit partitions without changing authority order.
4. Remove avoidable timestamps and unstable serialization from stable prefixes.
5. Add prefix fingerprints and provider cache-usage extraction.
6. Add dashboards and regression benchmarks for repeated-turn workloads.
7. Document provider-specific cache behavior and safe invalidation.

## Repository Touchpoints

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/models/openai_llm.py`
- System prompt, tool schema, skill, memory, and agent-definition assembly paths
- SDK/backend monitoring modules

## Tests and Definition of Done

- Determinism tests produce byte-identical stable prefixes for unchanged configuration.
- Change tests attribute every prefix invalidation to a known reason.
- Repeated-turn benchmarks show measurable cached-input reuse on supported providers.
- Regression tests prove authority ordering, privacy, and fit remain unchanged.
- Provider-agnostic tests work when cache metrics are unavailable.
- W16 is done when stable prefixes are deterministic, cache usage and invalidation are
  observable, and supported providers meet the W15 cache-reuse target.

