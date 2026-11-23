# Context processing P/C 对照实验

`run_context_manager_comparison.py` 是 `run_benchmark.py` 的上层编排器。PR #3475
之后 ContextManager 和 ContextItems assembly 始终启用，实验只改变 processing policy：

| 组别 | Runtime | Policy | 测量目标 |
|---|---|---|---|
| P | `context_items` | `passthrough` | 同一 assembly 下不执行自适应压缩 |
| C | `context_items` | `adaptive_compact` | 执行生产自适应压缩 |

因此：

```text
P vs C = adaptive compaction 的增量效果
```

旧版 Legacy 不在本脚本内运行。历史 L 基线固定为
`32152c3bf7d43c37ff36336080d120284a42046d`，应在独立 worktree/环境中运行，
再由离线 L/P/C 报告层合并结果。不能把 L/C 差异直接称为 compression effect。

## 推荐命令

正式实验应显式设置模型、步数、temperature、soft/hard budget 和预算分类。对于本次
`qwen3.7-max` 配置（context window 1,000,000，输出预留 8,192，生产解析 hard
为 891,808），GAIA 推荐使用低 soft + 生产容量 hard：既提高 C 组压缩触发率，又避免把
正常长轨迹误判为 hard-budget failure。

```bash
backend/.venv/bin/python \
  sdk/benchmark/generic/run_context_manager_comparison.py \
  --dataset gaia-level1-reasoning \
  --run-prefix gaia-reasoning-pc-20260724 \
  --repeat 3 \
  --soft-input-budget 10000 \
  --hard-input-budget 891808 \
  --budget-profile synthetic_trigger \
  --runner-args \
    --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
    --language zh \
    --evaluators gaia_exact_match \
    --max-steps 15 \
    --temperature 0
```

P 组会使用 `passthrough`，C 组使用 `adaptive_compact`；两组共享 soft/hard。soft
只在 C 组触发压缩，hard 对 P/C 都是安全天花板。

一次 smoke：

```bash
backend/.venv/bin/python \
  sdk/benchmark/generic/run_context_manager_comparison.py \
  --dataset gaia-level1-reasoning \
  --run-prefix gaia-reasoning-pc-smoke-20260724 \
  --repeat 1 \
  --formal-items 1 \
  --soft-input-budget 10000 \
  --hard-input-budget 891808 \
  --budget-profile synthetic_trigger \
  --runner-args \
    --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
    --language zh \
    --evaluators gaia_exact_match \
    --max-steps 15 \
    --temperature 0
```

若要使用英文模板，把 `--language` 改为 `en`。

## 参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--dataset` | 必填 | P/C 使用的同一 Langfuse dataset |
| `--run-prefix` | 必填 | 本次实验唯一前缀 |
| `--repeat` | `1` | 正式 P/C 重复次数 |
| `--smoke-items` | `1` | smoke 使用 dataset 前 N 项 |
| `--skip-smoke` | 关闭 | 跳过 smoke |
| `--formal-items` | 全部 | 正式阶段限制前 N 项 |
| `--compression-threshold` | `10000`（未传显式预算时） | 旧式阈值；soft 等于 threshold，hard 自动派生为 1.1 倍 |
| `--soft-input-budget` | 无 | P/C 共用的显式 soft budget；必须与 hard 一起提供 |
| `--hard-input-budget` | 无 | P/C 共用的显式 hard budget；必须大于 soft |
| `--budget-profile` | `legacy_threshold` | 预算来源/实验意图分类；显式预算必须选择 synthetic profile |
| `--seed` | `0` | P/C 执行顺序随机种子 |
| `--required-url NAME=URL` | 无 | 调用模型前做服务可达性预检 |
| `--runner-args` | 无 | 其后参数原样传给 `run_benchmark.py` |

comparison runner 控制以下参数，不能通过 `--runner-args` 覆盖：

```text
--dataset
--run-name
--item-limit
--experiment-time
--context-processing-mode
--enable-context-manager
--disable-context-manager
--token-threshold
--soft-input-budget
--hard-input-budget
--budget-profile
```

comparison runner 接受三个 profile：

| profile | 预算要求 | 实验含义 |
|---|---|---|
| `legacy_threshold` | 只传或默认 `--compression-threshold` | 兼容旧实验；hard 为 threshold 的 1.1 倍 |
| `synthetic_trigger` | 必须显式传 soft/hard | 人为降低 soft 以稳定或大概率触发 C 组压缩，hard 保持为安全容量 |
| `synthetic_stress` | 必须显式传 soft/hard | 同时收紧 soft/hard，专门测压缩极限和 hard failure |

`budget_profile` 只负责正确分类，不改变预算值。comparison runner 不接受
`production_like`，因为 P/C 的主要目标是构造可归因的模拟实验；若需要单次生产容量复现，
可直接调用 `run_benchmark.py --budget-profile production_like`。

`--context-window-tokens` 仍可由 `run_benchmark.py` 接受，但当前 Benchmark 没有完整引入
生产的容量解析，因此它不会自动根据 context window、最大输出、输出预留和 uncertainty
reserve 推导 soft/hard。P/C 已显式传入预算时不要依赖它改变预算。

## Manifest 与公平性校验

每组由 `run_benchmark.py` 写入 schema v3 resolved manifest。P/C 完成后自动检查：

- dataset、item IDs、代码 commit；
- 模型、endpoint、model factory、temperature、max steps；
- tool schema hash、system prompt hash、evaluator；
- parity snapshot hash 和 budget profile；
- 两组均使用 `context_runtime=context_items`；
- P 为 `passthrough`，C 为 `adaptive_compact`；
- resolved hard input budget 存在；
- context policy fingerprint 存在；
- 除 processing policy 外的受控变量一致。

运行时 `ContextEvidence` 合同至少包含：

```text
processing_mode
policy_fingerprint
soft_budget / hard_budget
raw_token_estimate / final_token_estimate
history_compression_triggered
over_hard_budget / compact_exhausted
selected_item_ids / selected_item_types
```

ContextEvidence 仍通过 `agent.final_context` OpenTelemetry event 输出，可使用
`tools/context_evidence_diff.py` 按 item、step、purpose 比较首次输入差异。

## 报告解释

P/C 每轮使用相同 item IDs，并生成二元 outcome matrix：

| 模式 | 含义 |
|---|---|
| `PP` | P、C 都通过 |
| `PF` | P 通过，C 失败，重点检查压缩信息损失 |
| `FP` | P 失败，C 通过，重点检查预算溢出或长上下文改善 |
| `FF` | 两组都失败 |

报告同时分开统计 provider prefix cache 与 ContextManager summary cache。

`passthrough` 不是旧 Legacy：它仍经过 ContextItems assembly、预算估算、工具规范化、
stable-prefix 和 hard-budget 检查。P 超过 hard budget 而失败属于新产品策略结果，必须与
答案错误、工具错误分别统计。

## Prompt/Tool assembly 的使用边界

- `--agent-config` 负责构造实际 duty/constraint、Agent version、显式工具和其他运行参数；
- Benchmark 与生产使用相同的 Nexent 固定身份描述；
- trace 中的 `system_prompt` 使用生产 renderer，`### Available Resources` 应展示实际工具
  及其描述/schema。

Builtin tools 不是生产 Agent 配置里的静态工具。Benchmark 会和生产 assembly 一样被动加入
`parallel_executor` 以及四个 builtin skill tools。没有配置 Skill 时可以不传
`--skills-path`；非空 YAML `skills:` 的发现、tenant/version 可见性过滤和完整执行链路目前
仍未完全模拟。

## L/P/C 历史实验

推荐目录：

```text
nexent/             当前代码，运行 P/C
nexent-legacy-l/    固定在 32152c3bf7d43c37ff36336080d120284a42046d，运行 L
```

L 使用旧版 `--disable-context-manager`。P/C 使用当前代码。三个环境分别保存：

- code commit 和 source snapshot；
- Python/dependency lock；
- model、provider、tool schema；
- dataset item IDs；
- prompt/config hashes。

比较口径：

```text
L vs P = #3475 上下文架构迁移的整体影响
P vs C = 新架构内部 adaptive compaction 的增量效果
L vs C = 产品版本整体效果，不作单变量归因
```
