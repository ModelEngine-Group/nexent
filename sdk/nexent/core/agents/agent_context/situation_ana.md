# Agent Context Management — Situation Analysis

## 1. Tool-Call Redundancy in CodeAgent

### Problem: Three-Layer Duplication

In smolagents' `CodeAgent`, each `ActionStep` carries three fields simultaneously:
- `model_output` — assistant text (containing `<code>...</code>` block)
- `tool_calls` — `[{name: 'python_interpreter', arguments: code_action}]`
- `observations` — execution result

`ActionStep.to_messages()` expands one ActionStep into 3 messages:

| # | Role | Content |
|---|------|---------|
| 1 | `assistant` | Full `model_output` (includes `<code>read_file(...)\nprint(content)\n</code>`) |
| 2 | `tool-call` | `"Calling tools:\n[{name:'python_interpreter', arguments:'read_file(...)\nprint(content)'}]`" |
| 3 | `tool-response` | `"Observation:\n{observations}"` |

The `arguments` field in tool-call is `code_action` — the **exact same code** parsed from `model_output`. So the code content appears **twice**: once in the assistant's `<code>` block, once in tool-call's `arguments`. This is an inherent architectural consequence of CodeAgent unifying all code execution as a single `python_interpreter` pseudo-tool-call.

### Where Compact Rendering Works (and Doesn't)

`StepRenderer.render_action_step` (step_renderer.py:220-229) replaces the verbose tool-call message with a compact summary when `invoked_tools` is available:

```python
if has_invoked_tools(action):
    if text.startswith("Calling tools:"):
        parts.append(f"Tool calls: {', '.join(action.invoked_tools)}")
```

This **does eliminate the duplication**, but only when called through the compression path:

| Path | render_action_step called? | Duplication eliminated? |
|------|---------------------------|------------------------|
| Normal (no compression) | **No** — `core_agent.py` uses `write_memory_to_messages()` directly | **No** — full redundancy |
| Compression (ContextManager triggered) | **Yes** | **Partially** — tool-call compacted, but assistant still has full `<code>` |

### Invoked Tools Assignment vs Usage Disconnect

```python
# core_agent.py:363-365 — assignment
memory_step.invoked_tools = extract_invoked_tools(code_action, self.tools) if self.tools else []

# step_renderer.py:220-229 — usage (only in compression path)
if has_invoked_tools(action):
    # compact rendering...
```

The assignment always happens, but the usage only activates when ContextManager compression is triggered. When ContextManager is disabled or token count is below threshold, `invoked_tools` is computed but never used.

---

## 2. Compression Chain Integrity Analysis

### CodeAgent's Step Model: "Trinity-in-One" with Exceptions

Unlike `ToolCallingAgent` where `tool_calls` and `observations` may appear in separate steps, CodeAgent's `ActionStep` is **typically self-contained**:

```
ActionStep (typical — tool-calling step) = {
  model_output:  "思考+代码"          ← assistant role
  tool_calls:    "python_interpreter"  ← tool-call role (redundant with model_output's code)
  observations:  "执行结果"            ← tool-response role
}
```

**However, not all ActionSteps have the full trinity.** When the model outputs a final answer directly (no `<code>` block), `parse_code_blobs` raises `ValueError`, which is caught as `FinalAnswerError` in `_run_stream`. In this case:

```
ActionStep (final-answer step) = {
  model_output:  "直接回答文本"        ← assistant role only
  tool_calls:    None                 ← no tool-call message
  observations:  None                 ← no tool-response message
}
```

This is confirmed in `core_agent.py:584-590`:
```python
except FinalAnswerError:
    final_answer = action_step.model_output
    if isinstance(final_answer, str):
        final_answer = convert_code_format(final_answer)
    returned_final_answer = True
    action_step.is_final_answer = True
```

The `tool_calls` field is only assigned at `core_agent.py:357-362`, inside the `try` block that succeeds only when code is parsed. When `FinalAnswerError` is raised, `tool_calls` and `observations` remain `None` (their dataclass defaults).

**Implication for compression logic:** The boundary adjustment in `manager.py:273-278` and the pair-integrity logic in `trim_actions_to_budget` should account for this — a final-answer ActionStep has `tool_calls=None` and `observations=None`, making `is_tool_call_step()` and `is_observation_step()` return False for these steps. The earlier statement that these functions "always return True for CodeAgent" is **not strictly correct** — they return True for tool-calling steps but False for final-answer steps.

### Prev Compression: No Chain Break Risk

`extract_pairs` groups `(TaskStep, ActionStep)` as an atomic unit. The entire ActionStep is rendered as one text block and sent to the LLM for summarization. No chain break possible. ✓

### Current Compression: ActionStep as Split Unit

`curr_action_steps` is split by `keep_n` into `actions_to_compress` and `actions_to_keep`. The split granularity is the **whole ActionStep**, so there is no intra-step chain break at the split boundary. ✓

### Boundary Adjustment Logic — Conceptual Mismatch

Manager.py:273-278:
```python
if (getattr(boundary, "observations", None) is not None
        and getattr(prev_a, "tool_calls", None) is not None):
    keep_n += 1
```

This logic assumes `observations` and `tool_calls` **may be in different ActionSteps** (true for ToolCallingAgent). For CodeAgent's tool-calling steps, **every** such ActionStep has both `observations` and `tool_calls`, so the condition is always True and `keep_n` always increments by 1. However, for final-answer steps (where `tool_calls=None` and `observations=None`), the condition is False — so the logic does differentiate between step types, just not along the most meaningful dimension (tool-calling vs final-answer). Harmless but reveals the code was designed for a mixed Agent model — CodeAgent's actual semantics are not precisely modeled.

### `trim_actions_to_budget` — Same Mismatch

budget.py:190-198 has the same assumption that `is_observation_step` and `is_tool_call_step` identify different types of steps. For CodeAgent's tool-calling steps, both always return True, making the pair-integrity logic redundant. For final-answer steps, both return False, so the logic correctly skips pair-integrity checks — but this is incidental rather than by design.

---

## 3. Information Breakage Risk When Tool-Call Compacted + Truncated

### Scenario: Semantic Chain Break

Consider a typical ActionStep rendered with compact tool-call:

```
我来分析内容
<code>analysis = read_file(file_path="sample.txt")
write_file(file_path="ana.txt", content=analysis)</code>
Tool calls: read_file, write_file
Observation:
Execution logs:
分析结果已写入 ana.txt
```

**Risk in `render_steps_with_truncation`'s `_truncate_text`:**

```python
def _truncate_text(self, text, max_len, mark="...[Truncated]"):
    if len(text) <= max_len:
        return text
    return text[:max_len - len(mark)] + mark
```

This is **brute-force character-level truncation** with no semantic boundary awareness. Possible outcomes when truncation kicks in:

- Cuts in the middle of the `<code>` block → partial code, unreadable
- Cuts off the Observation tail → key results lost
- Keeps `"Tool calls: read_file, write_file"` but cuts off the assistant's reasoning text → **chain break**: we know *which* tools were called but not *why* or *what was read*

**The compounding effect:** tool-call compacting removes the detailed call arguments from the tool-call message, while truncation may simultaneously remove the assistant text that contains the same information. This double loss creates an information gap where neither source preserves the full picture.

### The "Tool calls: name1, name2" Format is Too Minimal

Current compact format: `"Tool calls: read_file, write_file"` — only tool names.

If the assistant message is truncated away, this provides no information about:
- What file was read (`file_path` argument)
- What content was written (`content` argument)
- The reasoning connecting the calls

A more informative format like `"Tool calls: read_file(file_path=\"sample.txt\"), write_file(file_path=\"ana.txt\")"` would preserve causal understanding even when the assistant text is partially lost.

---

## 4. Observation (Tool Output) Handling Strategy

### From res.log: Observation is a Major Token Consumer

In the test run, Step 1's observation contains the **full content** of `sample.txt` (~700 chars). This content is fully repeated in Step 2's input messages as part of the tool-response history.

Step token data shows progressive context growth:
- Step 1: estimated_input=1811 tokens
- Step 2: estimated_input=2647 tokens (+46%)
- Step 3: estimated_input=3404 tokens (+29%)

The observation from Step 1 (full file content) is carried verbatim into all subsequent steps.

### Current Pre-Truncation Logic

`core_agent.py:407-416` already has head+tail observation truncation:

```python
if self.context_manager and self.context_manager.config.enabled:
    max_obs = self.context_manager.config.max_observation_length
    if max_obs > 0 and len(memory_step.observations) > max_obs:
        half = max_obs // 2
        truncation_marker = (
            f"\n...[Output truncated to {max_obs} characters. "
            f"Use search or read tools to find specific results.]\n"
        )
        memory_step.observations = obs_text[:half] + truncation_marker + obs_text[-half:]
```

**Issues:**
- Only activates when `context_manager.config.enabled` and `max_observation_length > 0`
- Default value is likely 0 (disabled)
- The strategy itself (head+tail) is sound — preserves beginning context and ending result

### Observation Handling Recommendations

| Principle | Rationale |
|-----------|-----------|
| **Pre-truncate with a large default** (e.g., 3000 chars) | Most normal outputs fit; only oversized tool returns get trimmed |
| **Head+tail preservation** is correct | Beginning provides context, ending provides the key result |
| **Do NOT attempt to preserve full output** | Long observations are the primary driver of context bloat; the agent can re-call tools to get the data |
| **Separate from ContextManager enablement** | Pre-truncation should work even without compression enabled — it's a hygiene measure, not a compression feature |

---

## 5. Summary of Issues and Improvement Directions

| # | Issue | Current State | Improvement Direction |
|---|-------|--------------|----------------------|
| 1 | Normal-path tool-call redundancy | `write_memory_to_messages()` bypasses `render_action_step` | Apply compact tool-call rendering in normal path too (post-process messages) |
| 2 | Compact tool-call format too minimal | `"Tool calls: read_file, write_file"` — only names | Include call signature summary: `"Tool calls: read_file(file_path=\"sample.txt\")"` |
| 3 | Brute-force truncation in compression | `_truncate_text` does character-level cut, no semantic awareness | Segment-aware truncation: split by `\nObservation:\n`, prioritize cutting observation tail |
| 4 | Observation pre-truncation disabled by default | `max_observation_length` default is 0 | Enable with large default (~3000 chars), decouple from ContextManager enablement |
| 5 | Boundary adjustment logic mismatch | `is_observation_step`/`is_tool_call_step` always True for CodeAgent | Use `has_invoked_tools` or treat ActionStep as atomic unit |
| 6 | Assistant loss + compact tool-call = chain break | No safeguard against both being truncated | More informative compact format (#2) + segment-aware truncation (#3) |

---

## Appendix: Key Code Locations

| File | Lines | Description |
|------|-------|-------------|
| `core_agent.py:362-365` | `invoked_tools` assignment | Always computed, only used in compression path |
| `core_agent.py:292-309` | `_step_stream` message building | `write_memory_to_messages()` bypasses `render_action_step` |
| `core_agent.py:407-416` | Observation pre-truncation | Head+tail strategy, but only when ContextManager enabled |
| `step_renderer.py:220-229` | `render_action_step` compact tool-call | Replaces `"Calling tools:"` with `"Tool calls: name1, name2"` |
| `step_renderer.py:359-362` | `_truncate_text` | Brute-force character truncation, no semantic boundary |
| `manager.py:273-278` | Boundary adjustment | `keep_n += 1` always triggers for CodeAgent |
| `budget.py:58-69` | `has_invoked_tools` | Checks `invoked_tools` list (AST-based, meaningful for CodeAgent) |
| `budget.py:72-79` | `is_observation_step` / `is_tool_call_step` | True for tool-calling steps, False for final-answer steps — designed for ToolCallingAgent model |
