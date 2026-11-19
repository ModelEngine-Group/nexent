# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read published monitoring metrics and current model inventory."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from infrastructure.rdb.client import get_db_session
from management.db.model.models import ModelRecord
from ops.monitoring.model import summarize
from ops.monitoring.search import filters


def days_inclusive(start: date, end: date):
    return (start + timedelta(days=offset) for offset in range((end - start).days + 1))


def model_catalog(tenant: str | None) -> list[dict]:
    columns = (ModelRecord.tenant_id, ModelRecord.model_id, ModelRecord.model_name, ModelRecord.display_name,
               ModelRecord.model_type, ModelRecord.model_factory, ModelRecord.connect_status)
    statement = select(*columns).where(ModelRecord.delete_flag == "N")
    if tenant is not None:
        statement = statement.where(ModelRecord.tenant_id == tenant)
    with get_db_session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]


def read_models(service, *, tenant, start: date, end: date, groups, model_id, model_type):
    write_failed = service.store.has_failed_batches(tenant, "model", start, end)
    rows = []
    with service.publication_snapshot(tenant, "model", start, end) as (states, point):
        published = [row for row in states if row["publish_id"]]
        if point is not None:
            for offset in range(0, len(published), 250):
                selection = {"bool": {"should": [
                    filters(tenant_id=state["tenant_id"], statistic_date=state["statistic_date"].isoformat(),
                            publish_id=str(state["publish_id"]))
                    for state in published[offset:offset + 250]
                ], "minimum_should_match": 1}}
                constraints = filters(fact_kind="model")
                for name, value in (("initiator_group_ids", groups), ("model_id", model_id), ("model_type", model_type)):
                    if value:
                        constraints["bool"]["filter"].extend(filters(**{name: value})["bool"]["filter"])
                constraints["bool"]["filter"].append(selection)
                rows.extend(point.documents(constraints))
    available = sorted({row["statistic_date"] for row in published})
    inventory = [row for row in model_catalog(tenant)
                 if (model_id is None or row["model_id"] == model_id)
                 and (model_type is None or row["model_type"] == model_type)]
    tenants = {row["tenant_id"] for row in inventory} | {row["tenant_id"] for row in states}
    if tenant is not None:
        tenants.add(tenant)
    whole_days = (end - start).days + 1
    coverage = "uncovered"
    if published:
        starts = service.store.coverage_starts(tenants, "model")
        complete = len(published) == whole_days * len(tenants) and all(
            row["tenant_id"] in starts and starts[row["tenant_id"]] <=
            datetime.combine(row["statistic_date"], time.min, tzinfo=service.zone)
            for row in published
        )
        coverage = "covered" if complete else "partial"
    status = {
        "data_as_of": min((row["source_snapshot_at"] for row in published), default=None),
        "coverage_state": coverage,
        "is_stale": write_failed or any(row["source_revision"] != row["published_source_revision"] for row in states),
    }
    return rows, inventory, available, status


def model_rows(rows, inventory, *, covered):
    by_model = defaultdict(list)
    identities = {(model["tenant_id"], model["model_id"]): model for model in inventory}
    for row in rows:
        key = row["tenant_id"], row.get("model_id")
        if key[1] is None:
            continue
        by_model[key].append(row)
        identities.setdefault(key, {"tenant_id": key[0], "model_id": key[1], "model_type": row.get("model_type")})
    return [{**model, "metrics": summarize(by_model[key]) if covered or key in by_model else None}
            for key, model in identities.items()]


def metric_value(row, metric):
    value = (row["metrics"] or {}).get(metric)
    if isinstance(value, dict):
        return int(value["value"]) if value["value"] is not None else None
    return value
