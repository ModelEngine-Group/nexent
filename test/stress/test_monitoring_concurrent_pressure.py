"""
Stress test: concurrent users calling the same model, monitoring write pressure.

Simulates N users concurrently making model calls through the monitoring pipeline.
Measures throughput, data integrity, and buffer behavior under load.

Usage:
    python test/stress/test_monitoring_concurrent_pressure.py
"""

from sdk.nexent.monitor.monitoring import (
    MonitoringRecordBuffer,
    _enqueue_monitoring_record,
    set_monitoring_context,
)
import os
import sys
import time
import threading
import uuid
from collections import deque
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@dataclass
class PressureTestResult:
    total_records_enqueued: int = 0
    total_records_written: int = 0
    total_records_lost: int = 0
    total_errors: int = 0
    elapsed_seconds: float = 0.0
    peak_buffer_size: int = 0
    write_call_count: int = 0

    @property
    def enqueue_rate(self) -> float:
        return (
            self.total_records_enqueued / self.elapsed_seconds
            if self.elapsed_seconds > 0
            else 0
        )

    @property
    def write_rate(self) -> float:
        return (
            self.total_records_written / self.elapsed_seconds
            if self.elapsed_seconds > 0
            else 0
        )

    @property
    def loss_rate(self) -> float:
        return (
            (self.total_records_lost / self.total_records_enqueued * 100)
            if self.total_records_enqueued > 0
            else 0
        )


def _create_test_buffer(
    batch_size: int = 100, buffer_maxlen: int = 5000, flush_interval: int = 3
) -> MonitoringRecordBuffer:
    os.environ["ENABLE_MODEL_MONITORING"] = "false"
    buf = MonitoringRecordBuffer()
    buf._enabled = True
    buf._running = False
    buf._batch_size = batch_size
    buf._flush_interval = flush_interval
    buf._buffer = deque(maxlen=buffer_maxlen)
    return buf


def _make_tracker(tenant_id, user_idx):
    """Create a mock tracker for pressure testing."""
    tracker = MagicMock()
    tracker.start_time = time.time()
    tracker.first_token_time = tracker.start_time + 0.05
    tracker.input_tokens = 100
    tracker.output_tokens = 200
    tracker.token_count = 50
    tracker._context_snapshot = {
        "tenant_id": tenant_id,
        "user_id": f"user-{user_idx}",
    }
    tracker._display_name = None
    return tracker


def _user_worker(user_idx, calls_per_user, buf, result, result_lock, peak_buffer):
    """Simulate a single user making multiple model calls."""
    tenant_id = str(uuid.uuid4())
    set_monitoring_context(tenant_id=tenant_id, user_id=f"user-{user_idx}")

    for _ in range(calls_per_user):
        try:
            tracker = _make_tracker(tenant_id, user_idx)

            _enqueue_monitoring_record(
                tracker,
                model_name="GLM-4.6V",
                operation="llm_completion",
                kwargs={},
                model_type="vlm",
            )

            with result_lock:
                result.total_records_enqueued += 1

            current_size = len(buf._buffer)
            if current_size > peak_buffer[0]:
                peak_buffer[0] = current_size

        except Exception:
            with result_lock:
                result.total_errors += 1


def _drain_buffer(buf):
    """Flush remaining buffer contents until no progress is made."""
    remaining = len(buf._buffer)
    while remaining > 0:
        buf._flush_to_db()
        new_remaining = len(buf._buffer)
        if new_remaining == remaining:
            break
        remaining = new_remaining


def run_pressure_test(
    num_users: int = 50,
    calls_per_user: int = 50,
    batch_size: int = 100,
    buffer_maxlen: int = 5000,
    db_write_delay_ms: int = 5,
    flush_interval: int = 3,
) -> PressureTestResult:
    """
    Simulate concurrent users calling one model and measure monitoring write pressure.

    Args:
        num_users: Number of concurrent user threads.
        calls_per_user: Number of model calls each user makes.
        batch_size: Buffer flush batch size.
        buffer_maxlen: Max buffer capacity (deque maxlen).
        db_write_delay_ms: Simulated DB write latency per record in milliseconds.
        flush_interval: Flush thread check interval in seconds.
    """
    result = PressureTestResult()
    result_lock = threading.Lock()
    peak_buffer = [0]
    written_count = [0]
    write_records_lock = threading.Lock()

    def mock_write_batch(batch):
        delay = db_write_delay_ms / 1000.0
        for _ in batch:
            time.sleep(delay)
            with write_records_lock:
                written_count[0] += 1

    buf = _create_test_buffer(batch_size, buffer_maxlen, flush_interval)

    def patched_write_batch(batch):
        mock_write_batch(batch)

    buf._write_batch = patched_write_batch
    buf._running = True
    flush_thread = threading.Thread(
        target=buf._flush_loop, name="test-flush", daemon=True
    )
    flush_thread.start()

    start_time = time.time()

    with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
        threads = []
        for i in range(num_users):
            t = threading.Thread(
                target=_user_worker,
                args=(i, calls_per_user, buf, result, result_lock, peak_buffer),
                daemon=True,
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        _drain_buffer(buf)

    buf._running = False
    flush_thread.join(timeout=5)

    end_time = time.time()

    result.elapsed_seconds = end_time - start_time
    result.total_records_written = written_count[0]
    result.peak_buffer_size = peak_buffer[0]
    result.total_records_lost = max(
        0, result.total_records_enqueued - result.total_records_written
    )
    result.write_call_count = written_count[0]

    return result


def main():
    scenarios = [
        {
            "name": "Baseline (10 users x 20 calls)",
            "num_users": 10,
            "calls_per_user": 20,
            "db_write_delay_ms": 2,
        },
        {
            "name": "Medium (50 users x 50 calls)",
            "num_users": 50,
            "calls_per_user": 50,
            "db_write_delay_ms": 5,
        },
        {
            "name": "High (100 users x 100 calls)",
            "num_users": 100,
            "calls_per_user": 100,
            "db_write_delay_ms": 5,
        },
        {
            "name": "Burst (200 users x 10 calls)",
            "num_users": 200,
            "calls_per_user": 10,
            "db_write_delay_ms": 2,
        },
        {
            "name": "Slow DB (50 users x 50 calls, 20ms write)",
            "num_users": 50,
            "calls_per_user": 50,
            "db_write_delay_ms": 20,
        },
    ]

    print("=" * 80)
    print("MONITORING WRITE PRESSURE TEST")
    print("=" * 80)

    for scenario in scenarios:
        name = scenario.pop("name")
        print(f"\n{'─' * 60}")
        print(f"Scenario: {name}")
        print(f"{'─' * 60}")

        r = run_pressure_test(**scenario)

        print(f"  Total enqueued:       {r.total_records_enqueued:>8}")
        print(f"  Total written to DB:  {r.total_records_written:>8}")
        print(f"  Records lost:         {r.total_records_lost:>8}")
        print(f"  Errors during enqueue:{r.total_errors:>8}")
        print(f"  Peak buffer size:     {r.peak_buffer_size:>8}")
        print(f"  Elapsed time:         {r.elapsed_seconds:>8.2f}s")
        print(f"  Enqueue rate:         {r.enqueue_rate:>8.1f} records/s")
        print(f"  Write rate:           {r.write_rate:>8.1f} records/s")
        print(f"  Data loss rate:       {r.loss_rate:>8.2f}%")

        status = (
            "\u2705 PASS"
            if r.loss_rate == 0 and r.total_errors == 0
            else "\u26a0\ufe0f  ISSUE"
        )
        print(f"  Status:               {status}")

    print(f"\n{'=' * 80}")
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
