# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent Token projections of independently published model request usage."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from ops.monitoring.model import TOKEN_FIELDS, summarize
from ops.monitoring.query import (_publication_status, _read_published_rows, agent_catalog_tenants, days_inclusive,
                                  group_scope_ids)


@dataclass
class AgentTokenUsage:
    tokens: dict
    status: dict
    agents: dict
    days: dict


def _token_values(rows, status):
    if not rows and status["coverage_state"] != "covered":
        return dict.fromkeys(TOKEN_FIELDS)
    values = summarize(rows)
    return {field: values[field] for field in TOKEN_FIELDS}


def read_agent_tokens(service, *, tenant, start, end, groups, agent_id, identities=None, resource_group=None):
    """Count each attributed model request under its actual Agent and start date."""
    scoped = group_scope_ids(tenant, "agent", resource_group) if resource_group is not None else None
    rows, states, published = _read_published_rows(
        service, tenant=tenant, kind="model", start=start, end=end,
        initiator_group_ids=groups, agent_id=agent_id, has_agent_run=True, exclude_system_agents=True,
        **({"resource_scope": ("agent_id", scoped)} if scoped is not None else {}),
    )
    rows = [row for row in rows if row.get("agent_id") is not None and row.get("has_agent_run")]
    identities = None if identities is None else set(identities)
    if tenant is not None:
        tenants = {tenant}
    elif identities is None:
        tenants = agent_catalog_tenants(agent_id)
    else:
        tenants = {key[0] for key in identities}
    tenants.update(row["tenant_id"] for row in rows)
    states = [state for state in states if state["tenant_id"] in tenants]
    published = [state for state in published if state["tenant_id"] in tenants]
    starts = service.store.coverage_starts(tenants, "model") if published else {}
    failures = service.store.failed_batch_tenants(tenants, "model", start, end)
    by_agent = defaultdict(list)
    by_day = defaultdict(list)
    for row in rows:
        by_agent[row["tenant_id"], row["agent_id"]].append(row)
        by_day[date.fromisoformat(row["statistic_date"])].append(row)

    def publication(scopes, first, last):
        selected = [state for state in states if state["tenant_id"] in scopes
                    and first <= state["statistic_date"] <= last]
        return _publication_status(
            service, kind="model", start=first, end=last, tenants=scopes, states=selected,
            published=[state for state in selected if state["publish_id"]],
            write_failed=bool(scopes & failures), coverage_starts=starts,
        )

    status = publication(tenants, start, end)
    tenant_status = {scope: publication({scope}, start, end) for scope in tenants}
    agents = {}
    for key in set(by_agent) | (identities or set()):
        selected_status = tenant_status[key[0]]
        agents[key] = {"tokens": _token_values(by_agent[key], selected_status), "token_status": selected_status}
    days = {}
    for day in days_inclusive(start, end):
        selected_status = publication(tenants, day, day)
        days[day] = {"tokens": _token_values(by_day[day], selected_status), "token_status": selected_status}
    return AgentTokenUsage(_token_values(rows, status), status, agents, days)
