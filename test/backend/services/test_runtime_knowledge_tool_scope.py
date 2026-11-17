# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime retains tool scope, citation and catalog behavior after SDK retirement."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_tool import knowledge_tool_info
from runtime.knowledge_base.tool import KnowledgeBaseSearchTool


@pytest.mark.parametrize("raw,expected", [(None, 3), ("7", 7), (2.9, 2), (True, 1), (False, 3), ("0", 1), (0, 3), (200, 100), (-4, 1)])
def test_top_k_retains_existing_normalization(raw, expected):
    assert KnowledgeBaseSearchTool(index_names=[], top_k=raw).top_k == expected


@pytest.mark.parametrize("requested,allowed,used,denied,unknown", [
    (None, ["kb-a"], ["kb-a"], [], []),
    ([], ["kb-a"], ["kb-a"], [], []),
    (["A"], ["kb-a"], ["kb-a"], [], []),
    (["B"], ["kb-a"], ["kb-a"], ["kb-b"], []),
    (["missing"], ["kb-a"], ["kb-a"], [], ["missing"]),
    (["A", "B"], ["kb-a"], ["kb-a"], ["kb-b"], []),
    (None, [], [], [], []),
])
def test_scope_notice_and_display_names_are_preserved(requested, allowed, used, denied, unknown):
    tool = KnowledgeBaseSearchTool(index_names=["kb-a", "kb-b"])
    tool.display_name_to_index_map = {"A": "kb-a", "B": "kb-b"}
    tool.set_allowed_index_names(allowed)
    scope = tool._resolve_search_scope(requested)
    assert scope.used_scope == used and scope.permission_denied_scope == denied and scope.unavailable_scope == unknown


def test_deny_all_does_not_invoke_any_backend():
    tool = KnowledgeBaseSearchTool(index_names=["kb"])
    tool.set_allowed_index_names([])
    tool.searcher = Mock(side_effect=AssertionError("No query is permitted"))
    assert "results" in tool.forward("query")
    tool.searcher.assert_not_called()


def test_unbound_tool_has_no_legacy_query_fallback():
    tool = KnowledgeBaseSearchTool(index_names=["kb"])
    with pytest.raises(RuntimeError, match="bound standard backend"):
        tool.forward("query")
    for field in ("vdb_core", "embedding_model", "rerank_model", "_internal_document_paths"):
        assert not hasattr(tool, field)


@pytest.mark.parametrize("field", ["vdb_core", "embedding_model", "rerank_model", "document_paths"])
def test_obsolete_execution_arguments_are_rejected(field):
    with pytest.raises(TypeError):
        KnowledgeBaseSearchTool(index_names=["kb"], **{field: object()})


def test_contract_metadata_is_detached_and_matches_runtime_tool():
    first, second = knowledge_tool_info(), knowledge_tool_info()
    first.params[0]["default"] = 99
    assert second.params[0]["default"] == 3
    assert first.class_name == KnowledgeBaseSearchTool.__name__
    assert json.loads(first.inputs) == KnowledgeBaseSearchTool.inputs
    assert first.description == KnowledgeBaseSearchTool.description and not first.is_user_selectable


def test_typed_image_and_file_metadata_are_kept_in_search_event():
    from nexent.core.utils.observer import ProcessType

    events = []
    tool = KnowledgeBaseSearchTool(index_names=["kb"])
    ref = {"space": "files", "key": "images/a.png", "version": "v1", "sha256": "a" * 64}
    tool.searcher = lambda **kwargs: {"results": [{"content": "image", "filename": "image.png", "score": .5,
                                                  "image_ref": ref, "file_ref": {"file_id": "f" * 32}}]}
    tool.observer = SimpleNamespace(add_message=lambda *event: events.append(event))
    assert "image" in tool.forward("query")
    content, = [event for event in events if event[1] == ProcessType.SEARCH_CONTENT]
    assert json.loads(content[2])[0]["image_ref"] == ref
