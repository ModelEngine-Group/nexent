# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared Elasticsearch mappings, physical routing and snapshot iteration."""

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime

from elasticsearch import Elasticsearch, NotFoundError

from ops.monitoring.contracts import MonitoringKind


FACTS = "monitoring-facts"
DAILY = "monitoring-daily"
COMMON = {
    **dict.fromkeys(("tenant_id", "fact_kind", "group_snapshot_state", "group_key",
                     "skill_id", "skill_name", "trigger_kind"), "keyword"),
    "initiator_group_ids": "integer", "agent_id": "integer",
}
FACT_FIELDS = {
    **COMMON,
    **dict.fromkeys(("fact_id", "call_context_id", "root_run_id", "agent_run_id", "usage_source",
                     "outcome"), "keyword"),
    **dict.fromkeys(("partition_anchor_at", "started_at", "ended_at", "triggered_at"), "date"),
    **dict.fromkeys(("record_revision", "write_version", "duration_ms"), "long"),
    "contract_version": "integer",
}
DAILY_FIELDS = {**COMMON, "publish_id": "keyword"}


def mapping(fields: Mapping[str, str]) -> dict:
    return {"dynamic": "strict", "properties": {
        **{name: {"type": field_type} for name, field_type in fields.items()},
        "statistic_date": {"type": "date", "format": "strict_date"},
    }}


def install_templates(es: Elasticsearch, replicas: int, kinds: Iterable[MonitoringKind]) -> None:
    facts, daily = dict(FACT_FIELDS), dict(DAILY_FIELDS)
    for kind in kinds:
        for fields, additions in ((facts, kind.fact_fields), (daily, kind.daily_fields)):
            for name, field_type in additions.items():
                if name == "statistic_date" or fields.get(name, field_type) != field_type:
                    raise ValueError(f"Incompatible monitoring mapping for {name}")
                fields[name] = field_type
    for prefix, fields in ((FACTS, facts), (DAILY, daily)):
        es.indices.put_index_template(
            name=prefix, index_patterns=[f"{prefix}-*"], priority=200,
            template={"settings": {"number_of_shards": 1, "number_of_replicas": replicas},
                      "mappings": mapping(fields)},
        )
        indexes = list(es.indices.get(index=f"{prefix}-*", allow_no_indices=True))
        if indexes:
            es.indices.put_mapping(index=indexes, **mapping(fields))


def partition(prefix: str, day: date | datetime) -> str:
    return f"{prefix}-{day:%Y.%m}"


def existing_fact(es: Elasticsearch, index: str, doc_id: str) -> dict | None:
    try:
        return es.get(index=index, id=doc_id)["_source"]
    except NotFoundError:
        return None


def bulk_write(es: Elasticsearch, writes: list[dict], *, external: bool) -> None:
    if not writes:
        return
    operations = []
    for write in writes:
        action = {"_index": write["index"], "_id": write["id"]}
        if external:
            action.update(version=write["document"]["write_version"], version_type="external")
        operations.extend(({"index": action}, write["document"]))
    result = es.bulk(operations=operations, refresh="wait_for")
    conflicted_indexes = set()
    if len(result["items"]) != len(writes):
        raise RuntimeError("Invalid Elasticsearch bulk result")
    for entry, write in zip(result["items"], writes, strict=True):
        item = entry["index"]
        if 200 <= item["status"] < 300 and not item.get("_shards", {}).get("failed"):
            continue
        if (external and item["status"] == 409 and
                existing_fact(es, write["index"], write["id"]) == write["document"]):
            conflicted_indexes.add(write["index"])
            continue
        raise RuntimeError("Monitoring bulk item failed")
    if conflicted_indexes:
        response = es.indices.refresh(index=sorted(conflicted_indexes))
        if response["_shards"]["failed"]:
            raise RuntimeError("Monitoring shard refresh failed")


def delete_documents(es: Elasticsearch, hits: Iterator[dict]) -> None:
    """Delete only the document IDs captured by the cleanup snapshot."""
    operations = []
    for hit in hits:
        operations.append({"delete": {"_index": hit["_index"], "_id": hit["_id"]}})
        if len(operations) == 500:
            _bulk_delete(es, operations)
            operations.clear()
    if operations:
        _bulk_delete(es, operations)


def _bulk_delete(es: Elasticsearch, operations: list[dict]) -> None:
    result = es.bulk(operations=operations)
    if len(result["items"]) != len(operations):
        raise RuntimeError("Invalid monitoring deletion result")
    for entry in result["items"]:
        item = entry["delete"]
        if item["status"] not in {200, 404} or item.get("_shards", {}).get("failed"):
            raise RuntimeError("Monitoring bulk deletion failed")


class PointInTime:
    def __init__(self, client: Elasticsearch, pit_id: str):
        self.client = client
        self.id = pit_id

    def documents(self, query: dict) -> Iterator[dict]:
        for hit in self.hits(query):
            yield hit["_source"]

    def hits(self, query: dict, *, source: bool = True) -> Iterator[dict]:
        after = None
        while True:
            response = self.client.search(
                pit={"id": self.id, "keep_alive": "2m"}, query=query, sort=["_shard_doc"],
                search_after=after, size=500, source=source, allow_partial_search_results=False,
            )
            self.id = response.get("pit_id", self.id)
            if response["timed_out"] or response["_shards"]["failed"]:
                raise RuntimeError("Incomplete monitoring search")
            hits = response["hits"]["hits"]
            if not hits:
                return
            yield from hits
            after = hits[-1]["sort"]


@contextmanager
def snapshot(es: Elasticsearch, indexes: str):
    response = es.open_point_in_time(index=indexes, keep_alive="2m")
    if response.get("_shards", {}).get("failed"):
        es.close_point_in_time(id=response["id"])
        raise RuntimeError("Incomplete monitoring point in time")
    with_point = PointInTime(es, response["id"])
    try:
        yield with_point
    finally:
        es.close_point_in_time(id=with_point.id)


def filters(**terms: str | int | Iterable[str | int]) -> dict:
    return {"bool": {"filter": [
        {"term": {key: value}} if isinstance(value, (str, int)) else {"terms": {key: list(value)}}
        for key, value in terms.items()
    ]}}
