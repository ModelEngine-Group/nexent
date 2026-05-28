# Agent Context 改进实践方案

> 基于 `situation_ana.md` 中的问题分析，本文档给出 8 项改进的具体实施方案。
> 每项方案包含：改动目标、涉及文件、具体代码变更、风险点和验证方式。
>
> **改进 7-8 为本次补充**，针对大量模型输出和工具输出的卸载、截断与重载问题。

---

## 改进 1：正常路径也应用 tool-call 紧凑渲染

### 目标

消除未触发压缩时 `assistant` 的 `<code>` 块与 `tool-call` 的 `"Calling tools:\n[...]"` 之间的代码冗余。

### 现状

`core_agent.py:_step_stream` 中，`write_memory_to_messages()` 直接调用 smolagents 原生的 `ActionStep.to_messages()`，产出完整的 `"Calling tools:\n[{...full code...}]"` 消息，绕过了 `StepRenderer.render_action_step` 的紧凑替换。

### 方案

在 `core_agent.py` 中新增一个消息后处理函数，在 `write_memory_to_messages()` 返回后对消息列表做一次遍历，将 tool-call 角色消息中的冗余内容替换为紧凑格式。**不修改 smolagents 上游代码，不改变消息角色和消息结构。**

#### 涉及文件

- `core_agent.py` — 新增后处理函数，在 `_step_stream` 中调用
- `code_analysis.py` — 扩展 `extract_invoked_tools` 返回值，同时提取调用签名

#### 具体变更

**1) 扩展 `code_analysis.py` — 新增 `extract_tool_call_signatures`**

当前 `extract_invoked_tools` 只返回工具名列表 `["read_file", "write_file"]`，信息不足以支撑紧凑格式。新增函数提取调用签名摘要：

```python
def extract_tool_call_signatures(code_action: str, registered_tools: dict) -> List[str]:
    """Extract tool call signatures from code_action via AST analysis.

    Returns a list of "tool_name(key_args)" strings for each registered tool
    call found in the code. Key arguments are the first 2 positional or
    keyword arguments, truncated to 60 chars each.

    Example: ['read_file(file_path="sample.txt")', 'write_file(file_path="ana.txt")']
    """
    if not code_action:
        return []
    try:
        tree = ast.parse(code_action)
    except SyntaxError:
        return []
    signatures = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name not in registered_tools:
            continue
        # Collect up to 2 key arguments
        key_parts = []
        for arg in node.args[:2]:
            key_parts.append(_ast_to_signature(arg))
        for kw in node.keywords[:2]:
            key_parts.append(f"{kw.arg}={_ast_to_signature(kw.value)}")
        sig = f"{name}({', '.join(key_parts)})" if key_parts else name
        # Truncate each signature to 80 chars
        if len(sig) > 80:
            sig = sig[:77] + "..."
        signatures.append(sig)
    return signatures


def _ast_to_signature(node) -> str:
    """Convert an AST node to a compact signature string."""
    if isinstance(node, ast.Constant):
        val = str(node.value)
        if len(val) > 60:
            val = val[:57] + "..."
        # Add quotes for strings
        if isinstance(node.value, str):
            return f'"{val}"'
        return val
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.JoinedStr):  # f-string
        return "<f-string>"
    return "..."
```

**2) 修改 `core_agent.py` — `invoked_tools` 赋值时同时计算签名**

```python
# 当前代码 (core_agent.py:363-365):
memory_step.invoked_tools = extract_invoked_tools(
    code_action, self.tools
) if self.tools else []

# 改为:
if self.tools:
    memory_step.invoked_tools = extract_invoked_tools(code_action, self.tools)
    memory_step.tool_call_signatures = extract_tool_call_signatures(code_action, self.tools)
else:
    memory_step.invoked_tools = []
    memory_step.tool_call_signatures = []
```

需要在 `core_agent.py` 顶部 monkey-patch 区追加：

```python
if not hasattr(ActionStep, 'tool_call_signatures'):
    ActionStep.tool_call_signatures = None
```

**3) 新增消息后处理函数 `compact_tool_call_messages`**

```python
def compact_tool_call_messages(messages: List[ChatMessage], action_step: ActionStep) -> List[ChatMessage]:
    """Replace verbose 'Calling tools:' messages with compact tool call signatures.

    When action_step has tool_call_signatures, the tool-call role message
    containing 'Calling tools:\\n[...]' is replaced with a compact
    'Tool calls: tool_name(arg1=val1), ...' summary.

    This preserves the message role and structure while eliminating the
    redundant full-code duplication between assistant and tool-call messages.
    """
    signatures = getattr(action_step, 'tool_call_signatures', None)
    if not signatures:
        return messages

    compact_text = f"Tool calls: {', '.join(signatures)}"
    result = []
    for msg in messages:
        if msg.role == MessageRole.TOOL_CALL:
            text = _extract_msg_text(msg)
            if text and text.startswith("Calling tools:"):
                # Replace content in-place within a new ChatMessage
                result.append(ChatMessage(
                    role=msg.role,
                    content=[{"type": "text", "text": compact_text}],
                ))
                continue
        result.append(msg)
    return result


def _extract_msg_text(msg: ChatMessage) -> str:
    """Extract plain text from a ChatMessage's content."""
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)
```

**4) 在 `_step_stream` 中应用后处理**

```python
# 当前代码 (core_agent.py:292-309):
memory_messages = self.write_memory_to_messages()
# ... token estimation ...
input_messages = memory_messages.copy()
if self.context_manager and self.context_manager.config.enabled:
    input_messages = self.context_manager.compress_if_needed(...)

# 改为:
memory_messages = self.write_memory_to_messages()

# Apply compact tool-call rendering for the latest action step
# (eliminates "Calling tools:" redundancy even without compression)
if memory_step.invoked_tools:
    memory_messages = compact_tool_call_messages(memory_messages, memory_step)

# ... token estimation (unchanged) ...
input_messages = memory_messages.copy()
if self.context_manager and self.context_manager.config.enabled:
    input_messages = self.context_manager.compress_if_needed(...)
```

### 注意事项

- 后处理只替换**最新步**的 tool-call 消息（即 `memory_step` 对应的），不影响历史步的消息。历史步的冗余在压缩时由 `render_action_step` 处理。
- 这意味着每次 `_step_stream` 调用时，`memory_messages` 中只有最后一个 ActionStep 的 tool-call 被紧凑化。前面步的消息仍是冗余的。要完全消除，需要在 `write_memory_to_messages` 层面做全局替换——但这会修改 smolagents 行为，风险更大。**暂且只处理最新步，作为第一阶段的折中。**

### 验证方式

运行 `test_with_tools.py` 的 `test_read_ana_file`，在日志中检查 MODEL INPUT PARAMETERS 中最新步的 tool-call 消息是否变为 `"Tool calls: read_file(file_path=\"sample.txt\")"` 格式。

---

## 改进 2：紧凑格式从仅工具名升级为调用签名

### 目标

将 `"Tool calls: read_file, write_file"` 升级为 `"Tool calls: read_file(file_path=\"sample.txt\"), write_file(file_path=\"ana.txt\")"` ，确保即使 assistant 文本被截断，tool-call 消息仍保留足够的因果信息。

### 方案

此改进已在改进 1 中一并完成——`extract_tool_call_signatures` 的返回值直接用于紧凑格式。

但 `step_renderer.py` 中的 `render_action_step` 也需要同步升级：

#### 涉及文件

- `step_renderer.py` — `render_action_step` 中的紧凑格式

#### 具体变更

```python
# 当前代码 (step_renderer.py:225-226):
if text.startswith("Calling tools:"):
    parts.append(f"Tool calls: {', '.join(action.invoked_tools)}")

# 改为:
if text.startswith("Calling tools:"):
    signatures = getattr(action, 'tool_call_signatures', None)
    if signatures:
        parts.append(f"Tool calls: {', '.join(signatures)}")
    else:
        # Fallback: no AST signatures available, use tool names only
        parts.append(f"Tool calls: {', '.join(action.invoked_tools)}")
```

### 风险点

- `tool_call_signatures` 是 monkey-patch 字段，旧 ActionStep（改进前创建的）可能为 `None`。fallback 分支保证兼容性。
- 签名中可能包含敏感路径（如 `/etc/shadow`）。但 smolagents 的 summary prompt 已有凭据脱敏指令，且此处签名是给 LLM 看的中间表示，不直接暴露给用户。风险可接受。

### 验证方式

运行带压缩的测试（token_threshold 设置较低以触发压缩），检查压缩后的 summary 是否包含具体的工具调用参数信息。

---

## 改进 3：分段感知截断（替代暴力字符截断）

### 目标

`step_renderer.py` 的 `_truncate_text` 做暴力字符截断，可能在 `<code>` 块中间或 observation 关键结果处截断。改为按语义段落截断，优先保留 assistant 思考文本，其次保留 observation 头部。

### 方案

将 `render_action_step` 的输出按语义段分割，按优先级分配 token 预算。

#### 涉及文件

- `step_renderer.py` — `_truncate_text` 和 `_truncate_entries_to_budget`

#### 语义段定义

`render_action_step` 的输出天然由 `to_messages()` 拼接，各消息之间以 `\n` 分隔。在紧凑模式下，一段典型的输出结构为：

```
[assistant 思考文本]          ← 优先级 P0（最高）
<code>代码块</code>           ← 优先级 P2（冗余，tool-call 签名已覆盖）
Tool calls: 签名摘要          ← 优先级 P1（因果关键）
Observation:\n执行结果        ← 优先级 P1.5（头部重要，尾部可截）
```

#### 具体变更

在 `StepRenderer` 中新增方法：

```python
def _segment_aware_truncate(self, text: str, max_chars: int) -> str:
    """Truncate rendered action step text with semantic segment awareness.

    Split text into segments by detecting key boundaries:
    - "<code>" block start
    - "Tool calls:" line
    - "Observation:" line

    Allocate budget by priority:
    - P0: assistant thinking text (before <code>)
    - P1: "Tool calls:" line
    - P2: <code> block (most redundant — can be heavily truncated)
    - P1.5: Observation (keep head, truncate tail)

    Returns text fitted within max_chars.
    """
    if len(text) <= max_chars:
        return text

    # Split into segments
    segments = self._split_segments(text)

    # Allocate budget: P0 + P1 are mandatory (as long as they fit)
    mandatory_chars = len(segments.get("thinking", "")) + len(segments.get("tool_calls", ""))
    remaining = max_chars - mandatory_chars - 20  # 20 for separators and markers

    if remaining < 0:
        # Even mandatory parts don't fit; fall back to head truncation
        return text[:max_chars - 12] + "...[Truncated]"

    # Distribute remaining budget between code and observation
    code_text = segments.get("code", "")
    obs_text = segments.get("observation", "")

    # Code is lowest priority: give it 20% of remaining, observation gets 80%
    code_budget = max(0, int(remaining * 0.2))
    obs_budget = remaining - code_budget

    # Truncate code (if present)
    code_part = ""
    if code_text:
        if len(code_text) <= code_budget:
            code_part = code_text
        else:
            code_part = code_text[:code_budget - 12] + "...[Code truncated]"

    # Truncate observation: keep head, cut tail
    obs_part = ""
    if obs_text:
        if len(obs_text) <= obs_budget:
            obs_part = obs_text
        else:
            obs_part = obs_text[:obs_budget - 20] + "...[Output truncated]"

    # Reassemble
    parts = []
    if segments.get("thinking"):
        parts.append(segments["thinking"])
    if code_part:
        parts.append(code_part)
    if segments.get("tool_calls"):
        parts.append(segments["tool_calls"])
    if obs_part:
        parts.append(obs_part)

    return "\n".join(parts)


def _split_segments(self, text: str) -> dict:
    """Split rendered action step text into semantic segments."""
    segments = {
        "thinking": "",
        "code": "",
        "tool_calls": "",
        "observation": "",
    }

    # Find boundaries
    code_start = text.find("<code>")
    code_end = text.find("</code>", code_start) if code_start != -1 else -1
    tool_call_start = text.find("Tool calls:")
    obs_start = text.find("Observation:")

    # Thinking: everything before <code>, or before "Tool calls:" if no code
    think_end = code_start if code_start != -1 else tool_call_start if tool_call_start != -1 else obs_start if obs_start != -1 else len(text)
    if think_end > 0:
        segments["thinking"] = text[:think_end].rstrip()

    # Code block
    if code_start != -1 and code_end != -1:
        segments["code"] = text[code_start:code_end + len("</code>")]

    # Tool calls line
    if tool_call_start != -1:
        tc_end = text.find("\n", tool_call_start)
        tc_end = tc_end if tc_end != -1 else len(text)
        segments["tool_calls"] = text[tool_call_start:tc_end]

    # Observation
    if obs_start != -1:
        segments["observation"] = text[obs_start:]

    return segments
```

然后修改 `_truncate_text` 的调用点，在有 `invoked_tools` 的步骤中使用分段截断：

```python
def _truncate_text(self, text: str, max_len: int, mark: str = "...[Truncated]") -> str:
    if len(text) <= max_len:
        return text
    # If text contains semantic markers from render_action_step, use segment-aware truncation
    if "Tool calls:" in text or "<code>" in text:
        return self._segment_aware_truncate(text, max_len)
    # Fallback: plain text truncation
    return text[:max_len - len(mark)] + mark
```

### 风险点

- `_split_segments` 基于字符串查找，如果 LLM 输出格式偏差（如 `<code >` 带空格、`Observation：` 全角冒号），可能识别失败。**fallback 分支保证即使识别失败，也退化为原有暴力截断，不会更差。**
- 分段截断的预算分配比例（code 20% / observation 80%）是经验值，可能需要根据实际场景调整。

### 验证方式

构造一个 observation 极长（>5000 字符）的 ActionStep，在 `render_steps_with_truncation` 中设置较小的 `max_tokens`，验证截断结果中 assistant 思考文本和 tool-call 签名保留完整，observation 被正确截尾。

---

## 改进 4：Observation 预截断默认开启

### 目标

将 observation 预截断从 ContextManager 专属功能变为通用卫生措施，即使不开启压缩也对过大输出做 head+tail 截断。

### 现状

`core_agent.py:407-416` 中，observation 预截断仅在 `self.context_manager and self.context_manager.config.enabled` 时生效。`summary_config.py` 中 `max_observation_length` 默认值为 20000 字符——但实际上因为条件守卫 `self.context_manager` 和 `self.context_manager.config.enabled`，不开启 ContextManager 时此逻辑根本不执行。

### 方案

将预截断逻辑从 ContextManager 条件中解耦，变为 CoreAgent 自身的通用行为。同时提供合理的默认值。

#### 涉及文件

- `core_agent.py` — 修改预截断逻辑的条件守卫
- `summary_config.py` — 调整 `max_observation_length` 默认值

#### 具体变更

**1) `core_agent.py` — 解耦预截断条件**

```python
# 当前代码 (core_agent.py:407-416):
if self.context_manager and self.context_manager.config.enabled:
    max_obs = self.context_manager.config.max_observation_length
    if max_obs > 0 and memory_step.observations and len(memory_step.observations) > max_obs:
        obs_text = memory_step.observations
        half = max_obs // 2
        truncation_marker = (
            f"\n...[Output truncated to {max_obs} characters. "
            f"Use search or read tools to find specific results.]\n"
        )
        memory_step.observations = obs_text[:half] + truncation_marker + obs_text[-half:]

# 改为:
# Observation pre-truncation is a general hygiene measure, not compression-specific.
# It limits context bloat from oversized tool outputs regardless of whether
# ContextManager compression is enabled.
max_obs = self._get_max_observation_length()
if max_obs > 0 and memory_step.observations and len(memory_step.observations) > max_obs:
    obs_text = memory_step.observations
    half = max_obs // 2
    truncation_marker = (
        f"\n...[Output truncated to {max_obs} characters. "
        f"Use search or read tools to find specific results.]\n"
    )
    memory_step.observations = obs_text[:half] + truncation_marker + obs_text[-half:]
```

**2) 新增 `_get_max_observation_length` 方法**

```python
def _get_max_observation_length(self) -> int:
    """Get the maximum observation length for pre-truncation.

    Priority: ContextManager config > CoreAgent default > 0 (disabled).
    """
    if self.context_manager and self.context_manager.config.enabled:
        cm_max = self.context_manager.config.max_observation_length
        if cm_max > 0:
            return cm_max
    # CoreAgent default: always apply a ceiling to prevent unbounded context growth
    return 3000  # Default: ~2000 tokens at 1.5 chars/token
```

**3) `summary_config.py` — 默认值说明更新**

`max_observation_length` 保持 20000 不变（作为 ContextManager 开启时的配置值），CoreAgent 自身的默认值（3000）硬编码在 `_get_max_observation_length` 中。如果用户显式配置了 ContextManager，以用户配置为准。

### 风险点

- 3000 字符可能截断某些合法的长输出（如大文件内容）。但 head+tail 策略保留了开头和结尾各 1500 字符，对于大多数工具输出足够理解上下文。agent 可以通过重新调用工具获取完整内容。
- 如果某些工具的完整输出确实必须保留（如 JSON 结构化数据），需要后续增加工具级粒度的截断豁免机制。**当前方案作为第一阶段先不处理。**

### 验证方式

在不开启 ContextManager 的条件下运行 `test_read_ana_file`，确认 Step 1 的 observation 仍被截断为 head+tail 格式。

---

## 改进 5：边界调整逻辑适配 CodeAgent 语义

### 目标

`manager.py` 的边界调整逻辑基于 `is_observation_step`/`is_tool_call_step`，这对 CodeAgent 的 tool-calling 步是无条件 True 的，导致 `keep_n` 总是被 +1。改为基于 CodeAgent 实际的步类型语义。

### 方案

引入基于 `invoked_tools` 和 `is_final_answer` 的步类型判断，替代基于 `observations`/`tool_calls` 存在性的判断。

#### 涉及文件

- `budget.py` — 新增 `is_tool_invoking_step` 和 `is_final_answer_step` 函数
- `manager.py` — 修改边界调整逻辑
- `budget.py` — 修改 `trim_actions_to_budget` 的 pair-integrity 逻辑

#### 具体变更

**1) `budget.py` — 新增步类型判断函数**

```python
def is_tool_invoking_step(action: ActionStep) -> bool:
    """Check if an ActionStep invokes registered tools.

    Unlike is_tool_call_step() which checks for tool_calls is not None
    (always True for CodeAgent tool-calling steps AND meaningless for
    python_interpreter), this checks the invoked_tools list which
    reflects actual semantic tool usage detected by AST analysis.
    """
    return bool(getattr(action, 'invoked_tools', None))


def is_final_answer_step(action: ActionStep) -> bool:
    """Check if an ActionStep is a final-answer step (no tool calls).

    These steps have model_output only, with tool_calls=None and
    observations=None. They represent the agent's direct response.
    """
    return getattr(action, 'is_final_answer', False) or (
        getattr(action, 'tool_calls', None) is None
        and getattr(action, 'observations', None) is None
        and getattr(action, 'model_output', None) is not None
    )
```

**2) `manager.py` — 修改边界调整逻辑**

```python
# 当前代码 (manager.py:273-278):
if keep_n > 0 and keep_n < len(curr_action_steps):
    boundary = curr_action_steps[-keep_n]
    prev_a = curr_action_steps[-keep_n - 1]
    if (getattr(boundary, "observations", None) is not None
            and getattr(prev_a, "tool_calls", None) is not None):
        keep_n += 1

# 改为:
# Boundary adjustment: avoid splitting between a tool-invoking step
# and its following final-answer step. In CodeAgent, both fields
# (tool_calls, observations) always exist on tool-invoking steps,
# so the old check was always True. The meaningful boundary is:
# don't leave a final-answer step orphaned from the preceding
# tool-invoking step that produced its context.
if keep_n > 0 and keep_n < len(curr_action_steps):
    boundary = curr_action_steps[-keep_n]
    prev_a = curr_action_steps[-keep_n - 1]
    if is_final_answer_step(boundary) and is_tool_invoking_step(prev_a):
        # The final-answer depends on the tool-invoking step's context
        keep_n += 1
```

**3) `budget.py` — 修改 `trim_actions_to_budget` 的 pair-integrity逻辑**

当前逻辑检查 `is_observation_step(remaining[0]) and is_tool_call_step(actions[drop - 1])`，对 CodeAgent 总是 True。改为检查 final-answer 与 tool-invoking 的关联：

```python
# 当前代码 (budget.py:194-195):
if is_observation_step(remaining[0]) and is_tool_call_step(actions[drop - 1]):
    continue

# 改为:
if is_final_answer_step(remaining[0]) and is_tool_invoking_step(actions[drop - 1]):
    continue
```

同样修改 fallback 逻辑：

```python
# 当前代码 (budget.py:207-209):
if len(actions) >= 2 and is_observation_step(last_action):
    prev_action = actions[-2]
    if is_tool_call_step(prev_action):

# 改为:
if len(actions) >= 2 and is_final_answer_step(last_action):
    prev_action = actions[-2]
    if is_tool_invoking_step(prev_action):
```

### 风险点

- 这改变了 trim 的行为：旧逻辑对 CodeAgent 总是 skip（相当于从最前面逐个丢弃直到 budget 够），新逻辑只在 final-answer/tool-invoking 边界时 skip。对于纯 tool-invoking 步序列（大多数中间步），新逻辑会更快地找到可丢弃的分割点——**这实际上是更正确的**，因为纯 tool-invoking 步是自包含的，可以独立丢弃。
- 对 ToolCallingAgent 的兼容性：`is_final_answer_step` 对 ToolCallingAgent 的 observation 步会返回 False（因为 `tool_calls` 不为 None），所以不会误判。但如果 ToolCallingAgent 的 observation 步确实需要和前一步绑定，旧逻辑的保护就丢失了。**需要确认项目中是否使用 ToolCallingAgent。** 如果是，需要保留旧逻辑作为 fallback。

### 验证方式

构造一个 5 步序列 `[tool-invoke, tool-invoke, tool-invoke, final-answer, tool-invoke]`，设置 `keep_n=2`，验证边界调整后 final-answer 与其前一个 tool-invoke 被一起保留。

---

## 改进 6：assistant 与 tool-call/tool-response 的完整链保护

### 目标

在压缩渲染中，确保一个 ActionStep 的 `assistant(model_output) → tool-call → tool-response` 语义链不被分开截断。即使 tool-call 已被紧凑化，assistant 思考文本与 observation 之间仍需保持因果连贯。

### 现状

`render_action_step` 将一个 ActionStep 的所有消息拼为一段文本，`_truncate_text` 对整段做字符截断。在改进 3（分段感知截断）之后，单步内的截断已有语义保护。但跨步的因果关系（Step N 的 observation 影响 Step N+1 的 assistant 思考）没有保护。

### 方案

这个改进分为两个层面：

#### 层面 A：单步内（已由改进 3 覆盖）

改进 3 的分段感知截断已经保证：在同一 ActionStep 的渲染文本内，assistant 思考、tool-call 签名、observation 不会出现无意义的切割。

#### 层面 B：跨步因果保护（新增）

在 `CurrentCompressor.compress` 中，`trim_actions_to_budget` 丢弃前面的步时，可能丢掉 Step N 的 observation（包含 Step N+1 依赖的关键数据），而 Step N+1 的 assistant 思考引用了这些数据。

**应对策略：在 LLM summary prompt 中强化因果链保存指令。** 这不是代码结构层面的保护，而是 prompt 层面的引导——告诉总结 LLM 显式保留步骤间的因果关系。

#### 涉及文件

- `summary_config.py` — 在 summary prompt 中增加因果链指令

#### 具体变更

在 `summary_system_prompt` 和 `incremental_summary_system_prompt` 的 shared preamble 中追加：

```
"Causal chain preservation: When steps reference results from previous steps
(e.g., 'based on the file content read above', 'using the variable from step N'),
ensure the summary captures both the source (what was read/computed) and the
dependent action (what was done with it) together. Do not summarize a dependent
action without also summarizing the prerequisite that produced its inputs."
```

同时在 `summary_json_schema` 的 `completed_work` 字段描述中更新格式指引：

```python
"completed_work": (
    "Numbered list of concrete actions taken. Format: N. ACTION target — outcome [tool: name]. "
    "Be specific with file paths, commands, line numbers. "
    "Preserve causal chains: if step B depends on step A's output, "
    "include both A's key output and B's action. (<=300 words)"
),
```

### 风险点

- Prompt 引导不能保证 100% 遵从。LLM 可能仍然丢失因果信息。这是所有 LLM-based 压缩方案的固有限制。
- 更长的 prompt 会消耗额外的 token。但这段指令约 80 tokens，相对于总结输入（通常数千 tokens）占比很小。

### 验证方式

构造一个多步测试场景（Step 1: read_file → Step 2: 基于读取内容做分析 → Step 3: 将分析写入文件），在压缩触发后检查 summary 中是否保留了 Step 1 的读取结果与 Step 2 的分析动作之间的因果关联。

---

## 改进 7：模型输出（model_output）的分级截断与卸载

### 目标

当模型输出过大时（如 LLM 在 assistant 消息中生成超长代码块或大段分析文本），当前只有压缩路径的 `_truncate_text` 暴力截断，没有独立的卸载/重载机制。需要在正常路径和压缩路径都引入分级处理。

### 问题分析

模型输出膨胀的场景：

1. **超长 `<code>` 块**：LLM 生成包含大量逻辑的代码（如完整脚本、循环体），代码本身可达数千字符。但 `<code>` 块的内容与 `tool-call` 的 `arguments` 完全重复——改进 1 的紧凑渲染已消除 `tool-call` 侧的冗余，`<code>` 块本身的冗余还需处理。
2. **超长分析文本**：LLM 在 `<code>` 块之外生成大量推理/分析文本（如 res.log 中 Step 2 的 `analysis = """..."""` 多行字符串），这部分是**原创信息**，不可丢弃。
3. **`<DISPLAY>` 展示代码**：LLM 使用 `<DISPLAY:language>...</DISPLAY>` 向用户展示代码，这部分代码不执行，但占上下文。在 assistant 消息中它是合理的，但压缩时可截断。

关键区分：
- `<code>` 块：与 tool-call 重复 → 可安全截断/卸载（完整信息在 tool-call 签名中保留）
- 思考/分析文本：原创 → 需保留或卸载后可重载
- `<DISPLAY>` 展示代码：仅展示用途 → 可截断

### 方案：三级处理

| 级别 | 条件 | 处理方式 | 重载能力 |
|------|------|---------|---------|
| L1 保留 | model_output ≤ `max_model_output_keep` (默认 4000 字符) | 原样保留 | 不需要 |
| L2 分段截断+卸载 | `max_model_output_keep` < model_output ≤ `max_model_output_offload` (默认 20000 字符) | 保留思考文本 + `<code>` 块摘要 + 卸载标记 | 可通过 `ReloadOriginalContextTool` 重载完整 `<code>` 块 |
| L3 激进截断 | model_output > `max_model_output_offload` | 思考文本保留前 N 字符 + 截断标记 | 卸载完整内容，可重载 |

#### 涉及文件

- `core_agent.py` — 在 `memory_step.model_output = model_output` 之后新增处理
- `summary_config.py` — 新增配置项
- `step_renderer.py` — `render_action_step` 中对 model_output 部分做卸载标记

#### 具体变更

**1) `summary_config.py` — 新增配置**

```python
# Maximum length of model_output to keep in full (characters).
# Below this threshold, model_output is preserved verbatim.
max_model_output_keep: int = 4000

# Maximum length of model_output before aggressive truncation.
# Between max_model_output_keep and this value, content is offloaded
# with a summary placeholder. Above this value, thinking text is
# also truncated.
max_model_output_offload: int = 20000
```

**2) `core_agent.py` — model_output 分级处理**

在 `memory_step.model_output = model_output` 之后插入：

```python
# --- Model output size management ---
if model_output and len(model_output) > self._get_max_model_output_keep():
    memory_step = self._trim_model_output(memory_step, model_output)
```

新增方法：

```python
def _get_max_model_output_keep(self) -> int:
    """Get the max model_output length before trimming is applied."""
    if self.context_manager and self.context_manager.config.enabled:
        return self.context_manager.config.max_model_output_keep
    return 4000  # CoreAgent default

def _trim_model_output(self, step: ActionStep, original_output: str) -> ActionStep:
    """Trim oversized model_output with segment-aware strategy.

    Strategy:
    - Extract thinking text (before <code>)
    - Extract <code> block
    - Keep thinking text (up to budget)
    - Replace <code> with signature summary + offload marker
    - Store full content in offload store for reload
    """
    # Split model_output into thinking vs code
    code_start = original_output.find("<code>")
    code_end = original_output.find("</code>", code_start) if code_start != -1 else -1

    thinking_text = original_output[:code_start].rstrip() if code_start != -1 else original_output
    code_block = original_output[code_start:code_end + len("</code>")] if (code_start != -1 and code_end != -1) else ""

    max_keep = self._get_max_model_output_keep()
    max_offload = 20000
    if self.context_manager and self.context_manager.config.enabled:
        max_offload = self.context_manager.config.max_model_output_offload

    # Allocate budget: thinking text gets priority
    thinking_budget = max_keep - 200  # Reserve 200 for code summary + markers
    trimmed_thinking = thinking_text
    if len(trimmed_thinking) > thinking_budget:
        trimmed_thinking = thinking_text[:thinking_budget - 15] + "...[Truncated]"

    # Code block: always replace with summary
    code_summary = ""
    if step.invoked_tools:
        signatures = getattr(step, 'tool_call_signatures', None) or step.invoked_tools
        code_summary = f"<code><!-- Tool calls: {', '.join(signatures) if isinstance(signatures, list) else ', '.join(signatures)} -->"
    elif code_block:
        code_summary = f"<code><!-- Code block of {len(code_block)} chars -->"

    # Offload full content if available
    offload_marker = ""
    if self.context_manager and hasattr(self.context_manager, 'offload_store'):
        handle = self.context_manager.offload_store.store(original_output)
        offload_marker = f" [[OFFLOAD:handle={handle}]]"

    step.model_output = trimmed_thinking + "\n" + code_summary + offload_marker
    # Preserve original for potential offload retrieval
    step._original_model_output = original_output  # monkey-patch field

    return step
```

### 与改进 3（分段截断）的协作

- 改进 7 在**写入 memory 时**（`_step_stream` 中）做预截断+卸载，作用于 `memory_step.model_output` 字段
- 改进 3 在**渲染时**（`render_action_step` → `_truncate_text`）做分段感知截断，作用于渲染后的文本
- 两者不冲突：预截断减少了渲染时的文本量，渲染截断处理预截断后仍超限的情况

### 风险点

- 截断 `model_output` 意味着 `to_messages()` 生成的 assistant 消息内容变短。LLM 在后续步看到的 assistant 历史是截断版，可能丢失细节。但 `[[OFFLOAD]]` 标记 + `ReloadOriginalContextTool` 提供了重载路径。
- `step._original_model_output` 是 monkey-patch 字段，smolagents 的序列化/日志可能看不到原始内容。需要确认是否影响调试。

### 验证方式

构造一个模型输出超过 4000 字符的场景（如 LLM 生成 200 行代码），验证 `memory_step.model_output` 被截断为思考文本 + 代码摘要 + `[[OFFLOAD]]` 标记，且通过 `ReloadOriginalContextTool` 可重载原始内容。

---

## 改进 8：工具输出（observation）的卸载增强与重载闭环

### 目标

当前 observation 只做 head+tail 预截断（改进 4），截断后的内容不可恢复。对超大 observation 应提供卸载+重载路径，使 agent 在需要时能通过工具调用取回完整输出。

### 问题分析

当前 observation 处理的三层现状：

| 层级 | 机制 | 触发条件 | 可恢复性 |
|------|------|---------|----------|
| 预截断 | `core_agent.py` head+tail | ContextManager enabled + `max_observation_length` | 不可恢复 |
| 压缩渲染截断 | `_truncate_text` 暴力截断 | 压缩时超 token 预算 | 不可恢复 |
| 压缩渲染卸载 | `render_action_step` → `OffloadStore` | `per_step_render_limit` (3000) | 可通过 `ReloadOriginalContextTool` 重载 |

**问题：**
1. 预截断是不可逆的——head+tail 截断丢弃了中间内容，且没有 `[[OFFLOAD]]` 标记
2. `per_step_render_limit` 卸载的是**整个渲染后的步文本**（assistant + tool-call + observation 拼接），而不是单独的 observation——这意味着 agent 重载时会得到包含 assistant 和 tool-call 的完整步文本，而非仅 observation
3. 正常路径（无压缩）完全没有卸载机制——超大 observation 直接膨胀上下文

### 方案：Observation 独立卸载 + 标记式截断

#### 核心思路

对 observation 做**独立的卸载+标记**，而非仅 head+tail 截断：

```
原始 observation:
"Execution logs:\n文件内容(5000字符)...\n分析结果已写入 ana.txt"

处理后:
"Execution logs:\n文件内容(前500字符)...[Output offloaded: [[OBS_OFFLOAD:handle=abc123]]]...分析结果已写入 ana.txt(末尾500字符)"
```

与 head+tail 的区别：
- head+tail **丢弃**中间内容，不可恢复
- 卸载+标记**保留**中间内容在 OffloadStore 中，agent 可通过 `ReloadOriginalContextTool` 重载

#### 涉及文件

- `core_agent.py` — 修改 observation 预截断逻辑
- `step_renderer.py` — 在渲染时对 observation 部分做独立卸载
- `reload_original_context_tool.py` — 增强 reload 工具，支持按 observation handle 重载

#### 具体变更

**1) `core_agent.py` — Observation 卸载式截断**

替代改进 4 中的 head+tail 逻辑：

```python
# 替代改进 4 中的 _get_max_observation_length 和 head+tail 逻辑
max_obs = self._get_max_observation_length()
if max_obs > 0 and memory_step.observations and len(memory_step.observations) > max_obs:
    obs_text = memory_step.observations
    # Try offload first (preserves full content for reload)
    if self.context_manager and hasattr(self.context_manager, 'offload_store'):
        handle = self.context_manager.offload_store.store(obs_text)
        half = max_obs // 2
        truncation_marker = (
            f"\n...[Output offloaded ({len(obs_text)} chars): "
            f"[[OBS_OFFLOAD:handle={handle}]]. "
            f"Use reload_original_context_messages tool to retrieve full content.]\n"
        )
        memory_step.observations = obs_text[:half] + truncation_marker + obs_text[-half:]
    else:
        # No offload store available; fall back to simple head+tail truncation
        half = max_obs // 2
        truncation_marker = (
            f"\n...[Output truncated to {max_obs} characters. "
            f"Use search or read tools to find specific results.]\n"
        )
        memory_step.observations = obs_text[:half] + truncation_marker + obs_text[-half:]
```

**2) `step_renderer.py` — 渲染时 observation 独立卸载**

当前 `render_action_step` 在 `per_step_render_limit` 超限时卸载整个步文本。改为对 observation 部分做独立卸载：

```python
def render_action_step(self, action: ActionStep, offload_store: Optional[OffloadStore] = None) -> str:
    """Render an ActionStep to text, with optional per-step offload."""
    if has_invoked_tools(action):
        msgs = action.to_messages(summary_mode=False)
        parts = []
        for msg in msgs:
            text = _extract_text_from_messages([msg]) or ""
            if text.startswith("Calling tools:"):
                signatures = getattr(action, 'tool_call_signatures', None)
                if signatures:
                    parts.append(f"Tool calls: {', '.join(signatures)}")
                else:
                    parts.append(f"Tool calls: {', '.join(action.invoked_tools)}")
            elif text.startswith("Observation:"):
                # Observation-specific offload
                obs_text = text[len("Observation:"):]
                obs_limit = self._config.max_observation_render_length  # new config, default 2000
                if (offload_store is not None and obs_limit > 0
                        and len(obs_text) > obs_limit):
                    handle = offload_store.store(obs_text)
                    half = obs_limit // 2
                    truncated_obs = (
                        obs_text[:half]
                        + f"\n...[Observation offloaded: [[OBS_OFFLOAD:handle={handle}]]]\n"
                        + obs_text[-half:]
                    )
                    parts.append("Observation:" + truncated_obs)
                else:
                    parts.append(text)
            else:
                parts.append(text)
        full_text = "\n".join(parts)
    else:
        msgs = action.to_messages(summary_mode=False)
        full_text = _extract_text_from_messages(msgs) or ""

    # Per-step overall limit (unchanged — safety net for total rendered size)
    if offload_store is not None and self._config.per_step_render_limit > 0 and len(full_text) > self._config.per_step_render_limit:
        handle = offload_store.store(full_text)
        limit = self._config.per_step_render_limit
        return full_text[:limit] + f"\n...[Content offloaded: [[OFFLOAD:handle={handle}]]]"
    return full_text
```

**3) `summary_config.py` — 新增配置**

```python
# Maximum length of observation text in rendered output (characters).
# When observation exceeds this, the middle portion is offloaded
# and replaced with an [[OBS_OFFLOAD]] marker.
max_observation_render_length: int = 2000
```

**4) `reload_original_context_tool.py` — 增强 handle 识别**

当前 reload 工具只查找 `[[OFFLOAD:handle=...]]` 格式。需要同时支持 `[[OBS_OFFLOAD:handle=...]]` 格式。实际上两种标记都通过同一个 `OffloadStore` 存储，handle 本身无格式差异，所以 reload 工具的 `forward` 方法不需要改动——只需更新 `description` 文档：

```python
description = (
    "Reload the original full content of a compressed/offloaded context step. "
    "Use this when you see an [[OFFLOAD:handle=<id>]] or [[OBS_OFFLOAD:handle=<id>]] "
    "marker in the conversation and need to review the detailed original content "
    "that was removed to save space. Pass the handle value from the marker."
)
```

### 与改进 4 的关系

改进 4 将 observation 预截断从 ContextManager 解耦。改进 8 在此基础上进一步将截断方式从"不可逆 head+tail"升级为"可卸载+重载 head+tail"。两者合并实施——改进 8 替代改进 4 的截断方式，但保留改进 4 的解耦条件（不依赖 ContextManager enabled）。

改进 8 在无 OffloadStore 时（即无 ContextManager），退化为改进 4 的 head+tail——所以**改进 4 的逻辑作为 fallback 被保留在改进 8 中**。

### 风险点

- `OffloadStore` 是内存存储，最多 200 条。大量长 observation 会快速填满。当 store 满 LRU 淘汰最早的内容——此时 `[[OBS_OFFLOAD]]` 标记指向的 handle 可能已被淘汰，reload 返回 not found。这是可接受的降级——agent 收到 not found 后应重新调用工具获取数据。
- 每次卸载是一次 `store` 调用 + UUID 生成，性能开销可忽略（微秒级）。
- Observation 卸载在正常路径（无压缩）也会触发，因为预截断已解耦——这意味着正常路径也会产生 `[[OBS_OFFLOAD]]` 标记。但 `ReloadOriginalContextTool` 需要被注册为 agent 工具才能使用。**如果 agent 没有注册此工具，标记只是提示性的，不影响功能。**

### 验证方式

1. 不开启 ContextManager，运行 `test_read_ana_file`，确认超大 observation 被卸载+标记（而非简单截断）
2. 注册 `ReloadOriginalContextTool`，运行 agent，确认 agent 能通过工具重载完整 observation
3. 在 OffloadStore 满的情况下，确认 LRU 淘汰后 reload 返回 not found

---

## 实施优先级与依赖关系

```
改进 1 (正常路径紧凑渲染) ──→ 改进 2 (紧凑格式升级)  ──→ 改进 3 (分段截断)
         │                                                    │
         │                                                    ↓
         │                                             改进 6 (因果链 prompt)
         ↓
改进 4 (Observation 预截断) ──→ 改进 8 (Observation 卸载增强)

改进 5 (边界调整逻辑)  ── 独立，可并行

改进 7 (Model output 截断+卸载)  ── 依赖改进 1（需要 tool_call_signatures）
```

| 优先级 | 改进项 | 理由 |
|--------|--------|------|
| P0 | 改进 1 | 收益最大（消除正常路径的代码冗余），改动集中 |
| P0 | 改进 8 | 超大 observation 是上下文膨胀的首要来源，卸载+重载形成闭环 |
| P1 | 改进 2 | 与改进 1 一并完成，成本极低 |
| P1 | 改进 4 | 改进 8 的前提（解耦预截断条件），改动极小 |
| P1 | 改进 7 | 超大 model_output 的截断+卸载，与改进 8 形成对称 |
| P1 | 改进 5 | 修正逻辑语义，减少无意义的 keep_n +1 |
| P2 | 改进 3 | 完善截断质量，但需要较多的测试验证 |
| P2 | 改进 6 | Prompt 层面增强，效果依赖 LLM 遵从度 |

---

## 兼容性说明

- 所有改动通过 monkey-patch（`ActionStep.invoked_tools`, `ActionStep.tool_call_signatures`, `ActionStep._original_model_output`）实现，不修改 smolagents 上游代码。
- 所有改动有 fallback：`tool_call_signatures` 为 None 时退化为仅工具名；分段截断识别失败时退化为暴力截断；无 OffloadStore 时 observation 退化为 head+tail 截断；预截断可通过 `max_observation_length=0` 关闭。
- `is_final_answer_step` / `is_tool_invoking_step` 向后兼容旧 ActionStep（没有 `invoked_tools` 字段时 `getattr` 返回 None）。
- `ReloadOriginalContextTool` 的 `description` 更新向后兼容——旧标记 `[[OFFLOAD:handle=...]]` 仍可识别，新增 `[[OBS_OFFLOAD:handle=...]]` 格式使用同一存储后端。
