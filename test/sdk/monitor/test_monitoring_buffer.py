import importlib.util
from pathlib import Path
import time


MODULE_PATH = Path(__file__).parents[3] / "sdk" / "nexent" / "monitor" / "monitoring.py"


def _load_monitoring_module():
    spec = importlib.util.spec_from_file_location("monitoring_under_test", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stop_interrupts_flush_interval(monkeypatch):
    monkeypatch.setenv("ENABLE_MODEL_MONITORING", "true")
    monkeypatch.setenv("MODEL_MONITORING_FLUSH_INTERVAL_SECONDS", "20")
    monitoring = _load_monitoring_module()
    buffer = monitoring.MonitoringRecordBuffer()

    time.sleep(0.1)
    started = time.monotonic()
    buffer.stop()

    assert time.monotonic() - started < 0.5
    assert not buffer._flush_thread.is_alive()
