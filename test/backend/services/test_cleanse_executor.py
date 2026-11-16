# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management composes structural parsing with checked object publication."""

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import CleanseArtifact
from management.services.file.cleanse_executor import CleanseExecutor
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from test.backend.services.test_file_cleanse_objects import Store, source


def test_executor_preserves_structure_and_pinned_version():
    store = Store()
    core = SimpleNamespace(
        file_process=Mock(return_value=([{"content": "parsed"}], []))
    )
    runtime = SimpleNamespace(file_process=core.file_process, ensure_initialized=Mock())
    executor = CleanseExecutor(
        runtime=runtime, objects=store, parser_version="parser-v1"
    )
    ref = executor(
        {"parser_version": "parser-v1"},
        SimpleNamespace(source=source(), filename="source.txt"),
        context=OperationContext("test", monotonic() + 5),
    )
    output = CleanseArtifact.model_validate_json(store.data[ref.key])
    assert output.parser_version == "parser-v1"
    assert output.blocks[0].content == "parsed"
    core.file_process.assert_called_once_with(
        file_data=b"source", filename="source.txt", chunking_strategy="none"
    )


def test_wrong_version_does_not_initialize_or_read_objects():
    runtime, objects = Mock(), Mock()
    executor = CleanseExecutor(
        runtime=runtime, objects=objects, parser_version="parser-v1"
    )
    with pytest.raises(ValueError, match="version"):
        executor(
            {"parser_version": "other"},
            Mock(),
            context=OperationContext("test", monotonic() + 5),
        )
    runtime.ensure_initialized.assert_not_called()
    objects.stat.assert_not_called()


def test_expired_request_does_not_initialize_or_publish():
    runtime, objects = Mock(), Mock()
    executor = CleanseExecutor(
        runtime=runtime, objects=objects, parser_version="parser-v1"
    )
    with pytest.raises(DeadlineExceeded):
        executor(
            {"parser_version": "parser-v1"},
            Mock(),
            context=OperationContext("test", monotonic() - 1),
        )
    runtime.ensure_initialized.assert_not_called()
    objects.put.assert_not_called()


def test_deadline_expired_during_warmup_does_not_read_source():
    runtime, objects, context = Mock(), Mock(), Mock()
    context.remaining.side_effect = [5, 5, DeadlineExceeded()]
    executor = CleanseExecutor(
        runtime=runtime, objects=objects, parser_version="parser-v1"
    )
    with pytest.raises(DeadlineExceeded):
        executor({"parser_version": "parser-v1"}, Mock(), context=context)
    runtime.ensure_initialized.assert_called_once()
    objects.stat.assert_not_called()
