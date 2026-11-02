# Nexent model profile source catalog

## Source and scope

Selected upstream TOML files are copied byte-for-byte from
[models.dev](https://github.com/anomalyco/models.dev), commit
`e69e1844210e5cfe7c7e7f68d57328bc7451a51c`.
The original MIT copyright and permission notice is retained in [LICENSE](LICENSE).
All 66 selected upstream files were also checked against `dev` commit
`ab9af7ba4aa16ee65e9f42c01544393f4f49ec44` on 2026-10-16 and are unchanged.

The inventory contains 26 model files, 35 provider-model files and six provider
files. Five provider files are copied from models.dev; the TokenPony provider
is authored by Nexent from its [official documentation](https://docs.tokenpony.cn/).
Its manifest entry explicitly records `origin = "nexent"`, a local revision and
source URL; it is not attributed to the upstream MIT data.
This is source material, not a verified support list. Pricing remains reference
data; this change does not implement cost estimation or change VLM consumers.

## File ownership

- Copied files under `models/` and `providers/` retain upstream paths, spelling, comments and bytes.
- Nexent-authored TOML uses the same schema; its manifest origin, documentation URL and local revision are mandatory.
- `manifest.toml` pins source kinds, paths, hashes and the upstream revision.
- Nexent normalization and API binding rules belong under `rules/` separately;
  do not silently rewrite upstream files.
- Source references are provenance. Saved outlets retain their resolved
  configuration and do not recompose it when the catalog changes.

## Updating the selection

1. Select one upstream commit and inspect its authored schema and generator.
2. Copy reviewed files and their complete `base_model` dependencies.
3. Preserve original bytes and paths; update manifest hashes and revision.
4. Review every field against the versioned Nexent mapping rules, including
   fields retained as references or explicitly ignored.
5. Run integrity, parser, normalization, composition and installed-package
   checks. Run the reusable real-model matrix before declaring support.
6. Keep deleted upstream entries locally unless deliberately removed in a Nexent
   release; do not modify saved outlets automatically.

No upstream TypeScript project, online synchronization or npm dependency is
required at runtime. Model weight licenses and service terms remain separate
from the license of these descriptive files.


## Nexent supplements and complete catalog loading

`resolver.load_source_catalog()` reads source facts only.
`resolver.load_profile_catalog()` additionally validates `rules/manifest.toml`,
reads exact Nexent supplement declarations and publishes immutable atomic views.
The manifest pins each supplement file's digest separately from upstream data.

Exact provider-model supplements bind the copied reasoning controls to registered
OpenAI Chat request fields. They preserve each source's effort enum and budget
bounds, keep unknown bounds unknown, and do not add numeric defaults. Alibaba
China and SiliconFlow toggles use `/enable_thinking`; Volcengine and DeepSeek
use `/thinking/type` through `thinking_toggle_v1`. Effort uses
`/reasoning_effort`, and the declared numeric budget uses `/thinking_budget`.
The separate `alibaba-cn/qwen3.5-plus` rule retains its earlier explicit defaults
and maximum-output declaration. Every known combination is tested through
composition and request rendering; that is not real-provider qualification.

Keep upstream TOML unchanged. Put model rules under `rules/models/` and provider
or exact provider-model rules under `rules/providers/`; update their manifest
hashes when editing. Use the optional `json_fields` table only for JSON-only
values such as explicit null, never as a string alias or arbitrary path patch.

## Complete selected inventory (2026-10-16)

The tables enumerate available configuration references, not a provider/model
support certification. Provider selection does not imply every model is served
by that provider; the exact copied combinations are listed separately below.
Saved outlets are never recomposed by this source update.

### Providers

| Key | Name | Suggested API base URL | Origin |
| --- | --- | --- | --- |
| `alibaba-cn` | [Alibaba (China)](providers/alibaba-cn/provider.toml) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | models_dev |
| `deepseek` | [DeepSeek](providers/deepseek/provider.toml) | `https://api.deepseek.com` | models_dev |
| `siliconflow-cn` | [SiliconFlow (China)](providers/siliconflow-cn/provider.toml) | `https://api.siliconflow.cn/v1` | models_dev |
| `tokenpony` | [TokenPony 小马算力](providers/tokenpony/provider.toml) | `https://api.tokenpony.cn/v1` | nexent |
| `volcengine-coding-plan` | [Volcengine Ark Coding Plan](providers/volcengine-coding-plan/provider.toml) | `https://ark.cn-beijing.volces.com/api/coding/v3` | models_dev |
| `volcengine` | [Volcengine Ark](providers/volcengine/provider.toml) | `https://ark.cn-beijing.volces.com/api/v3` | models_dev |

### Models

| Model key | Name |
| --- | --- |
| `alibaba/qwen3-coder-next` | [Qwen3 Coder Next](models/alibaba/qwen3-coder-next.toml) |
| `alibaba/qwen3.5-27b` | [Qwen3.5 27B](models/alibaba/qwen3.5-27b.toml) |
| `alibaba/qwen3.5-35b-a3b` | [Qwen3.5 35B-A3B](models/alibaba/qwen3.5-35b-a3b.toml) |
| `alibaba/qwen3.5-397b-a17b` | [Qwen3.5 397B-A17B](models/alibaba/qwen3.5-397b-a17b.toml) |
| `alibaba/qwen3.5-flash` | [Qwen3.5 Flash](models/alibaba/qwen3.5-flash.toml) |
| `alibaba/qwen3.5-plus` | [Qwen3.5 Plus](models/alibaba/qwen3.5-plus.toml) |
| `alibaba/qwen3.7-max` | [Qwen3.7 Max](models/alibaba/qwen3.7-max.toml) |
| `alibaba/qwen3.7-plus` | [Qwen3.7 Plus](models/alibaba/qwen3.7-plus.toml) |
| `alibaba/qwen3.8-2.4t-a95b` | [Qwen3.8 2.4T A95B](models/alibaba/qwen3.8-2.4t-a95b.toml) |
| `alibaba/qwen3.8-27b` | [Qwen3.8 27B](models/alibaba/qwen3.8-27b.toml) |
| `alibaba/qwen3.8-flash` | [Qwen3.8 Flash](models/alibaba/qwen3.8-flash.toml) |
| `alibaba/qwen3.8-max` | [Qwen3.8 Max](models/alibaba/qwen3.8-max.toml) |
| `bytedance-seed/seed-2.1-pro` | [Seed 2.1 Pro](models/bytedance-seed/seed-2.1-pro.toml) |
| `deepseek/deepseek-v4-flash-0731` | [DeepSeek V4 Flash 0731](models/deepseek/deepseek-v4-flash-0731.toml) |
| `deepseek/deepseek-v4-flash` | [DeepSeek V4 Flash](models/deepseek/deepseek-v4-flash.toml) |
| `deepseek/deepseek-v4-pro-0813` | [DeepSeek V4 Pro 0813](models/deepseek/deepseek-v4-pro-0813.toml) |
| `deepseek/deepseek-v4-pro` | [DeepSeek V4 Pro](models/deepseek/deepseek-v4-pro.toml) |
| `deepseek/deepseek-v4.1-flash` | [DeepSeek V4.1 Flash](models/deepseek/deepseek-v4.1-flash.toml) |
| `minimax/MiniMax-M2.7` | [MiniMax-M2.7](models/minimax/MiniMax-M2.7.toml) |
| `minimax/MiniMax-M3` | [MiniMax-M3](models/minimax/MiniMax-M3.toml) |
| `moonshotai/kimi-k3` | [Kimi K3](models/moonshotai/kimi-k3.toml) |
| `zhipuai/glm-5.1` | [GLM-5.1](models/zhipuai/glm-5.1.toml) |
| `zhipuai/glm-5.2` | [GLM-5.2](models/zhipuai/glm-5.2.toml) |
| `zhipuai/glm-5.3-flash` | [GLM-5.3-Flash](models/zhipuai/glm-5.3-flash.toml) |
| `zhipuai/glm-5.3` | [GLM-5.3](models/zhipuai/glm-5.3.toml) |
| `zhipuai/glm-5` | [GLM-5](models/zhipuai/glm-5.toml) |

### Provider-model records

| Provider/model request ID | Declared base model |
| --- | --- |
| [alibaba-cn/MiniMax/MiniMax-M2.7](providers/alibaba-cn/models/MiniMax/MiniMax-M2.7.toml) | Standalone upstream record; no base_model declared |
| [alibaba-cn/deepseek-v4-flash](providers/alibaba-cn/models/deepseek-v4-flash.toml) | `deepseek/deepseek-v4-flash` |
| [alibaba-cn/deepseek-v4-pro](providers/alibaba-cn/models/deepseek-v4-pro.toml) | `deepseek/deepseek-v4-pro` |
| [alibaba-cn/deepseek-v4.1-flash](providers/alibaba-cn/models/deepseek-v4.1-flash.toml) | `deepseek/deepseek-v4.1-flash` |
| [alibaba-cn/glm-5.1](providers/alibaba-cn/models/glm-5.1.toml) | Standalone upstream record; no base_model declared |
| [alibaba-cn/glm-5.2](providers/alibaba-cn/models/glm-5.2.toml) | `zhipuai/glm-5.2` |
| [alibaba-cn/glm-5.3](providers/alibaba-cn/models/glm-5.3.toml) | `zhipuai/glm-5.3` |
| [alibaba-cn/glm-5](providers/alibaba-cn/models/glm-5.toml) | Standalone upstream record; no base_model declared |
| [alibaba-cn/kimi-k3](providers/alibaba-cn/models/kimi-k3.toml) | `moonshotai/kimi-k3` |
| [alibaba-cn/qwen3.5-397b-a17b](providers/alibaba-cn/models/qwen3.5-397b-a17b.toml) | Standalone upstream record; no base_model declared |
| [alibaba-cn/qwen3.5-flash](providers/alibaba-cn/models/qwen3.5-flash.toml) | Standalone upstream record; no base_model declared |
| [alibaba-cn/qwen3.5-plus](providers/alibaba-cn/models/qwen3.5-plus.toml) | Standalone upstream record; no base_model declared |
| [alibaba-cn/qwen3.7-max](providers/alibaba-cn/models/qwen3.7-max.toml) | `alibaba/qwen3.7-max` |
| [alibaba-cn/qwen3.7-plus](providers/alibaba-cn/models/qwen3.7-plus.toml) | `alibaba/qwen3.7-plus` |
| [alibaba-cn/qwen3.8-flash](providers/alibaba-cn/models/qwen3.8-flash.toml) | `alibaba/qwen3.8-flash` |
| [alibaba-cn/qwen3.8-max](providers/alibaba-cn/models/qwen3.8-max.toml) | `alibaba/qwen3.8-max` |
| [deepseek/deepseek-flash](providers/deepseek/models/deepseek-flash.toml) | `deepseek/deepseek-v4.1-flash` |
| [deepseek/deepseek-v4-flash](providers/deepseek/models/deepseek-v4-flash.toml) | `deepseek/deepseek-v4.1-flash` |
| [deepseek/deepseek-v4-pro](providers/deepseek/models/deepseek-v4-pro.toml) | `deepseek/deepseek-v4-pro-0813` |
| [siliconflow-cn/Pro/zai-org/GLM-5.1](providers/siliconflow-cn/models/Pro/zai-org/GLM-5.1.toml) | Standalone upstream record; no base_model declared |
| [siliconflow-cn/Pro/zai-org/GLM-5](providers/siliconflow-cn/models/Pro/zai-org/GLM-5.toml) | Standalone upstream record; no base_model declared |
| [siliconflow-cn/deepseek-ai/DeepSeek-V4-Flash](providers/siliconflow-cn/models/deepseek-ai/DeepSeek-V4-Flash.toml) | `deepseek/deepseek-v4-flash` |
| [siliconflow-cn/deepseek-ai/DeepSeek-V4-Pro](providers/siliconflow-cn/models/deepseek-ai/DeepSeek-V4-Pro.toml) | Standalone upstream record; no base_model declared |
| [siliconflow-cn/zai-org/GLM-5.2](providers/siliconflow-cn/models/zai-org/GLM-5.2.toml) | `zhipuai/glm-5.2` |
| [volcengine-coding-plan/deepseek-v4-flash](providers/volcengine-coding-plan/models/deepseek-v4-flash.toml) | `deepseek/deepseek-v4-flash` |
| [volcengine-coding-plan/deepseek-v4-pro](providers/volcengine-coding-plan/models/deepseek-v4-pro.toml) | `deepseek/deepseek-v4-pro` |
| [volcengine-coding-plan/glm-5.3-flash](providers/volcengine-coding-plan/models/glm-5.3-flash.toml) | `zhipuai/glm-5.3-flash` |
| [volcengine-coding-plan/glm-5.3](providers/volcengine-coding-plan/models/glm-5.3.toml) | `zhipuai/glm-5.3` |
| [volcengine-coding-plan/kimi-k3](providers/volcengine-coding-plan/models/kimi-k3.toml) | `moonshotai/kimi-k3` |
| [volcengine-coding-plan/minimax-m3](providers/volcengine-coding-plan/models/minimax-m3.toml) | `minimax/MiniMax-M3` |
| [volcengine/deepseek-v4-flash-ga-260731](providers/volcengine/models/deepseek-v4-flash-ga-260731.toml) | `deepseek/deepseek-v4-flash-0731` |
| [volcengine/deepseek-v4-pro-ga-260813](providers/volcengine/models/deepseek-v4-pro-ga-260813.toml) | `deepseek/deepseek-v4-pro-0813` |
| [volcengine/doubao-seed-2-1-pro-260628](providers/volcengine/models/doubao-seed-2-1-pro-260628.toml) | `bytedance-seed/seed-2.1-pro` |
| [volcengine/glm-5-2-260617](providers/volcengine/models/glm-5-2-260617.toml) | `zhipuai/glm-5.2` |
| [volcengine/glm-5-3-flash-260828](providers/volcengine/models/glm-5-3-flash-260828.toml) | `zhipuai/glm-5.3-flash` |

DeepSeek official `deepseek-flash` declares `deepseek/deepseek-v4.1-flash` as
its base model. The retained `deepseek-v4-flash` request name is marked deprecated
upstream and now routes to V4.1 Flash. Preserve this distinction from the
provider-independent V4 Flash profile. TokenPony has no imported per-model
records; exact request model IDs remain operator-provided until documented.

## Nexent experience precedence

Source TOML remains unchanged. Outlet previews first combine authored model,
provider and exact hosted-model facts, then overlay Nexent supplement rules in
model, provider, exact-combination order. Higher layers replace a parameter's
complete declaration, a named implementation binding or an instruction strategy;
unmentioned keys inherit. Capability changes retain their evidence and previous
values. Permitted user values are applied last; fixed values, schema constraints,
conditions, registered references and protected request paths remain validated.

Composer `profile_policy_composer_v6` participates in catalog revisions. Saving
revalidates the same draft before freezing the outlet; connection checks run after
saving. Existing outlets continue using their stored snapshot without recomposition.
