# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-SDK-DPR-WEB-IMAGE-01: shared callback contract for web search tools."""

import importlib
import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture(params=[("exa", "Exa"), ("tavily", "Tavily"), ("linkup", "Linkup")])
def tool(request):
    name, prefix = request.param
    module = importlib.import_module(f"nexent.core.tools.{name}_search_tool")
    cls = getattr(module, f"{prefix}SearchTool")
    tool = object.__new__(cls)
    tool.observer = MagicMock()
    tool.image_filterer = MagicMock(return_value=["https://img.invalid/2"])
    return tool


def test_actual_filter_method_delegates_and_emits_original_event(tool):
    urls = ["https://img.invalid/1", "https://img.invalid/2"]
    tool._filter_images(urls, "query")
    tool.image_filterer.assert_called_once_with(urls, "query")
    args = tool.observer.add_message.call_args.args
    assert args[0] == "" and args[1].value == "picture_web"
    assert json.loads(args[2]) == {"images_url": urls[1:]}
    assert not hasattr(tool, "data_process_service")


def test_missing_callback_is_a_configuration_error_without_event(tool):
    tool.image_filterer = None
    with pytest.raises(ValueError, match="image_filterer"):
        tool._filter_images(["https://img.invalid/1"], "query")
    tool.observer.add_message.assert_not_called()


def test_existing_whole_batch_failure_semantics_are_preserved(tool):
    tool.image_filterer.side_effect = OSError("failed")
    urls = ["https://img.invalid/1"]
    tool._filter_images(urls, "query")
    tool.image_filterer.assert_called_once()
    assert json.loads(tool.observer.add_message.call_args.args[2]) == {"images_url": urls}
