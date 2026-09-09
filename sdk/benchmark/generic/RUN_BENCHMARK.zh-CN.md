# run\_benchmark.py 使用文档

统一的 benchmark 运行器，替代 `run_experiment.py` 和 `re_evaluate.py`。

## 功能

- 从 YAML 配置文件加载 Agent 参数
- CLI 参数覆盖 YAML 配置
- 运行新实验（调用 LLM）
- 重新评分已有结果（不调用 LLM）
- 上传数据集 + 运行一体化
- 记录 Web Search → Fetch 证据与工具成本统计
- Exa 结果 record/replay
- 只对已有 run 的失败题做小范围重复实验

## 命令行参数

### Agent 配置

| 参数               |  必填 | 说明                                               |
| ---------------- | :-: | ------------------------------------------------ |
| `--agent-config` |  否  | Agent YAML 配置文件路径（由 `export_agent_config.py` 生成） |

### 数据集

| 参数             |  必填 | 说明                              |
| -------------- | :-: | ------------------------------- |
| `--dataset`    |  ✅  | Langfuse 数据集名称                  |
| `--upload`     |  否  | JSONL 文件路径（上传后运行）               |
| `--input-key`  |  否  | JSONL 中问题字段的 key（默认 `question`） |
| `--output-key` |  否  | JSONL 中答案字段的 key（默认 `answer`）   |

### 评分器

| 参数                  |  必填 | 说明                        |
| ------------------- | :-: | ------------------------- |
| `--evaluators`      |  否  | 评分器名称列表（默认 `exact_match`） |
| `--list-evaluators` |  否  | 列出所有可用评分器并退出              |

**可用评分器**：

| 评分器              | 说明               | 适用场景         |
| ---------------- | ---------------- | ------------ |
| `numeric_answer` | 提取数字并比较          | 数学题、计算题      |
| `exact_match`    | SQuAD 标准化后精确匹配   | 短答案 QA       |
| `em`             | exact\_match 的别名 | 同上           |
| `f1`             | Token 级 F1 分数    | 开放式 QA       |
| `keyword_match`  | 关键词命中率           | 需要包含特定关键词的回答 |
| `gaia_exact_match` | GAIA 标准化最终答案精确匹配 | GAIA 正式准确率 |
| `gaia_final_answer` | 最终答案格式、候选与提交损失诊断 | 放在 `gaia_exact_match` 之后 |

### Agent 执行参数（覆盖 YAML）

| 参数                     | 说明                      |
| ---------------------- | ----------------------- |
| `--max-steps`          | 最大执行步数                  |
| `--temperature`        | LLM 温度；标准导出 YAML 不含该字段，不传时通常使用 `0.1` |
| `--language`           | 提示语言（`en` / `zh`）       |
| `--duty-prompt`        | 角色描述 prompt             |
| `--constraint-prompt`  | 约束条件 prompt             |
| `--few-shots-prompt`   | Few-shot 示例 prompt      |
| `--system-prompt-file` | 自定义系统 prompt 文件（跳过模板引擎） |
| `--tenant-id` | builtin skill tools 的运行范围；默认依次取 CLI、YAML `agent_info.tenant_id`、`tenant_id` |
| `--skills-path` | builtin skill tools 使用的本地 Skill 根目录；未传时读取 `SKILLS_PATH` |

`--language` 会选择和生产相同的公共 Prompt 模板与 ContextItem 装配路径。
Benchmark 与生产使用相同的 Nexent 固定身份描述：

```text
zh -> Nexent 是一个开源智能体平台，基于 MCP 工具生态系统，提供灵活的多模态问答、检索、数据分析、处理等能力。
en -> Nexent is an open-source agent platform built on the MCP tool ecosystem, providing flexible multimodal Q&A, retrieval, data analysis, and processing capabilities.
```

`--language` 不会翻译 YAML 中的 `duty_prompt`、`constraint_prompt` 或
`few_shots_prompt`；这些 Agent 自定义字段必须来自待测生产版本。切换语言后应重新生成对应
snapshot，不能把 `en` snapshot 用于 `zh` run。

### 上下文管理

PR #3475 后 ContextManager/ContextItems assembly 始终启用。配置控制的是
`processing_mode`，而不是选择 Legacy/Managed runtime。

**YAML 配置示例**：
```yaml
agent_config:
  enable_context_manager: true  # 或 false
```

**CLI 参数**：

| 参数                          | 说明        |
| --------------------------- | --------- |
| `--context-processing-mode passthrough` | 同一 ContextItems assembly，不执行 adaptive compaction |
| `--context-processing-mode adaptive_compact` | 启用 adaptive compaction |
| `--enable-context-manager` | 兼容别名，映射为 `adaptive_compact` |
| `--disable-context-manager` | 兼容别名，映射为 `passthrough` |
| `--token-threshold` | 压缩阈值；Benchmark 默认 32,768 |
| `--soft-input-budget` | 显式 soft input budget；默认跟随 threshold，即 32,768 |
| `--hard-input-budget` | 显式 hard input budget；默认是 threshold 的 1.1 倍，即 36,044 |
| `--budget-profile` | 预算来源/实验意图分类，只写入 manifest，不改变预算计算 |
| `--context-window-tokens` | 记录到 ContextManager 的 context-window 值；默认 32,768，当前不会执行完整生产容量解析 |

预算解析规则：

- 显式传入 `--soft-input-budget` / `--hard-input-budget` 时，ContextManager 直接使用这两个值；
- 未显式传入时，Benchmark 使用 Nexent 的 32K legacy fallback：threshold/soft 为 32,768，
  hard 为 `int(32768 * 1.1)`，即 36,044；显式修改 threshold 时，soft/hard 继续按
  threshold 和 `threshold * 1.1` 派生；
- `--context-window-tokens` 当前不会根据模型的 `max_input_tokens`、输出预留和 uncertainty
  reserve 自动推导 soft/hard，因此已经显式传入预算时通常不需要再传它；
- 默认 hard 是 legacy threshold guard，并不是根据 provider 容量计算的安全输入上限；正式实验仍应
  根据模型容量显式传入 soft/hard；
- P (`passthrough`) 仍执行 hard-budget 防护；超过 hard 后会报错，而不是无限制调用模型；
- C (`adaptive_compact`) 压缩后仍超过 hard 时会报
  `Context input remains over the model hard budget after compaction`。

`run_benchmark.py` 可记录以下 profile：

| profile | 含义 |
|---|---|
| `legacy_threshold` | 仅使用旧 `token_threshold` 及其 1.1 倍 hard 派生 |
| `production_like` | 调用方已按生产容量规则计算并显式传入预算 |
| `synthetic_trigger` | 人为降低 soft 以提高压缩触发率，同时把 hard 保持在可安全运行的容量内 |
| `synthetic_stress` | 人为收紧 soft/hard，用于观察压缩极限和 hard-budget 失败，不作为正常准确率对照 |

profile 是归因标签，不是容量解析器。若直接调用 `run_benchmark.py` 且显式预算但不传
profile，manifest 会记录 `explicit_unclassified`。

**逻辑流程**：
1. 从 YAML 读取旧 `enable_context_manager`，映射为 policy；
2. `--context-processing-mode` 优先覆盖 YAML；
3. 创建带 `PolicyLayers` 的 `ContextManagerConfig`；
4. P/C 始终使用 `context_runtime=context_items`。

### 执行控制

| 参数                  | 说明           |
| ------------------- | ------------ |
| `--max-concurrency` | 最大并行数（默认 1）  |
| `--item-id` | 精确选择一个 DatasetItem ID；可重复传入 |
| `--exa-cache-mode` | `off`、`record` 或严格 `replay` |
| `--exa-cache-path` | record/replay 使用的 JSON 文件 |
| `--run-name`        | 自定义运行名称      |
| `--dry-run`         | 仅上传数据集，不运行实验 |

Web evidence、Exa replay、失败题重复与 GAIA 最终答案诊断的完整使用方法见
[`WEB_BENCHMARK_OPTIMIZATIONS.zh-CN.md`](./integrations/langfuse/WEB_BENCHMARK_OPTIMIZATIONS.zh-CN.md).

### 重新评分模式

| 参数               | 说明                |
| ---------------- | ----------------- |
| `--rescore`      | 启用重新评分模式（不调用 LLM） |
| `--existing-run` | 要重新评分的已有运行名称      |

## 使用示例
 `source backend/.venv/bin/activate` 激活环境

### 场景 1：使用 Agent 配置运行实验

```bash
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer \
  --run-name gsm8k-math-assistant-zh
```

### 场景 2：CLI 参数覆盖 YAML 配置

```bash
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --max-steps 20 \
  --temperature 0.2 \
  --language zh \
  --evaluators numeric_answer em f1
```

### 场景 3：不用 YAML，纯 CLI 参数

```bash
python run_benchmark.py \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer \
  --duty-prompt "你是一个专业的数学解题助手，仅输出最终数字答案。" \
  --max-steps 15 \
  --run-name gsm8k-custom-prompt
```

### 场景 4：重新评分已有结果（秒级，不调 LLM）

```bash
python run_benchmark.py \
  --rescore \
  --dataset gsm8k-n10 \
  --existing-run gsm8k-math-assistant \
  --evaluators em f1 exact_match
```

### 场景 5：上传新数据集并运行

```bash
# 先只上传，确认无误
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset my-new-benchmark \
  --upload data/test.jsonl \
  --evaluators numeric_answer \
  --dry-run

# 确认后运行实验
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset my-new-benchmark \
  --evaluators numeric_answer
```

### 场景 6：对比不同 Agent 配置

```bash
# Agent A
python run_benchmark.py \
  --agent-config configs/agent_5.yaml \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer \
  --run-name gsm8k-agent5

# Agent B
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer \
  --run-name gsm8k-agent7

# 在 Langfuse UI 中对比两个 run 的结果
```

### 场景 7：使用自定义系统 prompt

```bash
# 创建自定义 prompt 文件
cat > my_prompt.txt << 'EOF'
你是一个专业的数学解题助手。
请仔细阅读题目，逐步推导，最后只输出数字答案。
不要输出解题过程。
EOF

# 使用自定义 prompt
python run_benchmark.py \
  --dataset gsm8k-n10 \
  --system-prompt-file my_prompt.txt \
  --evaluators numeric_answer \
  --run-name gsm8k-custom-system-prompt
```

### 场景 8：选择上下文处理策略

```bash
# 自适应压缩
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --context-processing-mode adaptive_compact \
  --token-threshold 10000 \
  --evaluators numeric_answer

# 同一 ContextItems assembly，不压缩
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --context-processing-mode passthrough \
  --evaluators numeric_answer
```

## 配置优先级

**CLI 参数 > YAML 配置 > 默认值**

```
--duty-prompt "..."           → 覆盖 YAML 中的 duty_prompt
--max-steps 20                → 覆盖 YAML 中的 max_steps
--context-processing-mode adaptive_compact → 覆盖 YAML policy
--temperature 0.5             → 覆盖默认值 0.1
```

## 完整工作流

```bash
# 1. 导出 Agent 配置
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 7 --output configs/agent_7.yaml

# 2. 运行实验
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer

# 3. 用不同评分器重新评分（不调用 LLM）
python run_benchmark.py \
  --rescore \
  --dataset gsm8k-n10 \
  --existing-run gsm8k-n10-1720432800 \
  --evaluators em f1 exact_match keyword_match

# 4. 在 Langfuse UI 查看结果
# http://localhost:3100 → Datasets → gsm8k-n10 → Runs
```

## Context processing P/C 标准对照

使用 `run_context_manager_comparison.py` 一次执行两组同代码配对实验：

完整参数和运行规范见
[`RUN_CONTEXT_MANAGER_COMPARISON.md`](./RUN_CONTEXT_MANAGER_COMPARISON.md)。

- P：`context_items + passthrough`；
- C：`context_items + adaptive_compact`。

默认先对每组运行一个 item 的 smoke test，再执行正式实验：

```bash
python sdk/benchmark/generic/run_context_manager_comparison.py \
  --dataset gaia-level1-web-search \
  --run-prefix gaia-context-20260723 \
  --repeat 3 \
  --soft-input-budget 10000 \
  --hard-input-budget 891808 \
  --budget-profile synthetic_trigger \
  --required-url data-process=http://localhost:5010/health \
  --runner-args \
    --agent-config path/to/gaia-agent.yaml \
    --evaluators gaia_exact_match \
    --max-steps 20 \
    --temperature 0
```

关键行为：

- 两组共享 dataset、item 顺序、模型、tools、prompts、budget 和 evaluator；
- 每轮随机交错 P/C 执行顺序，并记录实际顺序；
- system prompt 模板使用相同实验时间；
- run name 自动包含 phase、repeat 和组别；
- 本地或 Langfuse 已存在同名 run 时拒绝启动；
- smoke 使用相同的前 N 个 item，正式运行可用 `--formal-items` 限制；
- 每轮运行后校验 resolved manifest 的非目标字段一致；
- 输出不可覆盖的 JSON 和 Markdown 配对报告。

报告中的比较口径：

```text
P vs C：同一 ContextItems runtime 下 adaptive compaction 的增量效果
```

历史 L 基线固定为 `32152c3bf7d43c37ff36336080d120284a42046d`，只在独立
worktree 中运行。L/P 比较是架构迁移效果，不能和 P/C 的策略归因混为一谈。

外部工具依赖通过重复传入 `--required-url NAME=URL` 纳入启动前检查。健康检查返回
5xx 或无法连接时，任何 Agent/LLM 调用开始前即终止。

## 输出示例

```
Loading agent config from: configs/agent_7.yaml
  Agent: 数学解答助手
  Description: 你是一个数学解答助手，擅长解答GSM8K等数学问题...

Evaluators: ['numeric_answer']
Langfuse connected: http://localhost:3100

Configuration:
  Max steps:    15
  Temperature:  0.1
  Language:     en
  Context mgr:  True
  Duty prompt:  你是一个专业的数学解题助手，负责解答各类数学计算问题...

  10 items loaded

============================================================
Running experiment: gsm8k-math-assistant
  Dataset:      gsm8k-n10 (10 items)
  Model:        deepseek-v4-flash
============================================================

[1/10] {"question": "Janet's ducks lay 16 eggs..."} ✓ numeric_answer=1.00
[2/10] {"question": "A robe takes 2 bolts..."} ✓ numeric_answer=1.00
...
[10/10] {"question": "Josh decides to try..."} ✗ numeric_answer=0.00

============================================================
Experiment complete: gsm8k-math-assistant
  Total:  10
  Passed: 9
  Failed: 1
  Avg numeric_answer: 0.9000

View in Langfuse: http://localhost:3100/dataset/xxx
============================================================
```

每个 trace output 和 step metadata 分开记录两类缓存：

- `compression.summary_cache_hits` / `summary_cache_types`：ContextManager 本地摘要复用；
- `provider_cache`：provider 明确返回的 prompt/KV prefix cache usage。

`summary_cache_hits` 只统计 `previous_cache_hit` 和 `current_cache_hit`；
未调用压缩模型的 `stable_bypass` 不等同于复用已有 summary，因而不计入。

`provider_cache.status` 的语义：

- `available`：provider 返回了可信 cache token 字段，可计算 hit rate 和 cached input ratio；
- `unavailable`：provider capability 已知，但本次响应没有 cache metrics；
- `unsupported`：当前 provider capability 未声明支持。

只有 `available` 调用进入 `provider_prefix_hit_rate` 的分母。`unavailable` 和
`unsupported` 不会按 0% 命中处理，也不会通过 estimated/API token 差值推断。

运行 DeepSeek 官方接口时应显式声明：

```bash
--model-factory deepseek
```

OpenAI 官方接口使用 `--model-factory openai`。未知 provider 默认是 `unsupported`；
benchmark 不会仅凭 OpenAI-compatible URL 擅自启用。

## 重新评分输出示例

```
Evaluators: ['em', 'f1', 'exact_match']
Langfuse connected: http://localhost:3100

Rescore 'gsm8k-math-assistant-rescore': 10 traces from 'gsm8k-math-assistant'
  [1] scores={'em': 1.0, 'f1': 1.0, 'exact_match': 1.0}
  [2] scores={'em': 1.0, 'f1': 1.0, 'exact_match': 1.0}
  ...
  [10] scores={'em': 0.0, 'f1': 0.5, 'exact_match': 0.0}

Rescore 'gsm8k-math-assistant-rescore' DONE: 9/10 passed
  avg_em=0.9000
  avg_f1=0.9500
  avg_exact_match=0.9000
```

## 环境变量

### 必需

| 变量                    | 说明            |
| --------------------- | ------------- |
| `LLM_API_KEY`         | LLM API 密钥    |
| `LLM_MODEL_NAME`      | LLM 模型名称      |
| `LLM_API_URL`         | LLM API 地址    |
| `LANGFUSE_HOST`       | Langfuse 服务地址 |
| `LANGFUSE_PUBLIC_KEY` | Langfuse 公钥   |
| `LANGFUSE_SECRET_KEY` | Langfuse 私钥   |

### 可选

| 变量                 | 说明            | 默认值    |
| ------------------ | ------------- | ------ |
| `LANGFUSE_ENABLED` | 是否启用 Langfuse | `true` |

## 故障排除

### Langfuse 连接失败

```bash
# 检查 Langfuse 容器状态
docker ps | grep langfuse

# 检查环境变量
echo $LANGFUSE_HOST
echo $LANGFUSE_PUBLIC_KEY
echo $LANGFUSE_SECRET_KEY
```

### LLM API 调用失败

```bash
# 检查 LLM 配置
echo $LLM_API_URL
echo $LLM_MODEL_NAME

# 测试 API 连接
curl -X POST $LLM_API_URL/chat/completions \
  -H "Authorization: Bearer $LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "'$LLM_MODEL_NAME'", "messages": [{"role": "user", "content": "test"}]}'
```

### 数据集不存在

```bash
# 先上传数据集
python run_benchmark.py \
  --dataset my-dataset \
  --upload data/test.jsonl \
  --dry-run

# 或检查 Langfuse UI 中是否存在该数据集
```

### 评分器不存在

```bash
# 列出所有可用评分器
python run_benchmark.py --list-evaluators
```

## 性能优化

### 并行执行

```bash
# 增加并行数（注意 LLM API 限制）
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --max-concurrency 5 \
  --evaluators numeric_answer
```

### 减少 LLM 调用

```bash
# 使用重新评分模式（不调用 LLM）
python run_benchmark.py \
  --rescore \
  --dataset gsm8k-n10 \
  --existing-run previous-run \
  --evaluators em f1
```

### 减少步数

```bash
# 限制最大步数（减少 token 消耗）
python run_benchmark.py \
  --agent-config configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --max-steps 5 \
  --evaluators numeric_answer
```

## 与旧脚本的对比

| 功能          | run\_experiment.py | re\_evaluate.py | run\_benchmark.py |
| ----------- | ------------------ | --------------- | ----------------- |
| 运行新实验       | ✅                  | ❌               | ✅                 |
| 重新评分        | ❌                  | ✅               | ✅                 |
| 从 YAML 加载配置 | ❌                  | ❌               | ✅                 |
| CLI 覆盖配置    | 部分                 | 部分              | ✅                 |
| 上传数据集       | ✅                  | ❌               | ✅                 |
| 统一入口        | ❌                  | ❌               | ✅                 |

**结论**：`run_benchmark.py` 完全替代 `run_experiment.py` 和 `re_evaluate.py`。
## Prompt 与 Tool assembly

Benchmark 不经过 `backend/agents/create_agent_info.py`，因此在 benchmark assembly 中显式模拟
生产的被动注入行为：

- YAML `tools:` 只保存 Agent 显式配置的工具；
- 运行时额外注入 `parallel_executor`；
- 运行时额外注入 `run_skill_script`、`read_skill_md`、`read_skill_config`、
  `write_skill_file`；
- builtin skill tools 使用 `agent_id`、`tenant_id`、`version_no` 和 skills path
  标记运行范围，不要求用户把它们写入 YAML；
- YAML `skills:` 当前尚未实现生产的 Skill 发现、可见性过滤和完整执行链路。非空
  `skills:` 不应被描述成已经完全对齐生产。

trace output 的 `system_prompt` 使用生产 `ContextItemRenderer` 渲染压缩前静态上下文，因此
`### Available Resources` 会包含实际装配的工具名称、描述、输入 schema 和输出类型，而不再
只是空的资源标题。

## 运行完整性检查

`run_integrity.py` 是独立的只读事后检查器，用于检查 dataset item 覆盖、重复 item、评分器
score 覆盖、trace output 必需字段、trace errors，以及可选 manifest 一致性：

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_integrity.py \
  --dataset gaia-level1-reasoning \
  --run-name YOUR_RUN_NAME \
  --evaluators gaia_exact_match \
  --manifest $NEXENT_BENCHMARK_DATA_ROOT/artifacts/manifests/YOUR_RUN_NAME.manifest.json
```

返回码 `0` 表示完整，`1` 表示检查发现缺失或不一致，`2` 表示连接、认证或输入问题。
