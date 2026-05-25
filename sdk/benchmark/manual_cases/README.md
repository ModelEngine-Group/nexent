# benchmark — Nexent Agent 上下文压缩评测

评估 **Agent Context Compression** 的实用效果：压缩后 Agent 还能不能继续完成
任务、记住关键状态，且 token 确实下降。不测 summary 与原文的文本相似度，只测
**功能性保留**。

> 评测机制的完整设计说明见 [`note_benchmark.md`](note_benchmark.md)。
> 本文件只讲**怎么跑**。

---

## 运行前提

- 用 backend 的 venv（已装好 nexent SDK 与依赖）：`nexent/backend/.venv/bin/python`
- LLM 凭据在仓库根的 `nexent/.env`（`agent_runner` 会 `load_dotenv`）：
  `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- 下文命令默认你站在本目录（`sdk/benchmark/`），路径用的是相对路径。

---

## 两个入口

### 1. `test_benchmark.py` —— 端到端 case 评测（主入口）

```bash
nexent/backend/.venv/bin/python test_benchmark.py
```

自动发现 `cases/*/case.json` 下的所有 case，每个 case 跑两组对比实验：

| 组 | 压缩 | 作用 |
|---|---|---|
| Baseline | `enabled=False` | 能力天花板 |
| Compressed | `enabled=True` + case 自定义参数 | 压缩后的实际表现 |

评三个维度：**Continuation**（多轮任务延续）、**Probe**（早期历史记忆保持）、
**Token Reduction**（token 削减率）。无命令行参数；逐 case 报告写到
`reports/<case_id>.json`，跨 case 汇总写到 `reports/summary.json`。

### 2. `summary_inspector.py` —— 压缩器静态质量检查

不跑 Agent，直接检查 summary 文本是否保留了关键信息——用来区分「压缩器漏了」
与「Agent 没用上」两种故障根因。

```bash
# 跑 inspections/ 下全部用例
nexent/backend/.venv/bin/python summary_inspector.py
# 只跑指定一个
nexent/backend/.venv/bin/python summary_inspector.py -n example_infra
# 自定义压缩参数 + 顺带保存 summary 原文
nexent/backend/.venv/bin/python summary_inspector.py --config cfg.json --save-summary
```

---

## 目录结构

```
manual_cases/
├── test_benchmark.py     # 端到端 case 评测入口
├── summary_inspector.py  # 静态 summary 质检入口
├── agent_runner.py       # Agent 运行封装（构建 run info、跑带 tracking 的 agent）
├── eval_utils.py         # LLM 评分工具（eval_text / average_score）
├── cases/<case_id>/      # 端到端评测 case
│   ├── case.json         #   配置：id / history_file / queries / probes /
│   │                     #         summary_checks / task_checks / compressed_config
│   └── history.json      #   初始多轮对话历史（user/assistant pairs）
├── inspections/<name>/   # 静态质检用例
│   ├── history.json      #   待压缩的对话历史
│   └── checks.json       #   summary 关键信息检查项
├── reports/              # test_benchmark.py 输出（<case_id>.json + summary.json）
└── note_benchmark.md     # 评测机制完整设计说明
```

---

## 加一个新 case

1. 建目录 `cases/<id>/`，放 `history.json`（初始历史）与 `case.json`。
2. `case.json` 字段：`id`、`history_file`、`queries`（多轮延续问题）、
   `probes`（只问被压缩区域的记忆探针）、`summary_checks`、`task_checks`、
   `compressed_config`（压缩参数覆盖）。
3. 跑 `test_benchmark.py`，结果出现在 `reports/<id>.json`。

> 想看一次 benchmark 跑动时上下文构建与压缩的全过程 trace，用
> [`../../ctx_debugger/`](../../ctx_debugger/)（`example_with_benchmark.py` 把
> debugger 挂到 benchmark 上批量跑）。