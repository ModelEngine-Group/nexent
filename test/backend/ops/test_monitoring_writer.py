# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Batch replay, publication visibility and pinned cleanup contracts."""

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from elasticsearch import NotFoundError

from infrastructure.monitoring.facts import ModelFact, SkillFact
from ops.monitoring import service
from ops.monitoring.contracts import MonitoringKind
from ops.monitoring.model import MODEL_MONITORING, SKILL_MONITORING


DAY = date(2026, 11, 23)


def payload(**changes):
    return {"tenant_id": "t", "fact_kind": "model", "fact_id": "f", "call_context_id": "r",
            "model_type": "llm", "started_at": "2026-11-23T00:00:00Z",
            "record_revision": 1, "outcome": "started", **changes}


@pytest.fixture
def writer(mocker):
    store, es = MagicMock(), MagicMock()
    instance = service.Monitoring(store, es, ZoneInfo("UTC"), {"model": MODEL_MONITORING, "skill": SKILL_MONITORING})
    store.next_batch.return_value = None
    store.dirty_days.return_value = [(DAY, 7)]
    mocker.patch.object(service, "existing_fact", return_value=None)
    return instance


def test_stage_coalesces_attempt_revisions_and_retains_original_write_version(writer):
    staged = writer._stage({"write_version": 42, "replay_payload": [payload(), payload(
        record_revision=2, outcome="succeeded", duration_ms=1000,
        ended_at="2026-11-23T00:00:01Z", input_tokens=3)]}, "model", "t")
    assert len(staged["writes"]) == 1
    row = staged["writes"][0]
    assert row["index"] == "monitoring-facts-2026.11"
    assert row["document"]["outcome"] == "succeeded"
    assert row["document"]["input_tokens"] == 3
    assert row["document"]["write_version"] == 42
    assert staged["coverage"] == {"2026-11-23": "2026-11-23T00:00:00+00:00"}


def test_stage_marks_both_old_and_new_statistic_dates(writer, mocker):
    previous = ModelFact.model_validate(payload()).document(writer.zone)
    previous.update(statistic_date="2026-11-22", write_version=4)
    mocker.patch.object(service, "existing_fact", return_value=previous)
    staged = writer._stage({"write_version": 5, "replay_payload": [payload(record_revision=2)]}, "model", "t")
    assert set(staged["coverage"]) == {"2026-11-22", "2026-11-23"}


@pytest.mark.parametrize("previous_revision", [1, 2])
def test_stage_ignores_identical_or_older_revision(writer, mocker, previous_revision):
    previous = ModelFact.model_validate(payload(record_revision=previous_revision)).document(writer.zone)
    previous["write_version"] = 4
    mocker.patch.object(service, "existing_fact", return_value=previous)
    assert writer._stage({"write_version": 5, "replay_payload": [payload()]}, "model", "t") == {
        "writes": [], "coverage": {}}


def test_stage_rejects_cross_tenant_batch(writer):
    with pytest.raises(ValueError, match="scope"):
        writer._stage({"write_version": 1, "replay_payload": [payload(tenant_id="other")]}, "model", "t")


def test_stage_merges_skill_duplicate_using_earliest_trigger(writer, mocker):
    skill_payload = {"tenant_id": "t", "fact_kind": "skill", "fact_id": "skill-use",
                     "call_context_id": "run", "started_at": "2026-11-23T00:00:00Z",
                     "triggered_at": "2026-11-23T01:00:00Z", "trigger_kind": "script_started",
                     "skill_id": "7", "skill_name": "summarize", "record_revision": 1,
                     "outcome": "succeeded"}
    previous = SkillFact.model_validate({**skill_payload, "triggered_at": "2026-11-23T02:00:00Z"}).document(writer.zone)
    mocker.patch.object(service, "existing_fact", return_value=previous)
    staged = writer._stage({"write_version": 5, "replay_payload": [skill_payload]}, "skill", "t")
    assert staged["writes"][0]["document"]["trigger_kind"] == "script_started"
    assert staged["writes"][0]["document"]["record_revision"] == 2


def test_stage_merges_out_of_order_sdk_skill_fact_without_changing_identity(writer, mocker):
    previous_payload = {"tenant_id": "t", "fact_kind": "skill", "fact_id": "skill-use",
                        "call_context_id": "run", "started_at": "2026-11-23T02:00:00Z",
                        "triggered_at": "2026-11-23T02:01:00Z", "trigger_kind": "guide_read",
                        "skill_id": "7", "skill_name": "summarize", "record_revision": 1,
                        "outcome": "succeeded"}
    incoming_payload = {**previous_payload, "started_at": "2026-11-23T01:00:00Z",
                        "triggered_at": "2026-11-23T01:01:00Z", "trigger_kind": "script_started"}
    previous = SkillFact.model_validate(previous_payload).document(writer.zone)
    mocker.patch.object(service, "existing_fact", return_value=previous)

    staged = writer._stage({"write_version": 5, "replay_payload": [incoming_payload]}, "skill", "t")

    document = staged["writes"][0]["document"]
    assert document["started_at"] == previous["started_at"]
    assert document["triggered_at"] == "2026-11-23T01:01:00Z"
    assert document["trigger_kind"] == "script_started"
    assert document["record_revision"] == 2


def test_stage_skips_skill_duplicate_when_existing_trigger_is_earlier(writer, mocker):
    skill_payload = {"tenant_id": "t", "fact_kind": "skill", "fact_id": "skill-use",
                     "call_context_id": "run", "started_at": "2026-11-23T00:00:00Z",
                     "triggered_at": "2026-11-23T02:00:00Z", "trigger_kind": "script_started",
                     "skill_id": "7", "skill_name": "summarize", "record_revision": 1,
                     "outcome": "succeeded"}
    previous = SkillFact.model_validate({**skill_payload, "triggered_at": "2026-11-23T01:00:00Z"}).document(writer.zone)
    mocker.patch.object(service, "existing_fact", return_value=previous)
    assert writer._stage({"write_version": 5, "replay_payload": [skill_payload]}, "skill", "t") == {
        "writes": [], "coverage": {},
    }


def test_queued_batch_is_staged_written_then_confirmed(writer, mocker):
    queued = {"batch_id": "b", "batch_state": "queued", "write_version": 42, "replay_payload": [payload()]}
    pending = {**queued, "batch_state": "pending"}
    events = []

    def stage(conn, batch_id, serialized, days):
        pending["replay_payload"] = json.loads(serialized)
        assert batch_id == "b" and days == [DAY.isoformat()]
        events.append("staged")

    writer.store.stage.side_effect = stage
    writer.store.next_batch.side_effect = [queued, pending]
    mocker.patch.object(service, "bulk_write", side_effect=lambda *a, **kw: events.append("written"))
    writer.store.confirm.side_effect = lambda *a: events.append("confirmed")
    assert writer.apply_batch("t", "model") is True
    assert events == ["staged", "written", "confirmed"]
    assert pending["replay_payload"]["writes"][0]["document"]["write_version"] == 42
    writer.store.batch_failed.assert_not_called()


def test_pending_batch_retries_exact_staged_payload_and_never_confirms_failed_write(writer, mocker):
    staged = writer._stage({"write_version": 42, "replay_payload": [payload()]}, "model", "t")
    pending = {"batch_id": "b", "batch_state": "pending", "replay_payload": staged}
    writer.store.next_batch.return_value = pending
    bulk = mocker.patch.object(service, "bulk_write", side_effect=[RuntimeError("ES offline"), None])
    with pytest.raises(RuntimeError, match="ES offline"):
        writer.apply_batch("t", "model")
    writer.store.confirm.assert_not_called()
    writer.store.batch_failed.assert_called_once()
    assert writer.store.batch_failed.call_args.args[1:] == ("b", "WRITE_FAILED")
    assert writer.apply_batch("t", "model") is True
    assert bulk.call_args_list[0] == bulk.call_args_list[1]
    writer.store.stage.assert_not_called()
    writer.store.confirm.assert_called_once()


def test_empty_queue_does_not_write_or_confirm(writer, mocker):
    bulk = mocker.patch.object(service, "bulk_write")
    assert writer.apply_batch("t", "model") is False
    bulk.assert_not_called()
    writer.store.confirm.assert_not_called()


def pin_documents(mocker, documents):
    point = MagicMock()
    point.documents.return_value = iter(documents)
    snapshot = mocker.patch.object(service, "snapshot")
    snapshot.return_value.__enter__.return_value = point
    return snapshot, point


def test_publication_reduces_real_facts_and_updates_pointer_only_after_es(writer, mocker):
    fact = ModelFact.model_validate(payload(record_revision=2, outcome="succeeded", input_tokens=3)).document(writer.zone)
    snapshot, point = pin_documents(mocker, [fact])
    writes, events = [], []

    def write(es, rows, *, external):
        assert es is writer.es and external is False
        writes.extend(deepcopy(rows))
        events.append("es")

    mocker.patch.object(service, "bulk_write", side_effect=write)
    writer.store.publish.side_effect = lambda *a: events.append("pointer")
    writer.publish("t", "model")
    assert events == ["es", "pointer"]
    assert len(writes) == 1
    document = writes[0]["document"]
    assert document["request_count"] == 1 and document["input_tokens_sum"] == 3
    assert document["tenant_id"] == "t" and document["fact_kind"] == "model"
    args = writer.store.publish.call_args.args
    assert args[1:4] == ("t", "model", [(DAY, 7)])
    assert str(args[4]) == document["publish_id"]
    assert point.documents.call_args.args[0]["bool"]["filter"] == [
        {"term": {"tenant_id": "t"}}, {"term": {"fact_kind": "model"}},
        {"term": {"usage_source": "formal"}}, {"terms": {"statistic_date": [DAY.isoformat()]}}]
    snapshot.return_value.__exit__.assert_called_once()


def test_failed_publication_keeps_previous_pointer_and_closes_snapshot(writer, mocker):
    snapshot, _ = pin_documents(mocker, [ModelFact.model_validate(payload()).document(writer.zone)])
    mocker.patch.object(service, "bulk_write", side_effect=RuntimeError("ES offline"))
    with pytest.raises(RuntimeError, match="ES offline"):
        writer.publish("t", "model")
    writer.store.publish.assert_not_called()
    snapshot.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("blocked", ["no_reducer", "pending", "no_days"])
def test_publication_without_confirmed_reducible_days_does_not_open_es(writer, mocker, blocked):
    if blocked == "no_reducer":
        writer.kinds = {"model": MonitoringKind(ModelFact)}
    elif blocked == "pending":
        writer.store.next_batch.return_value = {"batch_state": "pending"}
    else:
        writer.store.dirty_days.return_value = []
    snapshot = mocker.patch.object(service, "snapshot")
    writer.publish("t", "model")
    snapshot.assert_not_called()
    writer.store.publish.assert_not_called()


@pytest.mark.parametrize("count", [0, 500, 501])
def test_publication_flushes_bounded_batches_including_empty_days(writer, mocker, count):
    def aggregate(documents):
        for row in documents:
            yield str(row["model_id"]), {"statistic_date": row["statistic_date"], "request_count": 1}

    writer.kinds = {"model": MonitoringKind(ModelFact, aggregate)}
    pin_documents(mocker, [{"model_id": i, "statistic_date": DAY.isoformat()} for i in range(count)])
    sizes = []
    mocker.patch.object(service, "bulk_write", side_effect=lambda es, rows, **kw: sizes.append(len(rows)))
    writer.publish("t", "model")
    assert sizes == ([500, count - 500] if count >= 500 else [count])
    writer.store.publish.assert_called_once()


def test_reducer_cannot_publish_outside_locked_dates(writer, mocker):
    pin_documents(mocker, [ModelFact.model_validate(payload(started_at="2026-11-22T00:00:00Z")).document(writer.zone)])
    bulk = mocker.patch.object(service, "bulk_write")
    with pytest.raises(ValueError, match="outside"):
        writer.publish("t", "model")
    bulk.assert_not_called()
    writer.store.publish.assert_not_called()


@pytest.mark.parametrize("published", [False, True])
def test_query_pins_publication_before_releasing_database_lock(writer, mocker, published):
    events = []
    states = [{"publish_id": "current" if published else None, "published_source_revision": 1}]

    @contextmanager
    def read_states(*args, **kwargs):
        assert kwargs == {"lock": True}
        events.append("locked")
        yield states
        events.append("unlocked")

    @contextmanager
    def snapshot(*args):
        events.append("pinned")
        yield "point"
        events.append("closed")

    writer.store.read_states = read_states
    mocker.patch.object(service, "snapshot", side_effect=snapshot)
    with writer.publication_snapshot("t", "model", DAY, DAY) as (rows, point):
        assert rows == states and point == ("point" if published else None)
        assert events == (["locked", "pinned", "unlocked"] if published else ["locked", "unlocked"])
    if published:
        assert events[-1] == "closed"


def test_cleanup_only_deletes_snapshot_ids_excluding_current_publication(writer, mocker):
    writer.store.published_days.return_value = [(DAY, "current")]
    snapshot, point = pin_documents(mocker, [])
    point.hits.return_value = iter([{"_index": "daily", "_id": "obsolete"}])
    deleted = []
    mocker.patch.object(service, "delete_documents", side_effect=lambda es, hits: deleted.extend(hits))
    writer.cleanup("t", "model")
    assert deleted == [{"_index": "daily", "_id": "obsolete"}]
    query = point.hits.call_args.args[0]["bool"]
    assert point.hits.call_args.kwargs == {"source": False}
    assert query["should"] == [{"bool": {"filter": [{"term": {"statistic_date": DAY.isoformat()}}],
                                           "must_not": [{"term": {"publish_id": "current"}}]}}]
    assert query["minimum_should_match"] == 1
    assert {"term": {"tenant_id": "t"}} in query["filter"]
    assert {"term": {"fact_kind": "model"}} in query["filter"]
    assert {"exists": {"field": "publish_id"}} in query["filter"]
    snapshot.return_value.__exit__.assert_called_once()


def test_cleanup_empty_catalog_never_queries_es(writer, mocker):
    writer.store.published_days.return_value = []
    snapshot = mocker.patch.object(service, "snapshot")
    writer.cleanup("t", "model")
    snapshot.assert_not_called()


def test_cleanup_missing_index_keeps_publication_and_does_not_delete(writer, mocker):
    writer.store.published_days.return_value = [(DAY, "current")]
    mocker.patch.object(service, "snapshot", side_effect=NotFoundError(
        "missing", meta=MagicMock(status=404), body={}))
    delete = mocker.patch.object(service, "delete_documents")
    writer.cleanup("t", "model")
    delete.assert_not_called()
    writer.store.publish.assert_not_called()


@pytest.mark.parametrize("field", ["tenant_id", "fact_kind", "fact_id", "started_at", "call_context_id"])
def test_revision_rejects_changes_to_attempt_identity(writer, field):
    document = ModelFact.model_validate(payload()).document(writer.zone)
    with pytest.raises(ValueError, match="identity changed"):
        service._apply_revision({**document, field: "other"}, document)
