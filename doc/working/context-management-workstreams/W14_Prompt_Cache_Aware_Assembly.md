# W14: Prompt-Cache-Aware Assembly

## Objective

Increase provider prompt-cache reuse by making stable prompt prefixes deterministic,
observable, and resistant to unnecessary per-request changes.

## Assembly Contract

W14 owns deterministic partition planning and allowed cache-directive advice. It does
not own final provider payload assembly or fingerprints, does not change authority,
selection, fit, or privacy decisions, and must degrade correctly when a provider has no
prompt-cache capability.

W14 consumes the selected W1 capability profile. Cache directives are emitted only
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
overrides W15 fit, W8 authority, W9 minimum fidelity, or W11 privacy.

## Observability

For providers that expose cache usage, record cached input tokens, uncached input
tokens, hit/reuse ratio, estimated savings, stable-prefix fingerprint, and the reason
the prefix changed. For providers without metrics, track deterministic prefix equality
as a proxy and label it clearly.

Define a prefix-change reason registry: system prompt version, tool schema version,
policy version, agent version, ordering change, provider serialization change, and
unexpected nondeterminism.

## Partition-Plan Interface and Final Manifest

```text
partition_for_cache(provider, selected_representations, policy_version)
  -> CachePartitionPlan
```

The plan contains partition assignments, deterministic ordering rules, allowed cache
directives when supported, and anticipated prefix-change reasons. W15 consumes the plan
and alone produces the final ordered provider payload, exact serialized token count,
stable-prefix fingerprint, full-prompt fingerprint, and final prefix-change manifest
from the exact payload accepted for dispatch. W14 never fingerprints a pre-fit payload,
dispatches requests, or changes authority/selection decisions.

## Subagent Cache Optimization

Subagent sessions apply W14 cache optimization independently using their own agent
configuration. The subagent's cache partition plan is scoped to the subagent's
session and does not interact with the parent session's cache optimization.

## Canonicalization and Provider Rules

- Each provider adapter declares supported cache boundaries/directives and versioned
  serialization behavior through the approved W1 capability profile.
- Stable partitions contain no request IDs, timestamps, unstable map order, or dynamic
  user/session data unless correctness requires them.
- A component moves between partitions only through an approved/versioned rule.
- Unexpected stable-prefix changes emit `unexpected_nondeterminism` and fail
  determinism tests; cache unavailability degrades to normal uncached execution.

## Required Deliverables and Phases

- Deliver partition-plan schema, canonical ordering/serializer integration,
  provider cache adapters, final-manifest interpretation, change-reason detector,
  metrics, dashboards, and repeated-turn benchmark suite.
- Phase through prefix inventory/measurement, deterministic assembly, provider cache
  directives, dashboards, then optimization against W13 targets.

## Implementation Plan

1. Inventory current prompt assembly and identify stable/dynamic boundaries.
2. Define partition and ordering rules consumed by W15's canonical serializer.
3. Refactor assembly into explicit partitions without changing authority order.
4. Remove avoidable timestamps and unstable serialization from stable prefixes.
5. Add W15-produced final-payload fingerprints and provider cache-usage extraction.
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
- Integration tests prove W15 computes fingerprints from the exact final dispatched
  payload and the trusted dispatch path does not modify prompt/cache content.
- Change tests attribute every prefix invalidation to a known reason.
- Repeated-turn benchmarks show measurable cached-input reuse on supported providers.
  Performance baseline tests for repeated-turn workloads are lower priority (after
  functional implementation is stable).
- Regression tests prove authority ordering, privacy, and fit remain unchanged.
- Provider-agnostic tests work when cache metrics are unavailable.
- Unknown-cache-capability tests prove no cache directive is emitted and proxy prefix
  equality is never labeled as a provider cache hit.
- W14 is done when stable prefixes are deterministic, cache usage and invalidation are
  observable, and supported providers meet the W13 cache-reuse target.

## Codebase Gap Analysis (2026-06-17)

**Verdict: High value, low effort, zero dependencies. Moved to Phase 1.**

### Current state
- **Already cache-aware (partial)**: timestamps excluded from system prompts (`context_utils.py:538`, `core_agent.py:483`) with explicit comments about KV cache stability
- **Zero provider integration**: no cache directives sent to OpenAI API, no `cache_control` parameter
- **Zero metrics extraction**: `cached_tokens`, `cache_read_input_tokens` not read from usage objects
- **All models mark "unknown"**: every entry in `capability_profiles.py` leaves `prompt_cache` as "unknown"
- **No prefix fingerprinting**: no mechanism to detect or log stable-prefix changes

### Impact potential
- Agent conversations typically have 10-30+ steps with same system prompt prefix
- OpenAI reports 80% latency reduction for cached prompts
- OpenAI charges 50% less for cached input tokens
- Current codebase gets zero benefit despite already trying to stabilize prefixes

### Phase 1 actions (1-2 days)
1. Extract `cached_tokens` from OpenAI usage objects (~5 lines in `openai_llm.py`)
2. Add prefix fingerprinting to monitoring (~50 lines)
3. Populate `prompt_cache` field in `capability_profiles.py`
4. Inject `cache_control` parameter for supported providers (~10 lines)

### Risk
Memory injection into system prompt (`create_agent_info.py:622`) makes prefix user-specific. Must move to dynamic partition or cache hits will be per-user only.
