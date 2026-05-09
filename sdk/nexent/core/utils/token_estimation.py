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
    Returns None when the content type is unsupported or msg is None.
    """
    if msg is None:
        return None
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
    if msg is None:
        return 0
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

    Collects ALL messages (system prompt + all steps) into one flat list,
    then calls estimate_tokens_text exactly once. This eliminates per-step
    int() truncation drift and keeps the result consistent with
    msg_token_count(flat_list).
    """
    all_msgs = []
    if memory.system_prompt:
        all_msgs.extend(memory.system_prompt.to_messages())
    for step in memory.steps:
        all_msgs.extend(step.to_messages())

    text = _extract_text_from_messages(all_msgs)
    if text is not None:
        return estimate_tokens_text(text)
    return int(msg_char_count(all_msgs) / chars_per_token)

def estimate_tokens_for_system_prompt(
    memory: AgentMemory, chars_per_token: float = 1.5
) -> int:
    """Estimate token count for system prompt in AgentMemory."""
    if not memory.system_prompt:
        return 0

    sys_msgs = memory.system_prompt.to_messages()
    text = _extract_text_from_messages(sys_msgs)

    if text is not None:
        return estimate_tokens_text(text)
    else:
        # Fallback to character-based estimation
        char_count = msg_char_count(sys_msgs)
        return int(char_count / chars_per_token)