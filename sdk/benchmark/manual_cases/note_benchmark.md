# Benchmark 测试机制分析
> LongBench、LooGLE、Needle等Benchmark评估的是基础LLM的长上下文理解能力（一次性输入长文本，测试理解/推理/检索），而非Agent的上下文压缩能力（多轮交互后历史被压缩，测试压缩后能否继续工作）。
## 1. 核心目标

评估 **Agent Context Compression** 的实用效果，回答：

> **压缩后，Agent 是否还能继续工作，并记住关键状态？**

不评估 summary 与原文的文本相似度，而是评估**功能性保留**。

重点三个维度：
- **Continuation**：压缩后还能否继续完成任务
- **Memory Retention**：压缩后还能否记住关键状态
- **Token Reduction**：token 是否有效下降

---

## 2. 测试结构：每个 Case 的两组实验

每个 `cases/<case_id>/` 目录包含：
- `history.json`：初始多轮对话历史（user/assistant pairs）
- `case.json`：测试配置与检查条件

每个 case 跑两组对比实验：

| 组 | 压缩状态 | 目的 |
|---|---|---|
| **Baseline** | `enabled=False` | 无压缩，测能力天花板 |
| **Compressed** | `enabled=True` + 自定义参数 | 开启压缩，测实际表现 |

---

## 3. Case 配置关键字段

```json
{
  "queries": [],        // 多轮 continuation 问题
  "probes": [],         // 记忆探针问题（测 early history）
  "task_checks": [],    // 任务输出检查
  "summary_checks": [], // 静态摘要检查
  "compressed_config": {} // 压缩参数覆盖
}
```

---

## 4. 三大评估维度

### 4.1 Continuation Evaluation（任务延续能力）

模拟真实多轮 Agent 交互：
- 按顺序执行 `queries`，每轮将 `(query, answer)` 追加到 history
- Compressed 组**共享同一个 ContextManager**，压缩在运行中**持续触发**
- 对指定轮次的 `final_answer` 做 `task_checks` 评分

**指标**：`task_success_retention = compressed_task_score / baseline_task_score`

---

### 4.2 Probe Evaluation（记忆保持能力）

检验压缩后 Agent 能否**利用** summary 中残留的信息，回答关于早期历史的问题。

**关键设计**（避免冗余 LLM 调用）：
1. 从 compressed run 的 `export_summary()` 获取摘要与压缩边界
2. `build_precompressed_history()` 构建预压缩 history：
   - 被压缩的前缀 pairs → 替换为一条 user summary message
   - 保留的尾部 pairs → 原样保留
3. 所有 probes **复用同一份**预压缩 history
4. 每个 probe `deep copy` 后**独立运行**，压缩禁用

Baseline Probe 同样基于 compressed run 结束后的完整 history 运行，建立天花板。

**指标**：`probe_retention = compressed_probe_score / baseline_probe_score`

**Probe 构建原则**：只问被压缩区域（early history）的信息。若问尾部保留区域，则测不出 memory retention。

---

### 4.3 Static Summary Inspection（压缩器静态质量）

不跑 Agent，直接检查 summary 文本是否包含关键信息。

- 对 `previous_summary + current_summary` 做 `summary_checks`
- 与 Probe Eval 区分故障根因：

| | Probe Eval | Static Inspection |
|---|---|---|
| 输入 | 完整压缩上下文（summary + 尾部保留 steps） | 仅 summary 文本 |
| 执行方式 | 跑 Agent（LLM） | 直接文本检查 |
| 测什么 | Agent **能否利用**残留信息 | 压缩器 **是否保留**了关键信息 |
| 失败含义 | summary 有但 Agent 没用上 | summary 里根本就没有 |

---

## 5. Token Reduction 计算

两级 fallback：
1. **优先用 ContextManager 实际 token 统计**：取 compressed run 最后一轮的 `last_uncompressed` vs `last_compressed`
2. **Fallback 文本估算**：`1 - compressed.final_tokens / baseline.final_tokens`

---

## 6. 最终报告结构

```json
{
  "case_id": "...",
  "baseline": { "task_score", "probe_score", "final_tokens" },
  "compressed": { "task_score", "probe_score", "final_tokens", "cm_stats", "cm_summary" },
  "metrics": {
    "task_success_retention": ...,   // 任务延续保留率
    "probe_retention": ...,          // 记忆探针保留率
    "token_reduction": ...,          // token 压缩率
    "summary_score": ...             // 静态摘要评分
  },
  "task_eval": [...],
  "probe_eval": { "baseline": [...], "compressed": [...] },
  "summary_inspection": [...]
}
```

所有 case 汇总至 `reports/summary.json`。

---

## 7. 关键设计原则总结

1. **Stateful Continuation**：Compressed 组共享 `ContextManager`，模拟真实运行
2. **Probe 隔离**：每个 probe `deep copy` + 独立运行，互不污染
3. **Probe 复用压缩结果**：预压缩 history 只构建一次，避免重复 LLM 调用
4. **Inspection vs Probe 分离**：区分「压缩器漏了」与「Agent 没用上」两种故障
5. **只测功能性**：不测文本相似度，测 Agent 在压缩上下文中的实际工作能力
