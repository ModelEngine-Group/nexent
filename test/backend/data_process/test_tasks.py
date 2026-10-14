"""Focused tests for the Celery parser task boundary."""




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


def test_aggregate_store_chunks_reads_redis_references(monkeypatch):
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
    monkeypatch.setattr(parse_tasks, "ensure_document_not_deleted", lambda **_kwargs: None)
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    result = parse_tasks.aggregate_store_chunks.run(
        [{"part_redis_key": "part-a", "part_index": 0}],
        "final-key",
        source="source",
        index_name="index",
        task_id="aggregate",
    )
    assert result["chunks"] is None
    assert result["chunks_count"] == 1
    assert result["redis_key"] == "final-key"
    assert stored == [("final-key", [{"content": "part-a"}])]
