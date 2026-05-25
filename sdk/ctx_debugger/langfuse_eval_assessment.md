# Langfuse 评测能力适配评估

针对本仓库 (`sdk/benchmark/`) 下三套 benchmark — `manual_cases` / `acon_eval` /
`eventqa_eval` — 评估能否用 Langfuse 自带的 **Evaluation / Scores /
LLM-as-a-Judge / Human Annotation / Datasets** 作为评测主框架的可行性与 gap。

> 范围：仅评估 Langfuse 评测特性本身。我们已经在用 Langfuse 的 trace 可视化和
> session 分组（`ctx_debugger/langfuse_export.py`），这部分不在本文讨论范围。

---

## 1. Langfuse 评测能力 vs 本仓库需求对照

| Langfuse 功能 | 设计用途 | 适合本仓库哪里 |
|---|---|---|
| **Scores** | 把数值/类别指标贴在 trace / observation / session 上 | ✅ 把每题对错 / retention / token_reduction 推上去；dashboard 跨 session 对比 |
| **LLM-as-a-Judge** | 让一个 judge LLM 给开放式回答打分 | ⚠️ 我们大部分评测是确定性的（MCQ、EM/F1、关键词）；judge 反而引入噪声 |
| **Human Annotation** | trace 排队人工标注 | ⚠️ 只在开放式输出/质量主观判断时有用 |
| **Datasets** | 输入 + 期望输出对的集合，跑 experiment | ⚠️ 数据集与 task 模型不匹配（见下） |

---

## 2. (a) 整个 benchmark 适配评估

三个 benchmark 的评测方式：

| benchmark | 评测方式 | Langfuse 替代可行性 |
|---|---|---|
| `manual_cases` | `eval_text(text, check)` 关键词 `must_contain` / `must_contain_any` | 关键词检查在外做更省、更准；**但 summary inspection 那层换 LLM-as-a-Judge 有价值**——现在 `must_contain` 只能验"出现没出现"，judge 能问"这段 summary 是否保留了关键状态" |
| `acon_eval` | EM / F1（确定性字符串） | ❌ 不需要 judge / 标注 |
| `eventqa_eval` | 六选一字符串匹配 | ❌ 不需要 judge / 标注 |

**结构性 gap**：Langfuse 的 Experiment 框架是 **"一个输入 → 一次 LLM 调用 → 一个输出"** 的模型。我们的 task 是**整套 agent run + 多轮 ingest + 多个 probe**——跟 Langfuse Dataset/Experiment 的 "task per item" 不匹配。硬塞进去等于把 `run_*.py` 拆成一堆 Langfuse callback，复杂度上升、收益不大。

**真实增量价值**有两块：

1. **Scores 推送（高优先级）**：扩展 `langfuse_export.py`，给每个 probe trace 贴一个 `correctness: 0/1` 分数、给整个 session 贴 aggregate `accuracy` / `retention` / `token_reduction`。dashboard 就能可视化时序对比不同参数/schema/模型。**性价比最高的整合**。
2. **LLM-as-a-Judge 只用在 `manual_cases` 的 summary inspection 层**：现在 `summary_checks` 用 `must_contain` 检查关键字，会漏掉同义改写。换 judge 评 "summary 是否保留了 X 信息" 更鲁棒。但 acon/eventqa 不要碰——MCQ 上 judge 反而引入误判。

---

## 3. (b) EventQA 单独评估

| 维度 | Langfuse 替代 | 评估 |
|---|---|---|
| 探针 MCQ 评分 | Langfuse Scores | ✅ **可行且推荐**——每个 probe trace 上贴 `correctness: 0/1`、`match_type: exact/containment/fuzzy/no_answer` |
| Token reduction | Langfuse 内置 token tracking | ✅ Langfuse **自带 per-call token 计数**（input/output/cost），比"取最后一轮 get_token_counts" 更精准；可以把 ingest 阶段 LLM 调用总 token 数作为 Score |
| Retention（compressed/baseline）| Langfuse 跨 session 聚合 | ⚠️ Langfuse **不自动算 retention**——只展示各自的 acc，比值要外部计算后再推一个 Score |
| LLM-as-a-Judge | — | ❌ **不需要**——MCQ 的 gold 是六选项之一，确定性匹配就够；judge 引入不必要的 LLM 调用 |
| Human Annotation | — | ❌ **不需要**——同上 |
| Datasets | 把 100 题装进 Langfuse Dataset | ⚠️ **重复存数据**——我们已经有 `data/eventqa_full.jsonl`；除非要走 Langfuse Experiment 流程，否则纯重复 |

### EventQA 的具体 Gap

1. **不能"端到端在 Langfuse 里跑 EventQA"**——它的 task model 是 "一次输入 → 一次 LLM 调用 → 一次输出"。EventQA 的"输入"是整本小说（要 24 轮 ingest 才能压缩），"输出"是 100 题答案。整个 ingest+probe 流程塞 Langfuse Experiment 不自然——还得在外面用 `run_eventqa.py` 跑、把结果导进去。
2. **Retention 是跨 arm 比值**：Langfuse 没"跨 session/trace 自动比对"概念。要 compressed_acc / baseline_acc 必须外部算好再推。
3. **Per-probe 上下文成本**：Langfuse 的 token 计数是 LLM 实际的 input/output tokens，**比 `manual_cases` 同款的"取最后一轮 effective tokens"更精准**。要换可以把 Langfuse 报告的真实 token cost 替代单点估算。

---

## 4. 落地方案优先级

按收益降序：

| 优先级 | 动作 | 收益 | 工作量 |
|---|---|---|---|
| **高（已落地）** | 扩展 `langfuse_export.py`：新增 `--benchmarkqa-outputs <dir>`；每个 probe trace 贴 `correctness`（NUMERIC 0/1）+ `match_type`（CATEGORICAL），score metadata 含 arm / schema / qid。Langfuse UI 自动按 session 聚合 `correctness`，filter by `metadata.arm` 可分 compressed / baseline。`retention` / `token_reduction` **不推**——已在 `outputs/<book>/summary.json`，再推到 Langfuse 反而要造一个 phantom "session-summary" trace 污染 trace 列表。 | dashboard 直接看时序 / 跨 session 对比；其他特性的基石 | ~80 行 |
| **中** | 给 `manual_cases` 的 summary_checks 加一个 LLM-as-a-Judge 评测器（同义改写不漏判）| `must_contain` 关键字法的真实补充 | ~100 行 + judge prompt 设计 |
| **低** | EventQA 数据搬进 Langfuse Dataset | 没多大新价值——已经有 jsonl 了 | ~30 行 |
| **不做** | 把 EventQA 评测主流程搬到 Langfuse Experiments | 模型不匹配——硬塞进去等于把 `run_eventqa.py` 拆成一堆 callback | × |
| **不做** | MCQ 上 LLM-as-a-Judge / Human Annotation | 引入噪声，无收益 | × |

---

## 5. 总结

- Langfuse 的评测框架**替代不了主流程**（agent 多轮 ingest + probe + 跨 arm retention 的结构与其 task model 不匹配）
- **唯一性价比高的整合是 Scores 推送**——把已有评分结果可视化进 Langfuse，便于跨 session 对比参数/模型/schema 调整
- LLM-as-a-Judge / Human Annotation / Datasets 只对 `manual_cases` 的 summary inspection 那一小段有边际价值；对 acon/eventqa 的确定性评测引入噪声
