"""Channel readiness must precede execution; cancelled requests must not retry."""

import json
import ssl
from concurrent.futures import CancelledError
from unittest.mock import MagicMock

import pytest
from nexent.core.agents import sandbox as sb
from websocket import (
    ABNF,
    WebSocketBadStatusException,
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
)


def message(request_id, kind, content=None):
    return (ABNF.OPCODE_TEXT, json.dumps({
        "parent_header": {"msg_id": request_id},
        "header": {"msg_type": kind}, "content": content or {},
    }))


@pytest.fixture
def lease():
    item = object.__new__(sb._DockerKernelLease)
    item._closed = item._unhealthy = False
    item._channel_session_id = "probe-session"
    item.kernel_id = "owned-kernel"
    item.ws_url = "ws://127.0.0.1:58023/api/kernels/owned-kernel/channels"
    item._receive_timeout_seconds = 0.05
    item._ssl_context = object()
    item._cancellation_scope = sb.RunCancellationScope()
    item._logger = item.logger = MagicMock()
    item._get_kernel_execution_state = MagicMock(return_value="idle")
    return item


def socket_for_execution(*, handshake_lost=False, execution_lost=False):
    ws = MagicMock()
    ws.getstatus.return_value = 101
    frames = []
    sent = []

    def send(payload):
        request = json.loads(payload)
        sent.append(request)
        request_id = request["header"]["msg_id"]
        if request["header"]["msg_type"] == "kernel_info_request":
            if handshake_lost:
                return
            frames.extend([
                message("stale", "status", {"execution_state": "idle"}),
                message(request_id, "kernel_info_reply"),
                message(request_id, "status", {"execution_state": "idle"}),
            ])
        elif not execution_lost:
            frames.extend([
                message(request_id, "stream", {"text": "OK\n"}),
                message(request_id, "execute_reply", {"status": "ok"}),
                message(request_id, "status", {"execution_state": "idle"}),
            ])

    def receive(**kwargs):
        if frames:
            return frames.pop(0)
        raise WebSocketTimeoutException("No matching frames")

    ws.send.side_effect = send
    ws.recv_data.side_effect = receive
    return ws, sent


def test_reconnects_only_handshake_then_submits_code_once(lease, monkeypatch):
    first, first_sent = socket_for_execution(handshake_lost=True)
    second, second_sent = socket_for_execution()
    connect = MagicMock(side_effect=[first, second])
    monkeypatch.setattr("websocket.create_connection", connect)
    result = lease.run_code_raise_errors("print('OK')")
    assert result.logs == "OK\n"
    assert [m["header"]["msg_type"] for m in first_sent] == ["kernel_info_request"]
    assert [m["header"]["msg_type"] for m in second_sent] == ["kernel_info_request", "execute_request"]
    first.close.assert_called_once()
    second.close.assert_called_once()
    assert not lease._cancellation_scope._closers


def test_handshake_retry_is_bounded_and_never_sends_code(lease, monkeypatch):
    ws, sent = socket_for_execution(handshake_lost=True)
    connect = MagicMock(return_value=ws)
    monkeypatch.setattr("websocket.create_connection", connect)
    with pytest.raises(RuntimeError, match="before code submission"):
        lease.run_code_raise_errors("side_effect()")
    assert connect.call_count == 3
    assert all(m["header"]["msg_type"] == "kernel_info_request" for m in sent)
    assert lease._unhealthy


def test_connection_timeout_is_retried_before_submission(lease, monkeypatch):
    ws, sent = socket_for_execution()
    connect = MagicMock(side_effect=[TimeoutError('connect timed out'), ws])
    monkeypatch.setattr('websocket.create_connection', connect)
    assert lease.run_code_raise_errors('pass').logs == 'OK\n'
    assert connect.call_count == 2
    assert sum(m['header']['msg_type'] == 'execute_request' for m in sent) == 1


def test_initialization_replaces_kernel_after_channel_failure(lease, monkeypatch):
    lease._cached_variables = lease._cached_tools = None
    lease._kernel_bootstrap_code = []
    lease.base_url = 'https://sandbox:8888'
    lease.host, lease.port = 'sandbox', 8888
    lease._requests = MagicMock()
    lease._requests.delete.return_value.status_code = 204
    lease._create_kernel = MagicMock(return_value='replacement')
    ws, sent = socket_for_execution()
    connect = MagicMock(side_effect=[TimeoutError('failed')] * 3 + [ws])
    monkeypatch.setattr('websocket.create_connection', connect)
    lease.register_kernel_bootstrap_code('initialize_workspace()')
    assert lease.kernel_id == 'replacement'
    lease._create_kernel.assert_called_once()
    assert lease._kernel_bootstrap_code == ['initialize_workspace()']
    assert sum(m['header']['msg_type'] == 'execute_request' for m in sent) == 1


@pytest.fixture
def recoverable_lease(lease):
    lease._cached_variables = lease._cached_tools = None
    lease._kernel_bootstrap_code = []
    lease.base_url = 'https://sandbox:8888'
    lease.host, lease.port = 'sandbox', 8888
    lease._requests = MagicMock()
    lease._requests.delete.return_value.status_code = 204
    lease._create_kernel = MagicMock(return_value='replacement')
    return lease


@pytest.mark.parametrize('operation', ['variables', 'tools', 'bootstrap'])
def test_failed_replacement_does_not_recurse(recoverable_lease, monkeypatch, operation):
    lease = recoverable_lease
    from smolagents.remote_executors import RemotePythonExecutor

    monkeypatch.setattr(RemotePythonExecutor, 'send_variables', lambda self, _: self.run_code_raise_errors('variables'))
    monkeypatch.setattr(RemotePythonExecutor, 'send_tools', lambda self, _: self.run_code_raise_errors('tools'))
    connect = MagicMock(side_effect=TimeoutError('unavailable'))
    monkeypatch.setattr('websocket.create_connection', connect)
    call = {
        'variables': lambda: lease.send_variables({'x': 1}),
        'tools': lambda: lease.send_tools({}),
        'bootstrap': lambda: lease.register_kernel_bootstrap_code('workspace'),
    }[operation]
    with pytest.raises(RuntimeError):
        call()
    lease._create_kernel.assert_called_once()
    assert connect.call_count == 6
    assert lease._unhealthy
    assert not lease._kernel_replacement_in_progress


def test_initially_unhealthy_setup_has_only_one_replacement(recoverable_lease, monkeypatch):
    lease = recoverable_lease
    lease._unhealthy = True
    monkeypatch.setattr('websocket.create_connection', MagicMock(side_effect=TimeoutError('unavailable')))
    with pytest.raises(RuntimeError):
        lease.register_kernel_bootstrap_code('workspace')
    lease._create_kernel.assert_called_once()


@pytest.mark.parametrize('failure', [
    ssl.SSLCertVerificationError('wrong certificate'),
    WebSocketBadStatusException('unauthorized', status_code=401),
    WebSocketBadStatusException('forbidden', status_code=403),
])
def test_security_failure_does_not_retry_or_replace(recoverable_lease, monkeypatch, failure):
    lease = recoverable_lease
    connect = MagicMock(side_effect=failure)
    monkeypatch.setattr('websocket.create_connection', connect)
    exception_type = type(failure)
    with pytest.raises(exception_type):
        lease.register_kernel_bootstrap_code('workspace')
    connect.assert_called_once()
    lease._create_kernel.assert_not_called()


def test_missing_kernel_can_be_replaced(recoverable_lease, monkeypatch):
    lease = recoverable_lease
    ws, _ = socket_for_execution()
    failure = WebSocketBadStatusException('missing kernel', status_code=404)
    connect = MagicMock(side_effect=[failure, failure, failure, ws])
    monkeypatch.setattr('websocket.create_connection', connect)
    lease.register_kernel_bootstrap_code('workspace')
    lease._create_kernel.assert_called_once()


def test_cancel_during_connection_failure_stops_recovery(recoverable_lease, monkeypatch):
    lease = recoverable_lease
    def connect(*args, **kwargs):
        lease._cancellation_scope.cancel()
        raise TimeoutError('cancelled connection')
    connect_mock = MagicMock(side_effect=connect)
    monkeypatch.setattr('websocket.create_connection', connect_mock)
    with pytest.raises(CancelledError):
        lease.register_kernel_bootstrap_code('workspace')
    connect_mock.assert_called_once()
    lease._create_kernel.assert_not_called()


def test_lost_execution_is_not_replayed_or_accepted_from_http_idle(lease, monkeypatch):
    ws, sent = socket_for_execution(execution_lost=True)
    connect = MagicMock(return_value=ws)
    monkeypatch.setattr("websocket.create_connection", connect)
    with pytest.raises(RuntimeError, match="kernel channel failed"):
        lease.run_code_raise_errors("side_effect()")
    assert connect.call_count == 1
    assert sum(m["header"]["msg_type"] == "execute_request" for m in sent) == 1
    assert lease._unhealthy


@pytest.mark.parametrize("phase", ["handshake", "execution"])
def test_cancellation_closes_only_current_channel_and_never_retries(lease, monkeypatch, phase):
    ws, _ = socket_for_execution()
    original_send = ws.send.side_effect

    def send(payload):
        original_send(payload)
        kind = json.loads(payload)["header"]["msg_type"]
        if kind == ("kernel_info_request" if phase == "handshake" else "execute_request"):
            lease._cancellation_scope.cancel()

    ws.send.side_effect = send
    connect = MagicMock(return_value=ws)
    monkeypatch.setattr("websocket.create_connection", connect)
    replace = MagicMock()
    monkeypatch.setattr(lease, "_replace_unhealthy_kernel", replace)
    with pytest.raises(CancelledError):
        lease.run_code_raise_errors("side_effect()")
    connect.assert_called_once()
    ws.shutdown.assert_called_once()
    ws.close.assert_called_once()
    replace.assert_not_called()
    assert not lease._cancellation_scope._closers


def test_close_induced_oserror_is_cancellation(lease, monkeypatch):
    ws, _ = socket_for_execution()
    def receive(**kwargs):
        lease._cancellation_scope.cancel()
        raise OSError("socket closed")
    ws.recv_data.side_effect = receive
    monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=ws))
    with pytest.raises(CancelledError):
        lease.run_code_raise_errors("side_effect()")


def test_cancelled_unhealthy_lease_is_not_replaced(lease):
    lease._unhealthy = True
    lease._cancellation_scope.cancel()
    lease._replace_unhealthy_kernel = MagicMock()
    with pytest.raises(CancelledError):
        lease.register_kernel_bootstrap_code("pass")
    lease._replace_unhealthy_kernel.assert_not_called()


def test_handshake_requires_both_matching_shell_reply_and_iopub_idle(lease):
    ws = MagicMock()
    ws.getstatus.return_value = 101
    frames = []
    def send(payload):
        request_id = json.loads(payload)["header"]["msg_id"]
        frames.extend([
            message(request_id, "kernel_info_reply"),
            message("other-request", "status", {"execution_state": "idle"}),
        ])
    ws.send.side_effect = send
    def receive(**kwargs):
        if frames:
            return frames.pop(0)
        raise WebSocketTimeoutException("No matching idle")
    ws.recv_data.side_effect = receive
    with pytest.raises(WebSocketTimeoutException):
        lease._wait_for_kernel_channel_ready(ws)


def test_handshake_tolerates_control_frames(lease):
    ws = MagicMock()
    ws.getstatus.return_value = 101
    frames = [(ABNF.OPCODE_PING, b'ping'), (ABNF.OPCODE_PONG, b'pong')]
    def send(payload):
        request_id = json.loads(payload)['header']['msg_id']
        frames.extend([message(request_id, 'kernel_info_reply'),
                       message(request_id, 'status', {'execution_state': 'idle'})])
    ws.send.side_effect = send
    ws.recv_data.side_effect = lambda **_: frames.pop(0)
    lease._wait_for_kernel_channel_ready(ws)
    assert not frames


@pytest.mark.parametrize('frame', [(ABNF.OPCODE_CLOSE, b'closed'), (ABNF.OPCODE_TEXT, b'')])
def test_handshake_rejects_closed_channels(lease, frame):
    ws = MagicMock()
    ws.getstatus.return_value = 101
    ws.recv_data.return_value = frame
    with pytest.raises(WebSocketConnectionClosedException):
        lease._wait_for_kernel_channel_ready(ws)


def test_handshake_obeys_total_deadline(lease, monkeypatch):
    times = iter([0, 1])
    monkeypatch.setattr(sb.time, 'monotonic', lambda: next(times))
    ws = MagicMock()
    ws.getstatus.return_value = 101
    with pytest.raises(WebSocketTimeoutException, match='handshake timed out'):
        lease._wait_for_kernel_channel_ready(ws)
    ws.recv_data.assert_not_called()


def test_execution_without_cancellation_scope_still_closes_channel(lease, monkeypatch):
    lease._cancellation_scope = None
    ws, _ = socket_for_execution()
    monkeypatch.setattr('websocket.create_connection', MagicMock(return_value=ws))
    assert lease.run_code_raise_errors("print('OK')").logs == 'OK\n'
    ws.close.assert_called_once()
