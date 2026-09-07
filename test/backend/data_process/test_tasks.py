"""Focused tests for the Celery parser task boundary."""

import types

import pytest


def test_parser_task_uses_late_ack_and_rejects_lost_children():
    from data_process.parse_tasks import ParserTask

    assert ParserTask.acks_late is True
    assert ParserTask.reject_on_worker_lost is True


def test_parser_task_payload_contains_object_reference_only():
    from data_process import parse_tasks

    assert parse_tasks.process_part.name == "data_process.tasks.process_part"
    assert parse_tasks.aggregate_store_chunks.name == "data_process.tasks.aggregate_store_chunks"


def test_aggregate_parts_reads_redis_references(monkeypatch):
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
