from collections.abc import Iterable


def build_memory_tool_policy(language: str, tool_names: Iterable[str]) -> str:
    """Build runtime guidance only when store_memory is available."""
    if "store_memory" not in set(tool_names):
        return ""

    if language == "zh":
        return """### Memory Tool Policy
- `store_memory` 只存储从用户与当前智能体对话中提取的短期记忆。短期记忆仅包括：用户偏好、任务目标、行动计划与最新进展、针对用户反馈或报错信息的反思总结。
- 提取时综合参考用户提问、工具或代码执行结果、模型最终回答；在输出最终回答前，由你判断、归纳和去重，将单条可复用记忆作为 `content` 入参传给 `store_memory`，然后再输出最终回答；不要传入整段对话。
- 每轮输出最终回答前都必须执行一次记忆价值评估。只要上述任一类短期记忆出现新增或更新，就必须调用 `store_memory`；只有确实没有合格条目时才可跳过，且不得为了调用工具而保存空洞内容。
- 系统已在本轮开始前固定检索历史记忆。若候选条目已出现在已提供的记忆上下文或历史工具结果中，不得再次调用 `store_memory`。
- 不要存储临时计算、中间噪声、未验证推测、重复内容或敏感密钥。
- 不要为了展示 Memory 功能而机械调用 `store_memory`。"""

    return """### Memory Tool Policy
- `store_memory` stores only short-term memory extracted from the conversation between the user and the current agent. Short-term memory is limited to user preferences, task goals, action plans and latest progress, and reflections on user feedback or errors.
- Consider the user's question, tool or code execution results, and the final answer you have determined. Before emitting that answer, judge, summarize, and deduplicate the information, pass one reusable memory entry as the `content` input, and then emit the final answer; never pass the whole conversation.
- Before every final answer, you must assess whether reusable memory was added or updated. If any eligible category changed, you must call `store_memory`; skip it only when no eligible entry exists, and never store empty content merely to call the tool.
- The system has already performed fixed memory retrieval before this turn. Do not call `store_memory` when the candidate already appears in the provided memory context or prior tool results.
- Do not store transient calculations, intermediate noise, unverified guesses, duplicates, or secrets.
- Do not call `store_memory` mechanically on every turn."""
