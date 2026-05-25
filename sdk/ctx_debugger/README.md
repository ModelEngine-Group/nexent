# ctx_debugger — Nexent 上下文调试器

观测 Nexent Agent 的**上下文构建与压缩**全过程的调试工具。从 system prompt、
多轮历史、压缩决策、LLM 调用，到工具执行、observer 事件，全部记录成可分析的
JSONL trace。

> **核心定位**：Nexent agent 运行时已经在「自言自语」（observer 事件、压缩日志、
> token 统计），ctx_debugger 就是在旁边「偷听」并结构化记录，**不改 Nexent 源码**。

---

## 1. 它解决什么问题

Agent 上下文压缩（`ContextManager`）出问题时，开发者需要回答：

- 这一步为什么触发了压缩？为什么没触发？
- 压缩 LLM 吃进去什么、吐出来什么、花了多久？
- 压缩后 agent 实际看到的上下文长什么样？
- summary 保留了哪些信息、丢了哪些？
- token 到底降了多少（含压缩调用本身的开销）？

这些信息散落在 `ContextManager` 内部状态、`step_metrics`、`MessageObserver`
事件里，没有统一、可回溯的视图。ctx_debugger 把它们汇成一份 trace。

---

## 2. 目录结构

```
ctx_debugger/
├── __init__.py              # 包入口，re-export ContextDebugger / attach_debugger
├── __main__.py              # python -m ctx_debugger.inspector 的入口
├── debugger.py              # 核心：ContextDebugger、attach_debugger、各层 proxy
├── interactive.py           # 交互式 REPL（主力调试模式）
├── inspector.py             # trace 文件的事后分析 CLI
├── langfuse_export.py       # 把 trace 导入 Langfuse 做可视化分析
├── example_with_benchmark.py# 把 debugger 挂到 benchmark 上批量跑
└── README.md
```

依赖方向：**ctx_debugger → 仅 import nexent SDK**，nexent 不反向依赖本包。

---

## 3. 运行前提

> 下文命令默认你站在本目录（README 所在的 `ctx_debugger/`）。相对路径约定：
> `.` = `ctx_debugger/`，`..` = `sdk/`，`../..` = nexent 仓库根目录
> （`sdk/`、`backend/`、`.env` 所在的那一层）。

- 用 backend 的 venv Python（已装好 nexent SDK 与依赖）：
  ```
  ../../backend/.venv/bin/python
  ```
- LLM 凭据在仓库根的 `.env`，即 `../../.env`（`agent_runner` 会 `load_dotenv`）：
  ```
  LLM_API_KEY=...
  LLM_MODEL_NAME=...
  LLM_API_URL=...
  ```
- trace 输出路径由环境变量 `NEXENT_CONTEXT_DEBUG` 控制，或在 `attach_debugger`
  里显式传 `trace_path`。

---

## 4. 三种使用模式

### 4.1 交互式 REPL —— 主力模式

你一句句输入 user 消息，每行触发一轮真实 agent 执行；历史累积、
`ContextManager` 跨轮共享，压缩到阈值自然触发。

```bash
# 在 ctx_debugger/ 目录下
../../backend/.venv/bin/python interactive.py
```

每轮自动显示 agent 回答 + context construction 面板（agent steps、main/压缩
LLM 调用、压缩是否触发、token 削减、summary 是否更新）。

面板里 token 数分两类，已分别标注：`main LLM` / `compression LLM` 行带
`(API)`，是 LLM 实报的 `token_usage`；`compression` 行带 `(est.)`，是
`ContextManager` 的启发式估算（`estimate_tokens_text`，CJK 感知，不走真
tokenizer）。**压缩阈值判断用的是估算值**，与 API 实测会有差值（中文文本上
启发式通常偏高估）。

Slash 命令：

| 命令 | 作用 |
|---|---|
| `/help` | 命令列表 |
| `/context [N]` | 上一轮主 LLM 实际收到的 context（压缩后：system + summary + 最近几轮）；`N` 选第 N 次主调用 |
| `/history` | 累积的 session 原始账本（每轮逐字，压缩前；REPL 自身的记账，不是模型看到的）|
| `/summary` | 当前压缩 summary 全文 |
| `/compress` | 上一轮压缩 LLM 的输入 prompt（喂进去的）与输出 summary（吐出来的），与主回答区分开 |
| `/tokens` | 逐轮 token 时间线 |
| `/stats` | 整个 session 的压缩统计——重点是「调用 LLM 的语义压缩」累计次数，外加缓存命中、token 开销 |
| `/trace` | 上一轮原始事件表 |
| `/step N` | 上一轮第 N 步的全部事件 JSON |
| `/config` | 当前 `ContextManagerConfig` |
| `/reset [threshold]` | 清空重来，可选新阈值 |
| `/quit` `/q` | 退出 |

默认 `token_threshold=3000`，几轮对话即可触发压缩。

输入行支持上/下方向键回溯历史（shell 习惯），历史持久化在
`~/.nexent_ctx_debugger_history`，跨 session 保留。

### 4.2 批量挂到 benchmark

不改 benchmark 代码，monkey-patch `CoreAgent.__init__` 让每个 agent 自动挂
debugger，整轮 benchmark 跑完得到一份 trace。

```bash
# 在 ctx_debugger/ 目录下
NEXENT_CONTEXT_DEBUG=/tmp/trace.jsonl \
  ../../backend/.venv/bin/python example_with_benchmark.py
```

### 4.3 事后分析 trace 文件

```bash
# 在上一级 sdk/ 目录下
cd ..
python -m ctx_debugger.inspector <子命令> <trace.jsonl> [选项]
```

| 子命令 | 作用 |
|---|---|
| `summary` | 总览：事件数、run 数、token 总量、事件直方图 |
| `runs` | 列出所有 run |
| `timeline [--run X]` | 按时间顺序的事件列表 |
| `compress` | 所有压缩周期的决策与 token 削减 |
| `llm [--tag main\|compression]` | LLM 调用列表（时长、token） |
| `step --step N [--run X]` | 某一步的全部事件 JSON |

`--run` 支持用 8 位短后缀匹配。

### 4.4 导入 Langfuse 做可视化分析

把 trace 映射进自托管的 [Langfuse](https://langfuse.com)，得到嵌套 trace、
逐调用 drill-down、token/耗时视图、session 分组——不必自己写 web 界面。

```bash
# 在上一级 sdk/ 目录下
cd ..
# 先干跑，看映射结构（不联网）
python -m ctx_debugger.langfuse_export <trace.jsonl> --dry-run
# 配好凭据后真正导入
LANGFUSE_HOST=http://localhost:3000 \
LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-... \
  python -m ctx_debugger.langfuse_export <trace.jsonl>
```

映射规则：

| ctx_debugger | Langfuse |
|---|---|
| 每个 agent 回合（`agent_init`） | 一条 trace |
| `llm_call_*` | generation（input/output、token、耗时） |
| `compress_*` | span，内部嵌套该周期的压缩 generation |
| `tool_call_*` / `code_execute_*` | tool / span 观测 |
| 整个 trace 文件 | 一个 Langfuse session（回合归组） |

依赖 `langfuse` SDK（`uv pip install langfuse`）。自托管 Langfuse 可用官方
docker compose 一键起。**已知限制**：observation 在导出时刻创建，单条耗时真实，
但在 Langfuse 时间轴上的绝对位置是导出时间、非原始时间。

---

## 5. 核心 API

### `attach_debugger(target, ...)`

把 debugger 挂到一个 agent 或 `ContextManager` 上。

```python
from ctx_debugger import attach_debugger
from nexent.core.agents.agent_context import ContextManager

cm = ContextManager(config=...)
attach_debugger(cm, trace_path="/tmp/run.jsonl")          # 只挂压缩层
# 或挂整个 agent，自动覆盖五层
attach_debugger(agent, trace_path="/tmp/run.jsonl")
```

参数：

| 参数 | 说明 |
|---|---|
| `target` | Nexent agent（CoreAgent/NexentAgent）或 `ContextManager` |
| `trace_path` | 输出 JSONL 路径；为空时回落到 `NEXENT_CONTEXT_DEBUG` 环境变量 |
| `layers` | `{"compression","model","observer","tools","executor"}` 的子集，默认全开 |
| `run_id` | 显式 run 标识，默认自动生成 |
| `capture_full_summary` | 压缩事件里是否带 summary 全文，默认 True |
| `capture_full_messages` | 主 LLM 调用是否也存消息全文，默认 False；压缩 LLM 调用始终存全文 |
| `append` | 追加到已有 trace 而不是覆盖 |
| `existing` | 复用一个已有的 `ContextDebugger`（交互式 session 跨多轮共享同一 trace/run_id 用） |

未解析到 trace 路径时返回 `None` 不做任何包装（零开销）。

### 五个观测层

| layer | 挂点 | 捕获 |
|---|---|---|
| `compression` | `ContextManager.compress_if_needed` 包装 | 压缩决策、压缩调用记录、summary 前后状态 |
| `model` | `agent.model` 换成 `_ModelProxy` | 每次 LLM 调用的输入输出/token/时长，并用 contextvar 标记 `main` vs `compression` |
| `observer` | `agent.observer.add_message` 镜像 | Nexent 自有的所有 observer 事件 |
| `tools` | 每个 `tool.forward` 实例级包装 | 单工具粒度的 args / return / 时长 |
| `executor` | `agent.python_executor` 换成 `_PyExecutorProxy` | 执行的 Python 代码全文 + 输出 + 时长 |

---

## 6. Trace 事件 Schema

每行一条 JSON，统一外层字段：

```json
{
  "seq": 42,                 // 全局单调递增序号
  "ts": 1778813372.87,       // Unix 时间戳
  "run_id": "run_a70c9017",  // 一次 attach 对应一个 run
  "agent_step": 1,           // 当前 agent 步号（来自 observer 的 step_count）
  "event": "compress_end",
  "data": { ... }            // 事件专属字段
}
```

事件类型：

| event | 何时发 | data 关键字段 |
|---|---|---|
| `run_begin` | debugger 创建时 | pid |
| `agent_init` | attach 到 agent 时 | system_prompt 全文、tools 列表、cm config |
| `compress_begin` | `compress_if_needed` 入口 | `predicted_decision`（决策分支 + compress_prev/curr）、`estimated_tokens` |
| `compression_call` | step 内每次压缩调用 | call_type、cache_hit、in/out tokens |
| `compress_end` | `compress_if_needed` 出口 | `token_counts`（压缩前后）、`summary_after`、`summary_changed` |
| `llm_call_begin` / `llm_call_end` | 每次 LLM 调用 | `tag`（main/compression）、input messages（压缩调用每条带 `text` 全文）、output（压缩调用带 `output_full` 全文）、token、时长 |
| `code_execute_begin` / `code_execute_end` | python executor 执行 | 代码全文、输出、logs、时长 |
| `tool_call_begin` / `tool_call_end` | 每个工具调用 | tool 名、args、return、时长 |
| `observer_event` | Nexent observer 每条消息 | process_type、content preview |
| `debug_error` | debugger 内部异常 | phase、error（不会中断 agent） |

文本字段都做了 bounded 截断（头 N 字 + `...[N chars elided]...` + 尾 M 字），
避免 trace 文件无限膨胀。

---

## 7. 设计原则

1. **零 SDK 源码改动**：靠 monkey-patch 包装 + proxy 对象，不动 `nexent/` 一行。
2. **只读公共面 + 少量稳定内部接口**：用到的 `_step_local_log`、
   `_effective_*_tokens` 等下划线接口，benchmark 本身也在用，视为事实稳定。
3. **五层可选**：`layers` 参数按需收窄，trace 体积可控。
4. **失败隔离**：每个挂点 try/except 兜底，单层失效只发 `debug_error` 事件，
   不会让 agent 崩。
5. **复用 Nexent 自有事件**：`observer` 层直接镜像 `MessageObserver`，不重复造轮子。
6. **不污染前端**：observer tap 改的是 instance 的 `add_message`，原方法照常调用，
   前端流不受影响。

### 与 Nexent 的耦合点

debugger 是「模拟/偷听」Nexent 行为，因此存在软耦合——Nexent 改了下列接口，
debugger 要跟着改（其它改动一律自动适配）：

- `agent.model` / `agent.observer` / `agent.python_executor` / `agent.tools` 重命名
- `tool.forward` 改方法名
- `compress_if_needed` 签名变化
- `observer.add_message` 参数顺序大改

---

## 8. 已知限制

- **主 LLM 调用默认只存 digest**：压缩 LLM 调用的 input messages 与 output 已
  逐字全量保存（每条消息带 `text`，输出带 `output_full`）；主 LLM 调用默认仍是
  截断 digest，需要全文时给 `attach_debugger` 传 `capture_full_messages=True`。
  交互式 REPL 已默认开启该选项，所以 `/context` 能看到全文。
- **trace 文件不限大小**：长 session 可能几十 MB；`inspector` 目前一次性载入内存。
- **多 agent 嵌套**：每次 attach 一个 run_id；交互式 session 用 `existing=` 复用
  同一 debugger 来统一 run_id。
- **交互式 REPL 需要真 TTY**：管道喂输入也可用，但体验为交互设计。
