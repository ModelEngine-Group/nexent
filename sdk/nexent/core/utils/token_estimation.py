"""Token estimation utilities.

Provides tiktoken-accurate estimation when available, with a CJK-aware
heuristic fallback. Extracted from agent_context for reuse across core.
"""

from typing import List, Optional, Union

from smolagents.memory import ActionStep, AgentMemory, MemoryStep
from smolagents.models import ChatMessage

_tiktoken_available = False
_encoders: dict = {}

try:
    import tiktoken

    _tiktoken_available = True
except ImportError:
    pass


def _is_cjk(char: str) -> bool:
    """Check if a character is CJK."""
    cp = ord(char)
    return (
        (0x4E00 <= cp <= 0x9FFF)
        or (0x3400 <= cp <= 0x4DBF)
        or (0x20000 <= cp <= 0x2A6DF)
        or (0x2A700 <= cp <= 0x2B73F)
        or (0x2B740 <= cp <= 0x2B81F)
        or (0x2B820 <= cp <= 0x2CEAF)
        or (0xF900 <= cp <= 0xFAFF)
        or (0x2F800 <= cp <= 0x2FA1F)
        or (0x3000 <= cp <= 0x303F)  # CJK punctuation
    )


def _count_tiktoken(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens using a specific tiktoken encoding."""
    if not _tiktoken_available:
        return 0
    if encoding_name not in _encoders:
        _encoders[encoding_name] = tiktoken.get_encoding(encoding_name)
    return len(_encoders[encoding_name].encode(text))


def estimate_tokens_text(text: str) -> int:
    """Estimate token count for a plain text string.

    Uses tiktoken cl100k_base if available, otherwise falls back to
    a CJK-aware heuristic (~4 chars/token for non-CJK, ~2 for CJK).
    """
    if not text:
        return 0
    # tiktoken is based on openai tokenizer
    # if _tiktoken_available:
    #     return _count_tiktoken(text, "cl100k_base")
    cjk_count = sum(1 for c in text if _is_cjk(c))
    non_cjk_count = len(text) - cjk_count
    return max(1, int((non_cjk_count // 4.0) + (cjk_count // 1.1)))


def _extract_text_from_chat_message(msg: ChatMessage) -> Optional[str]:
    """Extract plain text from a single ChatMessage.

    Compatible with content as str or list[{"type": "text", "text": "..."}].
    Returns None when the content type is unsupported.
    """
    if isinstance(msg.content, str):
        return msg.content
    if isinstance(msg.content, list):
        parts = [
            block.get("text", "")
            for block in msg.content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts) if parts else None
    return None


def _extract_text_from_messages(msgs: List[ChatMessage]) -> Optional[str]:
    """Extract plain text from a list of ChatMessages."""
    parts = []
    for msg in msgs:
        t = _extract_text_from_chat_message(msg)
        if t is not None:
            parts.append(t)
    return "".join(parts) if parts else None


def msg_char_count(msg: Union[ChatMessage, List[ChatMessage]]) -> int:
    """Calculate total character count for single or multiple ChatMessages.

    Compatible with content as str or list[{"type": "text", "text": "..."}].
    """
    if isinstance(msg, list):
        return sum(msg_char_count(single_msg) for single_msg in msg)

    text = _extract_text_from_chat_message(msg)
    if text is not None:
        return len(text)
    return 0


def msg_token_count(
    msg: Union[ChatMessage, List[ChatMessage]], chars_per_token: float = 1.5
) -> int:
    """Estimate token count for single or multiple ChatMessages.

    Prefers tiktoken-based (or CJK-heuristic) estimation when text can be
    extracted; falls back to ``chars / chars_per_token`` otherwise.
    """
    if isinstance(msg, list):
        text = ""
        fallback_chars = 0
        for single_msg in msg:
            t = _extract_text_from_chat_message(single_msg)
            if t is not None:
                text += t
            else:
                fallback_chars += msg_char_count(single_msg)
        tokens = estimate_tokens_text(text) if text else 0
        if fallback_chars:
            tokens += int(fallback_chars / chars_per_token)
        return tokens

    text = _extract_text_from_chat_message(msg)
    if text is not None:
        return estimate_tokens_text(text)
    return int(msg_char_count(msg) / chars_per_token)


def estimate_tokens_for_steps(
    steps: List[MemoryStep], chars_per_token: float = 1.5
) -> int:
    """Estimate token count for a list of MemorySteps."""
    return sum(
        msg_token_count(step.to_messages(), chars_per_token) for step in steps
    )


def estimate_tokens(
    memory: AgentMemory, chars_per_token: float = 1.5
) -> int:
    """Estimate total token count in an AgentMemory.

    Prefers using the last known ActionStep ``input_tokens`` as baseline,
    then adds incremental estimation for steps added after that.

    Note: do not naively sum ``input_tokens`` of every step, because each
    step's ``input_tokens`` is already a cumulative value (includes all
    previous steps).
    """
    last_known_tokens = 0
    last_known_idx = -1
    for i, step in enumerate(memory.steps):
        if isinstance(step, ActionStep) and step.token_usage:
            last_known_tokens = step.token_usage.input_tokens
            last_known_idx = i

    if last_known_tokens > 0:
        incremental_text = ""
        incremental_fallback_chars = 0
        for step in memory.steps[last_known_idx + 1 :]:
            msgs = step.to_messages()
            t = _extract_text_from_messages(msgs)
            if t is not None:
                incremental_text += t
            else:
                incremental_fallback_chars += msg_char_count(msgs)
        incremental_tokens = (
            estimate_tokens_text(incremental_text) if incremental_text else 0
        )
        if incremental_fallback_chars:
            incremental_tokens += int(
                incremental_fallback_chars / chars_per_token
            )
        return last_known_tokens + incremental_tokens

    total_tokens = estimate_tokens_for_system_prompt(memory) + estimate_tokens_for_steps(memory.steps)
    return total_tokens

def estimate_tokens_for_system_prompt(
    memory: AgentMemory, chars_per_token: float = 1.5
) -> int:
    """估算 AgentMemory 中系统提示的 token 数。"""
    if not memory.system_prompt:
        return 0

    sys_msgs = memory.system_prompt.to_messages()
    text = _extract_text_from_messages(sys_msgs)

    if text is not None:
        return estimate_tokens_text(text)
    else:
        # 回退到字符数估算
        char_count = msg_char_count(sys_msgs)
        return int(char_count / chars_per_token)