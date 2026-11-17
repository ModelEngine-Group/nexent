# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Linux one-task isolation for native parsers, with bounded JSON and group cleanup."""

import json
import multiprocessing
import os
import signal
import threading

from nexent.storage.errors import (
    CapabilityUnsupported,
    InvalidInput,
    OutcomeUnknown,
    Unavailable,
)
from nexent.storage.models import OperationContext

LIMIT = 64 * 1024
_unreclaimed = {}


class _TaskFailed(Exception):
    """A worker reported a deterministic execution failure, without private details."""


def ensure_isolation_available():
    if _unreclaimed:
        raise Unavailable()


def _encode(value):
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    except (ValueError, TypeError):
        raise InvalidInput() from None
    if len(encoded) > LIMIT:
        raise InvalidInput()
    return encoded


def _child(pipe, factory, deadline, operation_id):
    os.setsid()
    context = OperationContext(operation_id, deadline)
    try:
        # The factory constructs all SDK/provider handles after fork and only prewarms.
        execute = factory(context=context)
        context.remaining()
        pipe.send_bytes(_encode({"phase": "ready"}))
        payload = json.loads(pipe.recv_bytes(LIMIT))
        try:
            value = execute(payload, context=context)
            result = {"phase": "result", "value": value}
        except OutcomeUnknown:
            result = {"phase": "unknown"}
        except Exception:  # noqa: BLE001 - Send only a stable error category over IPC.
            result = {"phase": "failed"}
        pipe.send_bytes(_encode(result))
    except Exception:  # noqa: BLE001 - Never let provider details reach process bootstrap logs.
        try:
            pipe.send_bytes(_encode({"phase": "unknown"}))
        except (OSError, ValueError):
            pass
    finally:
        pipe.close()


def _reclaim(process):
    # Kill before join so the still-owned group ID cannot be reused after reaping.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.is_alive():
        process.kill()
    process.join(5)
    if process.is_alive():
        _unreclaimed[process.pid] = process
        raise OutcomeUnknown()
    process.close()


def run_isolated(factory, payload, *, context, tick=None, on_finished=None):
    """Call only from a fork-safe worker root; never from an HTTP request thread."""
    if "fork" not in multiprocessing.get_all_start_methods():
        raise CapabilityUnsupported()
    if (
        threading.current_thread() is not threading.main_thread()
        or threading.active_count() != 1
    ):
        raise CapabilityUnsupported()
    ensure_isolation_available()
    if (not callable(factory) or tick is not None and not callable(tick)
            or on_finished is not None and not callable(on_finished)):
        raise InvalidInput()
    encoded = _encode(payload)
    context.remaining()
    runtime = multiprocessing.get_context("fork")
    parent, child = runtime.Pipe(duplex=True)
    process = runtime.Process(
        target=_child, args=(child, factory, context.deadline, context.operation_id)
    )
    started = dispatched = False
    try:
        process.start()
        started = True
        child.close()
        while True:
            remaining = context.remaining()
            if dispatched and tick is not None:
                tick(context=context)
                remaining = context.remaining()
            if not parent.poll(min(remaining, 0.1)):
                continue
            message = json.loads(parent.recv_bytes(LIMIT))
            if not dispatched:
                if message != {"phase": "ready"}:
                    raise Unavailable()
                context.remaining()
                # Sending may succeed even if its acknowledgement is lost.
                dispatched = True
                parent.send_bytes(encoded)
                continue
            if not isinstance(message, dict):
                raise OutcomeUnknown()
            if message.get("phase") == "result" and set(message) == {"phase", "value"}:
                return message["value"]
            if message == {"phase": "failed"}:
                raise _TaskFailed()
            raise OutcomeUnknown()
    except _TaskFailed:
        raise InvalidInput(operation_id=context.operation_id) from None
    except Exception:  # noqa: BLE001 - All post-dispatch failures retain write uncertainty.
        if dispatched:
            raise OutcomeUnknown(operation_id=context.operation_id) from None
        raise Unavailable(operation_id=context.operation_id) from None
    finally:
        parent.close()
        child.close()
        if started:
            try:
                _reclaim(process)
            except Exception:  # noqa: BLE001 - Failed reclamation fences the worker root.
                _unreclaimed[process.pid] = process
                raise OutcomeUnknown(operation_id=context.operation_id) from None
        else:
            process.close()
        if on_finished is not None:
            on_finished()
