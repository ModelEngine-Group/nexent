"""Tests for the host-side document-write citation boundary."""

import pytest

from sdk.nexent.core.tools.citation_write_guard import (
    CitationWriteBlockedError,
    sanitize_citation_write_arguments,
    wrap_tool_with_citation_write_guard,
)


class FakeTool:
    def __init__(self, name="write_document"):
        self.name = name
        self.calls = []

    def forward(self, content, filename=None):
        self.calls.append({"content": content, "filename": filename})
        return "written"


def test_strip_mode_removes_internal_markers_from_document_body():
    tool = FakeTool()

    assert wrap_tool_with_citation_write_guard(tool, "strip") is True
    assert tool.forward(content="第一句 [[a1]]，第二句 [[b12]]", filename="report.md") == "written"

    assert tool.calls == [{"content": "第一句，第二句", "filename": "report.md"}]


def test_strip_mode_keeps_non_body_arguments_unchanged():
    tool = FakeTool()
    wrap_tool_with_citation_write_guard(tool, "strip")

    tool.forward(content="正文 [[a1]]", filename="[[a1]]-draft.md")

    assert tool.calls[0]["content"] == "正文"
    assert tool.calls[0]["filename"] == "[[a1]]-draft.md"


def test_allow_mode_leaves_document_body_untouched():
    tool = FakeTool()

    assert wrap_tool_with_citation_write_guard(tool, "allow") is False
    tool.forward(content="正文 [[a1]]")

    assert tool.calls[0]["content"] == "正文 [[a1]]"


def test_block_mode_prevents_write_before_the_tool_runs():
    tool = FakeTool()
    wrap_tool_with_citation_write_guard(tool, "block")

    with pytest.raises(CitationWriteBlockedError, match="write_document"):
        tool.forward(content="正文 [[a1]]")

    assert tool.calls == []


def test_metadata_can_opt_in_a_custom_mcp_write_tool_and_nested_content():
    class PayloadTool:
        name = "remote_mcp_writer"

        def __init__(self):
            self.calls = []

        def forward(self, payload):
            self.calls.append(payload)
            return "written"

    tool = PayloadTool()
    tool._nexent_citation_write_guard_config = {
        "enabled": True,
        "mode": "strip",
        "text_fields": ["payload"],
    }

    assert wrap_tool_with_citation_write_guard(tool, "allow") is True
    tool.forward(payload={"sections": [{"text": "证据 [[a1]]"}]})

    assert tool.calls[0] == {"sections": [{"text": "证据"}]}


def test_non_document_tool_is_not_wrapped_by_default():
    tool = FakeTool(name="knowledge_base_search")

    assert wrap_tool_with_citation_write_guard(tool, "strip") is False
    tool.forward(content="搜索关键词 [[a1]]")

    assert tool.calls[0]["content"] == "搜索关键词 [[a1]]"


def test_single_positional_argument_is_treated_as_document_content_when_uninspectable():
    def opaque_forward(*args, **kwargs):
        return args, kwargs

    args, kwargs, count = sanitize_citation_write_arguments(
        opaque_forward,
        ("正文 [[a1]]",),
        {},
    )

    assert args == ("正文",)
    assert kwargs == {}
    assert count == 1
