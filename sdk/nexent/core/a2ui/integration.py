"""Integration facade for wiring A2UI into the agent runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .finalizer import A2UIResponseFinalizer, should_finalize_a2ui_content
from .parser import may_contain_a2ui_content
from .prompt_builder import build_a2ui_system_prompt
from .stream_guard import A2UIStreamGuard
from .validator import validate_a2ui_response

logger = logging.getLogger(__name__)

# A2UI is always enabled in nexent
A2UI_ENABLED = True


def is_a2ui_enabled() -> bool:
    """A2UI is always enabled."""
    return True


def get_a2ui_system_prompt(language: str = "zh") -> str:
    """Get the A2UI system prompt to inject into the agent."""
    return build_a2ui_system_prompt(language)


def create_stream_guard() -> A2UIStreamGuard:
    """Create a new A2UI stream guard for processing streaming output."""
    return A2UIStreamGuard()


async def finalize_a2ui_content(
    content: str,
    *,
    user_query: Any = "",
    request_id: str = "",
    repair_call: Any = None,
    max_repair_attempts: int = 2,
    timeout_seconds: float = 45.0,
) -> str:
    """Validate, repair, and finalize an A2UI response.

    Flow:
    1. Fast-path validation (if content has no A2UI markers, skip)
    2. Schema and semantic validation
    3. If invalid, attempt repair (up to max_repair_attempts times)
    4. If repair fails, degrade to plain text
    """
    if not isinstance(content, str) or not should_finalize_a2ui_content(content):
        return content

    # Fast path: check if it's parseable tagged A2UI blocks
    if may_contain_a2ui_content(content):
        validation = validate_a2ui_response(content)
        if validation.valid:
            return content

    try:
        finalizer = A2UIResponseFinalizer()
        result = await asyncio.wait_for(
            finalizer.finalize_result(
                content,
                user_query=user_query,
                request_id=request_id,
                repair_call=repair_call,
                max_repair_attempts=max_repair_attempts,
            ),
            timeout=timeout_seconds,
        )
        return result.content
    except asyncio.TimeoutError:
        logger.warning("A2UI finalization timed out: request_id=%s", request_id)
        return content
    except Exception as exc:
        logger.error("A2UI finalization failed: request_id=%s error=%s", request_id, exc)
        return content


__all__ = [
    "A2UI_ENABLED",
    "is_a2ui_enabled",
    "get_a2ui_system_prompt",
    "create_stream_guard",
    "finalize_a2ui_content",
]