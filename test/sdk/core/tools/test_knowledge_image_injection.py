# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual KB SDK image projection uses only an injected capability."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
from nexent.core.utils.observer import ProcessType


def tool(observer):
    return KnowledgeBaseSearchTool(index_names=["allowed"], observer=observer, display_name_to_index_map={})


def test_image_projection_passes_scope_and_preserves_empty_result():
    observer = Mock()
    value = tool(observer)
    scope = object()
    value.cancellation_scope = scope
    value.image_filterer = Mock(return_value=[])
    value._record_search_results([], ["original"], "query")
    value.image_filterer.assert_called_once_with(["original"], "query", cancellation_scope=scope)
    assert observer.add_message.call_args.args[1] == ProcessType.PICTURE_WEB
    assert json.loads(observer.add_message.call_args.args[2]) == {"images_url": ["original"]}
    assert not hasattr(value, "data_process_service")
    assert not hasattr(value, "_filter_images")


def test_cancelled_filter_never_projects_picture_event():
    observer = Mock()
    value = tool(observer)
    value.image_filterer = Mock(side_effect=RunTerminated())
    with pytest.raises(RunTerminated):
        value._record_search_results([], ["original"], "query")
    assert all(call.args[1] != ProcessType.PICTURE_WEB for call in observer.add_message.call_args_list)


def test_factory_installs_local_image_capability_and_scope():
    scope, filterer = object(), Mock()
    owner = SimpleNamespace(observer=Mock(), cancellation_scope=scope)
    value = NexentAgent.create_local_tool(owner, ToolConfig(
        class_name="KnowledgeBaseSearchTool", name="knowledge_base_search", source="local",
        params={"index_names": ["allowed"]}, metadata={"image_filterer": filterer, "allowed_index_names": ["allowed"]},
    ))
    assert value.image_filterer is filterer
    assert value.cancellation_scope is scope
    assert value._allowed_index_names == {"allowed"}
