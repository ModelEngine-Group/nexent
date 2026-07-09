"""
Tests for ExternalKnowledgeSearchTool multi-adapter (kb_refs) support.

Covers:
  - old-format backward compat (tool constructed with kb_ids=... adapter_id=...
    resolves to canonical kb_refs)
  - new kb_refs format single adapter
  - new kb_refs format multi-adapter merge (verify top-k selection across adapters by score)
  - empty kb_refs returns early with the existing "No external knowledge base selected" message
  - merge sorting is stable: same-score results keep original adapter order
"""
import json
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from nexent.core.knowledge_base.platform_adapters import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from nexent.core.tools.external_kb_search_tool import ExternalKnowledgeSearchTool


def _build_mock_retrieve_across(adapter_results_map):
    def retrieve_across(kb_refs, request):
        groups = defaultdict(list)
        for ref in kb_refs:
            groups[ref["adapter_id"]].append(ref)

        all_results = []
        for adapter_id in sorted(groups.keys()):
            fake_results = adapter_results_map.get(adapter_id, [])
            for r in fake_results:
                all_results.append(SearchResult(
                    content=r.get("content", ""),
                    score=float(r.get("score", 0.0)),
                    knowledge_base_id=r.get("kb_id", ""),
                    knowledge_base_name=r.get("kb_name", ""),
                    document_id=r.get("document_id", ""),
                    document_name=r.get("document_name", r.get("filename", "")),
                    id=r.get("id", r.get("segment_id", "")),
                    position=r.get("position", 0),
                    tokens=r.get("tokens", 0),
                    keywords=r.get("keywords", []),
                    index_node_id=r.get("index_node_id", ""),
                    hit_count=r.get("hit_count", 0),
                    enabled=r.get("enabled", True),
                ))

        all_results.sort(key=lambda r: r.score, reverse=True)
        truncated = all_results[:request.top_k] if request.top_k else all_results
        return SearchResponse(
            results=truncated,
            query=request.query,
        )

    return retrieve_across


class TestOldFormatBackwardCompat:
    """Tool constructed with kb_ids=... adapter_id=... resolves to canonical kb_refs."""

    def test_old_format_resolves_to_kb_refs(self):
        kb_ids = ["kb-1", "kb-2"]
        kb_display_names = ["KB One", "KB Two"]
        adapter_id = 42

        tool = ExternalKnowledgeSearchTool(
            adapter_id=adapter_id,
            kb_ids=json.dumps(kb_ids),
            kb_display_names=json.dumps(kb_display_names),
        )

        assert len(tool.kb_refs) == 2
        assert tool.kb_refs[0] == {
            "adapter_id": 42,
            "kb_id": "kb-1",
            "display_name": "KB One",
        }
        assert tool.kb_refs[1] == {
            "adapter_id": 42,
            "kb_id": "kb-2",
            "display_name": "KB Two",
        }

    def test_old_format_list_inputs(self):
        kb_ids = ["kb-1"]
        kb_display_names = ["KB One"]

        tool = ExternalKnowledgeSearchTool(
            adapter_id=1,
            kb_ids=kb_ids,
            kb_display_names=kb_display_names,
        )

        assert len(tool.kb_refs) == 1
        assert tool.kb_refs[0]["adapter_id"] == 1
        assert tool.kb_refs[0]["kb_id"] == "kb-1"

    def test_old_format_missing_display_names_fallback_to_kb_id(self):
        tool = ExternalKnowledgeSearchTool(
            adapter_id=1,
            kb_ids=json.dumps(["kb-1"]),
        )

        assert tool.kb_refs[0]["display_name"] == "kb-1"

    def test_old_format_empty_kb_ids_produces_empty_refs(self):
        tool = ExternalKnowledgeSearchTool(
            adapter_id=1,
            kb_ids=json.dumps([]),
        )

        assert tool.kb_refs == []


class TestNewFormatSingleAdapter:
    """New kb_refs format with a single adapter."""

    def test_single_adapter_kb_refs(self):
        kb_refs = [
            {"adapter_id": 1, "kb_id": "kb-a", "display_name": "KB A"},
            {"adapter_id": 1, "kb_id": "kb-b", "display_name": "KB B"},
        ]

        tool = ExternalKnowledgeSearchTool(
            kb_refs=json.dumps(kb_refs),
        )

        assert len(tool.kb_refs) == 2
        assert tool.kb_refs[0]["adapter_id"] == 1
        assert tool.kb_refs[0]["kb_id"] == "kb-a"
        assert tool.kb_refs[1]["kb_id"] == "kb-b"

    def test_new_format_list_input(self):
        kb_refs = [{"adapter_id": 5, "kb_id": "kb-1", "display_name": "KB 1"}]

        tool = ExternalKnowledgeSearchTool(kb_refs=kb_refs)

        assert len(tool.kb_refs) == 1
        assert tool.kb_refs[0]["adapter_id"] == 5


class TestNewFormatMultiAdapterMerge:
    """Multi-adapter kb_refs: verify top-k selection across adapters by score."""

    def test_multi_adapter_merge_top_k(self):
        adapter_results = {
            1: [
                {"score": 0.9, "content": "adapter1 high", "kb_id": "kb-1"},
                {"score": 0.5, "content": "adapter1 low", "kb_id": "kb-1"},
            ],
            2: [
                {"score": 0.8, "content": "adapter2 medium", "kb_id": "kb-2"},
                {"score": 0.3, "content": "adapter2 low", "kb_id": "kb-2"},
            ],
        }

        kb_refs = [
            {"adapter_id": 1, "kb_id": "kb-1", "display_name": "KB 1"},
            {"adapter_id": 2, "kb_id": "kb-2", "display_name": "KB 2"},
        ]

        tool = ExternalKnowledgeSearchTool(
            kb_refs=json.dumps(kb_refs),
            top_k=3,
        )
        tool.client = MagicMock()
        tool.client.retrieve_across = _build_mock_retrieve_across(adapter_results)

        result = json.loads(tool.forward("test"))

        assert len(result) == 3
        top_content = [item["text"] for item in result]
        assert "adapter1 high" in top_content
        assert "adapter2 medium" in top_content
        assert "adapter1 low" in top_content
        assert "adapter2 low" not in top_content

    def test_multi_adapter_merge_different_scores(self):
        adapter_results = {
            1: [
                {"score": 0.6, "content": "a1 mid", "kb_id": "kb-1"},
            ],
            2: [
                {"score": 0.95, "content": "a2 best", "kb_id": "kb-2"},
                {"score": 0.4, "content": "a2 low", "kb_id": "kb-2"},
            ],
        }

        kb_refs = [
            {"adapter_id": 1, "kb_id": "kb-1", "display_name": "KB 1"},
            {"adapter_id": 2, "kb_id": "kb-2", "display_name": "KB 2"},
        ]

        tool = ExternalKnowledgeSearchTool(
            kb_refs=json.dumps(kb_refs),
            top_k=2,
        )
        tool.client = MagicMock()
        tool.client.retrieve_across = _build_mock_retrieve_across(adapter_results)

        result = json.loads(tool.forward("test"))

        assert len(result) == 2
        assert "a2 best" == result[0]["text"]
        assert "a1 mid" == result[1]["text"]


class TestEmptyKbRefs:
    """Empty kb_refs returns early with the existing message."""

    def test_empty_kb_refs_new_format(self):
        tool = ExternalKnowledgeSearchTool(kb_refs="[]")
        tool.client = MagicMock()

        result = tool.forward("test")
        parsed = json.loads(result)

        assert "No external knowledge base selected" in parsed

    def test_empty_kb_refs_old_format(self):
        tool = ExternalKnowledgeSearchTool(
            adapter_id=1,
            kb_ids=json.dumps([]),
        )
        tool.client = MagicMock()

        result = tool.forward("test")
        parsed = json.loads(result)

        assert "No external knowledge base selected" in parsed


class TestStableSortSameScore:
    """Same-score results keep original adapter order."""

    def test_same_score_preserves_adapter_order(self):
        adapter_results = {
            1: [
                {"score": 0.7, "content": "adapter1 first", "kb_id": "kb-1"},
                {"score": 0.7, "content": "adapter1 second", "kb_id": "kb-1"},
            ],
            2: [
                {"score": 0.7, "content": "adapter2 third", "kb_id": "kb-2"},
                {"score": 0.7, "content": "adapter2 fourth", "kb_id": "kb-2"},
            ],
        }

        kb_refs = [
            {"adapter_id": 1, "kb_id": "kb-1", "display_name": "KB 1"},
            {"adapter_id": 2, "kb_id": "kb-2", "display_name": "KB 2"},
        ]

        tool = ExternalKnowledgeSearchTool(
            kb_refs=json.dumps(kb_refs),
            top_k=4,
        )
        tool.client = MagicMock()
        tool.client.retrieve_across = _build_mock_retrieve_across(adapter_results)

        result = json.loads(tool.forward("test"))

        assert len(result) == 4
        titles = [item["text"] for item in result]
        assert "adapter1 first" == titles[0]
        assert "adapter1 second" == titles[1]
        assert "adapter2 third" == titles[2]
        assert "adapter2 fourth" == titles[3]
