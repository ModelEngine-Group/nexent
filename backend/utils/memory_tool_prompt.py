from collections.abc import Iterable


def build_memory_tool_policy(language: str, tool_names: Iterable[str]) -> str:
    """Build runtime guidance only when store_memory is available."""
    if "store_memory" not in set(tool_names):
        return ""

    if language == "zh":
        return """### Memory Tool Policy
- `store_memory` 只存储从用户与当前智能体对话中提取的短期记忆。短期记忆仅包括：用户偏好、任务目标、行动计划与最新进展、针对用户反馈或报错信息的反思总结。这些都是行动步骤中观察到的过程性信息。
- 仅在中间行动步骤（即调用工具或执行代码的步骤）中调用 `store_memory`。当你发现上述任一类短期记忆出现新增或更新时，由你判断、归纳和去重，将单条可复用记忆作为 `content` 入参传给 `store_memory`；不要传入整段对话。
- 生成最终回答时不要调用 `store_memory`。最终回答中的记忆将由系统在回答交付后自动提取，无需你手动保存。
- 系统已在本轮开始前固定检索历史记忆。若候选条目已出现在已提供的记忆上下文或历史工具结果中，不得再次调用 `store_memory`。
- 不要存储临时计算、中间噪声、未验证推测、重复内容或敏感密钥。
- 不要为了展示 Memory 功能而机械调用 `store_memory`。"""

    return """### Memory Tool Policy
- `store_memory` stores only short-term memory extracted from the conversation between the user and the current agent. Short-term memory is limited to user preferences, task goals, action plans and latest progress, and reflections on user feedback or errors. These are process-level observations made during action steps.
- Call `store_memory` only during intermediate action steps (i.e., steps that invoke tools or execute code). When you observe that any eligible category of short-term memory has been added or updated, judge, summarize, and deduplicate the information, then pass one reusable memory entry as the `content` input; never pass the whole conversation.
- Do NOT call `store_memory` when generating the final answer. Memory from the final answer will be extracted automatically by the system after the answer is delivered.
- The system has already performed fixed memory retrieval before this turn. Do not call `store_memory` when the candidate already appears in the provided memory context or prior tool results.
- Do not store transient calculations, intermediate noise, unverified guesses, duplicates, or secrets.
- Do not call `store_memory` mechanically on every turn."""
