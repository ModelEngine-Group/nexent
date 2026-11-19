# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual KB SDK image projection uses only an injected capability."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import KnowledgeContentRequest, ObjectReference
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.agents.resources.tools import ToolResources
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.utils.observer import ProcessType
from runtime.knowledge_base.tool import KnowledgeBaseSearchTool


def tool(observer):
    return KnowledgeBaseSearchTool(index_names=["allowed"], observer=observer, display_name_to_index_map={})


def image_entry():
    request = KnowledgeContentRequest(knowledge_id=1, file_id="a" * 32, file_version=0,
        image_ref=ObjectReference(space="files", key="images/a.png", version="v1", sha256="b" * 64))
    return request, {"file_ref": request.model_dump(exclude={"image_ref"}), "image_ref": request.image_ref.model_dump(),
                     "cite_index": 1, "tool_sign": "a"}


def test_image_projection_passes_scope_and_does_not_restore_unverified_empty_result():
    observer = Mock()
    value = tool(observer)
    scope = object()
    value.cancellation_scope = scope
    value.image_filterer = Mock(return_value=[])
    request, entry = image_entry()
    value._record_search_results([], [entry], "query")
    value.image_filterer.assert_called_once_with([request], "query", cancellation_scope=scope)
    assert all(call.args[1] != ProcessType.PICTURE_WEB for call in observer.add_message.call_args_list)
    assert not hasattr(value, "data_process_service")
    assert not hasattr(value, "_filter_images")


def test_picture_event_preserves_typed_identity_and_citation():
    observer = Mock()
    value = tool(observer)
    request, entry = image_entry()
    value.image_filterer = Mock(return_value=[request])
    value._record_search_results([], [entry], "query")
    assert json.loads(observer.add_message.call_args.args[2]) == {"images_url": [], "images_ref": [entry]}


def test_cancelled_filter_never_projects_picture_event():
    observer = Mock()
    value = tool(observer)
    value.image_filterer = Mock(side_effect=RunTerminated())
    with pytest.raises(RunTerminated):
        value._record_search_results([], [image_entry()[1]], "query")
    assert all(call.args[1] != ProcessType.PICTURE_WEB for call in observer.add_message.call_args_list)


def test_factory_installs_local_image_capability_and_scope():
    scope, filterer = object(), Mock()
    owner = ToolResources()
    owner.observer, owner.cancellation_scope = Mock(), scope
    value = owner.create_local_tool(ToolConfig(
        class_name="KnowledgeBaseSearchTool", name="knowledge_base_search", source="local",
        params={"index_names": ["allowed"]}, metadata={"image_filterer": filterer, "allowed_index_names": ["allowed"]},
    ))
    assert value.image_filterer is filterer
    assert value.cancellation_scope is scope
    assert value._allowed_index_names == {"allowed"}
