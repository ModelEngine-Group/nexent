# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Isolation protocol and failure policy with controlled OS/IPC boundaries."""

import json
from time import monotonic
from unittest.mock import Mock

import pytest
from nexent.storage.errors import InvalidInput, OutcomeUnknown, Unavailable
from nexent.storage.models import OperationContext

from infrastructure.file_processing import isolated


@pytest.fixture
def process_boundary(mocker):
    mocker.patch.object(isolated.threading, "active_count", return_value=1)
    mocker.patch.object(
        isolated.multiprocessing, "get_all_start_methods", return_value=["fork"]
    )
    runtime = mocker.patch.object(isolated.multiprocessing, "get_context").return_value
    parent, child, process = Mock(), Mock(), Mock()
    runtime.Pipe.return_value = parent, child
    runtime.Process.return_value = process
    parent.poll.return_value = True
    mocker.patch.object(isolated, "_reclaim")
    mocker.patch.object(isolated, "_unreclaimed", {})
    return parent, child, process


def context():
    return OperationContext("isolation-ut", monotonic() + 5)


def test_ready_precedes_dispatch_and_cleanup_precedes_return(process_boundary):
    parent, _, process = process_boundary
    parent.recv_bytes.side_effect = [
        b'{"phase":"ready"}',
        b'{"phase":"result","value":{"ok":true}}',
    ]
    assert isolated.run_isolated(Mock(), {"job": "one"}, context=context()) == {
        "ok": True
    }
    assert json.loads(parent.send_bytes.call_args.args[0]) == {"job": "one"}
    isolated._reclaim.assert_called_once_with(process)


@pytest.mark.parametrize("failure", [EOFError(), OSError(), ValueError()])
def test_failure_after_dispatch_has_unknown_outcome(process_boundary, failure):
    parent, _, process = process_boundary
    parent.recv_bytes.side_effect = [b'{"phase":"ready"}', failure]
    with pytest.raises(OutcomeUnknown):
        isolated.run_isolated(Mock(), {}, context=context())
    isolated._reclaim.assert_called_once_with(process)


def test_failure_before_ready_never_dispatches(process_boundary):
    parent, _, _ = process_boundary
    parent.recv_bytes.side_effect = EOFError()
    with pytest.raises(Unavailable):
        isolated.run_isolated(Mock(), {}, context=context())
    parent.send_bytes.assert_not_called()


@pytest.mark.parametrize(
    "payload", [{"bad": float("nan")}, {"large": "x" * isolated.LIMIT}]
)
def test_invalid_payload_rejected_before_start(process_boundary, payload):
    _, _, process = process_boundary
    with pytest.raises(InvalidInput):
        isolated.run_isolated(Mock(), payload, context=context())
    process.start.assert_not_called()


def test_tick_failure_stops_and_quarantines_dispatched_work(process_boundary):
    parent, _, process = process_boundary
    parent.recv_bytes.return_value = b'{"phase":"ready"}'
    tick = Mock(side_effect=RuntimeError("lease lost"))
    with pytest.raises(OutcomeUnknown):
        isolated.run_isolated(Mock(), {}, context=context(), tick=tick)
    isolated._reclaim.assert_called_once_with(process)


def test_reclaim_failure_fences_new_admission(process_boundary):
    parent, _, process = process_boundary
    parent.recv_bytes.side_effect = [
        b'{"phase":"ready"}',
        b'{"phase":"result","value":1}',
    ]
    isolated._reclaim.side_effect = RuntimeError("stuck")
    with pytest.raises(OutcomeUnknown):
        isolated.run_isolated(Mock(), {}, context=context())
    assert isolated._unreclaimed[process.pid] is process
    with pytest.raises(Unavailable):
        isolated.run_isolated(Mock(), {}, context=context())


def test_reclaim_kills_group_before_join(mocker):
    order = []
    process = Mock(pid=123)
    process.is_alive.return_value = False
    mocker.patch.object(isolated.signal, "SIGKILL", 9, create=True)
    mocker.patch.object(
        isolated.os,
        "killpg",
        create=True,
        side_effect=lambda *args: order.append("kill"),
    )
    process.join.side_effect = lambda _: order.append("join")
    isolated._reclaim(process)
    assert order == ["kill", "join"]
    process.close.assert_called_once()


def test_multithreaded_root_cannot_fork(process_boundary, mocker):
    from nexent.storage.errors import CapabilityUnsupported

    mocker.patch.object(isolated.threading, "active_count", return_value=2)
    with pytest.raises(CapabilityUnsupported):
        isolated.run_isolated(Mock(), {}, context=context())
    process_boundary[2].start.assert_not_called()


def test_initialization_error_does_not_escape_with_provider_details(mocker):
    mocker.patch.object(isolated.os, "setsid", create=True)
    pipe = Mock()
    isolated._child(
        pipe,
        Mock(side_effect=RuntimeError("private-provider-error")),
        monotonic() + 5,
        "init",
    )
    assert json.loads(pipe.send_bytes.call_args.args[0]) == {"phase": "unknown"}
    pipe.close.assert_called_once()
