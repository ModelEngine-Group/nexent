# Nexent Benchmark Framework - Generic Runner

基于 Langfuse 的通用 benchmark 框架，用于评估 Nexent Agent 在不同配置下的表现。

## 目录结构

```text
generic/
|-- run_benchmark.py
|-- run_context_manager_comparison.py
|-- run_legacy_p_comparison.py
|-- run_failed_item_repeats.py
|-- run_integrity.py
|-- common/
|-- runtime/
|-- provenance/
|-- tools/
|-- integrations/langfuse/
|-- evaluators/
|-- configs/
`-- datasets/
```

JSONL、GAIA 附件和运行产物不放在 Git 工作区，默认使用：

```text
$NEXENT_BENCHMARK_DATA_ROOT/
├── datasets/
└── artifacts/
```

可通过 `NEXENT_BENCHMARK_DATA_ROOT` 覆盖该根目录。

## 快速开始

### 1. 导出 Agent 配置

```bash
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 7 --output sdk/benchmark/generic/configs/agent_7.yaml
```

### 2. 运行实验

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --agent-config sdk/benchmark/generic/configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer
```

### 3. 查看结果

打开 Langfuse UI: http://localhost:3100 → Datasets → gsm8k-n10 → Runs

## 详细文档

- [export_agent_config.py documentation](./tools/EXPORT_AGENT_CONFIG.zh-CN.md)
- [run_benchmark.py 使用文档](./RUN_BENCHMARK.md)

## 可用评分器

| 评分器 | 说明 | 适用场景 |
|--------|------|----------|
| `numeric_answer` | 提取数字并比较 | 数学题、计算题 |
| `exact_match` | SQuAD 标准化后精确匹配 | 短答案 QA |
| `em` | exact_match 的别名 | 同上 |
| `f1` | Token 级 F1 分数 | 开放式 QA |
| `keyword_match` | 关键词命中率 | 需要包含特定关键词的回答 |

## 环境要求

- Python 3.11（使用 backend/.venv）
- Langfuse v2 SDK（`langfuse<3`）
- PostgreSQL 连接（Docker 环境：localhost:5434）

## 完整工作流示例

```bash
# 1. 导出多个 Agent 配置
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 5 --output sdk/benchmark/generic/configs/agent_5.yaml
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 7 --output sdk/benchmark/generic/configs/agent_7.yaml

# 2. 使用不同 Agent 运行同一数据集
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --agent-config sdk/benchmark/generic/configs/agent_5.yaml \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer \
  --run-name gsm8k-agent5

backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --agent-config sdk/benchmark/generic/configs/agent_7.yaml \
  --dataset gsm8k-n10 \
  --evaluators numeric_answer \
  --run-name gsm8k-agent7

# 3. 重新评分（不调用 LLM，秒级完成）
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --rescore \
  --dataset gsm8k-n10 \
  --existing-run gsm8k-agent7 \
  --evaluators em f1 exact_match

# 4. 在 Langfuse UI 对比不同 run 的结果
```
