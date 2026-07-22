"""LLM call orchestration for summary generation with retry and error handling."""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from smolagents.models import ChatMessage, MessageRole

from ..summary_cache import CompressionCallRecord
from .budget import _is_context_length_error, format_summary_output
from .config import ContextManagerConfig


logger = logging.getLogger("agent_context.llm_summary")


@dataclass
class SummaryResult:
    """Result from an LLM summary generation call."""
    summary_text: Optional[str] = None
    records: List[CompressionCallRecord] = field(default_factory=list)


class LLMSummary:
    """Handles LLM invocation for summarization with context-length retry and error handling."""

    def __init__(self, config: ContextManagerConfig, renderer):
        """
        Args:
            config: ContextManagerConfig providing prompts, schema, and token budgets.
            renderer: A StepRenderer instance for text rendering and truncation.
        """
        self.config = config
        self._renderer = renderer

    def generate_summary(
        self,
        text: str,
        model,
        call_type: str = "summary",
        prompt_type: str = "initial",
    ) -> SummaryResult:
        """Generate a summary from text, with retry on context-length errors.

        Args:
            text: The conversation content to summarize.
            model: An LLM model object.
            call_type: Label for compression call records (e.g. "previous_summary").
            prompt_type: "initial" for fresh compression, "incremental" for updating an existing summary.

        Returns:
            SummaryResult with summary_text and any records.
        """
        try:
            return self._do_generate_summary(text, model, call_type, prompt_type)
        except Exception as e:
            if _is_context_length_error(e):
                logger.warning(f"{call_type} exceeds context limit; retrying with 2/3 budget truncation")
                shrunk = self._renderer.truncate_text_to_tokens(
                    text, int(self.config.max_summary_input_tokens * 0.66)
                )
                try:
                    return self._do_generate_summary(shrunk, model, call_type + "_retry", prompt_type)
                except Exception as e2:
                    record = self._record_failed_compression(call_type + "_retry_failed", str(e2))
                    logger.exception("Retry still failed")
                    return SummaryResult(records=[record])
            record = self._record_failed_compression(call_type + "_failed", str(e))
            logger.exception("Summary generation exception")
            return SummaryResult(records=[record])

    def _do_generate_summary(
        self,
        text: str,
        model,
        call_type: str = "summary",
        prompt_type: str = "initial",
    ) -> SummaryResult:
        """Build prompts, call LLM, format output, record tokens."""
        if prompt_type == "incremental":
            system_prompt = (
                self.config.incremental_summary_system_prompt
                or self.config.summary_system_prompt
            )
        else:
            system_prompt = self.config.summary_system_prompt

        schema_desc = json.dumps(
            self.config.summary_json_schema, ensure_ascii=False, indent=2
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
            input_len=self._msg_char_count(messages),
            output_len=len(raw_output),
            response=response, call_type=call_type,
        )
        return SummaryResult(summary_text=summary, records=[record])

    def _record_failed_compression(self, call_type: str, error_msg: str) -> CompressionCallRecord:
        """Record a failed compression attempt so stats reflect actual triggers."""
        return CompressionCallRecord(
            call_type=call_type,
            input_tokens=0,
            output_tokens=0,
            input_chars=0,
            output_chars=0,
            cache_hit=False,
            details={"error": error_msg},
        )

    def _record_llm_call_token(self, input_len, output_len, response, call_type) -> CompressionCallRecord:
        """Record token usage from an LLM call."""
        return CompressionCallRecord(
            call_type=call_type,
            input_tokens=getattr(getattr(response, "token_usage", None), "input_tokens", 0) or 0,
            output_tokens=getattr(getattr(response, "token_usage", None), "output_tokens", 0) or 0,
            input_chars=input_len, output_chars=output_len,
        )

    @staticmethod
    def _msg_char_count(messages) -> int:
        """Count characters in a list of ChatMessage objects."""
        total = 0
        for msg in messages:
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                total += sum(len(str(part.get("text", ""))) for part in content if isinstance(part, dict))
            elif isinstance(content, str):
                total += len(content)
        return total
