# longmemeval_eval — LongMemEval (S*) 长记忆评测

基于 **LongMemEval (S\*)** 数据集（来自 MemoryAgentBench，arXiv 2507.05257v3
对原 LongMemEval arXiv 2410.10813 的"5 长对话共享 60 题"重构），评测**上下文
压缩**对**多 session 对话长记忆**的影响。

> 评测方法与维度沿用 `sdk/benchmark` 其余部分：**baseline（不压缩）vs
> compressed（压缩）** 对照。本文件讲**数据集形态**、**怎么跑**和**每个参数
> 什么意思**。

---

## 数据集

| 维度 | 值 |
|---|---|
| 长对话数 | 5（共享） |
| 每对话 token 量 | ~355K |
| 每对话 atomic session 数 | ~107–116（user/assistant 多轮成对） |
| 每对话问题数 | 60 |
| 问题总数 | **300** |
| 问题类型（6 类）| `multi-session` (75) · `temporal-reasoning` (75) · `single-session-user` (45) · `knowledge-update` (45) · `single-session-assistant` (30) · `single-session-preference` (30) |
| 答案 | 自由文本（用 LLM-as-judge 评分）|

数据来自 HuggingFace `ai-hyz/MemoryAgentBench` 的 `Accurate_Retrieval` split，
`metadata.source == "longmemeval_s*"` 的 5 行。**与 `eventqa_eval` 同一 parquet**。

每行包含：
- `context` — 整个对话拍扁成纯文本（用于 baseline 截断喂入）
- `haystack_sessions` — 嵌套结构 `list[60] of list[~2] of list[turn]`，
  `turn = {role, content, has_answer}`。`dataset.py` 把它展平成单层
  `list[session]`，按时间顺序拼接。
- `questions` / `answers` / `question_types` / `question_dates` / `question_ids`

---

## 运行前提

- 用 backend 的 venv：`nexent/backend/.venv/bin/python`（已含 `huggingface_hub`、
  `pyarrow`、`openai`）
- 被测 LLM 凭据：仓库根 `nexent/.env` 的 `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- **Judge 模型（可选）**：`JUDGE_API_KEY` / `JUDGE_MODEL_NAME` / `JUDGE_API_URL`
  - 留空时自动 fallback 到 `LLM_*`（同一模型既当被测也当判官 — 简单但存在
    self-judging bias）
  - 单独配后判官只跑评分一步，量不大，建议用更强模型避免 bias
- 命令默认站在本目录（`sdk/benchmark/longmemeval_eval/`）

---

## 两步走

### 第一步：下载数据

```bash
python download_data.py
```

写到 `data/longmemeval_s_star.jsonl`（约 30MB）。

### 第二步：跑评测

```bash
# 冒烟测试：1 个对话、1 道题、只 ingest 前 6 个 session（必触发压缩）
python run_longmemeval.py \
    --dialogue_index 0 --limit 1 \
    --max_ingest_sessions 6 --sessions_per_batch 2 \
    --token_threshold 3000 --keep_recent_pairs 1 \
    --baseline_context_chars 40000

# 默认抽样：5 个对话 × 20 题 = 100 题
python run_longmemeval.py

# 完整：5 个对话 × 60 题 = 300 题
python run_longmemeval.py --limit 60
```

---

## `run_longmemeval.py` 参数详解

### 评测范围

| 参数 | 默认 | 含义 |
|---|---|---|
| `--data_file` | `data/longmemeval_s_star.jsonl` | 下载脚本产出的数据 |
| `--dialogue_limit` | 全部（5）| 只跑前 N 个对话 |
| `--dialogue_index` | 无 | 只跑某个特定下标的对话（0-4），覆盖 `--dialogue_limit` |
| `--limit` | **20** | 每对话只跑前 N 题（**默认抽样**；设 60 跑完整 300 题）|

### 压缩臂：ContextManager 配置

| 参数 | 默认 | 含义 |
|---|---|---|
| `--token_threshold` | `12000` | 累计上下文超过该 token 数触发压缩，越小压缩越激进 |
| `--keep_recent_pairs` | `2` | 尾部保留多少对 (user, assistant) 不压缩 |
| `--keep_recent_steps` | `4` | ContextManager 单轮内保留 step 数 |
| `--max_observation_length` | `20000` | 单条 observation 字符上限 |
| `--sessions_per_batch` | `4` | 每个 ingest batch 装多少个 atomic session（越大压缩轮数越少、单轮输入越大）|
| `--max_ingest_sessions` | `0`（整本）| 压缩臂只取前 N 个 session，**冒烟测试用**——设小值能大幅加速 |
| `--ingest_max_steps` | `2` | ingest agent 最大步数（只是触发压缩，给 2 步够了）|

### 评分臂

| 参数 | 默认 | 含义 |
|---|---|---|
| `--probe_max_steps` | `3` | 每道 probe agent 最大步数 |

评分使用 LLM-as-judge：

- 每个 question_type 一份 judge prompt（`eval_utils.py`）
- 判官模型按 env 优先级解析：`JUDGE_*` → `LLM_*` → fallback substring 匹配
- Judge 实际行为打印在 `outputs/.../predictions.jsonl` 的 `judge_label` 字段
  里（`yes` / `no` / `unknown` / `error` / `fallback_*`）

### Baseline 臂

`longmemeval_s*` 对话 ~160 万字符（~355K tokens），**当窗口不够大时必须截断**。

| 参数 | 默认 | 含义 |
|---|---|---|
| `--baseline_context_chars` | `480000` | baseline 喂入字符上限（按模型窗口估）|

### 调试 / 跳过

| 参数 | 默认 | 含义 |
|---|---|---|
| `--skip_baseline` | 否 | 跳过 baseline（迭代压缩参数时省时间）|
| `--skip_compressed` | 否 | 跳过压缩臂 |
| `--debug` | 否 | 打印 agent 调试输出 |

---

## 评测维度与产出

两条臂回答**同一批题目**，retention 比值干净：

```
memory_retention = compressed_accuracy / baseline_accuracy
token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens
```

`token_reduction` 与 `manual_cases` / `eventqa_eval` 同法：取压缩臂最后一轮
ingest 的 `ContextManager.get_token_counts()` 单点采样。

**新增维度（相对 `eventqa_eval`）**：按 6 个 question_type 分桶报告
retention，定位压缩坏在哪类记忆上。

Continuation 不评——LongMemEval 题目彼此独立。

产出写到 `outputs/`：

```
outputs/
├── <dialogue_id>/
│   ├── predictions.jsonl   # 逐题 baseline vs compressed 答案 + judge 标签
│   └── summary.json        # 单对话指标 + 完整压缩摘要 + per-category
└── summary.json            # 跨对话汇总 + per-category 分类指标
```

---

## 与 eventqa_eval 的差异（关键）

| | eventqa_eval | longmemeval_eval |
|--|--|--|
| 历史形态 | 小说连续 prose，char-切片成 `[Novel part X]` 信封 | **真实多 session 对话**，按 session 切，turn 原样作为 `(user, assistant)` pair 进 history |
| 评分 | 六选一 MCQ → 字符串匹配 | **自由文本 → LLM-as-judge**（按类型不同 prompt）|
| 默认 schema | `default` / `narrative` / `both` | **只用 SDK 默认 schema**（先测产线行为，schema 实验待后续）|
| Probe 间独立 | ✓ | ✓ |
| 维度 | 单一 accuracy + token_reduction | accuracy + token_reduction + **per-category retention**（6 类）|

---

## 注意事项

- **Self-judging bias**：默认 fallback 用 LLM_* 同款模型做判官，数字偏乐观。
  做正式对比时建议单独配 `JUDGE_*`（外部强模型如 GPT-4o）。
- **抽样 vs 完整**：默认 `--limit 20`（5 × 20 = 100 题）适合迭代；要正式数字
  跑 `--limit 60`（5 × 60 = 300 题）。
- **ingest 是固定成本**：跟 `--limit` 无关——整个对话历史都得压一遍。
- 数据下载若 HF SSL 抖动会自动 fallback 到本地缓存。
