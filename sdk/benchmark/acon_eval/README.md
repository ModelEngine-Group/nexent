# ACON QA 评估

基于 [ACON](https://github.com/microsoft/acon) 的 `nq_multi_8` 数据集（多目标问题 + Wikipedia 搜索），评估 nexent 上下文压缩对 QA 准确率的影响。

## 目的

对比 **baseline**（不压缩）与 **context_manager**（nexent 内置压缩）在标准化数据集上的任务准确率（EM/F1）、token 消耗和压缩成本。

与 `manual_cases` 不同，这里不使用手工构造的 probe 或 continuation query，而是直接在标准化数据集上衡量：上下文压缩介入后，agent 是否仍能正确回答多跳问题。

## 目录结构

```
acon_eval/
├── data/nq_multi_8/              # ACON 数据集（JSONL）
│   ├── train.jsonl
│   ├── test.jsonl
│   └── folds/                    # few-shot 折叠数据
├── outputs/                      # 各模式结果
│   ├── baseline/test/
│   │   ├── predictions.jsonl     # 逐样本预测 + 得分
│   │   └── summary.json          # 汇总 EM/F1/token 指标
│   └── context_manager/test/
│       ├── predictions.jsonl
│       └── summary.json
├── run_acon_qa.py                # 主入口
├── dataset.py                    # JSONL 加载器 + QAExample 数据类
├── eval_utils.py                 # SQuAD 风格 EM 和 F1 评分
├── tools.py                      # wikipedia_search + final_answer 工具
└── retriever_sesrver.py          # 本地 FastAPI 检索引擎（BM25 over wiki-18）
```

## 前置准备

### 1. 启动 ACON Retriever 服务

下载 BM25 索引（约 2.2GB）和 wiki-18 语料（2018 年英文 Wikipedia 全量快照，约 14GB，约 500 万篇条目），然后启动检索引擎：

```bash
# 下载 BM25 索引
#   https://huggingface.co/datasets/PeterJinGo/wiki-18-bm25-index/tree/main/bm25
# 下载 wiki-18 语料
#   https://huggingface.co/datasets/PeterJinGo/wiki-18-corpus/tree/main
# export OPENAI_API_KEY="xxx" 程序默认需要非空的OPENAI_API_KEY，但是实际上用不到，这里需要占位 

python retriever_server.py \
    --index_path database/wikipedia/bm25/ \
    --corpus_path database/wikipedia/wiki-18.jsonl
```

服务监听在 `http://127.0.0.1:8005/retrieve`。

### 2. 数据集

将 `nq_multi_8` 数据集放入 `data/nq_multi_8/`。数据来源于 Natural Questions，每条样本包含 8 个子问题，需要 agent 通过 Wikipedia 搜索逐一回答。

**数据格式**（JSONL，每行一条）：

```json
{
  "id": "nq_multi8_test_2200",
  "question": "where is the food stored in a yam plant?; who plays lefou in beauty and the beast 1991?; ...",
  "answer": [
    ["an edible tuber"],
    ["Jesse Corti", "Venezuelan voice actor Jesse Corti"],
    ...
  ]
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `id` | 样本唯一标识 |
| `question` | 8 个子问题，用 `; ` 拼接。可通过 `--num_objectives` 截断使用前 N 个 |
| `answer` | 长度为 8 的列表，每个元素是一个 **gold answer 变体列表**（同义词/别名均视为正确） |

`QALoader`（`dataset.py`）负责解析 JSONL，自动兼容 `id`/`qid`/`question_id`、`question`/`query`、`answer`/`answers`/`final_answer` 等多种字段名。

## Agent 工具

`tools.py` 定义了两个 smolagents `Tool` 子类，供 nexent agent 调用。

### wikipedia_search

通过 HTTP POST 调用本地 retriever 服务，在 2018 Wikipedia BM25 索引中进行**关键词检索**（BM25 是基于词频和逆文档频率的词汇匹配算法，非语义搜索）。

**关键约束**：agent 必须通过 `wikipedia_search` 获取答案，**禁止依赖模型自有知识直接作答**。原因：(1) 数据集标注以 2018 Wikipedia 内容为准，模型训练数据可能过时或缺失相关条目；(2) 多跳搜索过程会产生 agent steps 累积，正是压缩评估所依赖的场景。

```python
class WikipediaSearchTool(Tool):
    name = "wikipedia_search"
    inputs = {
        "query": {"type": "string"},
        "n_results": {"type": "integer", "nullable": True},  # 3~10，默认 3
    }
    output_type = "string"

    def forward(self, query: str, n_results: int = 3) -> str:
        # POST http://127.0.0.1:{port}/retrieve
        # payload: {"queries": [query], "topk": n_results, "return_scores": True}
        # 返回 "Retrieved documents:\n\n[Document 0]\n<内容>..."
```

- `n_results` 自动钳位到 [3, 10]
- 返回值是拼接好的文档文本，agent 以 Observation 形式接收
- 端口通过 `--retriever_port` 指定（默认 8005）

### final_answer

提交最终答案，结束当前任务。

```python
class FinalAnswerTool(Tool):
    name = "final_answer"
    inputs = {"answer": {"type": "any"}}
    output_type = "any"

    def forward(self, answer: Any) -> Any:
        return answer
```

### 工具注册

`register_acon_tools()` 将两个类注入到 `nexent.core.tools` 和 `nexent.core.agents.nexent_agent` 模块的命名空间，使 `NexentAgent.create_local_tool()` 能通过 `globals()` 找到它们。`get_acon_tool_configs(port)` 返回对应的 `ToolConfig` 列表。

```python
from tools import register_acon_tools, get_acon_tool_configs
register_acon_tools()
tools = get_acon_tool_configs(port="8005")
```

## 用法

```bash
# Baseline（不压缩）
python run_acon_qa.py \
    --data_folder ./data/nq_multi_8 \
    --split test \
    --mode baseline \
    --num_objectives 4 \
    --limit 10

# Context manager（开启压缩）
python run_acon_qa.py \
    --data_folder ./data/nq_multi_8 \
    --split test \
    --mode context_manager \
    --num_objectives 4 \
    --token_threshold 6000 \
    --keep_recent_pairs 1 \
    --keep_recent_steps 4 \
    --limit 10
```

### 关键参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--mode` | `baseline` | `baseline`（不压缩）或 `context_manager`（开启压缩） |
| `--num_objectives` | `8` | 每个样本使用的子问题数（1-8） |
| `--token_threshold` | `7200` | 触发压缩的 token 阈值 |
| `--keep_recent_pairs` | `1` | 保留不压缩的最近消息对数 |
| `--keep_recent_steps` | `4` | 保留不压缩的最近 agent 步数 |
| `--max_steps` | `30` | 每个样本的最大 agent 步数 |
| `--retriever_port` | `8005` | Retriever 服务端口 |
| `--limit` | 无 | 限制样本数量 |
| `--id_list_file` | 无 | 按指定 ID 列表过滤样本 |

## 评估流程

1. **加载数据集** — `QALoader` 读取 JSONL，生成 `QAExample` 对象（id、question、answer）
2. **构建 agent** — nexent `CoreAgent` 配备 `wikipedia_search` + `final_answer` 工具，以及自定义 QA system prompt，强制按顺序回答子问题并使用 ANSWER_Q 标记
3. **逐样本运行** — agent 回答所有子问题；最终答案按 `;` 拆分后进行逐子问题评分
4. **评分** — SQuAD 风格的归一化 EM 和 max-F1，与 gold answer 变体对比
5. **汇总指标** — token 消耗、步数，以及（context_manager 模式下）压缩 token 成本

### Context Manager 模式细节

在 `context_manager` 模式下，共享的 `ContextManager` 追踪对话 token 数，超过阈值时触发压缩。压缩使用自定义 JSON schema 追踪每个子问题的进度（status、search_counts、answers），确保 agent 不会丢失"哪些子问题已回答/已耗尽"的状态。

> **说明**：该测试场景下不存在 previous history，只有 current 场景下的多步累积。压缩发生在 agent 步数增长的过程中。

## 评分指标

评分逻辑见 `eval_utils.py`，采用 SQuAD 风格的归一化 EM 和 F1。

### 答案归一化（`_normalize_answer`）

在比较前，预测和 gold answer 都会经过以下归一化流水线：

1. **小写化** — 全部转为小写
2. **去标点** — 移除所有英文标点符号
3. **去冠词** — 移除 `a`/`an`/`the`
4. **空白归一** — 多个连续空白合并为一个空格
5. **复数归一** — 长度 > 3 且以 `s` 结尾（非 `ss` 结尾）的单词，去掉末尾 `s`，统一单复数形式

例如 `"the Cats"` → `"cat"`，`"September 1980"` → `"september 1980"`。

### Exact Match (EM)

```python
em = any(normalize(pred) == normalize(gold_variant) for gold_variant in gold_list)
```

- 预测与 **任一** gold 变体归一化后完全一致即判为正确（True/False）
- 每个子问题独立计算，最终 `avg_em = sum(em_list) / n_sub`

### F1

```python
pred_tokens = normalize(pred).split()
gold_tokens = normalize(gold).split()

precision = overlap / len(pred_tokens)
recall    = overlap / len(gold_tokens)
f1        = 2 * precision * recall / (precision + recall)
```

- 在 token 级别计算 precision/recall，取调和平均
- 对每个 gold 变体分别计算 F1，**取最大值**（`f1_max`）
- 每个子问题独立计算，最终 `avg_f1 = sum(f1_list) / n_sub`

### 最终得分

```python
n_sub = len(gold_answer_list)         # 子问题数
em_score = sum(em_list) / n_sub        # 0.0 ~ 1.0
f1_score = sum(f1_list) / n_sub        # 0.0 ~ 1.0
```

如果预测的子答案数量不足，缺失部分补空字符串；超出则截断，始终与 gold 子问题数对齐。

## 输出格式

### `predictions.jsonl`（每行一个 JSON 对象）

```json
{
  "id": "example_id",
  "question": "子问题1; 子问题2; ...",
  "answer": [["gold1_v1", "gold1_v2"], ["gold2"]],
  "prediction": ["pred1", "pred2"],
  "pred_raw": "pred1; pred2",
  "em": 0.5,
  "f1": 0.67,
  "em_list": [true, false],
  "f1_list": [0.8, 0.54],
  "step_count": 12,
  "errors": [],
  "total_input_tokens": 45000,
  "total_output_tokens": 1200,
  "cm_stats": {...},
  "cm_token_counts": {...}
}
```

### `summary.json`

```json
{
  "total": 100,
  "avg_em": 0.42,
  "avg_f1": 0.58,
  "mode": "context_manager",
  "split": "test",
  "num_objectives": 4,
  "avg_input_tokens": 38000,
  "avg_output_tokens": 1100,
  "total_compression_input_tokens": 120000,
  "total_compression_output_tokens": 8000,
  "timestamp": "2026-05-25T..."
}
```

## 设计要点

- **无 prior history** — 与 `manual_cases` 不同，没有预存对话历史。压缩在 agent 步数累积过程中发生。
- **自定义 summary schema** — 摘要追踪每个子问题的状态（answers、status、search_counts），而非通用对话摘要，因为 agent 的任务是结构化的多问题 QA。
- **逐子问题评分** — 预测按 `;` 拆分，每个子答案独立评分后取平均，可细粒度地检测多跳链中哪一环在压缩下断裂。
