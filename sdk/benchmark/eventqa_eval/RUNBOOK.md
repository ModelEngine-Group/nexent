# EventQA 执行手册

操作步骤：从切换 LLM 凭据、烟雾测试、跑完整 100 题、到把 trace 导入 Langfuse。
参数细节见同目录 `README.md`。

---

## 0. 前提

日常用（环境已搭好）：

- venv：`nexent/backend/.venv/bin/python`
- 数据：一次性 `python download_data.py`（13MB，写到 `data/eventqa_full.jsonl`，已 .gitignore）
- LLM 凭据：仓库根 `nexent/.env` 的 `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- LLM 可选环境变量（仓库根 `nexent/.env`，与上一条 LLM_* 同区）：
  - `LLM_ENABLE_THINKING` — `false` 时给 Qwen3 类模型关 thinking（见 §8.1）
  - `LLM_EXTRA_BODY` — 通用版本，直接给一段 JSON 透传到 `chat.completions.create` 的 `extra_body`
- Langfuse（可选，用于 trace 可视化）：已自托管在 `http://localhost:3100`；凭据见 `sdk/ctx_debugger/langfuse/.env`

### 新环境从零起步

干净机器（`git clone` 之后）按下面装。

#### A. Python 依赖

```bash
# 1) 装 nexent SDK 自己（editable，方便改源码生效）
cd nexent/sdk
uv pip install -e .

# 2) backend 的依赖（按 uv.lock pin 住版本）+ benchmark extra（pyarrow / langfuse / huggingface_hub 一齐）
cd ../backend
uv sync --extra benchmark
```

#### B. Langfuse（可选——只在需要 trace 可视化时装）

前提：装好 Docker（Linux 装 docker engine；Windows 装 Docker Desktop 并开 WSL2 集成）。

**Step 1 — 生成 `sdk/ctx_debugger/langfuse/.env`**（gitignored，必须新机器自己造）：

```bash
cat > sdk/ctx_debugger/langfuse/.env <<EOF
# 实例密钥（每个新机器重新生成，ENCRYPTION_KEY 必须 64 字符 hex）
NEXTAUTH_SECRET=$(openssl rand -hex 32)
SALT=$(openssl rand -hex 16)
ENCRYPTION_KEY=$(openssl rand -hex 32)
TELEMETRY_ENABLED=false

# 单机用 localhost；要让局域网同事访问就填 Windows 主机 LAN IP
NEXTAUTH_URL=http://localhost:3100

# 首启自动建好 org / project / admin，不用 UI 注册
LANGFUSE_INIT_ORG_ID=ctxdbg
LANGFUSE_INIT_ORG_NAME=ctx_debugger
LANGFUSE_INIT_PROJECT_ID=ctxdbg
LANGFUSE_INIT_PROJECT_NAME=nexent-context
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-$(python3 -c "import uuid;print(uuid.uuid4())")
LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-$(python3 -c "import uuid;print(uuid.uuid4())")
LANGFUSE_INIT_USER_EMAIL=admin@ctxdbg.local
LANGFUSE_INIT_USER_NAME=admin
LANGFUSE_INIT_USER_PASSWORD=$(openssl rand -hex 8)
EOF
```

（也可直接把旧机器的 `.env` 拷过来——keys 和密码就跟着复用。）

**Step 2 — 启动**：

```bash
cd sdk/ctx_debugger/langfuse
docker compose up -d
```

首启 10–30 秒拉镜像 + 跑 6 个服务（langfuse-web / langfuse-worker / clickhouse / minio / redis / postgres）。

**Step 3 — 验证**：

```bash
curl -s http://localhost:3100/api/public/health    # 应返回 {"status":"OK", ...}
docker compose ps                                   # 全部 Up
```

浏览器开 `http://localhost:3100`，用 `.env` 里的 `LANGFUSE_INIT_USER_EMAIL` + `LANGFUSE_INIT_USER_PASSWORD` 登录。

**常用维护**：

```bash
docker compose logs -f langfuse-web   # 看日志
docker compose down                   # 停（保留数据卷）
docker compose down -v                # 停 + 清空所有 trace/账号
```

数据卷（`langfuse_postgres_data` 等）在 docker 内，`down` 不删、重启续用。

---

## 1. 切换到你的内网 DeepSeek

编辑 `nexent/.env`，把活动的三行换成你的内网值（保留旧值注释起来便于回切）：

```bash
# ===== Benchmark LLM Config =====
LLM_API_KEY="<your-internal-deepseek-key>"
LLM_MODEL_NAME="<your-internal-deepseek-model>"
LLM_API_URL="<your-internal-deepseek-base-url>"
```

验证：
```bash
grep -E "^LLM_(API_KEY|MODEL_NAME|API_URL)" /home/feiran/nexent/.env
```

> **避坑**：之前 glm-5（dashscope）会以"inappropriate content"拒收经典小说——
> 内网 DeepSeek 如果带类似审核，先用第 2 步烟雾测试探一下，否则跑 100 题会全废。

---

## 2. 快速烟雾测试（~3–5 分钟）

确认内网 DeepSeek 可达、不拦内容、窗口够大：

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python run_eventqa.py \
    --book_index 0 --limit 1 \
    --max_ingest_chars 200000 --chunk_chars 100000 \
    --token_threshold 200000 \
    --summary_schema narrative \
    --baseline_context_chars 200000
```

预期：终端最后打印 `RESULT: baseline_acc=... | narrative: acc=... ... token_reduction=...`，
不出现 `Error code: 400`、`inappropriate`、`Traceback`。

---

## 3. 完整运行：1 本书 × 100 题（**主命令**）

跑 book 0《乱世佳人》整本 + 全部 100 题、narrative schema、生产化 `token_threshold=200000`：

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python run_eventqa.py \
    --book_index 0 \
    --token_threshold 200000 --chunk_chars 100000 \
    --summary_schema narrative \
    --baseline_context_chars 800000
```

- 去掉 `--limit` = 跑全部 100 题
- 去掉 `--max_ingest_chars` = ingest 整本（约 23 chunk）
- 预计耗时 **~1.5–2.5 小时**（取决于内网 DeepSeek 速度；baseline 探针是大头：100 次 × 86 万字符喂入）

结果落在：

```
outputs/eventqa_full_book0/
├── predictions.jsonl    # 逐题 baseline vs compressed 答案
└── summary.json         # 单书指标 + 完整 narrative summary
outputs/summary.json     # 跨书汇总
```

### 节省成本/时间的常用开关

| 想做 | 加参数 |
|---|---|
| 只跑压缩臂（调压缩参数时用，baseline 是耗时大头）| `--skip_baseline` |
| 只跑 baseline | `--skip_compressed` |
| 抽样 20 题先看趋势 | `--limit 20` |
| 同时跑 default 和 narrative 对比 | `--summary_schema both`（压缩臂耗时翻倍）|
| 换本书（0–4 = 乱世佳人/悲惨世界/基督山/大卫科波菲尔/安娜卡列尼娜）| `--book_index <N>` |

---

## 4.（可选）用 ctx_debugger 抓 trace + 导入 Langfuse

只在**需要可视化看每步上下文/压缩**时走这条路（多了 trace 写盘开销，每次跑都是
一份独立 trace）。

### 4.1 跑测试时同时抓 trace

把上面第 3 节的命令换个**入口**，从 `ctx_debugger` 目录跑：

```bash
cd /home/feiran/nexent/sdk/ctx_debugger
NEXENT_CONTEXT_DEBUG=/tmp/eventqa_book0_narr.jsonl \
  ../../backend/.venv/bin/python example_with_eventqa.py \
      --book_index 0 \
      --token_threshold 200000 --chunk_chars 100000 \
      --summary_schema narrative \
      --baseline_context_chars 800000
```

参数和 `run_eventqa.py` 一样，原样转发。trace 写到 `$NEXENT_CONTEXT_DEBUG`。

**这次 demo 的命令**（1 本书 1 题，整本 ingest）：

```bash
cd /home/feiran/nexent/sdk/ctx_debugger
NEXENT_CONTEXT_DEBUG=/tmp/eventqa_narr_trace.jsonl \
  ../../backend/.venv/bin/python example_with_eventqa.py \
      --book_index 0 --limit 1 \
      --token_threshold 200000 --chunk_chars 100000 \
      --summary_schema narrative \
      --baseline_context_chars 800000
```

### 4.2 导入 Langfuse

```bash
cd /home/feiran/nexent/sdk
set -a; source ctx_debugger/langfuse/.env; set +a
LANGFUSE_HOST=http://localhost:3100 \
LANGFUSE_PUBLIC_KEY="$LANGFUSE_INIT_PROJECT_PUBLIC_KEY" \
LANGFUSE_SECRET_KEY="$LANGFUSE_INIT_PROJECT_SECRET_KEY" \
  ../backend/.venv/bin/python -m ctx_debugger.langfuse_export \
      /tmp/eventqa_book0_narr.jsonl \
      --session-id book0-narrative-full
```

**每次跑都换一个 `--session-id`**（如 `book0-narr-thr150k`、`book0-narr-chunk60k`），
就是新 session，方便在 Langfuse 里并排对比不同参数。已建过的 session 名：
`nexent-ctx-demo`、`eventqa-demo`、`eventqa-narrative`（这次 demo）。

在 Langfuse 项目 `nexent-context` 下点对应 session 即可看：每个 turn 嵌套展开
ingest 轮 / 压缩 span / 主 LLM 调用 / 工具调用 / token 用量。

### 4.3 不连网先看映射结构

```bash
cd /home/feiran/nexent/sdk
../backend/.venv/bin/python -m ctx_debugger.langfuse_export \
    /tmp/eventqa_book0_narr.jsonl --dry-run
```

---

## 5. 参数速查（细节见 README）

| 参数 | 这次用的值 | 含义 |
|---|---|---|
| `--book_index` | `0` | 0–4，5 本小说 |
| `--limit` | 缺省=100 / 烟雾用 1 | 每本题数 |
| `--question_start` | 缺省 `0` | 跳过前 N 道题（用于中断恢复，见 §7）|
| `--token_threshold` | `200000` | 压缩触发阈值，模仿 glm-5 200K 窗口生产配置 |
| `--chunk_chars` | `100000` | 小说切块粒度（~23k tokens/chunk，整本 ~23 块）|
| `--summary_schema` | `narrative` | `default` / `narrative` / `both` |
| `--baseline_context_chars` | `800000` | baseline 截断长度（~186k tokens，~200K 窗口生产场景）|
| `--keep_recent_pairs` | 缺省 `2` | 尾部保留 chunk 数 |
| `--max_ingest_chars` | 缺省 `0`（整本）/ 烟雾用 200000 | ingest 截断（0=不截断）|
| `--skip_baseline` / `--skip_compressed` | 缺省 否 | 跳过某一臂（恢复时用，见 §7）|

---

## 6. 故障排查

| 症状 | 原因 / 处置 |
|---|---|
| `Error code: 400 ... inappropriate content` | LLM 端点有内容审核拦经典文学。换模型/端点（DeepSeek 直连无此问题）。 |
| 输出大量 `</s>`、随机字符、`扫码失败` | LLM 在产出退化乱码（OpenRouter `:free` 见过）。换模型。 |
| `Still exceeds threshold after compression: X > Y` | 警告，不致命。说明保留尾部 + 当前 chunk 已经超过 token_threshold；可以减小 `--keep_recent_pairs` 或 `--chunk_chars`，或加大 `--token_threshold`。 |
| `compressed_pairs=0`（trace 显示压缩未触发）| ingest 累计 token 没超过 `--token_threshold`。增加 `--max_ingest_chars`、减小 `--token_threshold`、或减小 `--chunk_chars`。 |
| Langfuse 导入空白 | `--dry-run` 看 trace 是否非空；确认 `LANGFUSE_HOST`/keys 正确；`curl -s http://localhost:3100/api/public/health` 检查服务。 |
| `data file not found` | 先跑 `python download_data.py`。 |
| 大量 `no_answer`（baseline ≥50%）| 极有可能是模型 thinking 模式吃掉 `max_tokens`，`content` 来不及生成完整 `final_answer(...)` 代码块。见 §8。 |

---

## 7. 中断后恢复 / 抢救

EventQA 整本 + 100 题 + 双臂的运行偶尔会被网络断开/SSH 断开/超时杀死。本节给出一套**不丢已跑数据**的恢复流程。

前提是你**用 ctx_debugger 抓 trace 跑的**（见 §4.1）——trace 保存了每个 probe 的输入、模型回复、final_answer。没抓 trace 的纯 `run_eventqa.py` 跑断了只能从头跑。

恢复管线三步走：

```
   trace.jsonl  ──(1. salvage)──>  outputs/<book>_salvage/
                                          │
                                          │ 知道 baseline 跑到 qid N-1 处断了
                                          ▼
   run_eventqa.py --skip_compressed --question_start N
                              ──(2. resume)──>  outputs/<book>/
                                                       │
                                                       ▼
                                              (3. merge)
                                              outputs/<book>/
                                                (覆盖为合并后版本)
```

### 7.1 抢救 trace 里已有的 probe 结果

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python salvage_trace.py \
    /tmp/nexent_eventqa_trace.jsonl \
    --book_index 0 --schema narrative
```

写到 `outputs/eventqa_full_book0_salvage/`：
- `summary.json` — 含 compressed 准确率、baseline 部分准确率、压缩信息（previous_summary、token_counts、num_chunks）
- `predictions_compressed.jsonl` — compressed 臂逐题结果
- `predictions_baseline.jsonl` — baseline 臂已跑那部分逐题结果（如 0–43）

打印里会告诉你 baseline 跑到第几题断了（"qids 0..43 done, 56 remaining"）。

**怎么映射 trace 里的 turn 到 qid**：按 trace 内 turn 顺序。compressed 第 k 个 `eventqa_answerer` turn = items[k]；同样 baseline。前提是**probe 顺序跑、无重试**——目前的 `run_probes` 正是这样。如果将来加了重试，这里要重新设计。

### 7.2 续跑缺失的 baseline 部分

接上面的 "qids 0..43 done"，剩 qids 44..99 = 57 题。但安全起见**从 43 重跑**（断点那题大概率没完成），即 56 题：

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python run_eventqa.py \
    --book_index 0 --skip_compressed \
    --question_start 43 \
    --token_threshold 200000 --chunk_chars 100000 \
    --summary_schema narrative \
    --baseline_context_chars 800000
```

关键：
- `--skip_compressed` 跳过 ingest + compressed probe（保留 salvage 里已有的 compressed 数据）
- `--question_start 43` 跳过前 43 题（这是 §7.1 抢救告诉你的 done 数）
- 其他参数**必须和被中断那次完全一致**——尤其 `--token_threshold` / `--chunk_chars` / `--summary_schema` / `--baseline_context_chars`，否则合并出来的数据不可比

写到 `outputs/eventqa_full_book0/{summary.json, predictions.jsonl}`，此时**只含 qid 43..99 的 baseline**（compressed 为空字典）。

### 7.3 合并

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python merge_partial.py \
    --book_id eventqa_full_book0 \
    --schema narrative \
    --resume_start_qid 43
```

读 `outputs/<book>_salvage/` 和 `outputs/<book>/`（续跑后的），合并写回 `outputs/<book>/{summary.json, predictions.jsonl}`，包含：
- compressed 100 题（来自 salvage）
- baseline 100 题（0..42 来自 salvage、43..99 来自续跑）
- 重算后的 accuracy / retention / token_reduction
- `_merge_provenance` 字段记录数据来源（哪些 qid 来自 salvage、哪些来自续跑）

合并后的 `outputs/<book>/` 与从头跑一次完整的产出格式完全一致——后续工具（Langfuse、merge 后 dry-run 等）都能正常处理。

### 7.4 防中断

下次跑长任务时用 `tmux` / `nohup` / `setsid` 保护，避免 SSH 断开/终端关闭杀进程：

```bash
tmux new -s eventqa
# 在 tmux 里跑命令
# Ctrl+B 然后 D 脱离；下次 tmux attach -t eventqa
```

注意 tmux 只防 SSH 断开；LLM 端点抖动/超时仍会让 agent 个别 step 失败，那种情况 `run_agent_with_tracking` 的 fallback 会兜底为 `no_answer`，不会让整轮跑挂掉。

---

## 8. 已知限制

### 8.1 Qwen3 等 thinking 模型的影响

Qwen3 (`qwen36` 等)有"thinking"模式：模型先在 `reasoning_content` 通道里推理一通、再产出最终答案到 `content`。`nexent` 的 `OpenAIModel` 已经把两个通道分开捕获（`openai_llm.py:148-154`），所以 `content` 里**不会**出现 `<think>` 之类的污染。

**但是** thinking 仍会拖累 EventQA：
- thinking 喷的 token 算进 `max_tokens` 预算，**`content` 可能用完预算前来不及发完整 `final_answer(...)` 代码块** → smolagents 解析失败 → `no_answer`
- 大 context (baseline 喂 ~186k token) 上 thinking 喷得更长、更乱，比 compressed (~70k) 更易吃完预算
- 实测一次（qwen36 / 整本 book 0 / narrative / token_threshold=200000）：
  - baseline `no_answer` 率 **66%** (29/44)
  - compressed `no_answer` 率 21% (21/100)
  - retention = compressed_acc/baseline_acc = **1.76**（compressed 反超 baseline，因为 baseline 被 thinking 大量误伤、不是 compression 真的更优）

**缓解办法**：传 `extra_body={"chat_template_kwargs":{"enable_thinking":false}}` 关掉 thinking，让全部 `max_tokens` 预算留给 `content`。两种入口：

通过 `.env`（推荐，全局生效）：
```bash
# 任一即可，前者更通用
LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}
LLM_ENABLE_THINKING=false
```

通过 Python 直接构造 `OpenAIModel`：
```python
OpenAIModel(..., extra_body={"chat_template_kwargs":{"enable_thinking": False}})
```

代码改动涉及 SDK 三处（`agent_model.ModelConfig.extra_body` 字段、`openai_llm.OpenAIModel.extra_body` 参数、`nexent_agent.create_model` 传递）+ benchmark 侧 `agent_runner.py` 读 env。已落地，默认行为不变（不设 = 不传 = 与之前一致）。

**关 thinking 前后是不可比的两条数据**——如果你想做对照，跑两次：一次默认（thinking on），一次 `LLM_ENABLE_THINKING=false`，分别走 §3 流程，session id 区分（如 `eventqa-narr-thinkON` / `eventqa-narr-thinkOFF`）。

### 8.2 抢救机制的边界

§7 的 `salvage_trace.py` **按 trace 内 turn 顺序**映射到 `book.items[k]`，这依赖 `run_probes` 顺序跑、无重试。当前实现确实如此（一个 item 一次 `run_agent_with_tracking`）。如果将来在 probe 层加重试（一个 item 多次 agent_init），抢救的"按顺序"假设就破了，需要换更鲁棒的 qid 匹配策略（如 by-question-text 匹配——但 ctx_debugger 的消息截断让前缀匹配也容易误判，见过 fuzzy 匹配把累加前序事件的多个 qid 都归到 qid=1 的踩坑）。

### 8.3 token_reduction 是单点采样

如 README 里说明，`token_reduction` 取**最后一轮 ingest** 的 `get_token_counts()`（与 `manual_cases` 同法）。两种 schema 的最后一轮恰好撞到相同 token 数时，retention 会相同，属正常采样行为。

### 8.4 内容审核类阻断

经典文学（19 世纪西方小说）会触发部分国内 LLM 端点的内容审核（实测 glm-5 / dashscope 直接 400 `inappropriate content` 拦《乱世佳人》第一个 chunk）。这不是 benchmark 能绕过的——需换无文学审核的端点（DeepSeek 直连、自部署 Qwen3、等）。

### 8.5 baseline_context_chars 与模型窗口的平衡

`--baseline_context_chars 800000`（约 18.6 万 tokens）已逼近 200K 窗口模型的极限——加上 system prompt + question 容易撞窗口；若模型实际 effective context 短于标称（"lost in the middle"），baseline 准确率会被进一步压低，但这是**该模型在该窗口大小上的真实表现**，是 benchmark 该反映的，不是 bug。
