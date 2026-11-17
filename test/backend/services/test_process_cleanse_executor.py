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

    def isolate(initialize, snapshot, *, context, tick, on_finished):
        factory.assert_not_called()
        try:
            execute = initialize(context=context)
            return execute(snapshot, context=context)
        finally:
            on_finished()

    mocker.patch(
        "management.services.file.process_cleanse_executor.run_isolated",
        side_effect=isolate,
    )
    result = ProcessCleanseExecutor(factory)(row(), request(), context=context())
    assert result == artifact()
    factory.return_value.warmup.assert_called_once()
    factory.return_value.close.assert_called_once()


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


@pytest.mark.parametrize("phase", ["warmup", "execute"])
def test_owned_executor_closes_on_child_failure(mocker, phase):
    factory = Mock()
    if phase == "warmup":
        factory.return_value.warmup.side_effect = ValueError(
            "controlled warmup failure"
        )
    else:
        factory.return_value.side_effect = ValueError("controlled execution failure")

    def isolate(initialize, snapshot, *, context, tick, on_finished):
        try:
            return initialize(context=context)(snapshot, context=context)
        finally:
            on_finished()

    mocker.patch(
        "management.services.file.process_cleanse_executor.run_isolated",
        side_effect=isolate,
    )
    with pytest.raises(ValueError):
        ProcessCleanseExecutor(factory)(row(), request(), context=context())
    factory.return_value.close.assert_called_once()



def test_unknown_reclamation_never_invents_execution_end(mocker):
    mocker.patch("management.services.file.process_cleanse_executor.run_isolated", side_effect=OutcomeUnknown())
    finished = Mock()
    with pytest.raises(OutcomeUnknown):
        ProcessCleanseExecutor(Mock())(row(), request(), context=context(), on_finished=finished)
    finished.assert_not_called()


def test_pre_dispatch_unavailability_confirms_no_execution_started(mocker):
    from nexent.storage.errors import Unavailable

    mocker.patch("management.services.file.process_cleanse_executor.run_isolated", side_effect=Unavailable())
    finished = Mock()
    with pytest.raises(Unavailable):
        ProcessCleanseExecutor(Mock())(row(), request(), context=context(), on_finished=finished)
    finished.assert_called_once_with()
