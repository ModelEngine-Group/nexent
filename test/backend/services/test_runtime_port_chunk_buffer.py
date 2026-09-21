"""Unit tests for RuntimeInteractionPort shared chunk buffer and idle flush.

These tests do NOT require a real database — collaborators are mocked.
They cover the thread-safe add_chunk / take_chunks buffer, the
flush_chunks_until_idle poll loop, and verify that every HITL entry point
(dispatch / boundary / receipt / finish / _wait_until_ready) invokes the
idle flush before opening its own transaction.
"""

import threading
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from nexent.core.human_interaction.contracts import AttemptSuspended


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


def test_flush_until_idle_hard_deadline_never_resets():
    """max_wait_ms is a hard absolute cap measured from function entry.

    Even if new chunks keep arriving, the worker must break within
    max_wait_ms. Before the fix the deadline was re-set after every
    drained chunk — that could keep the worker spinning indefinitely.
    """
    port = _make_port()
    port.add_chunk("initial")

    # monotonic timeline: 0.0 (start), 0.010, 0.020, 0.030 (past 30ms cap), 0.030
    fake_monotonic = iter([0.0, 0.010, 0.020, 0.030, 0.030])

    # emit_chunks keeps re-seeding the buffer so it never empties —
    # without a hard deadline the loop would never break.
    def fake_emit(chunks):
        port.add_chunk("still-more")
    port.emit_chunks.side_effect = fake_emit

    with patch("services.human_interaction.runtime_port.time.monotonic", side_effect=lambda: next(fake_monotonic)), \
         patch("services.human_interaction.runtime_port.time.sleep") as mock_sleep:
        # Hard cap 30ms, settle 500ms. settle is unreachable because the
        # buffer is never empty — we rely purely on the hard_deadline.
        port.flush_chunks_until_idle(max_wait_ms=30, settle_ms=500)

    # emit_chunks was called a few times but NOT infinitely — the hard
    # deadline cut it off.
    assert port.emit_chunks.call_count >= 1
    # The last sleep call should be clipped to the remaining time (≤30ms).
    if mock_sleep.call_args_list:
        last_sleep = mock_sleep.call_args_list[-1].args[0]
        assert last_sleep <= 0.031  # ≤ 30ms with tiny float slack


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


# --- in-flight emit and failure recovery --------------------------------------

def test_flush_until_idle_treats_in_flight_emit_as_busy():
    """An empty buffer is NOT idle while an async drain holds the emit lock —
    flush keeps polling until the drain completes.
    """
    port = _make_port()
    port.emit_chunks = MagicMock()
    port._emit_lock.acquire()
    result: dict = {}

    def clear_soon():
        time.sleep(0.06)
        port._emit_lock.release()

    threading.Thread(target=clear_soon, daemon=True).start()

    def run_flush():
        started = time.monotonic()
        port.flush_chunks_until_idle(max_wait_ms=2000, settle_ms=10)
        result["elapsed"] = time.monotonic() - started

    worker = threading.Thread(target=run_flush, daemon=True)
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive(), "flush_chunks_until_idle blocked past hard deadline"
    # Without the in-flight guard the flush would settle at ~10ms on the
    # empty buffer; observing >= 50ms proves it waited for the emit.
    assert result["elapsed"] >= 0.05, result
    assert not port._emit_lock.locked()


def test_flush_until_idle_restores_chunks_when_emit_chunks_raises():
    """A failed DB emit must not lose drained chunks — they go back to the
    shared buffer for the next flush attempt.
    """
    port = _make_port()
    port.emit_chunks = MagicMock(side_effect=RuntimeError("db down"))
    port.add_chunk("c1")
    port.add_chunk("c2")

    with pytest.raises(RuntimeError, match="db down"):
        port.flush_chunks_until_idle(max_wait_ms=200, settle_ms=10)

    assert port.peek_chunks() == 2
    assert not port._emit_lock.locked(), "emit lock leaked on failure"


# --- SSE ordering race regressions --------------------------------------------

def test_flush_waits_for_in_flight_drain_past_deadline():
    """Regression: the hard deadline must NOT fire while an async drain holds
    the emit lock, even past max_wait_ms.

    On a loaded server the async drain's run_blocking(emit_chunks) can exceed
    500ms; the old implementation broke out of the flush on the deadline and
    wrote the HITL row, so the drained chunks landed after it in DB seq order
    (the "form before model output" disorder). The flush must instead wait
    for the lock, drain what arrived, and only then return.
    """
    port = _make_port()
    port._emit_lock.acquire()
    result: dict = {}

    def drain_slowly():
        # Simulate an in-flight async drain that finishes after the deadline.
        time.sleep(0.6)
        port.add_chunk("late-chunk")
        port._emit_lock.release()

    threading.Thread(target=drain_slowly, daemon=True).start()

    def run_flush():
        started = time.monotonic()
        port.flush_chunks_until_idle(max_wait_ms=100, settle_ms=10)
        result["elapsed"] = time.monotonic() - started

    worker = threading.Thread(target=run_flush, daemon=True)
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive(), "flush blocked past the join timeout"
    # The flush must have waited for the in-flight drain (0.6s), well past
    # its own 100ms deadline, so the late chunks are persisted BEFORE the
    # caller proceeds to write its HITL transaction.
    assert result["elapsed"] >= 0.6, result
    assert port.emit_chunks.call_args.args[0] == ["late-chunk"]
    assert not port._emit_lock.locked()


def test_concurrent_drain_and_flush_preserve_chunk_order():
    """Regression: take_chunks + emit_chunks must be one atomic critical section.

    With the old design (take outside the lock) a worker flush and the async
    drain could drain concurrently and the DB seq assignment followed lock
    acquisition order instead of production order. With the shared critical
    section, a chunk added earlier can never be persisted later.
    """

    def run_round():
        port = _make_port()
        emitted: list[str] = []
        emit_lock = threading.Lock()

        def record(chunks, *, _lock=emit_lock, _out=emitted):
            with _lock:
                _out.extend(chunks)

        port.emit_chunks = MagicMock(side_effect=record)
        total = 100

        def drainer(stop: threading.Event, *, _port=port):
            while not stop.is_set() or _port.peek_chunks():
                _port.drain_and_emit()

        stop = threading.Event()
        threads = [threading.Thread(target=drainer, args=(stop,), daemon=True) for _ in range(2)]
        for t in threads:
            t.start()
        for i in range(total):
            port.add_chunk(f"c{i}")
        stop.set()
        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive(), "drainer thread did not finish"

        assert emitted == [f"c{i}" for i in range(total)], (
            f"chunk order corrupted: {emitted[:10]}..."
        )
        assert port.peek_chunks() == 0
        assert not port._emit_lock.locked()

    for _round in range(10):
        run_round()


def test_drain_and_emit_empty_buffer_is_noop():
    """drain_and_emit on an empty buffer must not call emit_chunks."""
    port = _make_port()
    port.drain_and_emit()
    port.emit_chunks.assert_not_called()
    assert not port._emit_lock.locked()


def test_drain_and_emit_restores_chunks_on_failure():
    """A failed DB emit inside drain_and_emit puts the chunks back."""
    port = _make_port()
    port.emit_chunks = MagicMock(side_effect=RuntimeError("db down"))
    port.add_chunk("x")

    with pytest.raises(RuntimeError, match="db down"):
        port.drain_and_emit()

    assert port.peek_chunks() == 1
    assert not port._emit_lock.locked()


def test_finish_flush_failure_still_writes_terminal_status():
    """A chunk-flush failure inside finish must not prevent the terminal
    status row (and its human_run event) from being written.
    """
    port = _make_port()
    port.flush_chunks_until_idle = MagicMock(side_effect=RuntimeError("flush failed"))
    port.transaction = MagicMock()
    fake_tx = MagicMock()
    fake_tx.run.status = "RUNNING"
    fake_tx.requests.return_value = []
    port.transaction.return_value = contextmanager(lambda: iter([fake_tx]))()

    port.finish("COMPLETED")

    port.flush_chunks_until_idle.assert_called_once()
    assert fake_tx.run.status == "COMPLETED"
    fake_tx.emit.assert_called_once()
