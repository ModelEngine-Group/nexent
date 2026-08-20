# Nexent 通用 Benchmark Runner

[English version](./README.md)

本目录提供基于 Langfuse 的独立 benchmark 测试框架。它会执行真实的 Nexent
SDK Agent，但不需要启动 Nexent 后端或前端。Langfuse 保存数据集、trace、评分和
dataset run；本地产物保存 manifest、evidence 和对比报告。

## 主要入口

| 脚本 | 用途 |
|---|---|
| `run_benchmark.py` | 执行或重新评分一次不可变 benchmark run |
| `run_context_manager_comparison.py` | 对比当前版本的 passthrough（P）和 adaptive-compaction（C）模式 |
| `run_legacy_p_comparison.py` | 对比固定 Legacy worktree（L）和当前 passthrough（P）模式 |
| `run_failed_item_repeats.py` | 只重复一个已完成 run 中的失败题目 |
| `run_integrity.py` | 检查数据集关联、评分、trace 状态和 manifest |

操作型工具位于 `tools/`；可选的 Langfuse webhook 位于
`integrations/langfuse/`。其余子包负责 task 适配、评分器、manifest、replay 和
evidence 分析。

## 代码与数据目录

源码和标准示例配置提交在本目录下。数据集、附件、日志、生成的配置和运行产物不放入
Git 工作区。

默认外部目录为：

```text
<repo-parent>/nexent-data/benchmark/
├── datasets/
└── artifacts/
```

可通过 `NEXENT_BENCHMARK_DATA_ROOT` 指定其他位置。

Agent配置可以是：

- `configs/gaia_solver.yaml`
- `configs/gsm8k_solver_assistant.yaml`
- `configs/agent_7_test.yaml`

或者导出自定义的Nexent智能体。

configs下跟踪的yaml包括`configs/gaia_example.yaml`，实验专用配置变体和生成的结果文件应保留在本地。

## 端到端 Pipeline

```text
准备 Python 和凭据
  -> 启动 Langfuse
  -> 导入或选择数据集
  -> 运行单题冒烟
  -> 选择单次、P/C 或 L/P 实验
  -> 查看 Langfuse 和本地报告
  -> 验证运行完整性
```

除非步骤中明确切换目录，以下命令都从仓库根目录执行。

### 1. 准备环境

前置要求：

- `backend/.venv` 使用 Python 3.11，并以开发模式安装 SDK；
- 本地安装 Docker 和 Compose 插件，用于启动 Langfuse；
- 真实模型调用需要 `LLM_API_KEY`、`LLM_MODEL_NAME` 和 `LLM_API_URL`；
- 如果 Agent YAML 启用了相应工具，还需提供配置中引用的凭据，例如
  `EXA_API_KEY`。

可选：指定仓库外的数据和产物目录：

```bash
export NEXENT_BENCHMARK_DATA_ROOT=/path/to/benchmark-data
```

不要提交服务、模型或工具密钥。

### 2. 启动并配置 Langfuse

首次启动时复制环境模板，并替换所有 `replace-me` 值：

```bash
cd sdk/benchmark/infra/langfuse
cp .env.example .env
# 继续前先编辑 .env。
docker compose -p nexent-benchmark-langfuse up -d
docker compose -p nexent-benchmark-langfuse ps
curl -s http://localhost:3100/api/public/health
cd ../../../..
```

为 benchmark 进程导出 Langfuse 项目凭据：

```bash
set -a
source sdk/benchmark/infra/langfuse/.env
set +a
export LANGFUSE_HOST=http://localhost:3100
export LANGFUSE_PUBLIC_KEY="$LANGFUSE_INIT_PROJECT_PUBLIC_KEY"
export LANGFUSE_SECRET_KEY="$LANGFUSE_INIT_PROJECT_SECRET_KEY"
```

打开 `http://localhost:3100`，使用同一 `.env` 中的初始化账号登录。服务生命周期和
安全说明见 [本地 Langfuse 部署](../infra/langfuse/README.md)。通用 runner 会直接
连接 Langfuse，不依赖 `ctx_debugger`。

### 3. 导入或选择数据集

如果数据集已存在于当前 Langfuse 项目中，记住数据集名称并继续执行冒烟测试。新建
JSONL 数据集时，每行应包含约定的输入字段和期望输出字段，例如：

```json
{"question": "What is 2 + 2?", "answer": "4"}
```

只导入数据集而不调用模型：

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset my-benchmark \
  --upload /path/to/dataset.jsonl \
  --evaluators exact_match \
  --dry-run
```

JSONL 默认字段为 `question` 和 `answer`；其他 schema 可通过 `--input-key` 和
`--output-key` 指定。向已有 dataset 重复导入可能产生重复 item，因此再次导入前应
先在 Langfuse 中检查数据集。

也可使用 `datasets/gsm8k_loader.py` 下载并导入 GSM8K。GAIA 文件类题目还要求
dataset 中记录的 S3/MinIO 路径能够访问对应附件；准备附件时可使用
`tools/gaia/upload_files.py`。数据集相关细节见
[单次 runner 文档](./RUN_BENCHMARK.zh-CN.md)。

### 4. 执行真实单题冒烟

每次执行都使用新的 run name：

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset gaia-level1-web-search \
  --run-name gaia-web-smoke-YYYYMMDD \
  --item-limit 1 \
  --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
  --language en \
  --evaluators gaia_exact_match \
  --max-steps 15 \
  --temperature 0 \
  --model-factory openai \
  --context-processing-mode passthrough
```

开始正式实验前，应确认控制台结果、Langfuse evaluator score、dataset-run item 和
trace 状态一致。runner 会拒绝本地或 Langfuse 中已存在的同名 run，以保护实验
provenance。

### 5. 选择实验类型

#### 单次实验

使用 `run_benchmark.py` 评估一套配置或一种 context processing policy。它也是两个
对比编排器使用的底层执行器。完整参数、重新评分、输出和完整性检查见
[单次 Benchmark Runner](./RUN_BENCHMARK.zh-CN.md)。

#### 当前版本 P/C 对比

P/C 实验保持代码版本、数据集题目、模型、prompt、工具、评分器和实验时间一致。
P 使用 `passthrough`，C 使用 `adaptive_compact`。真实单题配对验收命令：

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_context_manager_comparison.py \
  --dataset gaia-level1-web-search \
  --run-prefix gaia-web-pc-smoke-YYYYMMDD \
  --skip-smoke \
  --formal-items 1 \
  --repeat 1 \
  --soft-input-budget 10000 \
  --hard-input-budget 900000 \
  --budget-profile synthetic_trigger \
  --runner-args \
    --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
    --language en \
    --evaluators gaia_exact_match \
    --max-steps 15 \
    --temperature 0 \
    --model-factory openai \
    --context-window-tokens 1000000
```

受控参数、parity 要求、配对结果和报告解释见
[P/C Context Processing 对比](./RUN_CONTEXT_MANAGER_COMPARISON.zh-CN.md)。

#### 跨版本 L/P 对比

L/P 使用独立的 Legacy worktree 和 Python 环境，对比当前候选版本的 passthrough
模式。这是端到端的跨版本回归实验；除非 assembly parity 已得到证明，否则不能将
结果解释为仅由 ContextManager 导致。两个 worktree 都要有可用的 Python 环境，并
继承同一套已导出的 Langfuse、模型和工具凭据。

```bash
export REPO_ROOT="$(pwd)"
export LEGACY_ROOT=/path/to/legacy-worktree

backend/.venv/bin/python sdk/benchmark/generic/run_legacy_p_comparison.py \
  --dataset gaia-level1-reasoning \
  --run-prefix gaia-reasoning-lp-smoke-YYYYMMDD \
  --legacy-root "$LEGACY_ROOT" \
  --smoke-only \
  --smoke-items 1 \
  --candidate-soft-input-budget 10000 \
  --candidate-hard-input-budget 900000 \
  --candidate-context-window-tokens 1000000 \
  --candidate-budget-profile synthetic_trigger \
  --runner-args \
    --agent-config "$REPO_ROOT/sdk/benchmark/generic/configs/gaia_solver.yaml" \
    --language en \
    --evaluators gaia_exact_match \
    --max-steps 15 \
    --temperature 0
```

worktree 准备、解释器校验、正式实验和 causal scope 规则见
[L/P 跨版本对比](./RUN_LEGACY_P_COMPARISON.md)。

### 6. 查看并验证结果

在 Langfuse dataset 页面检查 run item、trace、输出和评分。本地对比报告写入：

```text
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/comparisons/          # P/C
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/legacy_p_comparisons/ # L/P
```

单次实验应执行 [单次 runner 文档](./RUN_BENCHMARK.zh-CN.md) 中的只读完整性检查。
在缺失评分、缺失关联、空输出或 trace error 得到解释前，应将 `INCOMPLETE` 视为验收
不通过。每个实验结论都应保留 run name、manifest、源码版本、dataset item ID、评分器
名称和报告。

## 其他文档

- [单次 Benchmark Runner](./RUN_BENCHMARK.zh-CN.md)
- [P/C 对比](./RUN_CONTEXT_MANAGER_COMPARISON.zh-CN.md)
- [L/P 对比](./RUN_LEGACY_P_COMPARISON.md)
- [Agent 配置导出](./tools/EXPORT_AGENT_CONFIG.zh-CN.md)
- [Web evidence 与失败题重复实验](./integrations/langfuse/WEB_BENCHMARK_OPTIMIZATIONS.md)
- [Webhook 服务](./integrations/langfuse/README.md)
- [Webhook 部署](./integrations/langfuse/DEPLOY.md)

公共默认文档使用英文；完整中文版本使用 `.zh-CN.md` 后缀。历史实验报告保留原始
语言，以维护 provenance。
