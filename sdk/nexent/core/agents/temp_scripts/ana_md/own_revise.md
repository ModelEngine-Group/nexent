你说得对,我先把这个点确认清楚——observation 预截断(卫生开关)确实**不在压缩路径里**,它在 `_step_stream` 每步执行尾部跑,只是借 `context_manager.config` 取参数值而已。问题在于它被 `if self.context_manager and self.context_manager.config.enabled` 这个门挡住了——把"卫生"和"压缩是否启用"耦合了。


让我先精确定位再动手。你的 clone 比我之前读的版本更新——这里已经被改过了,不再是我最初看到的"裸 head+tail"。让我看全这段,以及 config 现在有哪些字段,避免重复造轮子。好,你的 clone 已经把 config 字段和卫生块都补上了——比我最初读的版本超前不少。

那么真正还**没接通**的就是核心那条死线:压缩路径调用渲染函数时不传 `offload_store`,导致 `render_action_step` 里的 offload 永远不触发,而且粒度还是"整步全文"。这才是现在该改的。让我把要改的几处的精确现状再核一遍。你的 clone 已经改得相当深入了——`render_action_step` 的两级 offload(observation 段 + 整步兜底)和自描述标记都已经写好,`current_compression` 的"新鲜压缩"路径也已经传了 `offload_store`。这跟我最初读到的版本完全不同。所以我现在的工作不是从零写,而是**找出剩下还没接通 / 不一致的调用点**。让我把所有调用点的 `offload_store` 传递情况扫一遍,定位漏网的。grep 的换行处理把 line 118 那个"已传"的判错了(它的 `offload_store=` 在下一行)。让我用更可靠的方式:逐个调用点取多行上下文,判断该调用是"真正用于发给 LLM 的渲染"(应 offload)还是"仅用于 token 估算/指纹"(绝不能 offload,否则产生副作用且污染估算)。现在分类清楚了。我把每个调用点的性质和"应否 offload"判定列出来——这决定了哪些要改、哪些**绝对不能**改:

| 调用点 | 用途 | 现状 | 应否 offload |
|---|---|---|---|
| `current_compression:79` | 增量压缩,拼给 LLM 的输入 | 未传 | **应传** |
| `current_compression:118` | 新鲜压缩,发给 LLM | 已传 ✓ | 应传 |
| `current_compression:141` | L3 fallback,发给 LLM | 未传 | **应传** |
| `previous_compression:83` | 增量压缩,拼给 LLM | 未传 | **应传** |
| `previous_compression:148` | 新鲜压缩 full_text,发给 LLM | 未传 | **应传** |
| `previous_compression:156` | 新鲜压缩 truncated,发给 LLM | 未传 | **应传** |
| `previous_compression:175` | L3 fallback,发给 LLM | 未传 | **应传** |
| `manager.py:108` | `_effective_prev_tokens` **仅 token 估算** | 未传 | **绝不能传** |
| `manager.py:127` | `_effective_curr_tokens` **仅 token 估算** | 未传 | **绝不能传** |

关键原则:**只有"渲染结果会真正进入发往 LLM 的消息"的调用点才 offload;纯估算/指纹的调用点必须传 None**——否则估算阶段就把内容存进 store 并产生 `[[OFFLOAD]]` 标记,既污染 token 估算(估的是截断后文本,与实际发送不一致),又会在 store 里堆垃圾、handle 永不出现在真实上下文里。`manager.py:108/127` 正属于后者,保持不传是对的。

所以要改的是 6 个"发给 LLM"的调用点。下面开始改,只展示改动片段。

## 改动 1:`current_compression.py` — 增量压缩路径(line 79)## 改动 2:`current_compression.py` — L3 fallback 路径(line 141)## 改动 3:`previous_compression.py` — 增量压缩路径(line 83)## 改动 4:`previous_compression.py` — 新鲜压缩 full_text(line 148)

这里有个**细节坑**:line 148 的 `full_text` 同时用于第 149 行的 token 估算判断(`if estimate_tokens_text(full_text) <= ...`)。如果在这里 offload,估算的就是截断后的文本——但这恰好是我们想要的,因为后面真正发给 LLM 的也是这个 `full_text`(line 162 的 `target_text = full_text`)。估算与发送一致,所以这里传是正确的。## 改动 5:`previous_compression.py` — 新鲜压缩 truncated 分支(line 156)Let me re-view the exact text of that branch.line 156 那处**已经有** `offload_store=self._renderer._offload_store` 了——你的 clone 里这处已经接通。剩下的是 line 175 的 L3 fallback(`reduced_text`)还没传。改它。

## 改动 5(修正):`previous_compression.py` — L3 fallback `reduced_text`(line 175)现在验证全部改动是否一致,并确认两个估算调用点(manager 108/127)保持未传。156 显示"未传"是行号偏移导致的检测假阴性(`offload_store=` 在 160 行,超出我设的 +3 窗口)。从刚才的 view 已确认它实际有传。最终用编译 + 精确计数复核。计数对上了:`current_compression` 3 处(79/118/141)、`previous_compression` 4 处(83/148/156/175),全部接通;`manager.py` 那 6 处 `offload_store` 是别的引用(`_offload_store` 初始化、property、clear 等),两个估算调用点本身确实没传。语法全部通过。

## 改动小结

我这次只动了**压缩侧渲染调用点的接线**,没动 `render_action_step` 的 offload 逻辑本身(你的 clone 里它已经写好了两级 offload + 自描述标记),也没碰 config 和卫生块(也都已就位)。

具体改了 4 处此前漏接的调用点,让 offload 真正能在所有压缩路径触发:

- `current_compression.py:79` — current 增量压缩,给 `actions_to_text` 补 `offload_store`
- `current_compression.py:141` — current L3 fallback,给 `render_steps_with_truncation` 补
- `previous_compression.py:83` — previous 增量压缩,给 `pairs_to_text` 补
- `previous_compression.py:148` — previous 新鲜压缩 `full_text`,给 `pairs_to_text` 补
- `previous_compression.py:175` — previous L3 fallback,给 `reduced_text` 补

(118 和 156 你的 clone 里已经传过了,未重复改。)

**刻意没改的两处,也是这次的关键判断**:`manager.py:108` 和 `127` 的 `pairs_to_text`/`actions_to_text` 调用保持不传 `offload_store`。它们在 `_effective_prev_tokens`/`_effective_curr_tokens` 里只做 token 估算,如果在这里 offload 会有两个 bug——一是估算阶段就往 store 里塞内容、生成 handle,而这些 handle 永远不会进真实上下文(纯垃圾);二是估算的是"截断后文本",与最终发送内容长度不一致,破坏阈值判断。这条"渲染会发给 LLM 才 offload,纯估算/指纹绝不 offload"的边界,正是上一轮我们讨论的两机制分工的代码体现。

---

剩下两件事我没动,想先跟你确认要不要继续:

1. **`pair_fingerprint` 的"尾 200 字"碰撞风险**——之前提过,offload 现在接通了,缓存命中判断的可靠性更重要了。
2. **offload store 跨 run 被 `clear()` 与 reload 标记残留的生命周期矛盾**——现在 reload 工具真接通了(你补的 `enable_reload` 那段),这个矛盾会真实触发报错。

要我接着处理这两个,还是先就当前 offload 接线跑一个最小验证(造一个超阈值的假 memory,看 offload 是否真的产生 handle、reload 能否取回)?