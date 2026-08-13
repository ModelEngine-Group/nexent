"""A2UI (Agent-to-User Interface) module for structured UI generation."""

from .types import A2UIResponsePart, A2UIValidationResult, A2UIExample
from .parser import (
    is_a2ui_message,
    coerce_message_list,
    parse_a2ui_response,
    may_contain_a2ui_content,
    iter_tagged_block_bodies,
    strip_tagged_a2ui_blocks,
)
from .prompt_builder import build_a2ui_system_prompt, build_a2ui_repair_prompt
from .finalizer import A2UIResponseFinalizer, A2UIFinalizationResult
from .integration import finalize_a2ui_content, is_a2ui_enabled
from .stream_guard import A2UIStreamGuard
from .constants import (
    A2UI_OPEN_TAG,
    A2UI_CLOSE_TAG,
    A2UI_PROTOCOL_VERSION,
    A2UI_MESSAGE_KEYS,
)

__all__ = [
    "A2UIResponsePart",
    "A2UIValidationResult",
    "A2UIExample",
    "A2UIResponseFinalizer",
    "A2UIFinalizationResult",
    "A2UIStreamGuard",
    "A2UI_OPEN_TAG",
    "A2UI_CLOSE_TAG",
    "A2UI_PROTOCOL_VERSION",
    "A2UI_MESSAGE_KEYS",
    "is_a2ui_message",
    "coerce_message_list",
    "parse_a2ui_response",
    "may_contain_a2ui_content",
    "iter_tagged_block_bodies",
    "strip_tagged_a2ui_blocks",
    "build_a2ui_system_prompt",
    "build_a2ui_repair_prompt",
    "finalize_a2ui_content",
    "is_a2ui_enabled",
]