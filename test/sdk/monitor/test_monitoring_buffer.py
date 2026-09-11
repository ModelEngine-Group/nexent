import time

from sdk.nexent.monitor.monitoring import MonitoringRecordBuffer


def test_stop_interrupts_flush_interval(monkeypatch):
    monkeypatch.setenv("ENABLE_MODEL_MONITORING", "true")
    monkeypatch.setenv("MODEL_MONITORING_FLUSH_INTERVAL_SECONDS", "20")
    buffer = MonitoringRecordBuffer()

    time.sleep(0.1)
    started = time.monotonic()
    buffer.stop()

    # The legacy worst case was ~2s (one tenth of the 20s interval); a 2s bound
    # still fails the old behaviour while leaving headroom on a loaded runner.
    assert time.monotonic() - started < 2.0
    assert not buffer._flush_thread.is_alive()


def test_flush_error_does_not_delay_retry_by_a_full_interval(monkeypatch):
    monkeypatch.setenv("ENABLE_MODEL_MONITORING", "false")
    monkeypatch.setenv("MODEL_MONITORING_FLUSH_INTERVAL_SECONDS", "20")
    buffer = MonitoringRecordBuffer()

    waits = []

    def fake_wait(timeout=None):
        waits.append(timeout)
        return len(waits) >= 3

    monkeypatch.setattr(buffer._stop_event, "wait", fake_wait)

    def boom():
        raise RuntimeError("transient")

    monkeypatch.setattr(buffer, "_flush_to_db", boom)
    buffer._buffer.append({"record": 1})
    buffer._last_flush_time = 0.0
    buffer._running = True

    buffer._flush_loop()

    # Retries back off from a short delay instead of always waiting the full
    # 20s flush interval.
    assert waits == [1.0, 2.0, 4.0]
