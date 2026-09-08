"""Focused tests for the Celery parser task boundary."""

import types

import pytest


def _configure_celery_environment(monkeypatch):
    """Provide import-time Celery URLs without requiring a local .env file."""
    broker_url = "redis://localhost:6379/0"
    backend_url = "redis://localhost:6379/1"
    monkeypatch.setenv("REDIS_URL", broker_url)
    monkeypatch.setenv("REDIS_BACKEND_URL", backend_url)

    from consts import const as constants

    monkeypatch.setattr(constants, "REDIS_URL", broker_url)
    monkeypatch.setattr(constants, "REDIS_BACKEND_URL", backend_url)


def test_parser_task_uses_late_ack_and_rejects_lost_children(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process.parse_tasks import ParserTask

    assert ParserTask.acks_late is True
    assert ParserTask.reject_on_worker_lost is True


def test_parser_task_payload_contains_object_reference_only(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process import parse_tasks

    assert parse_tasks.process_part.name == "data_process.tasks.process_part"
    assert parse_tasks.aggregate_store_chunks.name == "data_process.tasks.aggregate_store_chunks"


def test_aggregate_parts_reads_redis_references(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process import parse_tasks

    monkeypatch.setattr(
        parse_tasks,
        "load_chunks_from_redis",
        lambda key: [{"content": key}],
    )
    stored = []
    monkeypatch.setattr(
        parse_tasks,
        "store_chunks_atomically",
        lambda key, chunks: stored.append((key, chunks)),
    )
    result = parse_tasks.aggregate_parts.run(
        [{"part_redis_key": "part-a"}, [{"content": "inline"}]],
        marker="ok",
    )
    assert result["chunks"] is None
    assert result["chunks_count"] == 2
    assert result["marker"] == "ok"
    assert result["redis_key"].startswith("dp:")
    assert stored == [(result["redis_key"], [{"content": "part-a"}, {"content": "inline"}])]
