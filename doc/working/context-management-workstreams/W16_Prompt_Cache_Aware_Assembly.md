# W16: Prompt-Cache-Aware Assembly

## Objective

Increase provider prompt-cache reuse by making stable prompt prefixes deterministic,
observable, and resistant to unnecessary per-request changes.

## Assembly Contract

W16 owns deterministic partitioning and cache-aware assembly metadata. It does not
change authority, selection, fit, or privacy decisions and must degrade correctly when
a provider has no prompt-cache capability.

W16 consumes the selected W1 capability profile. Cache directives are emitted only
when that approved profile explicitly declares the provider/model cache mode. Unknown
cache capability disables directives and falls back to normal deterministic uncached
execution. Unknown cache metrics must never be reported as a cache hit; prefix equality
remains clearly labeled proxy evidence.

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

## Assembly Interface and Manifest

```text
assemble_cache_aware_prompt(provider, selected_representations, policy_version)
  -> PromptAssemblyResult
```

The result contains final ordered provider messages/components, partition boundaries,
stable-prefix bytes/fingerprint, full-prompt fingerprint, expected token counts,
cache directives when supported, and prefix-change reasons. It is passed to W3 for
final serialization/fit verification; W16 never dispatches requests or changes
authority/selection decisions.

## Canonicalization and Provider Rules

- Each provider adapter declares supported cache boundaries/directives and versioned
  serialization behavior through the approved W1 capability profile.
- Stable partitions contain no request IDs, timestamps, unstable map order, or dynamic
  user/session data unless correctness requires them.
- A component moves between partitions only through an approved/versioned rule.
- Unexpected stable-prefix changes emit `unexpected_nondeterminism` and fail
  determinism tests; cache unavailability degrades to normal uncached execution.

## Required Deliverables and Phases

- Deliver partition/assembly schema, canonical ordering/serializer integration,
  provider cache adapters, prefix manifest/fingerprints, change-reason detector,
  metrics, dashboards, and repeated-turn benchmark suite.
- Phase through prefix inventory/measurement, deterministic assembly, provider cache
  directives, dashboards, then optimization against W15 targets.

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
- Unknown-cache-capability tests prove no cache directive is emitted and proxy prefix
  equality is never labeled as a provider cache hit.
- W16 is done when stable prefixes are deterministic, cache usage and invalidation are
  observable, and supported providers meet the W15 cache-reuse target.
