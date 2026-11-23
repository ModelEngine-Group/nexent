# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual KB SDK image projection uses only an injected capability."""

import json
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import (
    KnowledgeContentRequest,
    KnowledgeLegacyImageRequest,
    ObjectReference,
)
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


def test_sdk_filters_and_emits_selected_historical_image_without_file_id():
    observer = Mock()
    value = tool(observer)
    request = KnowledgeLegacyImageRequest(knowledge_id=1, chunk_key="physical", index_uuid="origin",
        sequence=2, primary_term=1, image_ref=ObjectReference(space="files", key="images_in_attachments/old.png",
                                                              version="etag:one", sha256="a" * 64))
    reference = request.model_dump()
    row = {"content": "caption", "filename": "report.pdf", "legacy_image_ref": reference}
    rows, _, images = value._build_search_results([row])
    assert rows[0]["legacy_image_ref"] == reference and "file_ref" not in rows[0]
    value.image_filterer = Mock(return_value=[request])
    value._record_search_results(rows, images, "query")
    assert value.image_filterer.call_args.args == ([request], "query")
    assert observer.add_message.call_args.args[1] == ProcessType.PICTURE_WEB
    assert json.loads(observer.add_message.call_args.args[2])["images_ref"][0]["legacy_image_ref"] == reference
