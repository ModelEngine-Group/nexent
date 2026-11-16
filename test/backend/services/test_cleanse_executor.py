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
from test.backend.services.test_run_cleanse_service import request as run_request


def test_executor_preserves_structure_and_pinned_version():
    store = Store()
    core = SimpleNamespace(
        file_structure=Mock(return_value=([{"content": "parsed"}], []))
    )
    runtime = SimpleNamespace(
        file_structure=core.file_structure, ensure_initialized=Mock()
    )
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
    core.file_structure.assert_called_once_with(
        file_data=b"source", filename="source.txt"
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


def test_run_executor_uses_the_admitted_job_directory():
    store = Store()
    request = run_request().model_copy(update={"source": source()})
    parser = SimpleNamespace(
        ensure_initialized=Mock(),
        file_structure=Mock(return_value=([{"content": "parsed"}], [])),
    )
    executor = CleanseExecutor(runtime=parser, objects=store, parser_version="v1")
    result = executor(
        {"parser_version": "v1", "run_id": request.run_id, "job_id": "2" * 32},
        request,
        context=OperationContext("test", monotonic() + 5),
    )
    assert result.key.startswith(f"run-cleanse/{request.run_id}/{'2' * 32}/artifacts/")


@pytest.mark.parametrize("run_id,job_id", [("b" * 32, "2" * 32), ("a" * 32, "../job")])
def test_invalid_admitted_scope_never_initializes_parser(run_id, job_id):
    runtime, objects = Mock(), Mock()
    executor = CleanseExecutor(runtime=runtime, objects=objects, parser_version="v1")
    with pytest.raises(ValueError):
        executor(
            {"parser_version": "v1", "run_id": run_id, "job_id": job_id},
            run_request(),
            context=OperationContext("test", monotonic() + 5),
        )
    runtime.ensure_initialized.assert_not_called()
    objects.stat.assert_not_called()
