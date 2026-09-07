# Web Benchmark 观测、回放与失败题复测

这些能力只影响 `sdk/benchmark/generic` 的实验执行和观测，不修改 SDK
工具或生产 Agent 行为。

## 1. Web evidence artifact

每个新 run 都会写入：

```text
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/web_evidence/<run-name>.web-evidence.json
```

每题记录：

- `answer_candidate`；
- Search 定位到的 URL；
- Tavily Extract 或 Terminal 实际 Fetch 的 URL；
- `directly_supports_answer: null`，表示第一阶段不使用语义 judge 推断；
- 尚缺的证据；
- Exa/Tavily/Terminal 调用次数、重复 query、定位 URL 后继续搜索、
  定位 URL 但未 Fetch 等统计。

run 结束时会在控制台打印主要总量。完整事件和逐题统计以 artifact 为准。

## 2. Exa record/replay

首次运行使用 `record`。相同配置和 query 命中缓存时直接复用，miss 才调用 Exa：

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset gaia-level1-web-search \
  --run-name gaia-web-record-r01 \
  --exa-cache-mode record \
  --exa-cache-path /tmp/gaia-web-exa-cache.json \
  --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
  --evaluators gaia_exact_match gaia_final_answer
```

对照实验使用 `replay`：

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset gaia-level1-web-search \
  --run-name gaia-web-replay-r01 \
  --exa-cache-mode replay \
  --exa-cache-path /tmp/gaia-web-exa-cache.json \
  --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
  --evaluators gaia_exact_match gaia_final_answer
```

`replay` 遇到 miss 会立即失败，不允许静默访问真实 Exa。cache key 只包含 query
和影响 Exa 返回的工具参数，不包含 API key。

## 3. 只重复基准 run 的失败题

脚本从已有 run 的主 evaluator 分数中筛选失败 item ID，不创建新数据集：

```bash
backend/.venv/bin/python \
  sdk/benchmark/generic/run_failed_item_repeats.py \
  --dataset gaia-level1-web-search \
  --baseline-run BASELINE_RUN_NAME \
  --run-prefix gaia-web-failures-20260728 \
  --repeat 3 \
  --primary-evaluator gaia_exact_match \
  --runner-args \
    --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
    --language en \
    --max-steps 15 \
    --temperature 0 \
    --model-factory openai
```

脚本为每次重复创建独立 run，并写入：

```text
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/targeted_repeats/<prefix>.targeted-repeat.json
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/targeted_repeats/<prefix>.targeted-repeat.md
```

报告保留每题每次的 pass/fail 以及 pass rate。基准 run 缺少主 evaluator
分数时会报错，不把缺失观测当作失败。

## 4. GAIA final-answer evaluator

推荐 evaluator 顺序：

```bash
--evaluators gaia_exact_match gaia_final_answer
```

`gaia_exact_match` 仍是第一项和正式准确率。`gaia_final_answer` 仅增加诊断分数：

- `gaia_final_answer_present`：是否提交了非空答案；
- `gaia_final_answer_contract`：是否严格使用一次 `FINAL ANSWER:` 且答案简洁；
- `gaia_gold_candidate_seen`：模型生成过程是否曾出现正确候选；
- `gaia_submission_loss`：曾出现正确候选，但最终提交错误。

这些指标不会修改模型输出，也不会在运行时主动纠正答案。
