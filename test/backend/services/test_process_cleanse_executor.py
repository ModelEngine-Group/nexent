# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management keeps typed request and artifact contracts across the process boundary."""

from unittest.mock import Mock

import pytest
from management.services.file.process_cleanse_executor import ProcessCleanseExecutor
from nexent.storage.errors import InvalidInput, OutcomeUnknown

from test.backend.services.test_cleanse_jobs import artifact, context, request


def row():
    return {
        "scope_kind": "run",
        "run_id": request().run_id,
        "request_payload": request().model_dump(mode="json"),
        "parser_version": "v1",
    }


def test_factory_initializes_only_in_child_boundary(mocker):
    factory = Mock()
    factory.return_value.return_value = artifact()

    def isolate(initialize, snapshot, *, context, tick):
        factory.assert_not_called()
        execute = initialize(context=context)
        return execute(snapshot, context=context)

    mocker.patch(
        "management.services.file.process_cleanse_executor.run_isolated",
        side_effect=isolate,
    )
    result = ProcessCleanseExecutor(factory)(row(), request(), context=context())
    assert result == artifact()
    factory.return_value.warmup.assert_called_once()


def test_mismatched_request_never_starts_process(mocker):
    isolate = mocker.patch(
        "management.services.file.process_cleanse_executor.run_isolated"
    )
    with pytest.raises(InvalidInput):
        ProcessCleanseExecutor(Mock())(
            row(),
            request().model_copy(update={"filename": "changed"}),
            context=context(),
        )
    isolate.assert_not_called()


def test_invalid_published_reference_is_unknown_not_replayed(mocker):
    mocker.patch(
        "management.services.file.process_cleanse_executor.run_isolated",
        return_value={},
    )
    with pytest.raises(OutcomeUnknown):
        ProcessCleanseExecutor(Mock())(row(), request(), context=context())
