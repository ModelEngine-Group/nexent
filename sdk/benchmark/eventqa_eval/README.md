# eventqa_eval — EventQA 长文记忆评测

基于 MemoryAgentBench 的 **EventQA** 数据集，评测**上下文压缩**对超长文档记忆的
影响：一整本小说作为待压缩历史，压缩后还能不能答对"接下来发生什么"。

> 评测方法与维度沿用 `sdk/benchmark` 其余部分：**baseline（不压缩）vs
> compressed（压缩）** 对照。本文件讲**怎么跑**和**每个参数什么意思**。

---

## 数据集

EventQA 取自 ∞-Bench 的 5 部小说（《乱世佳人》《悲惨世界》《基督山伯爵》
《大卫·科波菲尔》《安娜·卡列尼娜》），每部 39 万–53 万 tokens。每本书 100 道
六选一 MCQ：给出已发生的前序事件，从 6 个候选里选出真实的后续事件
（1 真 + 5 个 GPT-4o 干扰项）。

数据在 HuggingFace `ai-hyz/MemoryAgentBench` 的 `Accurate_Retrieval` split 里，
`metadata.source == "eventqa_full"` 的 5 行就是整本小说版本。

---

## 运行前提

- 用 backend 的 venv：`nexent/backend/.venv/bin/python`（需 `huggingface_hub`、
  `pyarrow`）
- LLM 凭据在仓库根 `nexent/.env`：`LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- 命令默认站在本目录（`sdk/benchmark/eventqa_eval/`）

---

## 两步走

### 第一步：下载数据

```bash
python download_data.py
```

从 HuggingFace 下载 `Accurate_Retrieval` split，抽出 5 个 `eventqa_full` 行，写到
`data/eventqa_full.jsonl`（约 13MB，已 `.gitignore`，不入库）。

| 参数 | 默认 | 含义 |
|---|---|---|
| `--source` | `eventqa_full` | 取哪个变体：`eventqa_full`（整本）、`eventqa_65536`（截到 64K tokens）、`eventqa_131072`（截到 128K tokens）。注意截断变体的题目与 full **不同** |
| `--output_dir` | `./data` | 输出目录 |

### 第二步：跑评测

```bash
# 冒烟测试：1 本书、1 道题、小说截断到 4.8 万字符
python run_eventqa.py --book_limit 1 --limit 1 \
    --max_ingest_chars 48000 --chunk_chars 12000 \
    --token_threshold 3000 --keep_recent_pairs 1

# 完整运行：5 本书 × 100 题
python run_eventqa.py
```

---

## `run_eventqa.py` 参数详解

### 评测范围

| 参数 | 默认 | 含义 |
|---|---|---|
| `--data_file` | `data/eventqa_full.jsonl` | `download_data.py` 产出的数据文件 |
| `--book_limit` | 全部（5） | 只评前 N 本书。冒烟时设 `1` 只跑 1 本 |
| `--limit` | 全部（100） | 每本书只跑前 N 道题。冒烟时设 `1` 只跑 1 题 |

### 压缩臂：ContextManager 配置

整本小说会被切成多个 chunk、逐轮喂入，触发真实 ContextManager 增量压缩。

| 参数 | 默认 | 含义 |
|---|---|---|
| `--token_threshold` | `12000` | ContextManager 的压缩触发阈值。累计上下文超过这个 token 数就触发压缩。**越小压缩越早、越激进** |
| `--keep_recent_pairs` | `2` | 尾部保留多少个 chunk 不压缩（其余进入 summary）。**chunk 总数必须 > 这个值，压缩才会真正发生** |
| `--keep_recent_steps` | `4` | ContextManager 在当前轮内保留多少个 step 不压缩 |
| `--max_observation_length` | `20000` | ContextManager 单条 observation 的最大字符数 |
| `--chunk_chars` | `20000` | 每个小说 chunk 的字符数。小说总字符 / 这个值 = chunk 轮数。**建议 ≲ `token_threshold` 对应的字符数**，这样每轮增量压缩的输入在预算内、走快速增量路径；过大则退化为整段重压缩 |
| `--max_ingest_chars` | `0`（整本） | 压缩臂只取小说前 N 个字符。**冒烟测试用**——设小值（如 `48000`）能大幅缩短一本书的 ingest 时间。`0` 表示用整本 |
| `--ingest_max_steps` | `2` | 每个 ingest（确认）agent 运行的最大步数。ingest agent 只是用来触发压缩，步数给小即可 |
| `--summary_schema` | `default` | 压缩臂用哪种摘要模板：`default` / `narrative` / `both`，见下 |

### 两种摘要 schema（`--summary_schema`）

ContextManager 的默认摘要 schema 面向 agent 任务（`active_task` / `completed_work` / `relevant_files` …）。压缩叙事小说时，10 个字段里约 9 个变成 "None"，全书情节被挤进唯一的 `critical_context` 字段（还被限制 ≤300 词）——会大量丢失情节细节，compressed 分数被人为压低。

因此评测提供两种 schema：

| schema | 字段 | 测什么 |
|---|---|---|
| `default` | active_task / completed_work / relevant_files …（10 个，agent 任务向）| "生产 ContextManager 原样"在叙事文档上的表现 |
| `narrative` | events_so_far / characters / recent_events / unresolved_threads / setting（5 个，叙事向）| 压缩**机制**在适配模板下能否保留叙事记忆 |

`narrative` 仍是**真实 ContextManager 类 + 同一套增量压缩代码路径**，只替换了摘要模板（prompts + JSON schema，均为 `ContextManagerConfig` 的字段）。

`--summary_schema both` 让压缩臂用两种 schema 各跑一遍。两者之差能分离损失来源：

- `default` 与 `narrative` 的差距 → 多少损失来自 **schema 错配**
- `narrative` 与 baseline 的差距 → 多少损失来自 **压缩比本身**

注意：`both` 会让压缩臂（ingest + 探针）跑两遍，耗时约翻倍。

### Baseline 臂

`eventqa_full` 小说 170 万–320 万字符，**任何模型都无法整本不压缩喂入**，所以
baseline 用"截断到模型窗口"作为不压缩对照。

| 参数 | 默认 | 含义 |
|---|---|---|
| `--baseline_context_chars` | `480000` | baseline 臂喂给模型的小说字符数（从开头截断）。设成你的模型上下文窗口能容纳的大小。窗口外的事件相关的题目，baseline 会答错——这正是要测的 |

### 探针（probe）执行

| 参数 | 默认 | 含义 |
|---|---|---|
| `--probe_max_steps` | `3` | 每道 MCQ 探针 agent 运行的最大步数 |

### 跳过某一臂 / 调试

| 参数 | 默认 | 含义 |
|---|---|---|
| `--skip_baseline` | 否 | 跳过 baseline 臂（只迭代压缩臂时用） |
| `--skip_compressed` | 否 | 跳过压缩臂（只迭代 baseline 时用） |
| `--debug` | 否 | 打印 agent 调试输出 |

---

## 冒烟命令逐项解释

```bash
python run_eventqa.py --book_limit 1 --limit 1 \
    --max_ingest_chars 48000 --chunk_chars 12000 \
    --token_threshold 3000 --keep_recent_pairs 1
```

- `--book_limit 1`：只评 1 本书（而非全部 5 本）
- `--limit 1`：这本书只跑 1 道题（而非全部 100 道）
- `--max_ingest_chars 48000`：压缩臂只取小说前 4.8 万字符，不读整本——加速冒烟
- `--chunk_chars 12000`：每个 chunk 1.2 万字符 → `48000 / 12000 = 4` 个 chunk
- `--token_threshold 3000`：累计上下文超 3000 tokens 就触发压缩（小值，确保冒烟时压缩一定触发）
- `--keep_recent_pairs 1`：尾部只保留 1 个 chunk 不压缩 → 4 个 chunk 里前 3 个进入压缩区

整体效果：用极少的小说量和题量，确保**压缩真实触发**、端到端流程跑通。

---

## 评测维度与产出

两条臂回答**同一批题目**，所以 retention 比值干净：

```
memory_retention = compressed_accuracy / baseline_accuracy
token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens
```

**`token_reduction` 与 `manual_cases` 同法**：取压缩臂**最后一轮 ingest** 的 `ContextManager.get_token_counts()`，按 `1 - last_compressed / last_uncompressed` 计算（对应 `manual_cases/test_benchmark.py` 的主算法）。`acon_eval` 不测 token_reduction。注意这是"取最后一轮"的单点采样——若两种 schema 的最后一轮恰好落在相同 token 数，`token_reduction` 会相同，属该方法的固有行为，非异常。

不评 Continuation——EventQA 的 MCQ 彼此独立。

产出写到 `outputs/`（compressed 指标按 schema 分组，`--summary_schema both` 时含两组）：

```
outputs/
├── <book_id>/
│   ├── predictions.jsonl   # 逐题：baseline 与各 schema 的 compressed 对照
│   └── summary.json        # 单书指标 + 各 schema 的压缩信息/摘要
└── summary.json            # 跨书汇总，含 per_schema 分组指标
```

---

## 完整运行耗时估算

基于 DeepSeek-v4-flash 的冒烟实测（《悲惨世界》整本，单步时延）：

| 阶段 | 单位耗时（实测，粗略）| 说明 |
|---|---|---|
| ingest 轮 | ~20 s/轮 | 切块喂入 + 一次增量压缩 LLM 调用 |
| compressed 探针 | ~60 s/题 | 压缩后上下文小，但模型推理输出较长 |
| baseline 探针 | ~110 s/题 | 整本小说喂入（40 万–74 万 tokens），agent 约 2 步 |

- **ingest 轮数 = 小说字符数 ÷ `chunk_chars`**。默认 `chunk_chars=20000` 时 5 本合计约 590 轮。ingest 是**固定成本，与 `--limit` 无关**（整本都要压）。
- baseline 探针是耗时大头：每题喂整本，agent 常跑约 2 步、每步重发整本。

**完整运行（5 本 × 100 题，默认参数）粗估：**

| 阶段 | 量 | 估时 |
|---|---|---|
| ingest | ~590 轮 × 20s | ~3.3 h |
| compressed 探针 | 500 题 × 60s | ~8.3 h |
| baseline 探针 | 500 题 × 110s | ~15 h |
| **合计** | | **~25–30 小时** |

**抽样运行（`--limit 20`，5 本 × 20 题）粗估：** ingest 固定 ~3.3 h + 探针约 ~5 h ≈ **8–9 小时**。

建议：

- 先用 `--limit` 抽样（如 `--limit 20`）确认结果合理再放开。
- ingest 想提速可调大 `--chunk_chars`（轮数减半、耗时约减半），代价是每轮压缩输入更大。
- 只迭代某一臂时用 `--skip_baseline` / `--skip_compressed`——baseline 是耗时大头。

> 注：冒烟实测确认 **DeepSeek V4（1M 窗口）能整本喂入最大的《悲惨世界》**（3,171,853 字符 ≈ 743,179 tokens，单次调用无截断、无报错），5 本均可整本喂入 baseline 臂。
