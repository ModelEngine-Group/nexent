"""
unit/test_llm_summary.py
Tests for LLMSummary error-handling and output-formatting paths.
"""

from unittest.mock import MagicMock

from factories import make_cm
from loader import LLMSummary, SummaryResult
from smolagents.models import ChatMessage, MessageRole


class TestGenerateSummaryRetry:
    """Cover the error-handling / retry paths in generate_summary()."""

    def test_context_length_error_retry_succeeds(self):
        cm = make_cm()
        llm = LLMSummary(config=cm.config, renderer=cm._renderer)
        model = MagicMock()
        model.side_effect = [
            Exception("maximum context length exceeded"),
            MagicMock(content='{"task_overview": "ok"}'),
        ]
        result = llm.generate_summary("text", model, call_type="test")
        assert result.summary_text is not None

    def test_context_length_error_retry_fails(self):
        cm = make_cm()
        llm = LLMSummary(config=cm.config, renderer=cm._renderer)
        model = MagicMock()
        model.side_effect = Exception("context length exceeded")
        result = llm.generate_summary("text", model, call_type="test")
        assert len(result.records) == 1
        assert result.summary_text is None

    def test_general_exception_returns_failed_record(self):
        cm = make_cm()
        llm = LLMSummary(config=cm.config, renderer=cm._renderer)
        model = MagicMock()
        model.side_effect = RuntimeError("connection timeout")
        result = llm.generate_summary("text", model, call_type="test")
        assert len(result.records) == 1
        assert result.summary_text is None


class TestDoGenerateSummaryEdgeCases:
    """Cover non-standard response content formats."""

    def test_list_content_handled(self):
        """Model returning list-of-blocks content."""
        cm = make_cm()
        llm = LLMSummary(config=cm.config, renderer=cm._renderer)
        model = MagicMock()
        response = MagicMock()
        response.content = [
            {"type": "text", "text": '{"task_overview":'},
            {"type": "text", "text": '"from list"}', "extra": "ignored"},
        ]
        model.return_value = response
        result = llm.generate_summary("text", model)
        assert result.summary_text is not None

    def test_non_str_non_list_content_converted(self):
        cm = make_cm()
        llm = LLMSummary(config=cm.config, renderer=cm._renderer)
        model = MagicMock()
        response = MagicMock()
        class JsonLike:
            def __str__(self):
                return '{"task_overview": "converted"}'
        response.content = JsonLike()
        model.return_value = response
        result = llm.generate_summary("text", model)
        assert result.summary_text is not None


class TestMsgCharCount:
    """Cover the str-content branch of _msg_char_count."""

    def test_string_content_counted(self):
        cm = make_cm()
        llm = LLMSummary(config=cm.config, renderer=cm._renderer)
        msg = ChatMessage(role=MessageRole.USER, content="hello world")
        assert llm._msg_char_count([msg]) == 11
