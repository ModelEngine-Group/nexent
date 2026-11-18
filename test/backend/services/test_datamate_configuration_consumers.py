# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve DataMate requests while keeping configuration I/O in managed workers."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def service(monkeypatch):
    factory = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "nexent.vector_database.datamate_core",
        SimpleNamespace(DataMateCore=factory),
    )
    source = (
        Path(__file__).resolve().parents[3]
        / "backend/management/services/knowledge_base/providers/datamate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datamate_configuration_consumer_test", source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MODEL_ENGINE_ENABLED = "true"
    return module, factory


@pytest.mark.asyncio
async def test_explicit_url_skips_configuration_storage(service):
    module, factory = service
    module.datamate_configuration_url = MagicMock(
        side_effect=AssertionError("Unexpected configuration read")
    )
    factory.return_value.get_user_indices.return_value = ["external-kb"]

    async def blocking(name, fn, *args, **kwargs):
        assert kwargs["lane"] == "control-io"
        return fn(*args)

    module.run_blocking = blocking
    assert await module.check_datamate_connection("tenant-a", "http://explicit") == (
        True,
        "",
    )
    factory.assert_called_once_with(base_url="http://explicit", verify_ssl=True)
    module.datamate_configuration_url.assert_not_called()


@pytest.mark.asyncio
async def test_connection_configuration_runs_in_control_lane(service):
    module, factory = service
    reads = []
    module.datamate_configuration_url = MagicMock(return_value="http://configured")
    factory.return_value.get_user_indices.return_value = []

    async def blocking(name, fn, *args, **kwargs):
        reads.append((name, kwargs["lane"], kwargs["owner"]))
        return fn(*args)

    module.run_blocking = blocking
    assert await module.check_datamate_connection("tenant-a") == (True, "")
    assert reads[0] == ("datamate-read-url", "control-io", "management.knowledge_base")
    module.datamate_configuration_url.assert_called_once_with("tenant-a")


@pytest.mark.asyncio
async def test_file_list_constructs_configured_client_in_control_lane(service):
    module, factory = service
    module.datamate_configuration_url = MagicMock(return_value="http://configured")
    factory.return_value.get_documents_detail.return_value = [{"id": "file-a"}]
    operations = []

    async def blocking(name, fn, *args, **kwargs):
        operations.append((name, kwargs["lane"]))
        return fn(*args)

    module.run_blocking = blocking
    assert await module.fetch_datamate_knowledge_base_file_list(
        "external-kb", "tenant-a"
    ) == {"status": "success", "files": [{"id": "file-a"}]}
    assert operations == [
        ("datamate-configure-client", "control-io"),
        ("datamate-list-files", "control-io"),
    ]
    module.datamate_configuration_url.assert_called_once_with("tenant-a")
