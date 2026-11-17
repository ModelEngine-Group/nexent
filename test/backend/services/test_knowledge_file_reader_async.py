# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read cancellation, failure propagation and timeout logging remain request-owned."""

import asyncio
from time import monotonic

import pytest
from management.services.knowledge_base import file_reader as module
from nexent.storage.errors import Unavailable
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def test_success_and_storage_failure_signal_owned_context(monkeypatch):
    contexts = []
    payload = {"status": "success"}

    async def blocking(name, fn, *args, **kwargs):
        assert (kwargs["lane"], kwargs["owner"]) == (
            "control-io",
            "management.knowledge_base",
        )
        contexts.append(kwargs["context"])
        return payload

    monkeypatch.setattr(module, "run_blocking", blocking)
    assert (
        await module.read_document_error("kb", "path", ServicePrincipal("u", "t"))
        == payload
    )
    assert contexts[0].cancelled.is_set()

    async def fail(*args, **kwargs):
        contexts.append(kwargs["context"])
        raise Unavailable()

    monkeypatch.setattr(module, "run_blocking", fail)
    with pytest.raises(Unavailable):
        await module.read_document_error("kb", "path", ServicePrincipal("u", "t"))
    assert contexts[1].cancelled.is_set()


@pytest.mark.parametrize("phase", ["error-info", "file-list"])
async def test_timeout_cancels_once_and_logs_no_document_path(monkeypatch, caplog, phase):
    contexts = []

    async def blocking(*args, **kwargs):
        contexts.append(kwargs["context"])
        await asyncio.sleep(10)

    def context(operation_id, deadline, *, cancelled):
        return OperationContext(operation_id, monotonic() + 1, cancelled=cancelled)

    monkeypatch.setattr(module, "run_blocking", blocking)
    monkeypatch.setattr(module, "OperationContext", context)
    with pytest.raises(TimeoutError):
        if phase == "error-info":
            await module.read_document_error("kb", "sensitive-document-path", ServicePrincipal("u", "t"))
        else:
            await module.read_knowledge_files("kb", ServicePrincipal("u", "t"))
    assert len(contexts) == 1 and contexts[0].cancelled.is_set()
    records = [r for r in caplog.records if "knowledge_file_read_timeout" in r.message]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert "sensitive-document-path" not in caplog.text
    assert "phase=" + phase in caplog.text


async def test_public_list_service_propagates_timeout_before_querying_es(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from management.services.knowledge_base import files
    from nexent.storage.errors import DeadlineExceeded

    read, core = AsyncMock(side_effect=DeadlineExceeded()), Mock()
    monkeypatch.setattr(files, "read_knowledge_files", read)
    with pytest.raises(DeadlineExceeded):
        await files.KnowledgeBaseFileService.list_files("kb", include_chunks=False, vdb_core=core, user_id="u", tenant_id="t")
    assert read.await_count == 1
    core.get_documents_detail.assert_not_called()
