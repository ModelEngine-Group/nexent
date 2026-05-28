# EventQA Execution Runbook

Operation steps: From switching LLM credentials, smoke testing, running full 100 questions, to importing trace into Langfuse.
For parameter details see README.md in same directory.

---

## 0. Prerequisites

Daily use (environment already set up):

- venv: `nexent/backend/.venv/bin/python`
- Data: One-time `python download_data.py` (13MB, written to `data/eventqa_full.jsonl`, already .gitignore)
- LLM credentials: Repo root `nexent/.env`'s `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- LLM optional environment variables (repo root `nexent/.env`, same section as LLM_* above):
  - `LLM_ENABLE_THINKING` — `false` disables thinking for Qwen3-like models (see §8.1)
  - `LLM_EXTRA_BODY` — Generic version, directly pass a JSON to `chat.completions.create`'s `extra_body`
- Langfuse (optional, for trace visualization): Self-hosted at `http://localhost:3100`; credentials see `sdk/ctx_debugger/langfuse/.env`

### Fresh Environment from Scratch

Clean machine (after `git clone`) follow below to install.

#### A. Python Dependencies

```bash
# 1) Install nexent SDK itself (editable, convenient for source changes to take effect)
cd nexent/sdk
uv pip install -e .

# 2) backend dependencies (versions pinned by uv.lock) + benchmark extra (pyarrow / langfuse / huggingface_hub together)
cd ../backend
uv sync --extra benchmark
```

#### B. Langfuse (Optional — only install when need trace visualization)

Prerequisite: Docker installed (Linux install docker engine; Windows install Docker Desktop and enable WSL2 integration).

**Step 1 — Generate `sdk/ctx_debugger/langfuse/.env`** (gitignored, must create on new machine):

```bash
cat > sdk/ctx_debugger/langfuse/.env <<EOF
# Instance keys (regenerate on each new machine, ENCRYPTION_KEY must be 64-character hex)
NEXTAUTH_SECRET=$(openssl rand -hex 32)
SALT=$(openssl rand -hex 16)
ENCRYPTION_KEY=$(openssl rand -hex 32)
TELEMETRY_ENABLED=false

# Single machine use localhost; for LAN colleague access, fill Windows host LAN IP
NEXTAUTH_URL=http://localhost:3100

# First startup automatically creates org / project / admin, no UI registration needed
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

(Or directly copy old machine's `.env` over—keys and password will be reused.)

**Step 2 — Start**:

```bash
cd sdk/ctx_debugger/langfuse
docker compose up -d
```

First startup 10–30 seconds to pull images + run 6 services (langfuse-web / langfuse-worker / clickhouse / minio / redis / postgres).

**Step 3 — Verify**:

```bash
curl -s http://localhost:3100/api/public/health    # Should return {"status":"OK", ...}
docker compose ps                                   # All Up
```

Browser open `http://localhost:3100`, login with `.env`'s `LANGFUSE_INIT_USER_EMAIL` + `LANGFUSE_INIT_USER_PASSWORD`.

**Common Maintenance**:

```bash
docker compose logs -f langfuse-web   # View logs
docker compose down                   # Stop (preserve data volumes)
docker compose down -v                # Stop + clear all trace/accounts
```

Data volumes (`langfuse_postgres_data` etc.) are inside docker, `down` doesn't delete, restart continues using.

---

## 1. Switch to Your Internal DeepSeek

Edit `nexent/.env`, replace active three lines with your internal values (comment out old values for easy switching back):

```bash
# ===== Benchmark LLM Config =====
LLM_API_KEY="<your-internal-deepseek-key>"
LLM_MODEL_NAME="<your-internal-deepseek-model>"
LLM_API_URL="<your-internal-deepseek-base-url>"
```

Verify:
```bash
grep -E "^LLM_(API_KEY|MODEL_NAME|API_URL)" /home/feiran/nexent/.env
```

> **Pitfall avoidance**: Previous glm-5 (dashscope) would reject classic novels with "inappropriate content"—
> If internal DeepSeek has similar content moderation, first use Step 2 smoke test to probe, otherwise running 100 questions will all fail.

---

## 2. Quick Smoke Test (~3–5 minutes)

Confirm internal DeepSeek reachable, doesn't block content, window large enough:

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python run_eventqa.py \
    --book_index 0 --limit 1 \
    --max_ingest_chars 200000 --chunk_chars 100000 \
    --token_threshold 200000 \
    --summary_schema narrative \
    --baseline_context_chars 200000
```

Expected: Terminal finally prints `RESULT: baseline_acc=... | narrative: acc=... ... token_reduction=...`,
no `Error code: 400`, `inappropriate`, `Traceback` appear.

---

## 3. Full Run: 1 Book × 100 Questions (**Main Command**)

Run book 0 Gone with the Wind entire book + all 100 questions, narrative schema, production `token_threshold=200000`:

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python run_eventqa.py \
    --book_index 0 \
    --token_threshold 200000 --chunk_chars 100000 \
    --summary_schema narrative \
    --baseline_context_chars 800000
```

- Remove `--limit` = run all 100 questions
- Remove `--max_ingest_chars` = ingest entire book (~23 chunks)
- Estimated time **~1.5–2.5 hours** (depends on internal DeepSeek speed; baseline probes are bottleneck: 100 times × 860K chars fed)

Results land at:

```
outputs/eventqa_full_book0/
├── predictions.jsonl    # Per-question baseline vs compressed answers
└── summary.json         # Single-book metrics + complete narrative summary
outputs/summary.json     # Cross-book aggregate
```

### Common Switches for Cost/Time Savings

| Want to | Add Parameter |
|---|---|
| Only run compressed arm (when tuning compression params, baseline is time bottleneck) | `--skip_baseline` |
| Only run baseline | `--skip_compressed` |
| Sample 20 questions first to see trend | `--limit 20` |
| Run both default and narrative for comparison | `--summary_schema both` (compressed arm time doubles) |
| Switch book (0–4 = Gone with the Wind / Les Misérables / Count of Monte Cristo / David Copperfield / Anna Karenina) | `--book_index <N>` |

---

## 4. (Optional) Capture trace with ctx_debugger + Import to Langfuse

Only go this path when **need visualization of each step's context/compression** (adds trace write overhead, each run produces independent trace).

### 4.1 Run Test While Capturing Trace

Replace the above Step 3 command's **entry point**, run from `ctx_debugger` directory:

```bash
cd /home/feiran/nexent/sdk/ctx_debugger
NEXENT_CONTEXT_DEBUG=/tmp/eventqa_book0_narr.jsonl \
  ../../backend/.venv/bin/python example_with_eventqa.py \
      --book_index 0 \
      --token_threshold 200000 --chunk_chars 100000 \
      --summary_schema narrative \
      --baseline_context_chars 800000
```

Parameters same as `run_eventqa.py`, forwarded unchanged. Trace written to `$NEXENT_CONTEXT_DEBUG`.

**This demo's command** (1 book 1 question, entire book ingest):

```bash
cd /home/feiran/nexent/sdk/ctx_debugger
NEXENT_CONTEXT_DEBUG=/tmp/eventqa_narr_trace.jsonl \
  ../../backend/.venv/bin/python example_with_eventqa.py \
      --book_index 0 --limit 1 \
      --token_threshold 200000 --chunk_chars 100000 \
      --summary_schema narrative \
      --baseline_context_chars 800000
```

### 4.2 Import to Langfuse

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

**Change `--session-id` for each run** (e.g., `book0-narr-thr150k`, `book0-narr-chunk60k`),
that's a new session, convenient for side-by-side comparison in Langfuse. Already created session names:
`nexent-ctx-demo`, `eventqa-demo`, `eventqa-narrative` (this demo).

In Langfuse project `nexent-context`, click corresponding session to view: each turn nested expands
ingest turns / compression spans / main LLM calls / tool calls / token usage.

### 4.3 Offline Preview Mapping Structure

```bash
cd /home/feiran/nexent/sdk
../backend/.venv/bin/python -m ctx_debugger.langfuse_export \
    /tmp/eventqa_book0_narr.jsonl --dry-run
```

---

## 5. Parameter Quick Reference (Details in README)

| Parameter | This demo's value | Meaning |
|---|---|---|
| `--book_index` | `0` | 0–4, 5 novels |
| `--limit` | Default=100 / smoke use 1 | Questions per book |
| `--question_start` | Default `0` | Skip first N questions (for interrupted run recovery, see §7) |
| `--token_threshold` | `200000` | Compression trigger threshold, mimics glm-5 200K window production config |
| `--chunk_chars` | `100000` | Novel chunk granularity (~23k tokens/chunk, entire book ~23 chunks) |
| `--summary_schema` | `narrative` | `default` / `narrative` / `both` |
| `--baseline_context_chars` | `800000` | Baseline truncation length (~186k tokens, ~200K window production scenario) |
| `--keep_recent_pairs` | Default `2` | Tail retain chunk count |
| `--max_ingest_chars` | Default `0` (entire) / smoke use 200000 | Ingest truncation (0=no truncation) |
| `--skip_baseline` / `--skip_compressed` | Default No | Skip one arm (for recovery, see §7) |

---

## 6. Troubleshooting

| Symptom | Cause / Action |
|---|---|
| `Error code: 400 ... inappropriate content` | LLM endpoint has content moderation blocking classic literature. Switch model/endpoint (DeepSeek direct has no issue). |
| Output large amounts of `</s>`, random chars, `扫码失败` | LLM producing degraded gibberish (OpenRouter `:free` seen this). Switch model. |
| `Still exceeds threshold after compression: X > Y` | Warning, not fatal. Means retained tail + current chunk already exceeds token_threshold; can reduce `--keep_recent_pairs` or `--chunk_chars`, or increase `--token_threshold`. |
| `compressed_pairs=0` (trace shows compression not triggered) | Ingest cumulative tokens didn't exceed `--token_threshold`. Increase `--max_ingest_chars`, reduce `--token_threshold`, or reduce `--chunk_chars`. |
| Langfuse import blank | `--dry-run` check if trace non-empty; confirm `LANGFUSE_HOST`/keys correct; `curl -s http://localhost:3100/api/public/health` check service. |
| `data file not found` | First run `python download_data.py`. |
| Large amount of `no_answer` (baseline ≥50%) | Most likely model thinking mode eating up `max_tokens`, `content`来不及生成完整 `final_answer(...)` code block. See §8. |

---

## 7. Interrupted Recovery / Salvage

EventQA entire book + 100 questions + dual arms run occasionally gets killed by network disconnect/SSH disconnect/timeout. This section provides a **no data loss** recovery flow.

Prerequisite: You **ran with ctx_debugger capturing trace** (see §4.1)—trace saved each probe's input, model reply, final_answer. Without trace capture, pure `run_eventqa.py` interrupted can only restart from beginning.

Recovery pipeline three steps:

```
   trace.jsonl  ──(1. salvage)──>  outputs/<book>_salvage/
                                          │
                                          │ Knows baseline ran to qid N-1 then broke
                                          ▼
   run_eventqa.py --skip_compressed --question_start N
                              ──(2. resume)──>  outputs/<book>/
                                                       │
                                                       ▼
                                              (3. merge)
                                              outputs/<book>/
                                                (overwrite with merged version)
```

### 7.1 Salvage Existing Probe Results from Trace

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python salvage_trace.py \
    /tmp/nexent_eventqa_trace.jsonl \
    --book_index 0 --schema narrative
```

Writes to `outputs/eventqa_full_book0_salvage/`:
- `summary.json` — Contains compressed accuracy, baseline partial accuracy, compression info (previous_summary, token_counts, num_chunks)
- `predictions_compressed.jsonl` — Compressed arm per-question results
- `predictions_baseline.jsonl` — Baseline arm already-run partial results (e.g., 0–43)

Print will tell you where baseline broke ("qids 0..43 done, 56 remaining").

**How to map trace turns to qid**: By trace internal turn order. Compressed arm's k-th `eventqa_answerer` turn = items[k]; baseline similarly. Prerequisite is **probes run sequentially, no retries**—current `run_probes` does exactly this. If retries added in future, need redesign here.

### 7.2 Resume Missing Baseline Part

Following above "qids 0..43 done", remaining qids 44..99 = 57 questions. But for safety **restart from 43** (breakpoint question likely incomplete), i.e., 56 questions:

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python run_eventqa.py \
    --book_index 0 --skip_compressed \
    --question_start 43 \
    --token_threshold 200000 --chunk_chars 100000 \
    --summary_schema narrative \
    --baseline_context_chars 800000
```

Key:
- `--skip_compressed` skip ingest + compressed probes (preserve salvage's existing compressed data)
- `--question_start 43` skip first 43 questions (this is §7.1 salvage told you done count)
- Other parameters **must match exactly interrupted run**—especially `--token_threshold` / `--chunk_chars` / `--summary_schema` / `--baseline_context_chars`, otherwise merged data not comparable

Writes to `outputs/eventqa_full_book0/{summary.json, predictions.jsonl}`, at this point **only contains qid 43..99 baseline** (compressed empty dict).

### 7.3 Merge

```bash
cd /home/feiran/nexent/sdk/benchmark/eventqa_eval
../../backend/.venv/bin/python merge_partial.py \
    --book_id eventqa_full_book0 \
    --schema narrative \
    --resume_start_qid 43
```

Reads `outputs/<book>_salvage/` and `outputs/<book>/` (after resumed run), merges writes back to `outputs/<book>/{summary.json, predictions.jsonl}`, contains:
- compressed 100 questions (from salvage)
- baseline 100 questions (0..42 from salvage, 43..99 from resumed run)
- recalculated accuracy / retention / token_reduction
- `_merge_provenance` field recording data source (which qids from salvage, which from resumed)

Merged `outputs/<book>/` format completely identical to从头跑一次完整 output—subsequent tools (Langfuse, merge after dry-run etc.) all work normally.

### 7.4 Prevent Interruption

Next time running long task use `tmux` / `nohup` / `setsid` protection, avoid SSH disconnect/terminal close killing process:

```bash
tmux new -s eventqa
# In tmux run command
# Ctrl+B then D detach; next time tmux attach -t eventqa
```

Note tmux only prevents SSH disconnect; LLM endpoint jitter/timeout still causes individual agent step failures, that case `run_agent_with_tracking`'s fallback will default to `no_answer`, won't kill entire run.

---

## 8. Known Limitations

### 8.1 Qwen3 etc. Thinking Model Impact

Qwen3 (`qwen36` etc.) has "thinking" mode: model first in `reasoning_content` channel reasons, then produces final answer in `content`. `nexent`'s `OpenAIModel` already captures both channels separately (`openai_llm.py:148-154`), so `content` **won't** have `<tool_call>` etc. pollution.

**But** thinking still impacts EventQA:
- thinking喷的 token counts toward `max_tokens` budget, **`content` may run out of budget before producing complete `final_answer(...)` code block** → smolagents parse failure → `no_answer`
- Large context (baseline feeds ~186k tokens) thinking喷得更长更乱, compared to compressed (~70k) more easily exhausts budget
- Measured one run (qwen36 / entire book 0 / narrative / token_threshold=200000):
  - baseline `no_answer` rate **66%** (29/44)
  - compressed `no_answer` rate 21% (21/100)
  - retention = compressed_acc/baseline_acc = **1.76** (compressed beats baseline, because baseline heavily误伤by thinking, not compression actually better)

**Mitigation**: Pass `extra_body={"chat_template_kwargs":{"enable_thinking":false}}` to disable thinking, let all `max_tokens` budget留给 `content`. Two entry points:

Via `.env` (recommended, globally effective):
```bash
# Either works, former more generic
LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}
LLM_ENABLE_THINKING=false
```

Via Python directly constructing `OpenAIModel`:
```python
OpenAIModel(..., extra_body={"chat_template_kwargs":{"enable_thinking": False}})
```

Code changes involve SDK three places (`agent_model.ModelConfig.extra_body` field, `openai_llm.OpenAIModel.extra_body` param, `nexent_agent.create_model` pass-through) + benchmark side `agent_runner.py` env read. Already landed, default behavior unchanged (unset = not pass = consistent with before).

**Thinking off vs on are incomparable two datasets**—if you want comparison, run twice: one default (thinking on), one `LLM_ENABLE_THINKING=false`, separately go through §3 flow, session id distinguish (e.g., `eventqa-narr-thinkON` / `eventqa-narr-thinkOFF`).

### 8.2 Salvage Mechanism Boundaries

§7's `salvage_trace.py` **maps by trace internal turn order** to `book.items[k]`, this relies on `run_probes` running sequentially, no retries. Current implementation does exactly this (one item one `run_agent_with_tracking`). If probe-level retries added in future (one item multiple agent_init), salvage's "by order" assumption breaks, need more robust qid matching strategy (e.g., by-question-text matching—but ctx_debugger's message truncation makes prefix matching also容易误判, seen fuzzy matching把累加前序事件的多个qid都归到qid=1踩坑).

### 8.3 token_reduction is Single-point Sampling

As README explains, `token_reduction` takes **last ingest turn**'s `get_token_counts()` (same method as `manual_cases`). Two schemas' last turns happen to hit same token count, retention will be same, normal sampling behavior.

### 8.4 Content Moderation Blocking

Classic literature (19th century Western novels) triggers some domestic LLM endpoints' content moderation (measured glm-5 / dashscope directly 400 `inappropriate content` blocking Gone with the Wind first chunk). This isn't something benchmark can bypass—need to switch to endpoints without literature moderation (DeepSeek direct, self-deployed Qwen3, etc.).

### 8.5 baseline_context_chars vs Model Window Balance

`--baseline_context_chars 800000` (~186k tokens) already approaches 200K window model limit—adding system prompt + question容易撞窗口; if model actual effective context shorter than nominal ("lost in the middle"), baseline accuracy further lowered, but this is **the model's真实表现 at this window size**, what benchmark should reflect, not bug.