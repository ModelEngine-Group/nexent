"""LLM summary generation utilities for ContextManager."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from smolagents.models import ChatMessage, MessageRole

from ..summary_cache import CompressionCallRecord
from ...utils.token_estimation import msg_char_count

logger = logging.getLogger("agent_context.llm_summary")


# ============================================================
#  Standalone utilities (no ContextManager state required)
# ============================================================

def format_summary_output(raw_output: str) -> Optional[str]:
    """Clean and validate LLM summary output.

    Strips markdown code fences, attempts JSON parse for normalization,
    falls back to plain text if not valid JSON.
    """
    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        logger.warning("Summary output is not valid JSON; using as plain text")
        return cleaned


def _is_context_length_error(err: Exception) -> bool:
    """Check if an exception indicates a context length / token limit error."""
    msg = str(err).lower()
    return any(k in msg for k in (
        "context_length", "context length", "maximum context", "maximum context length",
        "prompt is too long", "reduce the length", "too many tokens",
        "token limit", "exceeds the maximum", "input is too long",
        "input length", "exceeds context", "context window",
    ))


# ============================================================
#  SummaryResult
# ============================================================

@dataclass
class SummaryResult:
    """Result of an LLM summary generation call."""
    summary_text: Optional[str]
    records: List[CompressionCallRecord] = field(default_factory=list)


# ============================================================
#  LLMSummary (standalone class, owns config + renderer)
# ============================================================

class LLMSummary:
    """LLM summary generation.

    Owns config and renderer reference. Returns SummaryResult
    with records instead of mutating shared log state.
    """

    def __init__(self, config, renderer):
        self._config = config
        self._renderer = renderer

    def generate_summary(
        self, text: str, model, call_type: str = "summary", prompt_type: str = "initial",
    ) -> SummaryResult:
        """Generate a summary with retry and error handling.

        Returns SummaryResult containing the summary text (or None on failure)
        and a list of CompressionCallRecord entries for the call(s) made.
        """
        try:
            return self._do_generate_summary(text, model, call_type, prompt_type)
        except Exception as e:
            if _is_context_length_error(e):
                logger.warning(f"{call_type} exceeds context limit; retrying with 2/3 budget truncation")
                shrunk = self._renderer.truncate_text_to_tokens(
                    text, int(self._config.max_summary_input_tokens * 0.66)
                )
                try:
                    return self._do_generate_summary(shrunk, model, call_type + "_retry", prompt_type)
                except Exception as e2:
                    logger.exception(f"Retry still failed: {e2}")
                    record = self._record_failed_compression(call_type + "_retry_failed", str(e2))
                    return SummaryResult(summary_text=None, records=[record])
            logger.exception(f"Summary generation exception: {e}")
            record = self._record_failed_compression(call_type + "_failed", str(e))
            return SummaryResult(summary_text=None, records=[record])

    def _do_generate_summary(
        self, text: str, model, call_type: str = "summary", prompt_type: str = "initial",
    ) -> SummaryResult:
        if prompt_type == "incremental":
            system_prompt = (
                self._config.incremental_summary_system_prompt
                or self._config.summary_system_prompt
            )
        else:
            system_prompt = self._config.summary_system_prompt

        schema_desc = json.dumps(
            self._config.summary_json_schema, ensure_ascii=False, indent=2
        )
        if prompt_type == "incremental":
            user_prompt = (
                f"Update the summary following this JSON structure:\n{schema_desc}\n\n"
                f"{text}"
            )
        else:
            user_prompt = (
                f"Output a summary following this JSON structure:\n{schema_desc}\n\n"
                f"Conversation content to summarize:\n{text}"
            )
        messages = [
            ChatMessage(role=MessageRole.SYSTEM,
                        content=[{"type": "text", "text": system_prompt}]),
            ChatMessage(role=MessageRole.USER,
                        content=[{"type": "text", "text": user_prompt}]),
        ]
        response = model(messages, stop_sequences=[])

        raw_output = response.content
        if isinstance(raw_output, list):
            raw_output = " ".join(
                block.get("text", "")
                for block in raw_output
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if not isinstance(raw_output, str):
            raw_output = str(raw_output)

        summary = format_summary_output(raw_output)
        record = self._record_llm_call_token(
            input_len=msg_char_count(messages),
            output_len=len(raw_output),
            response=response, call_type=call_type,
        )
        return SummaryResult(summary_text=summary, records=[record])

    def _record_llm_call_token(self, input_len, output_len, response, call_type) -> CompressionCallRecord:
        """Record a successful LLM call's token usage. Returns the record."""
        return CompressionCallRecord(
            call_type=call_type,
            input_tokens=getattr(getattr(response, "token_usage", None), "input_tokens", 0) or 0,
            output_tokens=getattr(getattr(response, "token_usage", None), "output_tokens", 0) or 0,
            input_chars=input_len, output_chars=output_len,
        )

    def _record_failed_compression(self, call_type: str, error_msg: str) -> CompressionCallRecord:
        """Record a failed compression attempt. Returns the record."""
        return CompressionCallRecord(
            call_type=call_type,
            input_tokens=0,
            output_tokens=0,
            input_chars=0,
            output_chars=0,
            cache_hit=False,
            details={"error": error_msg},
        )
