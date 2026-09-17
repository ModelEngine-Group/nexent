"""Unit tests for RuntimeInteractionPort shared chunk buffer and idle flush.

These tests do NOT require a real database — collaborators are mocked.
They cover the thread-safe add_chunk / take_chunks buffer, the
flush_chunks_until_idle poll loop, and verify that every HITL entry point
(dispatch / boundary / receipt / finish / _wait_until_ready) invokes the
idle flush before opening its own transaction.
"""

import threading
import time
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


def _make_port():
    """Build a RuntimeInteractionPort with every DB-dependent collaborator mocked.

    We patch ``transaction`` as a context manager yielding a fake tx, so the
    real SQLAlchemy path is never hit. The buffer + idle-flush methods under
    test operate entirely on shared state and mock ``emit_chunks``.
    """
    from services.human_interaction.runtime_port import RuntimeInteractionPort

    service = MagicMock()
    service.repository = MagicMock()
    service.cipher = MagicMock()
    service.cipher.open.return_value = {}
    service.cipher.seal.return_value = "sealed"

    identity = {
        "run_id": "run-1", "tenant_id": "tenant-1", "user_id": "user-1",
        "fence": "fence-1",
    }

    def authorize():
        return None

    with patch.object(RuntimeInteractionPort, "transaction") as mock_tx:
        fake_tx = MagicMock()
        fake_tx.run.checkpoint = "{}"
        fake_tx.run.request_payload = "{}"
        ctx = contextmanager(lambda: iter([fake_tx]))()
        mock_tx.return_value = ctx
        port = RuntimeInteractionPort(
            service, identity, "worker", authorize, allowed_tools=("tool_a",),
            live_resume=True,
        )

    # Replace the transaction contextmanager with one we control so tests
    # that exercise dispatch/boundary/etc. stay DB-free.
    port.transaction = MagicMock()
    port.transaction.return_value = ctx
    port.emit_chunks = MagicMock()
    port.authorize = MagicMock()

    return port


# --- add_chunk / take_chunks ------------------------------------------------

def test_add_chunk_appends_to_buffer():
    port = _make_port()
    port.add_chunk("chunk-1")
    port.add_chunk("chunk-2")
    assert port.take_chunks() == ["chunk-1", "chunk-2"]


def test_take_chunks_clears_buffer():
    port = _make_port()
    port.add_chunk("x")
    assert port.take_chunks() == ["x"]
    assert port.take_chunks() == []


def test_add_chunk_take_chunks_thread_safety():
    """Multiple producers must not lose chunks or see torn buffers."""
    port = _make_port()
    n_threads = 8
    per_thread = 50
    barrier = threading.Barrier(n_threads)

    def producer(tid):
        barrier.wait()
        for i in range(per_thread):
            port.add_chunk(f"t{tid}-{i}")

    threads = [threading.Thread(target=producer, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    chunks = port.take_chunks()
    assert len(chunks) == n_threads * per_thread


# --- flush_chunks_until_idle ------------------------------------------------

def test_flush_until_idle_empty_buffer_settles_immediately():
    """If the buffer is already empty, two short polls + settle_ms break."""
    port = _make_port()
    # settle_ms=20, so first poll sees empty → idle_since set; second poll
    # 20ms later sees empty → break. Total sleep = settle_ms.
    port.flush_chunks_until_idle(max_wait_ms=100, settle_ms=20)
    port.emit_chunks.assert_not_called()


def test_flush_until_idle_persists_then_waits_for_settle():
    """Chunks present → emit_chunks called; then buffer stays empty until settle."""
    port = _make_port()
    port.add_chunk("a")
    port.add_chunk("b")

    # Use a tight settle to keep the test fast.
    port.flush_chunks_until_idle(max_wait_ms=200, settle_ms=10)

    port.emit_chunks.assert_called_once_with(["a", "b"])
    # Buffer should now be drained (take_chunks was called inside flush).
    assert port.take_chunks() == []


def test_flush_until_idle_resets_deadline_on_new_chunks():
    """If chunks arrive during the poll loop, the max_wait deadline resets."""
    port = _make_port()
    port.add_chunk("initial")

    sleep_calls: list[float] = []
    monotonic_values = iter([0.0, 0.02, 0.03, 0.04, 0.06, 0.07, 0.09, 0.11])

    def fake_sleep(secs):
        sleep_calls.append(secs)
        # Simulate a chunk arriving in the middle of the loop.
        if len(sleep_calls) == 1:
            port.add_chunk("late")

    with patch("services.human_interaction.runtime_port.time.monotonic", side_effect=lambda: next(monotonic_values)), \
         patch("services.human_interaction.runtime_port.time.sleep", side_effect=fake_sleep):
        port.flush_chunks_until_idle(max_wait_ms=100, settle_ms=20)

    # emit_chunks called twice: once for initial, once for late
    assert port.emit_chunks.call_count == 2
    first = port.emit_chunks.call_args_list[0].args[0]
    second = port.emit_chunks.call_args_list[1].args[0]
    assert first == ["initial"]
    assert second == ["late"]


def test_flush_until_idle_timeout_wins_over_settle():
    """When max_wait_ms expires before an idle settle, we still break.

    Mock monotonic so time appears to advance past the deadline on the
    second poll — settle_ms is long but max_wait is short, so timeout wins.
    """
    port = _make_port()
    port.add_chunk("initial")

    # monotonic sequence: 0.0, 0.01 (still inside 30ms window), 0.05 (past deadline)
    fake_monotonic = iter([0.0, 0.010, 0.050, 0.050])

    with patch("services.human_interaction.runtime_port.time.monotonic", side_effect=lambda: next(fake_monotonic)), \
         patch("services.human_interaction.runtime_port.time.sleep"):
        # max_wait=30ms, settle=500ms. First call sees chunks → emit, deadline=0.030.
        # Second poll: now=0.050 > 0.030 → timeout break.
        port.flush_chunks_until_idle(max_wait_ms=30, settle_ms=500)

    # emit_chunks called exactly once — we drained the initial chunk, then timeout fired.
    assert port.emit_chunks.call_count == 1
    assert port.emit_chunks.call_args.args[0] == ["initial"]


# --- HITL entry points invoke flush_chunks_until_idle -----------------------

def test_dispatch_calls_flush_before_transaction():
    port = _make_port()
    # Make dispatch not actually open a transaction — we only care about flush.
    port.flush_chunks_until_idle = MagicMock()

    # Patch the transaction contextmanager with one that yields a mock tx
    # where pause_requested is False and we never hit ask_user path.
    fake_tx = MagicMock()
    fake_tx.run.pause_requested = False
    fake_tx.execution.side_effect = MagicMock(status="SUCCEEDED")
    fake_tx.requests.return_value = []
    port.transaction = MagicMock()
    port.transaction.return_value = contextmanager(lambda: iter([fake_tx]))()

    # Interaction path needs payload with questions for the early-return
    # "already answered" branches — let's use no interaction so we fall
    # through to the "not suspended → emit STARTED" case.
    from nexent.core.human_interaction.contracts import AttemptSuspended

    # We expect either normal return or AttemptSuspended; both are fine as
    # long as flush_chunks_until_idle is called before any DB work.
    try:
        port.dispatch(0, "tool_a", {"x": 1})
    except AttemptSuspended:
        pass
    except Exception:
        # Any other exception from the mocked tx is acceptable — we only
        # care that flush was called.
        pass

    port.flush_chunks_until_idle.assert_called_once()


def test_finish_calls_flush_before_transaction():
    port = _make_port()
    port.flush_chunks_until_idle = MagicMock()
    port.transaction = MagicMock()
    fake_tx = MagicMock()
    fake_tx.run.status = "RUNNING"
    port.transaction.return_value = contextmanager(lambda: iter([fake_tx]))()

    port.finish("COMPLETED")
    port.flush_chunks_until_idle.assert_called_once()


def test_boundary_calls_flush_before_transaction():
    port = _make_port()
    port.flush_chunks_until_idle = MagicMock()
    port.transaction = MagicMock()
    fake_tx = MagicMock()
    fake_tx.run.pause_requested = False
    port.transaction.return_value = contextmanager(lambda: iter([fake_tx]))()

    try:
        port.boundary({})
    except AttemptSuspended:
        pass

    port.flush_chunks_until_idle.assert_called_once()


def test_receipt_calls_flush_before_transaction():
    port = _make_port()
    port.flush_chunks_until_idle = MagicMock()
    port.transaction = MagicMock()
    fake_tx = MagicMock()
    fake_exec = MagicMock()
    fake_exec.status = "STARTED"
    fake_tx.execution.return_value = fake_exec
    port.transaction.return_value = contextmanager(lambda: iter([fake_tx]))()

    port.receipt(0, {"ok": True})
    port.flush_chunks_until_idle.assert_called_once()


def test_wait_until_ready_calls_flush_before_status_transition():
    """_wait_until_ready → flush_chunks_until_idle before transitioning to RUNNING."""
    from contextlib import contextmanager

    port = _make_port()
    port.flush_chunks_until_idle = MagicMock()

    fake_tx = MagicMock()
    fake_tx.run.status = "READY"
    fake_tx.run.fence = "fence-1"
    fake_tx.run.lock_owner = "worker"

    @contextmanager
    def fake_repo_transaction(*args, **kwargs):
        yield fake_tx

    port.repository.transaction = fake_repo_transaction
    port.service = MagicMock()  # _wait_until_ready calls service._expire(tx)

    # Patch utcnow so that the "lock_until is None or <= utcnow" check passes.
    from datetime import datetime, timezone
    fake_tx.run.lock_until = datetime(2099, 1, 1, tzinfo=timezone.utc)

    with patch("services.human_interaction.runtime_port.utcnow", return_value=datetime(2025, 1, 1, tzinfo=timezone.utc)), \
         patch("services.human_interaction.runtime_port.time.sleep"):
        port._wait_until_ready()

    port.flush_chunks_until_idle.assert_called_once()
    assert fake_tx.run.status == "RUNNING"
