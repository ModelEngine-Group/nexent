# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit tests for MCP retrieval tool citation annotation."""

import asyncio
import json
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

TEST_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = TEST_ROOT.parent
for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Import the real dependency-free modules through the installed package before
# the mocked agent harness so the annotation logic keeps the genuine observer
# and tool-sign implementations (the bare "sdk" name resolves to test/sdk here).
from nexent.core.agents.mcp_citation import (
    _looks_like_retrieval_result,
    annotate_mcp_search_results,
    wrap_mcp_tool_with_citation,
)
from nexent.core.utils.observer import (
    MessageObserver as RealMessageObserver,
    ProcessType as RealProcessType,
)

# Harness providing NexentAgent/ToolConfig with mocked heavy dependencies.
from test.sdk.core.agents.test_nexent_agent import MessageObserver, NexentAgent, ToolConfig


RAG_RESULTS = [
    {
        "title": "Deployment guide",
        "url": "https://wiki.example.com/deploy",
        "content": "Deploy the service with docker compose and check the health endpoint.",
        "publish_date": "2026-01-02",
        "similarity": 0.92,
    },
    {
        "title": "Troubleshooting handbook",
        "url": "https://wiki.example.com/troubleshoot",
        "content": "Common failures include port conflicts and expired credentials.",
        "publish_date": "2026-02-03",
        "similarity": 0.81,
    },
]


class _RecordingObserver:
    """Observer double recording reserved citations and reported messages."""

    def __init__(self):
        self.citations = {}
        self.messages = []

    def reserve_citations(self, tool_sign, count):
        start = self.citations.get(tool_sign, 1)
        self.citations[tool_sign] = start + count
        return start

    def add_message(self, agent_name, process_type, content, **kwargs):
        self.messages.append((agent_name, process_type, content))


def _make_tool(result_text):
    return SimpleNamespace(name="rag_search", forward=lambda query: result_text)


# ---------------------------------------------------------------------------
# Detection: which payloads are annotated vs passed through
# ---------------------------------------------------------------------------

def test_annotates_json_list_results():
    observer = _RecordingObserver()
    result = annotate_mcp_search_results(json.dumps(RAG_RESULTS), observer, "rag_search")
    assert result is not None
    payload = json.loads(result)
    assert [item["index"] for item in payload] == ["q1", "q2"]
    assert payload[0]["reference_mark"] == "[[q1]]"
    assert payload[0]["title"] == "Deployment guide"
    assert len(observer.messages) == 1
    agent_name, process_type, content = observer.messages[0]
    assert agent_name == ""
    assert process_type == RealProcessType.SEARCH_CONTENT
    reported = json.loads(content)
    assert reported[0]["tool_sign"] == "q"
    assert reported[0]["cite_index"] == 1
    assert reported[0]["search_type"] == "rag_search"


def test_annotates_nested_results_object():
    observer = _RecordingObserver()
    payload = {"code": 0, "results": RAG_RESULTS}
    result = annotate_mcp_search_results(json.dumps(payload), observer, "rag")
    assert result is not None
    assert [item["index"] for item in json.loads(result)] == ["q1", "q2"]


def test_annotates_single_result_object():
    observer = _RecordingObserver()
    single = {"title": "Doc", "content": "A long enough document chunk for detection."}
    result = annotate_mcp_search_results(json.dumps(single), observer, "rag")
    assert result is not None
    assert [item["index"] for item in json.loads(result)] == ["q1"]


def test_passes_through_non_json_text():
    observer = _RecordingObserver()
    assert annotate_mcp_search_results("plain text, not json", observer) is None
    assert observer.messages == []


def test_passes_through_non_string_result():
    observer = _RecordingObserver()
    assert annotate_mcp_search_results({"direct": "dict"}, observer) is None


def test_passes_through_string_list():
    observer = _RecordingObserver()
    assert annotate_mcp_search_results(json.dumps(["a", "b"]), observer) is None


def test_passes_through_tool_listing_output():
    # Shape used by installed-tool listings: identity fields but no text-like fields.
    observer = _RecordingObserver()
    listing = [
        {
            "tool_id": 1,
            "name": "send_email",
            "description": "Send an email to a recipient",
            "source": "mcp",
            "score": 0.5,
        }
    ]
    assert annotate_mcp_search_results(json.dumps(listing), observer) is None


def test_passes_through_chunks_without_identity_fields():
    observer = _RecordingObserver()
    chunks = [{"text": "only a long chunk without any identity fields at all"}]
    assert annotate_mcp_search_results(json.dumps(chunks), observer) is None


def test_passes_through_short_text():
    observer = _RecordingObserver()
    items = [{"title": "t", "text": "short"}]
    assert annotate_mcp_search_results(json.dumps(items), observer) is None


def test_passes_through_empty_results():
    observer = _RecordingObserver()
    assert annotate_mcp_search_results(json.dumps({"results": []}), observer) is None


def test_passes_through_scalar_json_payload():
    observer = _RecordingObserver()
    assert annotate_mcp_search_results(json.dumps(42), observer) is None
    assert annotate_mcp_search_results(json.dumps("a bare json string"), observer) is None
    assert observer.messages == []


def test_retrieval_heuristic_rejects_empty_items():
    # Defensive branch: an empty item list is never a retrieval result.
    assert _looks_like_retrieval_result([]) is False


def test_returns_none_without_observer():
    assert annotate_mcp_search_results(json.dumps(RAG_RESULTS), None) is None


# ---------------------------------------------------------------------------
# Field mapping onto the unified search result message
# ---------------------------------------------------------------------------

def test_maps_field_aliases_and_defaults():
    observer = _RecordingObserver()
    items = [{
        "doc_title": "Handbook",
        "link": "https://example.com/a",
        "chunk_content": "Chunk body long enough to pass detection thresholds.",
        "publish_date": "2026-03-04",
        "similarity": 0.75,
        "file_name": "handbook.pdf",
    }]
    annotate_mcp_search_results(json.dumps(items), observer, "rag")
    reported = json.loads(observer.messages[0][2])
    assert reported[0]["title"] == "Handbook"
    assert reported[0]["url"] == "https://example.com/a"
    assert reported[0]["text"].startswith("Chunk body")
    assert reported[0]["published_date"] == "2026-03-04"
    assert reported[0]["score"] == "0.75"
    assert reported[0]["filename"] == "handbook.pdf"
    assert reported[0]["source_type"] == "url"
    assert reported[0]["score_details"] is None


def test_defaults_to_file_source_type_without_url():
    observer = _RecordingObserver()
    items = [{"title": "Doc", "text": "A local document chunk long enough for checks."}]
    annotate_mcp_search_results(json.dumps(items), observer, "rag")
    reported = json.loads(observer.messages[0][2])
    assert reported[0]["source_type"] == "file"
    assert reported[0]["url"] == ""


def test_metadata_fills_missing_fields():
    observer = _RecordingObserver()
    items = [{
        # Top-level identity field so detection passes; remaining attributes
        # live in the nested metadata mapping.
        "source": "wiki",
        "text": "Document chunk with metadata carrying the remaining attributes.",
        "metadata": {"title": "From Meta", "url": "https://example.com/m", "score": 0.66},
    }]
    annotate_mcp_search_results(json.dumps(items), observer, "rag")
    reported = json.loads(observer.messages[0][2])
    assert reported[0]["title"] == "From Meta"
    assert reported[0]["url"] == "https://example.com/m"
    assert reported[0]["score"] == "0.66"
    assert reported[0]["score_details"] == {
        "title": "From Meta",
        "url": "https://example.com/m",
        "score": 0.66,
    }


def test_score_field_skips_boolean_values():
    observer = _RecordingObserver()
    items = [{
        "title": "Doc",
        "url": "https://example.com/s",
        "text": "Document chunk that is long enough to pass detection checks.",
        "score": True,
        "similarity": 0.87,
    }]
    annotate_mcp_search_results(json.dumps(items), observer, "rag")
    reported = json.loads(observer.messages[0][2])
    # The boolean must not shadow the numeric similarity (bool is an int subclass).
    assert reported[0]["score"] == "0.87"


def test_score_field_accepts_string_values():
    observer = _RecordingObserver()
    items = [{
        "title": "Doc",
        "url": "https://example.com/s",
        "text": "Document chunk that is long enough to pass detection checks.",
        "score": "high",
    }]
    annotate_mcp_search_results(json.dumps(items), observer, "rag")
    reported = json.loads(observer.messages[0][2])
    assert reported[0]["score"] == "high"


# ---------------------------------------------------------------------------
# Citation index continuity
# ---------------------------------------------------------------------------

def test_citation_indexes_are_continuous_across_calls():
    observer = _RecordingObserver()
    first = annotate_mcp_search_results(json.dumps(RAG_RESULTS[:1]), observer, "rag")
    second = annotate_mcp_search_results(json.dumps(RAG_RESULTS), observer, "rag")
    assert [item["index"] for item in json.loads(first)] == ["q1"]
    assert [item["index"] for item in json.loads(second)] == ["q2", "q3"]


# ---------------------------------------------------------------------------
# Tool wrapper behavior
# ---------------------------------------------------------------------------

def test_wrap_sync_forward_annotates_results():
    observer = _RecordingObserver()
    tool = wrap_mcp_tool_with_citation(_make_tool(json.dumps(RAG_RESULTS)), observer)
    payload = json.loads(tool.forward(query="deploy"))
    assert [item["index"] for item in payload] == ["q1", "q2"]


def test_wrap_async_forward_annotates_results():
    observer = _RecordingObserver()

    async def forward(query):
        return json.dumps(RAG_RESULTS)

    tool = wrap_mcp_tool_with_citation(SimpleNamespace(name="rag", forward=forward), observer)
    payload = json.loads(asyncio.run(tool.forward(query="deploy")))
    assert [item["index"] for item in payload] == ["q1", "q2"]


def test_wrap_is_idempotent():
    observer = _RecordingObserver()
    tool = _make_tool(json.dumps(RAG_RESULTS))
    wrapped = wrap_mcp_tool_with_citation(tool, observer)
    assert wrap_mcp_tool_with_citation(wrapped, observer) is wrapped
    payload = json.loads(wrapped.forward(query="deploy"))
    assert [item["index"] for item in payload] == ["q1", "q2"]


def test_wrap_tolerates_unwritable_citation_flag():
    class _SlotsTool:
        # No __dict__: writing the idempotency flag raises AttributeError
        # while the forward slot stays assignable.
        __slots__ = ("forward",)

        def __init__(self):
            self.forward = lambda query: json.dumps(RAG_RESULTS)

    observer = _RecordingObserver()
    tool = wrap_mcp_tool_with_citation(_SlotsTool(), observer)
    payload = json.loads(tool.forward(query="deploy"))
    assert [item["index"] for item in payload] == ["q1", "q2"]


def test_wrap_without_observer_returns_tool_unchanged():
    tool = _make_tool(json.dumps(RAG_RESULTS))
    assert wrap_mcp_tool_with_citation(tool, None) is tool


def test_wrap_preserves_non_retrieval_output():
    observer = _RecordingObserver()
    tool = wrap_mcp_tool_with_citation(_make_tool(json.dumps({"status": "ok"})), observer)
    assert tool.forward(query="x") == json.dumps({"status": "ok"})
    assert observer.messages == []


def test_wrap_keeps_result_when_annotation_fails():
    class _BrokenObserver(_RecordingObserver):
        def reserve_citations(self, tool_sign, count):
            raise RuntimeError("boom")

    observer = _BrokenObserver()
    original = json.dumps(RAG_RESULTS)
    tool = wrap_mcp_tool_with_citation(_make_tool(original), observer)
    assert tool.forward(query="x") == original


# ---------------------------------------------------------------------------
# Compatibility with the real observer implementation
# ---------------------------------------------------------------------------

def test_works_with_real_message_observer():
    observer = RealMessageObserver()
    result = annotate_mcp_search_results(json.dumps(RAG_RESULTS), observer, "rag_search")
    assert result is not None
    # The real observer stores each emitted unit as a Message.to_json() string.
    matched = [
        json.loads(entry)
        for entry in observer.message_query
        if json.loads(entry).get("type") == RealProcessType.SEARCH_CONTENT.value
    ]
    assert len(matched) == 1
    reported = json.loads(matched[0]["content"])
    assert [item["cite_index"] for item in reported] == [1, 2]
    assert all(item["tool_sign"] == "q" for item in reported)


# ---------------------------------------------------------------------------
# Integration: create_tool mcp branch wires the citation wrapper
# ---------------------------------------------------------------------------

def test_create_tool_mcp_branch_applies_citation_wrapper():
    observer = MessageObserver()
    agent = NexentAgent(observer=observer, model_config_list=[], stop_event=Event())
    template = SimpleNamespace(
        name="rag_search",
        inputs={"query": {}},
        forward=lambda query: json.dumps(RAG_RESULTS),
    )
    agent.mcp_tool_collection = SimpleNamespace(tools=[template])
    config = ToolConfig(
        class_name="rag_search", name="rag_search", description="RAG search",
        inputs="{}", output_type="string", params={}, source="mcp", metadata={},
    )
    tool = agent.create_tool(config)
    payload = json.loads(tool.forward(query="deploy"))
    assert [item["index"] for item in payload] == ["q1", "q2"]
    assert payload[0]["reference_mark"] == "[[q1]]"
    # The harness-loaded agent binds the mocked ProcessType whose
    # SEARCH_CONTENT member is the plain "search_content" string.
    search_messages = [
        entry for entry in observer.messages
        if len(entry["args"]) >= 3 and entry["args"][1] == "search_content"
    ]
    assert len(search_messages) == 1
    reported = json.loads(search_messages[0]["args"][2])
    assert reported[0]["cite_index"] == 1
    assert reported[0]["tool_sign"] == "q"
    # The shared collection template must stay unwrapped.
    assert template.forward(query="deploy") == json.dumps(RAG_RESULTS)
