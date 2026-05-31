# Offload 机制完整修改计划

## 背景

`ContextManager` 中有两条处理工具输出（observation）的机制，它们作用在不同生命周期阶段，但当前只有 observation 预截断在跑，offload 是一条"设计完善但未接通"的路径。

### 两条机制的分工

| | ① observation 预截断 | ② offload |
|---|---|---|
| **位置** | `core_agent._step_stream` 尾部 | 压缩路径的渲染函数内 |
| **时机** | 每步执行后，observation **入库前** | 压缩触发时，step **被渲染为 LLM 输入时** |
| **对象** | 单条 observation 字符串 | 单个消息段（model_output / observation） |
| **粒度** | 整条 observation | 按消息段独立判定 |
| **可逆性** | 不可逆（head+tail，丢中段） | **可逆**（存原文到 OffloadStore，handle 可 reload） |
| **作用区间** | 所有 step（与压缩无关） | 仅滑出 `keep_recent` 窗口的旧 step |
| **目的** | 防止单条超大输出污染所有后续轮次 | 防止压缩 LLM 输入因个别超大 step 而爆炸，同时保留信息可恢复性 |

### 当前断点

1. **调用链未接通**：`current_compression.py` 和 `previous_compression.py` 中 7 个发给 LLM 的渲染调用点未传入 `offload_store`（默认 `None`），导致 offload 判定永远不触发。

2. **配置字段缺失**：`step_renderer.py` 引用的 `per_step_render_limit` 在 `ContextManagerConfig` 中未定义，即使调用链接通也会 `AttributeError`。

3. **粒度太粗**：offload 判定对象是整步渲染全文（model_output + tool_call + observations 拼接），应下沉到**按消息段独立判定**——observation 超长则单独卸载，model_output 和 tool_call 保留原文，让压缩 LLM 有足够上下文做摘要。

4. **摘要丢失 handle**：压缩 LLM 产出的 summary JSON 中不保留 offload handle，主 Agent 后续无法用 `reload_original_context` 取回原文。

5. **Prompt 未指导**：`summary_system_prompt` 和 `incremental_summary_system_prompt` 未说明如何处理 `[[OFFLOAD]]` 标记，LLM 可能污染摘要或产生幻觉。

6. **observation 截断与 enabled 耦合**：`core_agent.py:430` 中 observation 截断被 `config.enabled` 门挡住，用户无法单独启用卫生截断而不启用压缩。

---

## 修改总览

```
修改文件: 5 个
├── summary_config.py        [奠基] 补全配置字段 + 更新 prompt/schema
├── step_renderer.py         [核心] 重构 offload 粒度为"按消息段独立判定"
├── current_compression.py   [接线] 3 个调用点传入 offload_store
├── previous_compression.py  [接线] 4 个调用点传入 offload_store
└── core_agent.py            [解耦] observation 截断与 enabled 脱钩（可选）
```

---

## 修改 1：`summary_config.py` — ContextManagerConfig

**文件路径**：`nexent\core\agents\summary_config.py`

### 1.1 新增字段：`per_step_render_limit`

**位置**：`ContextManagerConfig` 类中，`max_observation_length` 附近（约第 68 行后）

**为什么改**：`step_renderer.py` 中 `_render_segment` 和 `render_action_step` 已引用 `self._config.per_step_render_limit`，但该字段在 `ContextManagerConfig` 中不存在。不补全会导致 `AttributeError`。

**修改**：

```python
# 在 max_observation_length 字段附近新增：
per_step_render_limit: int = 0
"""Per-segment character threshold for offload.
When a rendered message segment exceeds this length and offload_store
is available, the full text is stored and replaced with an [[OFFLOAD]]
marker. 0 = disabled (no offload). Suggested value: 15000~30000.
"""
```

### 1.2 更新 `summary_json_schema`：新增 `offloaded_content` 字段

**位置**：`summary_json_schema` 的 `default_factory`（约第 50 行）

**为什么改**：压缩 LLM 产出的摘要如果不保留 handle，主 Agent 后续无法用 `reload_original_context(handle=...)` 取回原文，offload 存档变成"知道存在但无法访问"的幽灵数据。

**修改**：在 schema dict 末尾追加 `offloaded_content` 字段：

```python
summary_json_schema: Dict[str, Any] = field(default_factory=lambda: {
    "task_overview": "User's core request and success criteria (<=150 words)",
    "completed_work": "Work completed, files or results produced (<=200 words)",
    "key_decisions": "Important findings, decisions made and reasons (<=200 words)",
    "pending_items": "Specific steps pending, blockers (<=150 words)",
    "context_to_preserve": "User preferences, domain details, commitments (<=150 words)",
    "offloaded_content": [
        {
            "handle": "str: UUID handle for reloading the full archived content",
            "description": "str: what was offloaded (tool name, file name, segment type, size)",
            "step": "int: step number where the offload occurred"
        }
    ],
})
```

### 1.3 更新 `summary_system_prompt`：增加 offload 标记处理指引

**位置**：`summary_system_prompt` 字段（约第 28-33 行）

**为什么改**：LLM 不认识 `[[OBS_OFFLOAD]]` / `[[CONTENT_OFFLOAD]]` 标记，可能将其当成普通文本写入摘要、或试图"总结"标记内容而产生幻觉。需要明确指导如何处理。

**修改**：在原 `summary_system_prompt` 文本末尾追加 offload 处理指引：

```python
summary_system_prompt: str = (
    "You are a conversation summarization assistant. Compress the following "
    "conversation history into a structured summary, preserving all key information: "
    "user's core requirements, completed work, important findings and decisions, "
    "pending items, and context to preserve. Output strict JSON format without markdown blocks.\n\n"
    "When you see [[OBS_OFFLOAD: ...]] or [[CONTENT_OFFLOAD: ...]] markers in the "
    "conversation, these indicate that the full content for that segment has been "
    "archived externally and can be retrieved by the agent using the provided handle. "
    "Handle them as follows:\n"
    "- DO NOT copy the markers verbatim into your summary fields.\n"
    "- Record each offloaded segment in the 'offloaded_content' list with its handle, "
    "  a brief description (tool name, file name, size from the marker), and step number.\n"
    "- In other fields (e.g., 'completed_work'), reference offloaded content concisely, "
    "  e.g., 'Read config.json (full content archived, see offloaded_content).'\n"
    "- If a marker's visible prefix is insufficient to determine what happened, note it "
    "  as '[Step N: content archived]' rather than guessing.\n"
    "- If no offload markers appear in the conversation, set 'offloaded_content' to an empty list []."
)
```

### 1.4 同步更新 `incremental_summary_system_prompt`

**位置**：`incremental_summary_system_prompt` 字段（约第 39-48 行）

**为什么改**：增量压缩路径使用独立的 prompt，同样需要 offload 标记处理指引，否则增量摘要也会丢失 handle 或污染内容。

**修改**：在原有文本末尾追加与 1.3 相同的 offload 处理指引段落（额外增加 MERGE 逻辑）：

```python
incremental_summary_system_prompt: str = (
    "You are a conversation summarization assistant updating an existing "
    "structured summary. The input has two sections: '## Previous Summary' "
    "(the prior compaction) and '## New Conversations' or '## New Steps' "
    "(turns that occurred after the prior compaction). Produce an updated "
    "JSON summary that PRESERVES information from the previous summary "
    "(do not drop it unless clearly obsolete), MERGES the new turns into "
    "the appropriate fields, and KEEPS the same JSON schema. Do not include "
    "narration outside the JSON. No markdown code blocks.\n\n"
    "When you see [[OBS_OFFLOAD: ...]] or [[CONTENT_OFFLOAD: ...]] markers in the "
    "conversation, these indicate that the full content for that segment has been "
    "archived externally and can be retrieved by the agent using the provided handle. "
    "Handle them as follows:\n"
    "- DO NOT copy the markers verbatim into your summary fields.\n"
    "- Record each offloaded segment in the 'offloaded_content' list with its handle, "
    "  a brief description (tool name, file name, size from the marker), and step number.\n"
    "- In other fields, reference offloaded content concisely.\n"
    "- If the previous summary already contains an 'offloaded_content' list, MERGE new "
    "  entries into it rather than replacing it.\n"
    "- If no offload markers appear, set 'offloaded_content' to an empty list []."
)
```

---

## 修改 2：`step_renderer.py` — 重构 offload 粒度

**文件路径**：`nexent\core\agents\agent_context\step_renderer.py`

### 核心问题

当前 `render_action_step` 的 offload 判定对象是**整步拼接后的 `full_text`**：

```
model_output (800 chars) + tool_call (200 chars) + observations (50000 chars)
                → 拼接为 full_text (51000 chars)
                → 判定: 51000 > per_step_render_limit → offload 整步
                → 结果: 压缩 LLM 只能看到前 limit 字符（可能只有 model_output 的前半段）
                →       看不到 tool name，看不到 observation 开头 → 摘要质量极差
```

虽然 `render_action_step` 内部**已经在逐消息处理**（`for msg in msgs`），但 offload 判定放在了拼接之后。应把判定下沉到每个消息段。

### 理想粒度

按 `ActionStep.to_messages()` 产出的消息类型分别判定：

| 消息段 | 特征 | 是否应 offload |
|--------|------|---------------|
| `model_output`（推理/思考） | 中等长度，语义密集 | 通常不 offload；极端情况可 offload |
| `tool_call` | 很短（~200 chars） | **从不 offload** |
| `observations`（工具输出） | **主导长度**，可达数万字符 | **最需要 offload** |

### 2.1 修改 `render_action_step`：整步判定 → 按段判定

**函数**：`StepRenderer.render_action_step`（第 211-237 行）

**当前代码**：

```python
def render_action_step(self, action: ActionStep, offload_store: Optional[OffloadStore] = None) -> str:
    if has_invoked_tools(action):
        msgs = action.to_messages(summary_mode=False)
        parts = []
        for msg in msgs:
            text = _extract_text_from_messages([msg]) or ""
            if text.startswith("Calling tools:"):
                parts.append(f"Tool calls: {', '.join(action.invoked_tools)}")
            else:
                parts.append(text)
        full_text = "\n".join(parts)
    else:
        msgs = action.to_messages(summary_mode=False)
        full_text = _extract_text_from_messages(msgs) or ""
    if offload_store is not None and self._config.per_step_render_limit > 0 and len(full_text) > self._config.per_step_render_limit:
        handle = offload_store.store(full_text)
        limit = self._config.per_step_render_limit
        return full_text[:limit] + f"\n...[Content offloaded: [[OFFLOAD:handle={handle}]]]"
    return full_text
```

**修改后**：

```python
def render_action_step(self, action: ActionStep, offload_store: Optional[OffloadStore] = None) -> str:
    """Render an ActionStep to text, with per-segment offload.

    Each message segment (model_output, tool_call, observation) is independently
    checked against the offload threshold. Only oversized segments are offloaded;
    other segments remain intact, giving the compression LLM sufficient context
    to produce a high-quality summary.
    """
    if has_invoked_tools(action):
        msgs = action.to_messages(summary_mode=False)
        parts = []
        for msg in msgs:
            text = _extract_text_from_messages([msg]) or ""
            if text.startswith("Calling tools:"):
                # Tool call is always short -> keep verbatim with compact format
                parts.append(f"Tool calls: {', '.join(action.invoked_tools)}")
            else:
                # Per-segment offload check: observation or model_output
                parts.append(self._render_segment(text, offload_store))
        return "\n".join(parts)
    else:
        # No invoked tools: single segment (model_output only)
        msgs = action.to_messages(summary_mode=False)
        full_text = _extract_text_from_messages(msgs) or ""
        return self._render_segment(full_text, offload_store)
```

### 2.2 新增方法 `_render_segment`：单段渲染 + 自描述 offload 标记

**位置**：在 `StepRenderer` 类中，`render_action_step` 之后

```python
def _render_segment(self, text: str, offload_store: Optional[OffloadStore] = None) -> str:
    """Render a single message segment, with optional offload for oversized content.

    When the segment exceeds ``per_step_render_limit``, the full text is archived
    in ``offload_store`` and replaced with a self-describing [[OFFLOAD]] marker
    that tells the compression LLM what was offloaded and how to retrieve it.

    Args:
        text: The raw segment text (e.g., model_output or observation).
        offload_store: OffloadStore for archiving oversized segments.
                       When None or limit is 0, offload is disabled.

    Returns:
        The rendered segment — either the full text, or a truncated version
        with a self-describing [[OFFLOAD]] marker.
    """
    limit = self._config.per_step_render_limit
    if offload_store is None or limit <= 0 or len(text) <= limit:
        return text

    # --- Offload triggered ---
    handle = offload_store.store(text)

    # Build a self-describing marker so the compression LLM understands
    # what was offloaded and can decide whether to note it in the summary.
    if text.startswith("Observation:"):
        # Extract first line as context for the LLM
        first_line = text.split("\n")[0] if "\n" in text else text[:100]
        marker = (
            f"\n...[[OBS_OFFLOAD: {first_line[:80]}, "
            f"{len(text)} chars, handle={handle}]]"
        )
    else:
        # model_output or other content type
        preview = text[:80].replace("\n", " ").strip()
        marker = (
            f"\n...[[CONTENT_OFFLOAD: {preview}..., "
            f"{len(text)} chars, handle={handle}]]"
        )

    return text[:limit] + marker
```

**设计决策说明**：

| 决策 | 理由 |
|------|------|
| **`OBS_OFFLOAD` vs `CONTENT_OFFLOAD`** | 区分类型，让 LLM 和 prompt 指令能差异化处理（observation 是数据，model_output 是推理） |
| **标记包含 `first_line`/`preview` + `size` + `handle`** | 自描述——即便 prompt 没特别说明，LLM 也能从标记中判断这是什么 |
| **`text[:limit]` 保留头部** | 压缩 LLM 至少能看到 observation 或 model_output 的开头，足以判断"这一步做了什么" |
| **`limit` 对 observation 和 model_output 共用** | 简化配置；如需分别控制，后续可扩展 |

---

## 修改 3：`current_compression.py` — 3 个调用点接线

**文件路径**：`nexent\core\agents\agent_context\current_compression.py`

### 为什么这 3 处必须传

这三处的渲染结果都会进入发往 LLM 的压缩输入。如果不传 `offload_store`，超长 step 的全文就会原样塞进输入，撑爆 token 预算，导致压缩失败或被迫丢弃更多 step。

### 3.1 增量压缩路径

**位置**：`CurrentCompressor.compress` 方法，L1 增量分支（约第 79 行）

**现状**：
```python
f"## New Steps\n{task_text}{self._renderer.actions_to_text(new_actions)}"
```

**修改为**：
```python
f"## New Steps\n{task_text}{self._renderer.actions_to_text(new_actions, offload_store=self._renderer._offload_store)}"
```

**说明**：增量压缩时，新步骤直接拼入 prompt 发给 LLM。如果其中某步 observation 超长，不 offload 会导致增量输入超出 `max_summary_input_tokens` 而被迫降级为全量压缩（丢失增量优化）。

### 3.2 新鲜压缩路径

**位置**：`CurrentCompressor.compress` 方法，L1 新鲜分支（约第 117-120 行）

**现状**：
```python
full_text = task_text + self._renderer.render_steps_with_truncation(
    safe_actions, fmt="action", max_tokens=actions_budget,
)
```

**修改为**：
```python
full_text = task_text + self._renderer.render_steps_with_truncation(
    safe_actions, fmt="action", max_tokens=actions_budget,
    offload_store=self._renderer._offload_store,
)
```

**说明**：全量压缩的主路径。`render_steps_with_truncation` 内部会逐 step 调用 `render_action_step`，在此传入 `offload_store` 即可沿调用链透传生效。

### 3.3 L3 fallback 路径

**位置**：`CurrentCompressor.compress` 方法，L3 fallback 分支（约第 140-142 行）

**现状**：
```python
actions_text = self._renderer.render_steps_with_truncation(
    reduced_actions, fmt="action", max_tokens=self._config.max_summary_reduce_tokens,
)
```

**修改为**：
```python
actions_text = self._renderer.render_steps_with_truncation(
    reduced_actions, fmt="action", max_tokens=self._config.max_summary_reduce_tokens,
    offload_store=self._renderer._offload_store,
)
```

**说明**：LLM 调用两次均失败后的硬截断兜底。此时 token 预算极紧（`max_summary_reduce_tokens`），offload 在此同样需要生效，避免兜底文本本身也超长。

---

## 修改 4：`previous_compression.py` — 4 个调用点接线

**文件路径**：`nexent\core\agents\agent_context\previous_compression.py`

### 为什么这 4 处必须传

同 `current_compression`，这些调用点的输出进入发往 LLM 的压缩 prompt。历史 run 的步骤中同样可能有超大文件读取结果，且历史 run 的 `keep_recent_pairs` 通常更小（默认 2），更容易触发 offload。

### 4.1 增量压缩路径

**位置**：`PreviousCompressor.compress` 方法，L1 增量分支（约第 83 行）

**现状**：
```python
f"## New Conversations\n{self._renderer.pairs_to_text(new_pairs)}"
```

**修改为**：
```python
f"## New Conversations\n{self._renderer.pairs_to_text(new_pairs, offload_store=self._renderer._offload_store)}"
```

### 4.2 新鲜压缩 full_text

**位置**：`PreviousCompressor._summarize_pairs` 方法，L1 新鲜分支（约第 148 行）

**现状**：
```python
full_text = self._renderer.pairs_to_text(pairs)
if estimate_tokens_text(full_text) <= self._config.max_summary_input_tokens:
    target_text = full_text
```

**修改为**：
```python
full_text = self._renderer.pairs_to_text(pairs, offload_store=self._renderer._offload_store)
if estimate_tokens_text(full_text) <= self._config.max_summary_input_tokens:
    target_text = full_text
```

**注意**：该 `full_text` 在下一行用于 `estimate_tokens_text(full_text)` 做 token 判定。此处传 `offload_store` 后，估算的是**截断后文本长度**——这恰好是我们想要的，因为后面真正发给 LLM 的也是这个截断版（`target_text = full_text`）。估算与发送一致，阈值判定准确。

### 4.3 新鲜压缩 truncated 分支

**位置**：`PreviousCompressor._summarize_pairs` 方法，L2 trim 分支（约第 156-160 行）

**现状**：
```python
target_text = self._renderer.render_steps_with_truncation(
    trimmed_pairs, fmt="pair",
    max_tokens=self._config.max_summary_input_tokens,
    task_budget_chars=800, action_budget_chars=1500,
)
```

**修改为**：
```python
target_text = self._renderer.render_steps_with_truncation(
    trimmed_pairs, fmt="pair",
    max_tokens=self._config.max_summary_input_tokens,
    task_budget_chars=800, action_budget_chars=1500,
    offload_store=self._renderer._offload_store,
)
```

### 4.4 L3 fallback 路径

**位置**：`PreviousCompressor._summarize_pairs` 方法，L3 fallback 分支（约第 174-176 行）

**现状**：
```python
reduced_text = self._renderer.render_steps_with_truncation(
    reduced_pairs, fmt="pair", max_tokens=self._config.max_summary_reduce_tokens,
)
```

**修改为**：
```python
reduced_text = self._renderer.render_steps_with_truncation(
    reduced_pairs, fmt="pair", max_tokens=self._config.max_summary_reduce_tokens,
    offload_store=self._renderer._offload_store,
)
```

**说明**：LLM 调用失败后的硬截断兜底，token 预算极紧。

---

## 修改 5（可选）：`core_agent.py` — 解耦 observation 截断与 enabled

**文件路径**：`nexent\core\agents\core_agent.py`

### 问题

**位置**：`_step_stream` 方法，约第 430 行

**现状**：
```python
if self.context_manager and self.context_manager.config.enabled:
```

observation 预截断（卫生功能）被 `config.enabled` 门挡住，与"压缩是否启用"耦合。如果用户只想做 observation 截断而不启用整个压缩系统，目前做不到。

### 修改

```python
if self.context_manager and self.context_manager.config.max_observation_length > 0:
```

**理由**：`max_observation_length > 0` 本身就表达了用户的意图（"我想限制 observation 长度"），不需要额外依赖 `enabled` 标志。这是两个正交的功能：卫生截断应该在每步都跑（如果配置了），不管压缩是否启用。

---

## 不修改的点及理由

| 位置 | 调用 | 理由 |
|------|------|------|
| `manager.py:108` | `pairs_to_text(uncovered)` | **纯 token 估算**（`_effective_prev_tokens`）。如果在此 offload，会导致：① 估算阶段往 store 塞内容、handle 永不出现在真实上下文中（垃圾）；② 估算的是截断后文本长度，与最终发送内容不一致，阈值判断失真 |
| `manager.py:127` | `actions_to_text(uncovered)` | 同上（`_effective_curr_tokens`） |
| `step_renderer.py` 其他方法 | `pairs_to_text`, `actions_to_text`, `render_steps_with_truncation` | 这些方法**已有** `offload_store: Optional[OffloadStore] = None` 参数并透传至 `render_action_step`，方法签名本身无需改动 |
| `nexent_agent.py:421-438` | ContextManager 初始化 + Reload 工具注入 | 已正确配置，无需修改 |
| `offload_store.py` | 整体 | 接口完备（`store`/`reload`/`clear`），无需修改 |
| `llm_summary.py` | 整体 | 纯 LLM 调用封装，不涉及步骤渲染 |
| `budget.py` | 整体 | 纯数据工具函数 |
| `manager.py:202-206` | `build_messages` | 构建最终消息列表，不涉及渲染 |

---

## 修改后的数据流全景

```
[Step 执行完毕]
      │
      ▼
 ① observation 预截断 (core_agent._step_stream)
      │  max_observation_length > 0 → head+tail 截断
      │  不可逆，防污染
      ▼
 observation 进入 memory_step.observations
      │
      │  ... 后续每步 write_memory_to_messages ...
      ▼
 [token 超阈值 → compress_if_needed 触发]
      │
      ▼
 ② offload (渲染时触发，按消息段独立判定)
      │
 ActionStep(observations=50KB)
      │  render_action_step()
      │
      ├─ model_output (800 chars) → _render_segment
      │      800 < per_step_render_limit → 保留原文
      │
      ├─ tool_call (200 chars) → "Tool calls: read_file"
      │      始终保留
      │
      └─ observations (50000 chars) → _render_segment
            50000 > per_step_render_limit → OFFLOAD
            store(text) → handle="a1b2c3"
            返回: text[:limit] +
            "[[OBS_OFFLOAD: read_file, 50KB, handle=a1b2c3]]"
      │
      ▼
 压缩 LLM 输入:
 ┌──────────────────────────────────────────┐
 │ Thought: 需要读取 config.json...          │
 │ Tool calls: read_file                     │
 │ Observation:                               │
 │ File content starts with '{"server":...'   │
 │ ...[[OBS_OFFLOAD: Observation: File...,    │
 │       50000 chars, handle=a1b2c3]]         │
 └──────────────────────────────────────────┘
      │
      ▼  LLM 压缩（prompt 含 offload 处理指引）

 摘要 JSON:
 ┌──────────────────────────────────────────┐
 │ {                                         │
 │   "completed_work": "Read config.json     │
 │     (full content archived, see           │
 │     offloaded_content). Analyzed server    │
 │     config: localhost:8080.",              │
 │   "offloaded_content": [                  │
 │     {                                     │
 │       "handle": "a1b2c3",                 │
 │       "description": "config.json -       │
 │        50KB server configuration",        │
 │       "step": 2                           │
 │     }                                     │
 │   ]                                       │
 │ }                                         │
 └──────────────────────────────────────────┘
      │
      ▼  主 Agent 后续步骤看到摘要
 "completed_work" → 知道读了 config
 "offloaded_content[0].handle" →
      调用 reload_original_context("a1b2c3") 取回原文
```

---

## 修改汇总表

| # | 文件 | 位置/函数 | 改什么 | 类别 |
|---|------|-----------|--------|------|
| 1.1 | `summary_config.py` | `ContextManagerConfig` 字段区 | 新增 `per_step_render_limit: int = 0` | 奠基 |
| 1.2 | `summary_config.py` | `summary_json_schema` default_factory | 新增 `offloaded_content` 数组字段 | 奠基 |
| 1.3 | `summary_config.py` | `summary_system_prompt` | 末尾追加 offload 标记处理指引 | 奠基 |
| 1.4 | `summary_config.py` | `incremental_summary_system_prompt` | 末尾追加 offload 标记处理指引（含 MERGE 逻辑） | 奠基 |
| 2.1 | `step_renderer.py` | `render_action_step` (~L211-237) | 整步 offload → 按段 offload；引入 `_render_segment` | 核心 |
| 2.2 | `step_renderer.py` | 新增 `_render_segment` | 单段渲染 + 自描述 `[[OBS_OFFLOAD]]` / `[[CONTENT_OFFLOAD]]` 标记 | 核心 |
| 3.1 | `current_compression.py` | `compress` ~L79 | `actions_to_text` 补传 `offload_store`（增量路径） | 接线 |
| 3.2 | `current_compression.py` | `compress` ~L118 | `render_steps_with_truncation` 补传（新鲜压缩路径） | 接线 |
| 3.3 | `current_compression.py` | `compress` ~L141 | `render_steps_with_truncation` 补传（L3 fallback） | 接线 |
| 4.1 | `previous_compression.py` | `compress` ~L83 | `pairs_to_text` 补传 `offload_store`（增量路径） | 接线 |
| 4.2 | `previous_compression.py` | `_summarize_pairs` ~L148 | `pairs_to_text` 补传（新鲜压缩 full_text） | 接线 |
| 4.3 | `previous_compression.py` | `_summarize_pairs` ~L156 | `render_steps_with_truncation` 补传（truncated 分支） | 接线 |
| 4.4 | `previous_compression.py` | `_summarize_pairs` ~L175 | `render_steps_with_truncation` 补传（L3 fallback） | 接线 |
| 5 | `core_agent.py` | `_step_stream` ~L430 | `config.enabled` → `max_observation_length > 0` 解耦 | 可选 |

---

## 验证路径

修改完成后建议按以下顺序验证：

1. **单元验证**：构造一个含超长 observation 的假 ActionStep，调用 `render_action_step(action, offload_store=OffloadStore())`，验证：
   - `model_output` 和 `tool_call` 段保留原文
   - `observations` 段被截断并包含 `[[OBS_OFFLOAD: ... handle=...]]` 标记
   - `offload_store.reload(handle)` 能取回原文

2. **集成验证**：构造一个超过 token 阈值的假 memory，触发 `compress_if_needed`，验证：
   - 压缩输入中包含 offload 标记而非原文
   - 压缩 LLM 产出的摘要中 `offloaded_content` 字段包含 handle
   - `manager.py:108/127` 的估算调用未产生 offload 副作用

3. **Reload 验证**：在压缩完成后，调用 `reload_original_context(handle)` 验证能取回完整原文

