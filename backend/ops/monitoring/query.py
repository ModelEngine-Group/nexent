# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read published monitoring metrics and current model inventory."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from management.db.client import get_db_session
from management.db.model.models import ModelRecord
from ops.monitoring.mcp_tool import summarize as summarize_mcp_tool
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


def read_mcp_tools(service, *, tenant, start: date, end: date, groups, server_id, server_type, tool_name):
    """Read published MCP tool daily documents for one tenant window.

    Mirrors ``read_models`` with the ``mcp_tool`` kind; there is no PostgreSQL
    inventory for MCP servers, so rows come only from published daily documents
    and are grouped per (tenant, server identity, tool) entity.
    """
    write_failed = service.store.has_failed_batches(tenant, "mcp_tool", start, end)
    rows = []
    with service.publication_snapshot(tenant, "mcp_tool", start, end) as (states, point):
        published = [row for row in states if row["publish_id"]]
        if point is not None:
            for offset in range(0, len(published), 250):
                selection = {"bool": {"should": [
                    filters(tenant_id=state["tenant_id"], statistic_date=state["statistic_date"].isoformat(),
                            publish_id=str(state["publish_id"]))
                    for state in published[offset:offset + 250]
                ], "minimum_should_match": 1}}
                constraints = filters(fact_kind="mcp_tool")
                for name, value in (("initiator_group_ids", groups), ("mcp_server_id", server_id),
                                    ("mcp_server_type", server_type), ("tool_name", tool_name)):
                    if value:
                        constraints["bool"]["filter"].extend(filters(**{name: value})["bool"]["filter"])
                constraints["bool"]["filter"].append(selection)
                rows.extend(point.documents(constraints))
    available = sorted({row["statistic_date"] for row in published})
    tenants = {row["tenant_id"] for row in states}
    if tenant is not None:
        tenants.add(tenant)
    whole_days = (end - start).days + 1
    coverage = "uncovered"
    if published:
        starts = service.store.coverage_starts(tenants, "mcp_tool")
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
    return rows, available, status


def mcp_tool_rows(rows):
    """Group published MCP daily documents per (tenant, server identity, tool) entity."""
    by_tool = defaultdict(list)
    identities = {}
    for row in rows:
        key = (row["tenant_id"], row.get("mcp_server_id"), row.get("mcp_server_name"),
               row.get("mcp_server_type"), row["tool_name"])
        by_tool[key].append(row)
        identities.setdefault(key, {"tenant_id": key[0], "mcp_server_id": key[1], "mcp_server_name": key[2],
                                    "mcp_server_type": key[3], "tool_name": key[4]})
    return [{**identity, "metrics": summarize_mcp_tool(by_tool[key])} for key, identity in identities.items()]


def mcp_server_rows(rows):
    """Aggregate published MCP daily documents per (tenant, server) for the service view.

    ``active_tools`` counts the distinct tools with calls inside the requested
    window; metric sums merge across the server's tools without rounding.
    """
    by_server = defaultdict(list)
    tools = defaultdict(set)
    identities = {}
    for row in rows:
        key = (row["tenant_id"], row.get("mcp_server_id"), row.get("mcp_server_name"),
               row.get("mcp_server_type"))
        by_server[key].append(row)
        tools[key].add(row["tool_name"])
        identities.setdefault(key, {"tenant_id": key[0], "mcp_server_id": key[1], "mcp_server_name": key[2],
                                    "mcp_server_type": key[3]})
    return [{**identity, "active_tools": len(tools[key]), "metrics": summarize_mcp_tool(by_server[key])}
            for key, identity in identities.items()]


def mcp_server_catalog(tenant: str | None) -> list[dict]:
    """List registered MCP servers for filter dropdowns, including never-called ones.

    The type here is a coarse container/remote split for display only; fact
    rows carry the authoritative normalized ``mcp_server_type``.
    """
    from management.db.mcp.models import McpRecord
    from management.services.mcp.provisioning import _is_container_record

    columns = (McpRecord.tenant_id, McpRecord.mcp_id, McpRecord.mcp_name, McpRecord.container_id,
               McpRecord.config_json)
    statement = select(*columns).where(McpRecord.delete_flag == "N")
    if tenant is not None:
        statement = statement.where(McpRecord.tenant_id == tenant)
    with get_db_session() as session:
        records = [dict(row) for row in session.execute(statement).mappings()]
    return [{"service_id": record["mcp_id"], "name": record["mcp_name"],
             "type": "container" if _is_container_record(record) else "remote"} for record in records]


def mcp_services_by_tenant(tenant: str | None) -> list[dict]:
    """Count registered MCP servers per tenant for the platform overview card."""
    from management.db.mcp.models import McpRecord

    statement = (select(McpRecord.tenant_id, func.count().label("service_count"))
                 .where(McpRecord.delete_flag == "N").group_by(McpRecord.tenant_id))
    if tenant is not None:
        statement = statement.where(McpRecord.tenant_id == tenant)
    with get_db_session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]
