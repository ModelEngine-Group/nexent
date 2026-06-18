# W1 ADR: Capability Profile Catalog, Storage Medium, and Snapshot Fingerprint

| Field | Value |
| --- | --- |
| Status | Accepted |
| Owners | Model integration squad (W1 lead), Agent runtime squad (W2/W10 leads) |
| Affects | [W1](W1_Correct_Model_Token_Capacity_Configuration.md), [W2](W2_Output_and_Safety_Capacity_Reserve.md), [W10](W10_Guaranteed_Context_Fit.md), [W3](W3_Prompt_Cache_Aware_Assembly.md) |
| Related findings | CM-013, CM-016, CM-023 |
| Date | 2026-06-15 |
| Accepted on | 2026-06-15 |
| Supersedes | None |

## Context

W1 requires three concrete answers before implementation begins. The W1 specification
names them in passing but does not pin them down:

1. **What is in the day-one capability profile catalog.** Without an explicit catalog,
   the resolver only knows the `provider_capability_unknown` path and W2/W10 cannot
   activate production dispatch for any model.
2. **Where the catalog lives.** Code module, YAML asset, or DB table determines who
   may edit it, how versioning works, and what "approved" means operationally.
3. **How `ModelCapacitySnapshot.fingerprint` is computed.** W2 and W10 reject mismatched
   fingerprints; without an exact algorithm the contract between W1/W2/W10 cannot be
   verified end-to-end.

These three decisions are coupled (the field set in (3) depends on which fields
the catalog in (2) supplies for the entries in (1)). Resolving them together avoids
spec drift across W1, W2, W10, and W3.

## Decision 1: Day-One Capability Profile Catalog

**Decision:** This ADR defines the **schema, validation rules, and acceptance criteria**
for catalog entries. The list below is a **candidate selection** based on (a) what
Nexent's own test fixtures and benchmarks actually reference and (b) numbers that were
cross-checked against provider documentation on 2026-06-15. The W1 lead **owns the
final day-one roster** and must confirm or replace each entry, with the deciding input
being "which models do production tenants actually run." Names in this ADR are not
authoritative; they are a starting point for that conversation.

### Selection criteria (binding; entries that fail any of these must not ship)

1. The model is **actually run by a production tenant**, or is scheduled to be within
   the day-one window. (Coverage-only entries belong in unit-test fixtures, not in
   the production catalog.)
2. A named owner can **defend the numerical values** against the provider's official
   documentation at merge time and on each subsequent change.
3. The five required behavior dimensions (hard capacity, tokenizer/counting,
   reasoning window, provider overhead, prompt cache) are either filled with a
   verified value or explicitly marked `unknown`. No silent gaps.

### Candidate entries (pending W1 lead validation)

Numbers below were cross-checked against public provider documentation on 2026-06-15;
sources are listed under "Verification sources." Tokenizer-family identifiers
(`o200k_base`, `qwen`, `deepseek`) are **proposed names**, not verified to exist in
the Nexent tokenizer registry — see Open Item 2.

| # | provider | model_name | window shape | context_window_tokens | max_input_tokens | max_output_tokens | default_output_reserve_tokens | tokenizer_family | counting_mode | prompt_cache | rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `openai` | `gpt-4o` | combined | 128000 | — | 16384 | 4096 | `o200k_base` | `exact` (pending registry) | unknown | Legacy but widely deployed OpenAI tier; smallest credible window in the catalog |
| 2 | `openai` | `gpt-4.1` | combined | 1000000 | — | 32768 | 8192 | `o200k_base` | `exact` (pending registry) | unknown | Current OpenAI long-context API; stresses 1M budget arithmetic on the `exact` counting path |
| 3 | `dashscope` | `qwen-plus` | combined | 131072 | — | 16384 | 4096 | `qwen` | `estimated` | unknown | DashScope commercial main tier. Provider advertises up to 1M context but DashScope's default input cap is ~129K unless `max_input_tokens` is set explicitly — using the default is safer for day one |
| 4 | `dashscope` | `qwen-turbo` | combined | 1000000 | — | 16384 | 4096 | `qwen` | `estimated` | unknown | Long-context tier; verifies budget arithmetic at 1M scale where `qwen-plus` runs at default |
| 5 | `dashscope` | `glm-5.1` | combined | 200000 | — | 131072 | 8192 | `chatglm` | `estimated` | unknown | Current stable Zhipu GLM via Alibaba Cloud Bailian direct supply (released 2026-04). Tenants on Nexent run it for non-Qwen Chinese workloads. Excludes deprecated GLM-5 (2026-02) and brand-new GLM-5.2 (2026-06-13, no production-tenant evidence yet) |
| 6 | `silicon` | `deepseek-ai/DeepSeek-V4-Flash` | combined | 1000000 | — | 384000 | 8192 | `deepseek` | `estimated` | unknown | DeepSeek V4 family is what Nexent's own EventQA benchmark already runs against. 384K max output is unusually large and exercises output-cap edge cases |
| 7 | `silicon` | `Qwen/Qwen3.6-27B` | combined | 262144 | — | 65536 | 8192 | `qwen` | `estimated` | unknown | Self-hosted-class deployment via SiliconFlow. Qwen team advises >=128K to preserve thinking quality; output cap conservatively set to 64K (well below 262K theoretical max) for day one |
| 8 | `silicon` | `Pro/moonshotai/Kimi-K2.6` | combined | 262144 | — | 131072 | 8192 | `moonshot` | `estimated` | unknown | Moonshot Kimi via SiliconFlow Pro channel. 262K window and 256K-class output; covers the Moonshot tenant cohort. Output cap conservatively at 128K (below 262K theoretical max) for day one |

Notes:
- The day-one catalog is **eight entries** spanning three providers (OpenAI,
  DashScope, SiliconFlow). The original draft had six entries; GLM-5.1 and Kimi-K2.6
  were added during the 2026-06-15 Open Items round (see Resolution Log). GLM-5 was
  initially also added but dropped — same capacity as 5.1, redundant entry.
- `tokenizer_family` identifiers (`o200k_base`, `qwen`, `chatglm`, `deepseek`,
  `moonshot`) follow the naming rules below. `counting_mode` stays `estimated`
  for every entry until the tokenizer registry ships a verified adapter.
- `prompt_cache = unknown` for every entry. Promoting to `known` requires W3
  verification evidence for that specific provider/model deployment.
- Each entry carries its own `capability_profile_version` string (see Decision 2).
- `modelengine` and `tokenpony` entries are **deliberately excluded from day one**.
  They use the uncataloged-model path (operator-configured hard capacity + 10%
  uncertainty reserve) until a follow-up catalog revision adds them. (Confirmed for
  `modelengine` on 2026-06-15.)
- No model in this catalog uses a separate input limit; current providers' long-
  context tiers all advertise combined windows. The separate-input-limit code path
  is exercised by **unit-test fixtures**, not by a catalog entry.
- GLM-5.2 (released 2026-06-13 with 1M context / 131K output) is **excluded from
  day one** — too new for production-tenant adoption evidence. Candidate for the
  first catalog revision once tenants migrate.

### Tokenizer family naming rules

The tokenizer adapter registry (`sdk/nexent/core/models/tokenizer_registry.py`) maps
each `tokenizer_family` identifier to a counting implementation. Implementation is
owned by the AI Agent squad; this ADR fixes the **naming convention and registry
contract** so the catalog can be filled deterministically.

**Naming convention (binding):**

1. **Lowercase, ASCII, underscores or dots only.** No hyphens (reserves hyphens for
   provider/model strings elsewhere). Pattern: `^[a-z][a-z0-9_.]{0,49}$`.
2. **Use the upstream-canonical name when one exists.** Examples: OpenAI's tiktoken
   encodings (`o200k_base`, `cl100k_base`) are upstream canonical and reused as-is.
3. **For families without an upstream canonical name**, use the lowercased model-
   family slug: `qwen`, `chatglm`, `deepseek`, `moonshot`, `llama`. One identifier
   per **tokenizer family**, not per model — `Qwen/Qwen2.5-*` and `Qwen/Qwen3.6-*`
   share `qwen` if they share the underlying BPE vocab; bump to `qwen2`/`qwen3`
   only if the vocab actually changed.
4. **Unknown / unmapped is allowed.** A catalog entry may set `tokenizer_family:
   null` (or omit it). The resolver then forces `counting_mode = "estimated"`.

**Initial registry mapping (binding for day-one catalog):**

| tokenizer_family | Source of identifier | Used by catalog entries | Notes |
|---|---|---|---|
| `o200k_base` | tiktoken canonical | `openai/gpt-4o`, `openai/gpt-4.1` | Direct use of OpenAI's `tiktoken` library |
| `qwen` | model-family slug | `dashscope/qwen-plus`, `dashscope/qwen-turbo`, `silicon/Qwen/Qwen3.6-27B` | Hugging Face `Qwen/*` tokenizer JSON |
| `chatglm` | model-family slug (matches HF convention) | `dashscope/glm-5`, `dashscope/glm-5.1` | HF `THUDM/chatglm*` or `zai-org/*` tokenizer |
| `deepseek` | model-family slug | `silicon/deepseek-ai/DeepSeek-V4-Flash` | HF `deepseek-ai/*` tokenizer |
| `moonshot` | model-family slug | `silicon/Pro/moonshotai/Kimi-K2.6` | HF `moonshotai/*` tokenizer |

**Registry contract (binding):**

```python
# sdk/nexent/core/models/tokenizer_registry.py
class TokenizerAdapter(Protocol):
    family: str                                       # matches catalog tokenizer_family
    def count_tokens(self, messages: Sequence[dict]) -> int: ...

REGISTRY: Mapping[str, TokenizerAdapter]              # populated by AI Agent squad
FALLBACK: TokenizerAdapter                            # generic estimator, always present

def resolve(family: str | None) -> tuple[TokenizerAdapter, str]:
    """Return (adapter, counting_mode). counting_mode is 'exact' or 'estimated'."""
    if family is None or family not in REGISTRY:
        return FALLBACK, "estimated"
    return REGISTRY[family], "exact"
```

**Promotion criteria — `estimated` → `exact`:**

An adapter is marked `exact` (and `counting_mode = "exact"` flows through to the
snapshot) only when:

1. A fixture suite of ≥100 representative messages compares the adapter's count to
   the **provider's reported token usage** from real API responses.
2. Mean absolute error is **≤0.5%** and max single-message error is **≤2%** across
   the suite.
3. The fixture suite is checked into the repo and runs in CI.

Until these criteria are met, day-one catalog entries stay `estimated` and W2's
10% uncertainty reserve applies — which is the safe behavior CM-016 prescribes.

**Fallback (always-present generic estimator):**

The `FALLBACK` adapter uses `len(json.dumps(messages, ensure_ascii=False)) / 4` as
a coarse character-to-token heuristic. It is **never** marked `exact`. Its purpose
is to avoid hard failures when a catalog entry has an unknown tokenizer family;
operators always see a budget number, just one with the 10% uncertainty reserve
applied.

### Verification sources (consulted 2026-06-15)

- **OpenAI** — gpt-4o, gpt-4.1 specs: OpenAI API documentation
  ([openai.com/index/gpt-4-1/](https://openai.com/index/gpt-4-1/),
  [openai.com gpt-4o-mini introduction](https://openai.com/index/gpt-4o-mini-advancing-cost-efficient-intelligence/)).
- **DashScope (Qwen)** — qwen-plus, qwen-turbo defaults: Alibaba Cloud Model Studio
  docs; default input cap ~129K confirmed via
  [datastudios.org Qwen context window article](https://www.datastudios.org/post/qwen-context-window-token-limits-memory-policy-and-2025-rules)
  and 1M-context blog [qwenlm.github.io/blog/qwen2.5-turbo](https://qwenlm.github.io/blog/qwen2.5-turbo/).
- **DashScope (GLM direct supply)** — Alibaba Cloud Model Studio confirms GLM is
  direct-supplied via 百炼:
  [GLM 大模型服务平台百炼](https://www.alibabacloud.com/help/zh/model-studio/glm),
  [GLM-智谱-百炼](https://help.aliyun.com/zh/model-studio/glm-zhipu).
- **GLM specs** — GLM-5 (200K/128K, Feb 2026) and GLM-5.1 (200K/128K, Apr 2026):
  [apxml.com GLM-5.1 specs](https://apxml.com/models/glm-51),
  [llm-stats.com GLM-5](https://llm-stats.com/models/glm-5),
  [Puter Developer GLM-5.1](https://developer.puter.com/ai/z-ai/glm-5.1/).
  GLM-5.2 (1M/131K, 2026-06-13, excluded from day one):
  [codersera GLM-5.2 release](https://codersera.com/blog/glm-5-2-release-1m-context-coding-2026/).
- **DeepSeek V4-Flash** — 1M context / 384K output: confirmed across
  [Hugging Face DeepSeek-V4-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash),
  [openrouter.ai DeepSeek-V4-Flash](https://openrouter.ai/deepseek/deepseek-v4-flash),
  [llm-stats DeepSeek V4 Flash](https://llm-stats.com/models/deepseek-v4-flash-max),
  Hugging Face blog [deepseekv4](https://huggingface.co/blog/deepseekv4).
- **Qwen3.6-27B** — 262K native context, 262K max output:
  [qwen.ai blog Qwen3.6-27B](https://qwen.ai/blog?id=qwen3.6-27b),
  [Hugging Face Qwen/Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B),
  [marktechpost Qwen3.6-27B release](https://www.marktechpost.com/2026/04/22/alibaba-qwen-team-releases-qwen3-6-27b-a-dense-open-weight-model-outperforming-397b-moe-on-agentic-coding-benchmarks/).
- **Kimi-K2.6** — 262K context / 262K output:
  [Hugging Face moonshotai/Kimi-K2.6](https://huggingface.co/moonshotai/Kimi-K2.6),
  [Kimi K2.6 tech blog](https://www.kimi.com/blog/kimi-k2-6),
  [llm-stats Kimi K2.6](https://llm-stats.com/models/kimi-k2.6).

The W1 lead must re-verify against provider docs at merge time (specs can move).

### Verification sources (consulted 2026-06-15)

- **OpenAI** — gpt-4o, gpt-4.1 specs: OpenAI API documentation
  ([openai.com/index/gpt-4-1/](https://openai.com/index/gpt-4-1/),
  [openai.com gpt-4o-mini introduction](https://openai.com/index/gpt-4o-mini-advancing-cost-efficient-intelligence/)).
- **DashScope** — qwen-plus, qwen-turbo defaults: Alibaba Cloud DashScope Model Studio
  documentation; default input cap ~129K confirmed via
  [datastudios.org Qwen context window article](https://www.datastudios.org/post/qwen-context-window-token-limits-memory-policy-and-2025-rules)
  and 1M-context blog [qwenlm.github.io/blog/qwen2.5-turbo](https://qwenlm.github.io/blog/qwen2.5-turbo/).
- **DeepSeek V4-Flash** — 1M context / 384K output: confirmed across
  [Hugging Face DeepSeek-V4-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash),
  [openrouter.ai DeepSeek-V4-Flash](https://openrouter.ai/deepseek/deepseek-v4-flash),
  [llm-stats DeepSeek V4 Flash](https://llm-stats.com/models/deepseek-v4-flash-max),
  and Hugging Face blog [deepseekv4](https://huggingface.co/blog/deepseekv4).
- **Qwen3.6-27B** — 262K native context, 262K max output, ≥128K recommended for
  thinking: [qwen.ai blog Qwen3.6-27B](https://qwen.ai/blog?id=qwen3.6-27b),
  [Hugging Face Qwen/Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B),
  [marktechpost Qwen3.6-27B release](https://www.marktechpost.com/2026/04/22/alibaba-qwen-team-releases-qwen3-6-27b-a-dense-open-weight-model-outperforming-397b-moe-on-agentic-coding-benchmarks/).

The W1 lead must re-verify against provider docs at merge time (specs can move).

### Catalog completeness rule (binding)

A catalog entry is "complete" only when all five required behaviors are filled in:

1. Hard capacity (`context_window_tokens` or `max_input_tokens` + `max_output_tokens`).
2. `tokenizer_family` and `counting_mode`.
3. Reasoning-window behavior (any provider-side hidden reasoning tokens that count
   against capacity). Encoded as `reasoning_window_behavior: none | reserved | unknown`.
4. Provider-overhead behavior (per-request framing tokens not visible to caller).
   Encoded as `provider_overhead_behavior: negligible | bounded | unknown`.
5. Prompt-cache capability (`prompt_cache: none | supported | unknown`).

If any of (2)–(5) is `unknown` but hard capacity is set, the entry is still usable
and W2 applies the 10% uncertainty reserve per CM-016. If hard capacity is missing,
the entry is invalid and must not ship.

### Out of scope for day one

- Embedding/rerank/TTS/ASR model capacity (W1 explicit non-goal).
- Speculative entries for models Nexent does not run.
- Per-tenant overrides (handled via `capacity_source = "operator"` on `ModelRecord`).

### Rationale

- Six entries is the smallest set that exercises **both window shapes**, **both
  counting modes**, and the **three production providers**, giving W1 a representative
  test surface without becoming a maintenance burden.
- Excluding `modelengine`/`tokenpony` is intentional: their token-accounting behavior
  has not been formally surveyed. Claiming an unverified profile would defeat CM-016.
- Approving entries via PR (see Decision 2) means catalog growth is a normal review
  task, not a separate governance process.

## Decision 2: Catalog Storage Medium

**Decision:** Store the catalog as a **typed Python module** at
`backend/consts/capability_profiles.py`, owned by the backend layer, and pass it as
a parameter to the SDK `ModelCapacityResolver`.

### Layout

```
backend/consts/
  capability_profiles.py        # frozen dataclass catalog, CATALOG_REVISION constant
  capability_profile_types.py   # re-exports SDK types for type hints (no logic)
sdk/nexent/core/models/
  capacity_resolver.py          # ModelCapacityResolver (pure), CapabilityProfile dataclass
  tokenizer_registry.py         # tokenizer_family -> adapter mapping
```

- `CapabilityProfile`, `ModelCapacitySnapshot`, and `ResolverFailure` types live in
  SDK (`sdk/nexent/core/models/capacity_resolver.py`) so the SDK contract is
  self-contained.
- The catalog (concrete entries + revision constant) lives in backend
  (`backend/consts/capability_profiles.py`) so it can read approved provider/tenant
  state in future revisions without violating SDK purity.
- Backend services pass the catalog into the resolver via a `capability_profiles:
  Mapping[ProfileKey, CapabilityProfile]` parameter. The SDK never imports the
  catalog module.

### Versioning rules

- Each entry carries `capability_profile_version: str` (semver-like:
  `"<provider>/<model>@<int>"`, e.g. `"openai/gpt-4o@1"`). Bump the integer suffix
  on any change to that entry's behavior fields.
- A top-level `CATALOG_REVISION: str` constant (e.g. `"2026-06-15.1"`) is bumped on
  every PR that mutates the catalog. Included in monitoring; lets dashboards group
  requests by catalog revision.
- The SDK resolver records the per-entry version (not the catalog revision) into the
  snapshot's `capability_profile_version` field. The catalog revision is a
  deployment-level audit aid, not a per-request identity.

### Why Python module, not YAML or DB

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| Python module (chosen) | Code-reviewed via PR; type-checked; versioned via git; deployed atomically with the code that consumes it; trivial to import from tests | Requires a release to ship a new entry | Best fit for "small, approved" |
| YAML asset | Editable by non-developers | Adds a schema layer; risk of YAML/Python drift; still ships with code so the "easy edit" advantage is illusory | Rejected |
| DB table | Runtime-mutable, per-environment overrides | Conflicts with CM-016 ("approved versioned"); rows are not git-versioned; rollback becomes a data migration; encourages ad-hoc edits that bypass review | Rejected |

Operators that need a per-tenant or per-deployment override use the existing path:
set values on the `ModelRecord` row and the resolver records `capacity_source =
"operator"`. The catalog itself stays as compile-time approved data.

### Layer rule alignment

This satisfies `CLAUDE.md`'s SDK rule: the SDK accepts the profile catalog **via
parameter**; it does not read it from disk, env, or DB. Backend reads from
`consts.capability_profiles` and passes it through, exactly the pattern already
used for env vars in `consts.const`.

## Decision 3: ModelCapacitySnapshot Fingerprint Algorithm

**Decision:** SHA-256 of a canonical JSON serialization of the fingerprint field set,
hex-encoded, truncated to 32 characters (128 bits). Versioned by `resolver_version`,
which is included in the input.

### Algorithm (binding)

```python
import hashlib
import json
from typing import Mapping, Sequence

def compute_fingerprint(
    *,
    resolver_version: str,
    provider: str,
    model_name: str,
    context_window_tokens: int | None,
    max_input_tokens: int | None,
    max_output_tokens: int | None,
    default_output_reserve_tokens: int | None,
    requested_output_tokens: int,
    provider_input_limit_tokens: int,
    tokenizer_family: str | None,
    counting_mode: str,                              # "exact" | "estimated"
    capability_profile_version: str | None,
    unknown_capabilities: Sequence[str],
    field_sources: Mapping[str, str],
) -> str:
    payload = {
        "v": 1,                                       # fingerprint schema version
        "resolver_version": resolver_version,
        "provider": provider,
        "model_name": model_name,
        "context_window_tokens": context_window_tokens,
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
        "default_output_reserve_tokens": default_output_reserve_tokens,
        "requested_output_tokens": requested_output_tokens,
        "provider_input_limit_tokens": provider_input_limit_tokens,
        "tokenizer_family": tokenizer_family,
        "counting_mode": counting_mode,
        "capability_profile_version": capability_profile_version,
        "unknown_capabilities": sorted(unknown_capabilities),
        "field_sources": dict(sorted(field_sources.items())),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]
```

### Field set rationale

| Included | Reason |
|---|---|
| `resolver_version` | Bumped whenever the resolver's own logic changes; prevents stale fingerprints from collapsing across logic versions |
| `provider`, `model_name` | Identity of the dispatch target |
| Four capacity fields (`context_window`, `max_input`, `max_output`, `default_output_reserve`) | The actual numbers W2 derives the budget from |
| `requested_output_tokens` | Per-request choice; W2/W10 must reject a snapshot if request changes |
| `provider_input_limit_tokens` | Derived hard limit; included so a resolver bug that changes derivation can't silently match |
| `tokenizer_family`, `counting_mode` | Determines exact vs estimated path; W2 budgeting depends on it |
| `capability_profile_version` | Per-entry version; matches snapshot to a specific catalog row |
| Sorted `unknown_capabilities` | Different unknowns → different reserves under CM-016; must affect fingerprint |
| Sorted `field_sources` | Two configurations with the same numbers but different provenance (operator vs profile) are not interchangeable for audit |

| Excluded | Reason |
|---|---|
| `warnings` | Informational; may legitimately differ between identical resolutions (e.g., monitoring side-effects) |
| `model_record_id` | An audit pointer, not a contract input |
| Time/clock fields | Determinism requires the fingerprint to be a pure function of the resolved contract |
| `fingerprint` itself | Trivially excluded |

### Cross-workstream verification points

- W2 stores the W1 fingerprint inside `SafeInputBudgetSnapshot`. The W2 fingerprint
  uses **the same algorithm** with its own field set (defined in a sibling W2 ADR if
  needed) and includes the W1 fingerprint as one input — so a W1 change cascades
  through W2 by construction.
- W10 verifies the W1 fingerprint and W2 fingerprint before final assembly. The
  trusted dispatch boundary (CM-013) re-computes both from the active snapshots and
  rejects mismatch with the typed failure `capacity_fingerprint_mismatch`.
- 32 hex chars (128 bits) is sufficient for equality-check use; we are not using the
  fingerprint as a cryptographic commitment. Hex (not base64) keeps logs greppable.

### Resolver version policy

- `resolver_version` is a string constant inside `sdk/nexent/core/models/capacity_resolver.py`,
  e.g. `RESOLVER_VERSION = "1.0.0"`.
- Bump major when the field set in the fingerprint changes (forces all in-flight
  snapshots to become invalid; required for safety).
- Bump minor when resolver logic changes in a way callers must observe (e.g., new
  precedence rules).
- Bump patch for bug fixes that do not change accepted outputs.
- Include in W1 monitoring as a tag.

## Consequences

- **Day-one production scope is intentionally narrow.** Eight profiled models across
  three providers (OpenAI, DashScope, SiliconFlow). Any other model Nexent runs
  hits the uncataloged path: operator-set hard capacity + 10% uncertainty reserve,
  OR `provider_capability_unknown` rejection if hard capacity is also missing.
- **Catalog growth becomes a normal PR.** Adding a model = one entry + version bump
  + test fixture. No separate governance system.
- **The SDK stays pure.** Catalog data flows in via parameter; SDK has no I/O.
- **Fingerprint is deterministic and cross-language-stable** (canonical JSON +
  SHA-256 are reproducible from any runtime that needs to verify them).
- **W2 can begin once this ADR is accepted.** Its only blocker on W1 was the
  snapshot schema and fingerprint algorithm — both pinned here.

## Open items — Resolution Log (2026-06-15)

All five Open Items were addressed in a sign-off round on 2026-06-15. The catalog
table above already reflects these decisions; this log records who decided what.

| # | Item | Resolution | Effect on catalog |
|---|---|---|---|
| 1 | Numeric values for the candidates match official provider docs | **Accepted with additions.** Six original candidates approved. **GLM-5.1 added** as a DashScope-provided entry (Alibaba Cloud direct supply confirmed via Bailian docs); GLM-5 also reviewed but dropped — same 200K/128K shape as 5.1, redundant. W1 lead must re-verify all numbers against provider docs at PR merge time. | 6 candidates + 1 GLM = 7 (plus Kimi from Item 5 → 8 total) |
| 2 | `tokenizer_family` strings match the tokenizer adapter registry | **Rules fixed in this ADR.** Tokenizer registry not yet started; AI Agent squad owns implementation. Naming convention, initial mapping (5 families), registry contract, and promotion criteria are now binding (see "Tokenizer family naming rules" in Decision 1). Day-one entries stay `counting_mode = "estimated"` until adapter verification crosses the ≤0.5% MAE / ≤2% max-error gate. | Identifiers are no longer "(proposed)"; registry can be built directly from the rules |
| 3 | Whether `modelengine` joins day one | **Excluded.** Confirmed not in day-one catalog. Uses the uncataloged path (operator-configured hard capacity + 10% uncertainty reserve) until a follow-up revision adds it. | No `modelengine` entry; note in Decision 1 reflects the decision |
| 4 | `capability_profile_version` naming scheme acceptable to monitoring | **Accepted.** Current scheme `"<provider>/<model>@<int>"` is approved. ~10 distinct values for the day-one catalog. | No change to Decision 2; scheme stays |
| 5 | Whether to add Moonshot Kimi (`Kimi-K2.6`) | **Added.** `silicon/Pro/moonshotai/Kimi-K2.6` is the ninth catalog entry. Verified 262K context / 262K output; output cap conservatively set to 131K for day one. | One new entry; tokenizer family `moonshot` registered |

### Remaining verification gap (not blocking)

The web check covered **hard capacity numbers only**. The five behavior dimensions
required by the catalog completeness rule still have unknowns for every entry:

- `reasoning_window_behavior` — not consistently documented by any provider.
- `provider_overhead_behavior` — not documented at all; must be measured empirically.
- `prompt_cache` — marked `unknown` for every entry; promotion requires W3 evidence.
- `tokenizer_family` is **fixed** by this ADR, but `counting_mode` stays `estimated`
  until the registry's adapter passes the ≤0.5% MAE / ≤2% max-error gate.

Per CM-016, this is expected: incomplete required behavior triggers W2's 10%
context-window uncertainty reserve. Day-one entries ship with these gaps; promotion
to `exact` counting and `known` cache happens incrementally with evidence.

## Definition of done for this ADR

This ADR is accepted when:

- [x] **All five Open Items resolved** (signed off 2026-06-15; see Resolution Log).
- [x] **W2 and W10 leads signed off on Decision 3 fingerprint algorithm** (2026-06-15).
      They will use the same algorithm shape (different field sets) for their own
      snapshot fingerprints.
- [x] **Type skeleton PR merged** into `feature/model-capacity-and-request-safety`
      (2026-06-15). Adds `backend/consts/capability_profiles.py`,
      `sdk/nexent/core/models/capacity_resolver.py`,
      `sdk/nexent/core/models/tokenizer_registry.py`.
- [x] **Status flipped to Accepted** (2026-06-15).

Current status: **Accepted.** ADR closes here. Implementation continues in W1
follow-up PRs (DB migration, resolver implementation, provider adapter updates,
frontend, monitoring).

## Known Limitations (added post-acceptance)

These limitations were discovered during end-to-end testing of the W1 stack and
do not invalidate the ADR. They are recorded here so reviewers of follow-up
workstreams know the trade-offs that were intentionally left in W1's scope.

### CM-031 (formerly KL-1): Catalog miss for the default `model_factory` (2026-06-15)

**Observation.** The catalog is keyed on `(provider, model_name)` where
`provider` is the lower-cased value of `model_record_t.model_factory`. The
backend Pydantic schema for `ModelRequest` sets the default `model_factory =
'OpenAI-API-Compatible'`. The frontend "single model" add flow does not expose
a `model_factory` control for LLM/VLM models, so most manually-added LLM rows
end up with `model_factory = 'OpenAI-API-Compatible'`, which lower-cases to
`'openai-api-compatible'` and matches none of the catalog provider keys
(`openai`, `dashscope`, `silicon`).

**Auxiliary gap.** `_infer_model_factory` in
`backend/services/model_health_service.py` does infer `dashscope` from URLs
containing the substring, but it is **only called inside the
`embedding`/`multi_embedding` branch** of `model_management_service`. LLM/VLM
records skip the inference entirely.

**Net result.** Manual-add LLM models hit `ProviderCapabilityUnknown` at
resolve time and fall back to `_TOKEN_THRESHOLD_LEGACY_FALLBACK` (32768; was
8192 at W1 acceptance, retuned during W2 end-to-end validation — see W2
commit log) for `ContextManagerConfig.token_threshold`. The monitoring
record for such a request leaves all capacity columns null.

**Workarounds shipped with W1.**

- Operators can directly set `model_factory` to a catalog provider key via DB
  (`UPDATE nexent.model_record_t SET model_factory = 'dashscope' WHERE
  model_id = ...`). After this, subsequent requests hit the catalog
  (verified end-to-end 2026-06-15 with glm-5.1: `capability_profile_version =
  'dashscope/glm-5.1@1'`, `capacity_source = 'profile'`).
- Models added via the "provider browser" tab (SiliconFlow / DashScope /
  TokenPony) already get the correct `model_factory` from the provider hook
  and hit the catalog normally.

**Why not fix in W1.** The product fix has two design questions —
(a) extend `_infer_model_factory` to cover LLM (cheap, ~5 lines), or
(b) add a "suggest capacity at add time" UX with fuzzy catalog matching
(richer, see workstream proposal) — that should be decided in a fresh
workstream rather than shoehorned into a closed ADR. Tracked in
`doc/working/context-management-workstreams/W11_Capacity_Suggestion_On_Model_Add.md`.

### CM-032 (formerly KL-2): Provider-level "Edit Config" batch dialog does not expose capacity

**Observation.** `ProviderConfigEditDialog`, when invoked from the provider-
level "Edit Config" button (as opposed to the per-model gear icon), applies
settings to every model from one provider at once. Capacity fields
(`context_window_tokens` et al.) are per-model and not meaningful as a
batch operation, so the dialog hides them via `hideCapacityFields={true}` in
that path. The per-model gear path in the same dialog **does** expose them
(fix landed 2026-06-16).

**Why this is a limitation, not a bug.** Operators who want to batch
provision capacity for, say, all silicon models at once must either run a
SQL UPDATE or use the per-model gear icon for each row. A future workstream
could add a batch capacity panel; W1 does not.
