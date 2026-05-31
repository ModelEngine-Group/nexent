这是个很好的问题——offload 和 observation 截断确实在"处理工具输出"上重叠,但它们作用在**完全不同的生命周期阶段**,对象和粒度也不同。我先把代码里两者的真实触发点逐一钉死,再画出边界。

让我先确认几个关键事实,避免凭印象答错。这个发现很关键。让我确认压缩主流程里调用这些渲染函数时,到底传没传 `offload_store`——因为 `offload_store` 默认是 `None`,不传就不会 offload。这就把边界彻底钉死了,而且暴露出一个比"边界模糊"更严重的事实:**当前代码里 offload 实际上从不触发。** 下面我把完整图景给你。

## 先纠正一个前提:两者目前几乎没有真正的"交集"

你感觉它们有交集,是因为读代码时看到两处都"碰工具输出"。但把实际调用链跑通后会发现:

**observation 预截断是唯一真正在跑的工具输出处理;offload 这条路在当前代码里是死的。** 原因有两层:

1. 所有压缩侧的渲染调用(`pairs_to_text`、`actions_to_text`、`render_steps_with_truncation`)**没有一个传入 `offload_store`**,而该参数默认 `None`。`render_action_step` 里 offload 的前置条件是 `offload_store is not None`——永远不满足。
2. 即便传了,它读的 `self._config.per_step_render_limit` 字段在 `ContextManagerConfig` 里**根本没定义**,会 `AttributeError`。

所以现状是:**observation 截断在 source 阶段独立工作;offload 是一套写好但没接线的设施。** 你困惑的"边界",本质上是"作者设计了两个本应分工的机制,但只接通了一个"。下面我按"应然的边界"来讲,这也是 prac_scheme 想达到的状态。

## 两者的真实坐标:作用在不同生命周期阶段

把一条工具输出的一生画出来,两个机制站在不同的时间点:

```
[step 执行完] → observation 生成
      │
      ├─① observation 预截断  ← core_agent._step_stream 尾部,写入 memory 之前
      │      对象: 单条 observation 字符串
      │      触发: enabled 且 max_observation_length>0 且 len>该值
      │      手法: head+tail,丢中段,不可逆,无 handle
      │      时机: 每一步都过,与压缩无关
      ▼
[observation 进入 memory_step.observations]  ← 这是"已经被①处理过的"文本
      │
      │  ...后续每一步都把整个 memory 重新 write_memory_to_messages...
      │
      ▼
[某步 token 超阈值 → compress_if_needed 触发]
      │
      ├─② offload  ← 压缩时,在 render_action_step 内
      │      对象: 整个 step 的渲染全文(model_output+tool-call+observation 拼接)
      │      触发: 该 step 落在"待压缩区间"(keep_recent 之外) 且 渲染全文>per_step_render_limit
      │      手法: head + [[OFFLOAD:handle]],存原文,可 reload
      ▼
[被压缩的旧 step → 摘要文本 / offload 标记;keep_recent 的近期 step → 原样保留]
```

关键区别一句话:**① 是"入库前的卫生",作用对象是单条 observation,每步必过,不可逆;② 是"压缩时对旧步的归档",作用对象是整步全文,只对滑出近窗的旧步,可逆。**

## 压缩 / 非压缩 × prev / curr 下,谁在起作用

| 场景 | observation 预截断① | offload② |
|------|------|------|
| **非压缩**(token 未超阈值,或 `enabled=False`) | 若 `enabled` 且 `max_observation_length>0`,**每步都生效** | **完全不参与**(只有 `compress_if_needed` 路径才会调渲染函数) |
| **压缩 - current 待压缩区**(`curr_action_steps[:-keep_recent_steps]`) | ① 早已在这些 step 入库时做过了(若开启) | 这些旧 step 进 `actions_to_text`/`render_steps_with_truncation` 摘要;**应**在此 offload 超长步,但现状没传 store → 不触发 |
| **压缩 - current keep_recent 区**(`[-keep_recent_steps:]`) | 同上,入库时做过 | **不 offload**——这正是设计意图:近期步骤要保原样,模型马上还要用 |
| **压缩 - previous 待压缩区**(`prev_pairs[:-keep_recent_pairs]`) | 历史步入库时做过(若当时开启) | 这些 pair 进 `pairs_to_text` 摘要;**应** offload 超长步,现状同样不触发 |
| **压缩 - previous keep_recent 区**(`prev_pairs[-keep_recent_pairs:]`) | 入库时做过 | **不 offload**,保原文 |

从这张表能看出**它们的分工本应是正交的,不是重叠的**:

- ① 管的是"**单条 observation 太长怎么办**"——无论这步将来压不压,先把超大输出(整个文件、长 API 返回)在源头削到 `max_observation_length`。这是防止任何单步污染所有后续轮次的卫生措施。
- ② 管的是"**一个旧步整体太长、要被摘要时,如何不彻底丢失它**"——摘要是有损的,offload 给旧步留一份可回取的原文。它只对"已经决定要压缩掉"的旧步起作用。

它们碰到同一份 observation,只是在不同时刻、以不同身份:① 在它刚出生时限制它的体型;② 在它年老即将被摘要时给它拍张存档照。**理想边界:① 之后进 memory 的 observation 已经是 bounded 的;② 处理的是"即便每条 observation 都 bounded,整步拼起来仍然过长的旧步"。**

## offload 的判决条件:对象、时机、谓词

把 offload 的决策拆成三个正交问题,逐个给精确条件(这是它"应该"的样子,也是需要补线的地方):

**对象(what)** — 现状是"整步渲染全文",粒度过粗。prac_scheme 的方案2 是把它细化为"observation 段独立卸载"。我的看法:对象应按内容角色分两类——
- 工具输出(observation):长且多为一次性数据(文件、检索结果)→ 高 offload 价值;
- 产物型 model_output(草稿、报告正文):需逐字回取 → 也该 offload;
- 过程型 model_output(推理、思考):摘要即可,不必 offload。

**时机(when)** — 严格地:`compress_if_needed` 触发 **且** 该 step ∈ 待压缩区间(`keep_recent_*` 之外)**且** 渲染长度 > 阈值。近窗步骤永不 offload 是硬约束——这是 offload 与"模型马上要用的上下文"之间的安全边界。

**谓词(judge)** — 现状只有一个长度谓词 `len(full_text) > per_step_render_limit`。更好的判决应是二维的:`长度 × 未来复用概率的反比`。但"未来复用概率"难预测,所以实践上用 `keep_recent` 窗口做代理(近=高复用→不 offload,远=低复用→可 offload)+ 长度阈值,已经够用。真正缺的是**让谓词作用在正确的粒度上**(observation 段而非整步)和**让标记自描述**(`[[OBS_OFFLOAD: read_file output, 4.2KB, handle=...]]`),好让模型自己判断要不要 reload。

## 所以,边界在哪——一句话总结

**observation 预截断是"每步入库前、对单条工具输出的不可逆体型限制",offload 是"压缩时、对滑出近窗的旧步、为对抗摘要有损而做的可逆原文归档"。前者管单条输出的瞬时大小,后者管旧步整体在被摘要前的可恢复性。二者本应在生命周期上首尾衔接、不重叠;现状的"交集错觉"来自 offload 这条路其实没接通——既没传 `offload_store`,配置字段也缺失。**

要把它从"看似重叠且失效"变成"清晰分工且可用",最小修复是三步:补全 config 字段(`per_step_render_limit` / `max_offload_entries` / `enable_reload` / `max_observation_render_length`)→ 在压缩渲染调用点把 `self._offload_store` 传进去 → 按 prac_scheme 方案2 把 offload 粒度落到 observation 段并让标记自描述。


## 修改分析
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
