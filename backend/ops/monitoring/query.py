# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read published monitoring metrics and resource coverage."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from contracts.constants.environment import LOCAL_MCP_SERVER
from infrastructure.rdb.client import get_db_session
from management.db.agent.models import AgentInfo
from management.db.model.models import ModelRecord
from infrastructure.rdb.skill_execution_records import SkillInfo
from management.utils.serialization import convert_string_to_list
from ops.monitoring.agent import summarize_agent
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


def _read_published_rows(service, *, tenant, kind, start, end, **criteria):
    rows = []
    with service.publication_snapshot(tenant, kind, start, end) as (states, point):
        published = [row for row in states if row["publish_id"]]
        if point is not None:
            for offset in range(0, len(published), 250):
                selection = {"bool": {"should": [
                    filters(tenant_id=state["tenant_id"], statistic_date=state["statistic_date"].isoformat(),
                            publish_id=str(state["publish_id"]))
                    for state in published[offset:offset + 250]
                ], "minimum_should_match": 1}}
                constraints = filters(fact_kind=kind, **{name: value for name, value in criteria.items() if value})
                constraints["bool"]["filter"].append(selection)
                rows.extend(point.documents(constraints))
    return rows, states, published


def _publication_status(service, *, kind, start, end, tenants, states, published, write_failed,
                        coverage_starts=None):
    tenants = tenants | {row["tenant_id"] for row in states}
    whole_days = (end - start).days + 1
    coverage = "uncovered"
    if published:
        starts = service.store.coverage_starts(tenants, kind) if coverage_starts is None else coverage_starts
        complete = len(published) == whole_days * len(tenants) and all(
            row["tenant_id"] in starts and starts[row["tenant_id"]] <=
            datetime.combine(row["statistic_date"], time.min, tzinfo=service.zone)
            for row in published
        )
        coverage = "covered" if complete else "partial"
    return {
        "data_as_of": min((row["source_snapshot_at"] for row in published), default=None),
        "coverage_state": coverage,
        "is_stale": write_failed or any(row["source_revision"] != row["published_source_revision"] for row in states),
    }


def read_models(service, *, tenant, start: date, end: date, groups, model_id, model_type):
    write_failed = service.store.has_failed_batches(tenant, "model", start, end)
    rows, states, published = _read_published_rows(
        service, tenant=tenant, kind="model", start=start, end=end,
        initiator_group_ids=groups, model_id=model_id, model_type=model_type,
    )
    available = sorted({row["statistic_date"] for row in published})
    inventory = [row for row in model_catalog(tenant)
                 if (model_id is None or row["model_id"] == model_id)
                 and (model_type is None or row["model_type"] == model_type)]
    tenants = {row["tenant_id"] for row in inventory}
    if tenant is not None:
        tenants.add(tenant)
    status = _publication_status(
        service, kind="model", start=start, end=end, tenants=tenants,
        states=states, published=published, write_failed=write_failed,
    )
    return rows, inventory, available, status


def agent_catalog_tenants(agent_id: int | None) -> set[str]:
    """Find current Agent tenants when checking global coverage."""
    statement = select(AgentInfo.tenant_id).where(
        AgentInfo.delete_flag == "N", AgentInfo.tenant_id.is_not(None),
    ).distinct()
    if agent_id is not None:
        statement = statement.where(AgentInfo.agent_id == agent_id)
    with get_db_session() as session:
        return set(session.scalars(statement))


def read_agents(service, *, tenant, start: date, end: date, groups, agent_id):
    write_failed = service.store.has_failed_batches(tenant, "agent", start, end)
    rows, states, published = _read_published_rows(
        service, tenant=tenant, kind="agent", start=start, end=end,
        initiator_group_ids=groups, agent_id=agent_id,
    )
    if tenant is not None:
        tenants = {tenant}
    else:
        tenants = agent_catalog_tenants(agent_id) if published else set()
    status = _publication_status(
        service, kind="agent", start=start, end=end, tenants=tenants,
        states=states, published=published, write_failed=write_failed,
    )
    values = summarize_agent(rows)
    if not rows and status["coverage_state"] != "covered":
        values = dict.fromkeys(values)
    return values, status


def agent_catalog(tenant: str | None, agent_id: int | None) -> list[dict]:
    """Read current configuration once per Agent, excluding published snapshots."""
    columns = (AgentInfo.tenant_id, AgentInfo.agent_id, AgentInfo.name, AgentInfo.display_name,
               AgentInfo.model_ids, AgentInfo.group_ids, AgentInfo.current_version_no)
    statement = select(*columns).where(
        AgentInfo.delete_flag == "N", AgentInfo.version_no == 0, AgentInfo.tenant_id.is_not(None),
    )
    if tenant is not None:
        statement = statement.where(AgentInfo.tenant_id == tenant)
    if agent_id is not None:
        statement = statement.where(AgentInfo.agent_id == agent_id)
    with get_db_session() as session:
        inventory = [dict(row) for row in session.execute(statement).mappings()]
    for item in inventory:
        item["configured_group_ids"] = convert_string_to_list(item.pop("group_ids"))
    return inventory


def read_agent_views(service, *, tenant, start: date, end: date, groups, agent_id):
    """Join current inventory to one consistent published Agent snapshot."""
    inventory = agent_catalog(tenant, agent_id)
    write_failed = service.store.has_failed_batches(tenant, "agent", start, end)
    rows, states, published = _read_published_rows(
        service, tenant=tenant, kind="agent", start=start, end=end,
        initiator_group_ids=groups, agent_id=agent_id,
    )
    tenants = {item["tenant_id"] for item in inventory} | {state["tenant_id"] for state in states}
    if tenant is not None:
        tenants.add(tenant)
    starts = service.store.coverage_starts(tenants, "agent") if published else {}
    complete = {(state["tenant_id"], state["statistic_date"]) for state in published
                if state["tenant_id"] in starts and starts[state["tenant_id"]] <=
                datetime.combine(state["statistic_date"], time.min, tzinfo=service.zone)}
    all_dates = set(days_inclusive(start, end))
    by_agent = defaultdict(list)
    by_date = defaultdict(list)
    identities = {(item["tenant_id"], item["agent_id"]): {**item, "is_current": True} for item in inventory}
    for row in rows:
        key = row["tenant_id"], row["agent_id"]
        identities.setdefault(key, {"tenant_id": key[0], "agent_id": key[1], "is_current": False})
        by_agent[key].append(row)
        by_date[date.fromisoformat(row["statistic_date"])].append(row)
    items = []
    for key, metadata in identities.items():
        covered = all((key[0], day) in complete for day in all_dates)
        metrics = summarize_agent(by_agent[key]) if covered or key in by_agent else None
        items.append({**metadata, "metrics": metrics})
    published_days = {state["statistic_date"] for state in published}
    history = []
    for day in sorted(all_dates):
        covered = bool(tenants) and all((scope, day) in complete for scope in tenants)
        coverage = "covered" if covered else "partial" if day in published_days else "uncovered"
        values = summarize_agent(by_date[day])
        if not by_date[day] and not covered:
            values = dict.fromkeys(values)
        history.append({"statistic_date": day, **values, "coverage_state": coverage})
    coverage = "uncovered"
    if published:
        coverage = "covered" if len(complete) == len(tenants) * len(all_dates) else "partial"
    status = {
        "data_as_of": min((state["source_snapshot_at"] for state in published), default=None),
        "coverage_state": coverage,
        "is_stale": write_failed or any(state["source_revision"] != state["published_source_revision"] for state in states),
    }
    return items, len(inventory), history, status


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
    """List MCP servers for filter dropdowns, including never-called ones.

    The type here is a coarse container/remote split for display only; fact
    rows carry the authoritative normalized ``mcp_server_type``. The
    tenant-local endpoint hosts built-in and OpenAPI-converted tools but has
    no database record, so it is synthesized from the configuration; it
    carries no numeric id and is selected through ``server_type=builtin``.
    This is a registered-inventory view: the summary endpoint's
    ``service_count`` (servers with published facts) uses a different scope.
    """
    from infrastructure.monitoring.catalog import is_container_record
    from infrastructure.monitoring.contracts import LOCAL_MCP_NAME
    from infrastructure.rdb.mcp_execution_records import McpRecord

    columns = (McpRecord.tenant_id, McpRecord.mcp_id, McpRecord.mcp_name, McpRecord.container_id,
               McpRecord.config_json)
    statement = select(*columns).where(McpRecord.delete_flag == "N")
    if tenant is not None:
        statement = statement.where(McpRecord.tenant_id == tenant)
    with get_db_session() as session:
        records = [dict(row) for row in session.execute(statement).mappings()]
    servers = [{"service_id": record["mcp_id"], "name": record["mcp_name"],
                "type": "container" if is_container_record(record) else "remote"} for record in records]
    if LOCAL_MCP_SERVER:
        servers.append({"service_id": None, "name": LOCAL_MCP_NAME, "type": "builtin"})
    return servers


def mcp_services_by_tenant(tenant: str | None) -> list[dict]:
    """Count registered remote/container MCP servers per tenant for the overview card.

    Registered inventory only: the tenant-local endpoint is intentionally
    excluded because every tenant carries one.
    """
    from infrastructure.rdb.mcp_execution_records import McpRecord

    statement = (select(McpRecord.tenant_id, func.count().label("service_count"))
                 .where(McpRecord.delete_flag == "N").group_by(McpRecord.tenant_id))
    if tenant is not None:
        statement = statement.where(McpRecord.tenant_id == tenant)
    with get_db_session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]

def skill_catalog(tenant: str | None) -> list[dict]:
    columns = (SkillInfo.tenant_id, SkillInfo.skill_id, SkillInfo.skill_name)
    statement = select(*columns).where(SkillInfo.delete_flag != "Y")
    if tenant is not None:
        statement = statement.where(SkillInfo.tenant_id == tenant)
    with get_db_session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]


def read_skills(service, *, tenant, start: date, end: date, groups, skill_id, skill_name):
    write_failed = service.store.has_failed_batches(tenant, "skill", start, end)
    rows, states, published = _read_published_rows(
        service, tenant=tenant, kind="skill", start=start, end=end,
        initiator_group_ids=groups, skill_id=skill_id, skill_name=skill_name,
    )
    available = sorted({row["statistic_date"] for row in published})
    inventory = [dict(row, skill_id=str(row["skill_id"])) for row in skill_catalog(tenant)
                 if (skill_id is None or str(row["skill_id"]) == str(skill_id))
                 and (skill_name is None or row["skill_name"] == skill_name)]
    tenants = {row["tenant_id"] for row in inventory}
    if tenant is not None:
        tenants.add(tenant)
    status = _publication_status(
        service, kind="skill", start=start, end=end, tenants=tenants,
        states=states, published=published, write_failed=write_failed,
    )
    return rows, inventory, available, status


def skill_rows(rows, inventory, *, covered):
    by_skill = defaultdict(list)
    identities = {(row["tenant_id"], row["skill_id"]): row for row in inventory}
    for row in rows:
        raw_skill_id = row.get("skill_id")
        if raw_skill_id is None:
            continue
        key = row["tenant_id"], str(raw_skill_id)
        by_skill[key].append(row)
        identities.setdefault(key, {"tenant_id": key[0], "skill_id": key[1],
                                    "skill_name": row.get("skill_name")})
    result = []
    for key, skill in identities.items():
        usage_rows = by_skill.get(key, ())
        usage_count = sum(row.get("usage_count", 0) for row in usage_rows)
        result.append({**skill, "metrics": {"usage_count": usage_count}
                       if covered or key in by_skill else None})
    return result


def skill_metric_value(row):
    return (row["metrics"] or {}).get("usage_count")
