"""Focused tests for queue-specific Celery worker startup."""

from unittest.mock import MagicMock

import pytest


def test_parser_worker_arguments_use_prefork_autoscale(monkeypatch):
    from data_process import worker

    captured = {}

    class FakeApp:
        def worker_main(self, args):
            captured["args"] = args

    monkeypatch.setattr(worker, "app", FakeApp())
    monkeypatch.setattr(worker, "QUEUES", "parse_q")
    monkeypatch.setattr(worker, "WORKER_NAME", "parser")
    monkeypatch.setattr(worker, "DP_PARSE_MAX_PROCESSES", 3)
    monkeypatch.setattr(worker, "DP_PARSE_MIN_PROCESSES", 1)
    monkeypatch.setattr(worker, "DP_PARSE_MAX_TASKS_PER_CHILD", 1000)
    monkeypatch.setattr(worker, "_validate_parser_config", lambda: None)
    monkeypatch.setattr(worker, "sys", type("Sys", (), {"stdout": MagicMock(), "exit": MagicMock()}))

    worker.start_worker()

    assert "--pool=prefork" in captured["args"]
    assert "--autoscale=3,1" in captured["args"]
    assert "--max-tasks-per-child=1000" in captured["args"]


def test_non_parser_worker_arguments_use_threads(monkeypatch):
    from data_process import worker

    captured = {}

    class FakeApp:
        def worker_main(self, args):
            captured["args"] = args

    monkeypatch.setattr(worker, "app", FakeApp())
    monkeypatch.setattr(worker, "QUEUES", "forward_q")
    monkeypatch.setattr(worker, "WORKER_NAME", "forward")
    monkeypatch.setattr(worker, "WORKER_CONCURRENCY", 4)
    monkeypatch.setattr(worker, "_validate_parser_config", lambda: None)

    worker.start_worker()

    assert "--pool=threads" in captured["args"]
    assert "--concurrency=4" in captured["args"]
    assert not any(arg.startswith("--autoscale=") for arg in captured["args"])
