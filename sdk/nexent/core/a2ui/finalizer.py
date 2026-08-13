"""Final validation and repair for model-emitted A2UI responses."""

from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .constants import A2UI_OPEN_TAG
from .validator import validate_a2ui_response

logger = logging.getLogger(__name__)

RepairCall = Callable[[str], Any]

_A2UI_PROTOCOL_LINE_RE = re.compile(
    r'(?im)^\s*(?:[\[{,]\s*)*"?(?:beginRendering|surfaceUpdate|dataModelUpdate|deleteSurface)"?\s*(?::|$)'
)


@dataclass(frozen=True)
class A2UIFinalizationResult:
    """Structured finalization result."""
    content: str
    status: str  # "valid", "repaired", "repair_failed", "skipped"
    validation_error: str | None = None


def _coerce_model_message_content(message: Any) -> str:
    """Extract text content from a model message."""
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        value = message.get("content") or message.get("output") or ""
        return value if isinstance(value, str) else str(value)
    value = getattr(message, "content", None)
    if isinstance(value, str):
        return value
    value = getattr(message, "output", None)
    if isinstance(value, str):
        return value
    return str(message) if message is not None else ""


def has_a2ui_protocol_marker(content: str) -> bool:
    """Return True when content looks like an A2UI payload."""
    text = content or ""
    return A2UI_OPEN_TAG in text or bool(_A2UI_PROTOCOL_LINE_RE.search(text))


def should_finalize_a2ui_content(content: str) -> bool:
    """Return True when the response should enter A2UI validation/repair."""
    return isinstance(content, str) and has_a2ui_protocol_marker(content)


class A2UIResponseFinalizer:
    """Validate, repair, or safely degrade a model A2UI response."""

    async def finalize(
        self,
        content: str,
        *,
        user_query: Any,
        request_id: str,
        repair_call: RepairCall | None,
        max_repair_attempts: int = 2,
    ) -> str:
        result = await self.finalize_result(
            content,
            user_query=user_query,
            request_id=request_id,
            repair_call=repair_call,
            max_repair_attempts=max_repair_attempts,
        )
        return result.content

    async def finalize_result(
        self,
        content: str,
        *,
        user_query: Any,
        request_id: str,
        repair_call: RepairCall | None,
        max_repair_attempts: int = 2,
    ) -> A2UIFinalizationResult:
        if not should_finalize_a2ui_content(content):
            return A2UIFinalizationResult(content=content, status="skipped")

        started_at = time.perf_counter()
        logger.info(
            "A2UI finalizer validating: request_id=%s content_chars=%d",
            request_id,
            len(content or ""),
        )

        validation = validate_a2ui_response(content)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "A2UI finalizer validation: request_id=%s valid=%s duration_ms=%.1f",
            request_id,
            validation.valid,
            elapsed_ms,
        )

        if validation.valid:
            if A2UI_OPEN_TAG in content or self._check_raw_a2ui(content):
                return A2UIFinalizationResult(content=content, status="valid")
            last_error = "A2UI-like content without valid A2UI structure"
        else:
            last_error = validation.error

        # Try to repair
        repaired_content = content
        for attempt in range(1, max_repair_attempts + 1):
            if repair_call is None:
                break
            logger.info(
                "A2UI finalizer repair attempt: request_id=%s attempt=%d",
                request_id,
                attempt,
            )
            repair_prompt = self._build_repair_prompt(
                invalid_content=repaired_content,
                validation_error=last_error or "",
                user_query=str(user_query or ""),
            )
            response = repair_call(repair_prompt)
            if inspect.isawaitable(response):
                response = await response
            repaired_content = _coerce_model_message_content(response)
            validation = validate_a2ui_response(repaired_content)
            if validation.valid:
                logger.info(
                    "A2UI finalizer repair succeeded: request_id=%s attempt=%d",
                    request_id,
                    attempt,
                )
                return A2UIFinalizationResult(content=repaired_content, status="repaired")
            last_error = validation.error

        # All repair attempts failed - return degraded text
        logger.warning(
            "A2UI finalizer repair failed: request_id=%s", request_id,
        )
        fallback = self._fallback_text(repaired_content, last_error or "")
        return A2UIFinalizationResult(
            content=fallback,
            status="repair_failed",
            validation_error=last_error,
        )

    def _check_raw_a2ui(self, content: str) -> bool:
        """Check if content is raw JSON A2UI without tags."""
        stripped = (content or "").strip()
        if not stripped:
            return False
        try:
            import json
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                from .parser import coerce_message_list
                return coerce_message_list(parsed) is not None
        except (json.JSONDecodeError, ImportError):
            pass
        return False

    def _build_repair_prompt(
        self,
        invalid_content: str,
        validation_error: str,
        user_query: str,
    ) -> str:
        from .prompt_builder import build_a2ui_repair_prompt
        return build_a2ui_repair_prompt(
            invalid_content=invalid_content,
            validation_error=validation_error,
            user_query=user_query,
        )

    def _fallback_text(self, content: str, error: str) -> str:
        """Convert failed A2UI content to readable text."""
        from .parser import strip_tagged_a2ui_blocks
        stripped = strip_tagged_a2ui_blocks(content or "")
        if stripped:
            return stripped
        return "界面生成失败，请重试。"


__all__ = [
    "A2UIFinalizationResult",
    "A2UIResponseFinalizer",
    "has_a2ui_protocol_marker",
    "should_finalize_a2ui_content",
]