# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Infrastructure parser initialization is lazy, atomic and process-owned."""

import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from infrastructure.file_processing import parser


def test_lazy_initialization_sets_limits_before_core_import(mocker, monkeypatch):
    calls = []
    configure = mocker.patch.object(
        parser, "_configure_third_party_model_paths", return_value={}
    )
    limits = mocker.patch.object(
        parser,
        "_set_native_thread_limits",
        side_effect=lambda _: calls.append("limits"),
    )
    core = Mock()
    module = ModuleType("nexent.data_process")
    module.DataProcessCore = Mock(
        side_effect=lambda **_: (calls.append("core"), core)[1]
    )
    monkeypatch.setitem(sys.modules, "nexent.data_process", module)
    runtime = parser.DocumentParserRuntime(2, ["layout"], {})
    assert not runtime.initialized
    module.DataProcessCore.assert_not_called()
    assert runtime.core is core
    assert runtime.core is core
    assert calls == ["limits", "core"]
    core.preload_models.assert_called_once_with(["layout"])
    configure.assert_called_once_with({})
    limits.assert_called_once_with(2)


def test_failed_preload_never_publishes_partial_core(monkeypatch):
    broken, healthy = Mock(), Mock()
    broken.preload_models.side_effect = RuntimeError("preload")
    module = ModuleType("nexent.data_process")
    module.DataProcessCore = Mock(side_effect=[broken, healthy])
    monkeypatch.setitem(sys.modules, "nexent.data_process", module)
    runtime = parser.DocumentParserRuntime(1, [], {})
    with pytest.raises(RuntimeError, match="preload"):
        runtime.ensure_initialized()
    assert not runtime.initialized and runtime._core is None
    assert runtime.core is healthy and runtime.initialized


def test_forked_instance_rejected_before_touching_inherited_lock(mocker):
    runtime = parser.DocumentParserRuntime(1, [], {})
    runtime._initialized = True
    lock = mocker.patch.object(runtime, "_lock")
    mocker.patch.object(parser.os, "getpid", return_value=runtime._pid + 1)
    assert not runtime.initialized
    with pytest.raises(RuntimeError, match="fork"):
        runtime.ensure_initialized()
    lock.__enter__.assert_not_called()


@pytest.mark.parametrize("method", ["file_process", "file_structure"])
def test_parse_passes_explicit_model_paths(mocker, method):
    paths = {
        "table_transformer": "/models/table",
        "unstructured_default": "/models/layout.json",
    }
    runtime = parser.DocumentParserRuntime(1, [], paths)
    mocker.patch.object(runtime, "ensure_initialized")
    runtime._core = Mock()
    expected = getattr(runtime._core, method).return_value
    request = {"file_data": b"data", "filename": "file.pdf"}
    if method == "file_process":
        request["chunking_strategy"] = "none"
    result = getattr(runtime, method)(**request)
    assert result is expected
    getattr(runtime._core, method).assert_called_once_with(
        **request,
        table_transformer_model_path=paths["table_transformer"],
        unstructured_default_model_initialize_params_json_path=paths[
            "unstructured_default"
        ],
    )


@pytest.mark.parametrize("threads", [0, -1, True, 1.5])
def test_native_thread_count_validation(threads):
    with pytest.raises(ValueError):
        parser.DocumentParserRuntime(threads, [], {})
