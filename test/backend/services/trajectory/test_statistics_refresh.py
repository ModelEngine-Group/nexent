# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Refresh exact snapshots through real archive decoding and bounded sample reuse."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from ops.db.trajectory import statistics as database
from ops.services.trajectory.statistics import (
    StatisticsRefresher,
    StatisticsWorker,
    SummaryWorker,
)


@pytest.fixture
def refresh(tmp_path, mocker):
    @contextmanager
    def locked(*_):
        yield True

    mocker.patch.object(database, "scope_lock", locked)
    scope = mocker.patch.object(
        database,
        "read_scope",
        return_value={
            "complete": False,
            "source_revision": 7,
            "computed_revision": 6,
            "next_refresh_at": None,
        },
    )
    mocker.patch.object(
        database, "duration_statistics", return_value={"duration_sample_count": 4}
    )
    rows = mocker.patch.object(
        database,
        "archive_rows",
        return_value=[
            {
                "tenant_id": "t",
                "user_id": "u",
                "conversation_id": 1,
                "agent_id": None,
                "trajectory_id": "run",
            }
        ],
    )
    publish = mocker.patch.object(database, "publish", return_value=True)
    spans = []
    for index, (kind, ttft) in enumerate(
        (("LLM", 0), ("LLM", 10), ("TOOL", 5), ("LLM", None))
    ):
        attrs = {"openinference.span.kind": kind}
        if ttft is not None:
            attrs["llm.ttft_ms"] = str(ttft)
        spans.append(
            {
                "traceId": "a" * 32,
                "spanId": f"{index + 1:016x}",
                "startTimeUnixNano": "1000000000",
                "endTimeUnixNano": "1100000000",
                "attributes": [
                    {"key": k, "value": {"stringValue": v}} for k, v in attrs.items()
                ],
            }
        )
    path = tmp_path / "archive.jsonl"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}))
    run = {
        "confirmed_sha256": "v1",
        "confirmed_bytes": path.stat().st_size,
        "capture_state": "ready",
    }
    store = Mock()
    store.manifest.return_value = {"cleanup_version": 0}
    store._run.return_value = run
    refresher = StatisticsRefresher(store, Mock())

    @contextmanager
    def opened(*_):
        with path.open("rb") as file:
            yield file.fileno(), {}, run

    refresher.projector.archive = Mock()
    refresher.projector.archive.available.return_value = "available"
    refresher.projector.archive.opened.side_effect = opened
    return refresher, scope, rows, publish, run


def test_refresh_publishes_exact_model_quantiles_and_reuses_unchanged_archive(refresh):
    refresher, _, rows, publish, run = refresh
    assert refresher.refresh(["t"], "tenant", "t")
    values = publish.call_args.args[-1]
    assert values == {
        "duration_sample_count": 4,
        "ttft_sample_count": 2,
        "ttft_p50_ms": 5,
        "ttft_p90_ms": 9,
        "ttft_p99_ms": 9.9,
    }
    assert publish.call_args.args[:3] == ("tenant", "t", ["t"])
    assert publish.call_args.args[-2] == 7
    assert refresher.refresh(["t"], "tenant", "t")
    assert refresher.projector.archive.opened.call_count == 1
    rows.return_value[0]["agent_id"] = 7
    run["confirmed_sha256"] = "v2"
    refresher._cache_bytes = 64 * 1024 * 1024
    assert refresher.refresh(["t"], "tenant", "t")
    assert refresher.projector.archive.opened.call_count == 2
    assert list(refresher._cache) == [("run", "v2", 0)]
    assert refresher._cache_bytes == 320


@pytest.mark.parametrize("kind,identity", [("tenant", "t"), ("global", "global")])
def test_fresh_scope_skips_archive_scan_but_expired_scope_refreshes(refresh, kind, identity):
    refresher, scope, rows, publish, _ = refresh
    scope.return_value.update(
        complete=True,
        computed_revision=7,
        next_refresh_at=datetime.now(UTC) + timedelta(days=1),
    )
    assert refresher.refresh(["t"], kind, identity)
    rows.assert_not_called()
    publish.assert_not_called()
    scope.return_value["next_refresh_at"] = datetime.now(UTC) - timedelta(days=1)
    assert refresher.refresh(["t"], kind, identity)
    publish.assert_called_once()


def test_contended_scope_does_not_read_or_publish(refresh, mocker):
    refresher, scope, _, publish, _ = refresh

    @contextmanager
    def busy(*_):
        yield False

    mocker.patch.object(database, "scope_lock", busy)
    assert refresher.refresh(["t"], "tenant", "t") is False
    scope.assert_not_called()
    publish.assert_not_called()


@pytest.mark.parametrize("failure", ["expired", "cancelled", "corrupt"])
def test_failed_refresh_never_publishes_incomplete_statistics(refresh, failure):
    refresher, _, _, publish, _ = refresh
    check = Mock()
    if failure == "expired":
        refresher.projector.archive.available.return_value = "expired"
    elif failure == "cancelled":
        check.side_effect = InterruptedError("stopping")
    else:
        refresher.projector.archive.opened.side_effect = ValueError("invalid archive")
    with pytest.raises((ValueError, InterruptedError)):
        refresher.refresh(["t"], "tenant", "t", check)
    publish.assert_not_called()


def test_no_archives_publishes_empty_ttft_without_discarding_database_durations(
    refresh,
):
    refresher, _, rows, publish, _ = refresh
    rows.return_value = []
    assert refresher.refresh([], "global", "global")
    values = publish.call_args.args[-1]
    assert values["duration_sample_count"] == 4
    assert values["ttft_sample_count"] == 0 and values["ttft_p99_ms"] is None


def test_summary_queue_limit_allows_replacing_existing_owner(caplog):
    from infrastructure.observability.trajectory_store import CaptureIdentity

    worker = SummaryWorker(Mock(), Mock())
    for index in range(1001):
        worker.notify(CaptureIdentity("t", "u", str(index + 1), "7"))
    assert len(worker._pending) == 1000
    replacement = CaptureIdentity("t", "u", "1", "8")
    worker.notify(replacement)
    assert worker._pending[("t", "u", "1")] is replacement
    assert "trajectory.summary_queue_full" in caplog.text


@pytest.mark.parametrize("error", [PermissionError("revoked"), ValueError("corrupt")])
def test_summary_scan_continues_after_bad_owner_and_waits_before_rescan(mocker, error):
    worker = SummaryWorker(Mock(), Mock())
    worker.store.identities.return_value = iter(["bad", "good"])
    worker.projector.sync = Mock(side_effect=[error, None])
    mocker.patch("ops.services.trajectory.statistics.time.monotonic", return_value=100)
    for _ in range(4):
        worker.tick()
    assert [c.args[0] for c in worker.projector.sync.call_args_list] == ["bad", "good"]
    worker.repository.placeholders.assert_called_once()
    worker.repository.compact.assert_called_once()
    assert worker._iterator is None and worker._next_scan == 160


def test_summary_shutdown_closes_scan_and_checks_stop(caplog):
    worker = SummaryWorker(Mock(), Mock())
    iterator = worker._iterator = Mock()
    worker.tick = Mock(side_effect=RuntimeError("retry"))
    event = Mock()
    event.is_set.side_effect = [False, True]
    worker.run(event)
    iterator.close.assert_called_once()
    event.wait.assert_called_once_with(0.2)
    assert "trajectory.summary_refresh_deferred" in caplog.text
    worker.request_stop()
    with pytest.raises(InterruptedError):
        worker.check()


def test_statistics_loop_retries_after_failure_without_busy_spin(caplog):
    worker = StatisticsWorker(Mock(), Mock())
    worker.tick = Mock(side_effect=RuntimeError("database offline"))
    event = Mock()
    event.is_set.side_effect = [False, True]
    worker.run(event)
    event.wait.assert_called_once_with(60)
    assert "trajectory.statistics_check_deferred" in caplog.text
