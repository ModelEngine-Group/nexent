# Agent Context Compression Benchmark

## 目标

评估压缩后 Agent 是否还能正常工作：

- **Continuation**：压缩后是否还能继续任务？
- **Memory Retention**：压缩后是否还能记住关键状态？
- **Token Reduction**：token 是否有效下降？


---

## 两条评估路径

```
benchmark/
├── manual_cases/          # 手工构造的 case，完整评估流水线
├── acon_eval/             # 基于 ACON 数据集的 QA 评估
├── eventqa_eval/          # 基于 EventQA 数据集的长文记忆评估
└── paths.py               # 共享路径解析
```

### 1. manual_cases — 手工 Case 评估

手工构造的测试用例，运行完整评估流水线（continuation、probe、静态检查）。

```
manual_cases/
├── cases/                         # test_benchmark.py 输入
│   └── <case_id>/
│       ├── case.json              # queries, probes, checks, config
│       └── history.json           # 对话历史
├── inspections/                   # summary_inspector.py 输入（独立运行）
│   └── <name>/
│       ├── history.json
│       ├── checks.json            # [{"description": "...", "must_contain": [...]}]
│       ├── _result.json           # 输出：检查结果
│       └── _summary.txt           # 输出：原始摘要文本（--save-summary）
├── reports/                       # test_benchmark.py 输出
│   ├── <case_id>.json            # 单 case 完整报告
│   └── summary.json              # 跨 case 汇总指标
├── agent_runner.py                # agent 运行 + 追踪工具
├── eval_utils.py                  # 关键词评估
├── summary_inspector.py           # 独立摘要检查（低成本，不需要跑 agent）
└── test_benchmark.py              # 完整 benchmark 运行器
```

`case.json` 格式：

```json
{
  "id": "example_infra",
  "history_file": "history.json",
  "queries": [],
  "probes": [],
  "summary_checks": [],
  "task_checks": [],
  "compressed_config": {}
}
```

- `id`：case 唯一标识，也作为报告文件名
- `history_file`：对话历史文件，相对 case 目录（默认 `history.json`）
- `queries`：continuation query
- `probes`：记忆探针问题
- `summary_checks`：静态摘要检查
- `task_checks`：任务结果检查
- `compressed_config`：压缩配置覆盖

`history.json` 格式：

```json
[
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."}
]
```


#### 评估指标

每个 case 跑两组：

1. **baseline**（不压缩）
2. **compressed**（开启压缩）

核心指标：

```python
task_success_retention = compressed_task_score / baseline_task_score

probe_retention = compressed_probe_score / baseline_probe_score

token_reduction = 1 - compressed_tokens / baseline_tokens
```

---

**Continuation Evaluation**
continuation query 模拟真实多轮 Agent。

允许：

- history 增长
- compression 持续发生
- ContextManager 跨轮复用

这是 **有状态** 评估。


**Probe Evaluation**
probe 用于检查压缩后 agent 能否**利用**残留信息回答问题。

重要规则：

- freeze 压缩后的 history snapshot（每个 probe deep copy）
- 每个 probe 独立运行
- probe 不允许修改原始 history（用 deep copy 隔离）
- probe 之间不能共享上下文

压缩只做一次，所有 probe 复用结果：

1. 先从 compressed run 的 `export_summary()` 获取 summary + compression_boundary
2. 用 `build_precompressed_history()` 构建预压缩 history：
   - 被压缩的 pairs 替换为一条 (user=summary, assistant=ack)
   - 保留的尾部 pairs 原样保留
3. 每个 probe 用预压缩 history + compression disabled 运行
4. 避免每个 probe 重复走压缩流程（同样的输入 → 同样的压缩结果，无需重复调 LLM）


### 2. acon_eval — 数据集驱动 QA 评估

使用 ACON 的 `nq_multi_8` 数据集（多目标问题 + Wikipedia 搜索），评估压缩对 QA 准确率的影响。

与 manual_cases 不同，这里**不使用**手工构造的 probe 或 continuation query，而是在标准化数据集上直接对比 baseline 与 compressed 条件下的**任务准确率**（EM/F1）。

```
acon_eval/
├── data/nq_multi_8/              # ACON 数据集（JSONL）
│   ├── train.jsonl
│   ├── test.jsonl
│   └── folds/                    # few-shot 折叠数据
├── outputs/                      # 各模式结果
│   ├── baseline/test/
│   │   ├── predictions.jsonl
│   │   └── summary.json
│   └── context_manager/test/
│       ├── predictions.jsonl
│       └── summary.json
├── agent_runner.py                # agent 运行 + 追踪
├── dataset.py                     # ACON 数据集加载器
├── eval_utils.py                  # EM/F1 评分
├── run_acon_qa.py                 # 主入口
└── tools.py                       # wikipedia_search + final_answer 工具
```

用法：

```bash
# 先启动 ACON retriever 服务（参见 ACON README） https://github.com/microsoft/acon/blob/main/experiments/smolagents/README.md
#  python retriever_server.py  --index_path database/wikipedia/bm25/   --corpus_path database/wikipedia/wiki-18.jsonl
# 上述 retriever_server.py 内容有所更改(参考本目录提供的)，此外，需手动下载 bm25 索引文件 与wiki-18 数据集
# bm25: https://huggingface.co/datasets/PeterJinGo/wiki-18-bm25-index/tree/main/bm25
# wiki-18: https://huggingface.co/datasets/PeterJinGo/wiki-18-corpus/tree/main
python run_acon_qa.py \
    --data_folder ./data/nq_multi_8 \
    --split test \
    --mode baseline \
    --num_objectives 4 \
    --limit 1

python run_acon_qa.py \
    --data_folder ./data/nq_multi_8 \
    --split test \
    --mode context_manager \
    --num_objectives 4 \
    --token_threshold 6000 \
    --keep_recent_steps 4 \
    --enable_reload \
    --limit 1

```

**模式**：`baseline`（不压缩）vs `context_manager`（nexent 内置压缩）。
**说明**：这里的对话历史结构与 manual_cases 不同，该测试场景下不存在previous history，只有 current 场景下的多步。

---

### 3. eventqa_eval — EventQA 长文记忆评估

使用 MemoryAgentBench 的 EventQA 数据集（5 部小说，每部 39 万–53 万 tokens，各 100 道"接下来发生什么"六选一 MCQ），评估压缩对**超长文档记忆**的影响。

与 acon_eval 一样是数据集驱动，但场景不同：整本小说作为待压缩的历史，MCQ 直接作为记忆探针（probe）——题目自带前序事件，天然就是"给你压缩后的摘要，问接下来发生什么"，无需额外构造 probe。

```
eventqa_eval/
├── data/                      # download_data.py 下载的小说（.gitignore，不入库）
│   └── eventqa_full.jsonl
├── outputs/                   # 各书结果
│   └── <book_id>/
│   │   ├── predictions.jsonl  # 逐题 baseline vs compressed 对照
│   │   └── summary.json       # 单书指标
│   └── summary.json           # 跨书汇总
├── download_data.py           # 从 HuggingFace 下载 EventQA 数据
├── dataset.py                 # EventQA 加载器 + 六选一 MCQ 解析
├── eval_utils.py              # 六选一准确率评分
└── run_eventqa.py             # 主入口
```

**两条评估臂**（同一模型，retention 比值干净）：

| 臂 | 压缩 | 小说上下文 |
|---|---|---|
| Baseline | 关闭 | 整本截断到模型窗口后整段喂入（窗口外的题会错） |
| Compressed | 开启 | 整本切块、多轮喂入，真实 ContextManager 增量压缩；MCQ 作为 probe |

两条臂回答**同一批 100 道题**，因此 retention 比值干净：

```python
memory_retention = compressed_accuracy / baseline_accuracy

token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens
```

不评 Continuation——EventQA 的 MCQ 彼此独立，无多轮任务延续。

用法：

```bash
# 一次性：下载 5 部小说（约 13MB，写入 data/）
python download_data.py

# 冒烟测试：1 本书、1 题、小说截断到 4.8 万字符（触发压缩）
python run_eventqa.py --book_limit 1 --limit 1 \
    --max_ingest_chars 48000 --chunk_chars 12000 \
    --token_threshold 3000 --keep_recent_pairs 1

# 完整运行：5 本书 × 100 题
python run_eventqa.py
```

**说明**：`eventqa_full` 小说 170 万–320 万字符，任何模型都无法整本不压缩喂入，所以 baseline 用"截断到窗口"作为不压缩对照（`--baseline_context_chars` 控制截断长度）。数据集另有 `eventqa_65536` / `eventqa_131072` 预截断变体，但其问题与 `eventqa_full` 不同，无法与 full 直接对照。

---

## 补充说明

### Probe 构建原则：只指向被压缩的内容

probe 的核心目的是检测 memory retention，即"压缩掉的信息 agent 是否还能回答"。
因此 **probe 应该只问被压缩区域中的信息**，而不是保留在尾部 steps 中的信息。

压缩边界是时间性的：`keep_recent_pairs=N` 意味着最后 N 对原样保留，前面的全部进入 summary。因此：

- **probe 应该只问 history 前半部分（early pairs）中的细节**
- 如果 probe 问的是 recent pairs 中的信息，agent 不需要 summary 就能回答，probe 失效——测不出 memory retention

构建 probe 时无需提前知道压缩器具体保留了什么，只需确保 probe 依赖的信息来自 early history（必定被压缩的区域）。

**验证 probe 设计**：用 `export_summary()` 的 `compression_boundary` 字段确认哪些 pairs 被压缩、哪些被保留。如果 probe 的答案在 summary 里根本没有，这是压缩器的问题（归入 Static Inspection 层面），不是 agent 的问题。

---

### Static Summary Inspection vs Probe Eval

两者测的是不同的故障模式：

| | Probe Eval | Static Summary Inspection |
|--|-----------|--------------------------|
| 输入 | 完整压缩上下文（summary + 保留的尾部 steps + system prompt） | 仅 summary 文本 |
| 执行方式 | 让 agent 回答问题（跑 LLM） | 直接检查 summary 文本是否包含关键信息 |
| 测的是什么 | 压缩后 agent **能否利用**残留信息工作 | 压缩器**是否选择保留**了关键信息 |
| 失败含义 | summary 里有但 agent 没用上 → 检索/利用能力问题 | summary 里就没有 → 压缩器丢失了 |

**两个不同的故障模式**：
1. 压缩器保留了，但 agent 回答时没能利用 → **Probe Eval** 会发现，Inspection 不会
2. 压缩器根本没保留 → 两者都会发现，但应归因到 Inspection 层面

---

### Static Summary Inspection

直接检查 compressed summary 是否还包含关键信息。

#### 在线方案

在 agent 运行后导出压缩状态：

```python
compressed_state = shared_cm.export_summary()
# compressed_state 包含:
#   previous_summary / current_summary: 压缩后的摘要文本
#   compression_boundary: 哪些 pairs/steps 被压缩 vs 保留
#   previous_cache_info / current_cache_info: 缓存元信息

for check in summary_checks:
    eval_text(compressed_state["previous_summary"], check)
```

#### 离线方案

脱离 agent 运行，直接用相同的 prompt 和 schema 压缩纯文本 pairs：

```python
from nexent.core.agents.agent_context import compress_history_offline

result = compress_history_offline(
    pairs=[("用户说了什么", "助手做了什么"), ...],
    model=llm_model,
    config=ContextManagerConfig(),
)
# result["summary"]: 压缩后的摘要
# result["is_incremental"]: 是否使用了增量压缩
# result["is_fallback"]: LLM 是否失败并使用了 fallback
# result["input_text"]: 喂给 LLM 的原始文本（用于调试）

eval_text(result["summary"], {"must_contain": ["关键文件名"]})
```

离线方案的优势：
- 不需要跑 agent，只需一次 LLM 调用做压缩
- 不依赖 AgentMemory、ActionStep 等运行时对象
- 适合批量评估不同 prompt/schema 对压缩质量的影响