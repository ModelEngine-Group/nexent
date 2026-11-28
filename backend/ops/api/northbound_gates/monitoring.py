# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Northbound gates for the monitoring dashboard (/nb/v1/monitoring).

Per the northbound exposure design (Spring-style double-gate), every exposed
capability gets one hand-written gate under ``/nb/v1/monitoring``. The gates
reuse the internal routes' own machinery verbatim: the path-aware identity
dependency (``ops_principal`` — gateway-verified API key, tenant locked to
the key's owner), the shared selection dependencies (query-parameter
contracts, no re-declaration drift) and the original handler functions
(sorting, pagination, assembly, response body). The envelope middleware
wraps the returned internal body into the published partner envelope.

The gates are declared with ``@nb_exposed``; the offline generator compiles
the declarations into the Gateway exposure snapshot rows.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from contracts.northbound_exposure import nb_exposed
from ops.api.monitoring import (
    AgentMetric,
    AgentSelection,
    Metric,
    OpsPrincipal,
    RefreshSelection,
    Selection,
    ToolMetric,
    ToolSelection,
    agent_rankings,
    agent_selection,
    agent_summary,
    agent_trends,
    agents,
    mcp_tool_refresh_status,
    mcp_tools,
    mcp_tools_catalog,
    mcp_tools_overview,
    mcp_tools_rankings,
    mcp_tools_summary,
    mcp_tools_trends,
    model_refresh_status,
    models,
    nb_action_guard,
    ops_principal,
    ops_scoped_tenant,
    rankings,
    refresh_mcp_tools,
    refresh_models,
    refresh_skills,
    selection,
    skill_rankings,
    skill_refresh_status,
    skill_summary,
    skill_trends,
    skills,
    summary,
    tool_selection,
    trends,
)

nb_monitoring_router = APIRouter(prefix="/nb/v1/monitoring", tags=["northbound-gates"])


@nb_monitoring_router.get("/models")
@nb_exposed("monitoring.models.list")
def nb_models(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str, Query(max_length=100)] = "",
    sort_by: Metric | Literal["name"] = "request_count",
    descending: bool = True,
):
    """List model monitoring for the calling partner's tenant."""
    return models(request, scope, ops_scoped_tenant(principal, scope.tenant_id),
                  page=page, page_size=page_size, search=search,
                  sort_by=sort_by, descending=descending)


@nb_monitoring_router.get("/models/summary")
@nb_exposed("monitoring.models.summary")
def nb_models_summary(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Model monitoring summary for the calling partner's tenant."""
    return summary(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.get("/models/rankings")
@nb_exposed("monitoring.models.rankings")
def nb_models_rankings(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    metric: Literal["request_count", "total_tokens"] = "request_count",
):
    """Top 5 models for the calling partner's tenant."""
    return rankings(request, scope, ops_scoped_tenant(principal, scope.tenant_id), metric=metric)


@nb_monitoring_router.get("/models/trends")
@nb_exposed("monitoring.models.trends")
def nb_models_trends(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Model usage trends for the calling partner's tenant."""
    return trends(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.post("/models/refresh", status_code=202)
@nb_exposed("monitoring.models.refresh")
def nb_models_refresh(
    request: Request,
    scope: RefreshSelection,
    _guard: Annotated[None, Depends(nb_action_guard)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Queue a model monitoring recompute for the calling partner's tenant."""
    return refresh_models(request, scope, principal)


@nb_monitoring_router.get("/models/refreshes/{refresh_id}")
@nb_exposed("monitoring.models.refresh_status")
def nb_models_refresh_status(
    request: Request,
    refresh_id: str,
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Resolve one refresh token issued to the calling partner's tenant."""
    return model_refresh_status(request, refresh_id, principal)


@nb_monitoring_router.get("/skills")
@nb_exposed("monitoring.skills.list")
def nb_skills(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str, Query(max_length=100)] = "",
    descending: bool = True,
    sort_by: Literal["usage_count", "name"] = "usage_count",
):
    """List skill monitoring for the calling partner's tenant."""
    return skills(request, scope, ops_scoped_tenant(principal, scope.tenant_id),
                  page=page, page_size=page_size, search=search,
                  descending=descending, sort_by=sort_by)


@nb_monitoring_router.get("/skills/summary")
@nb_exposed("monitoring.skills.summary")
def nb_skills_summary(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Skill monitoring summary for the calling partner's tenant."""
    return skill_summary(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.get("/skills/rankings")
@nb_exposed("monitoring.skills.rankings")
def nb_skills_rankings(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Top 5 skills for the calling partner's tenant."""
    return skill_rankings(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.get("/skills/trends")
@nb_exposed("monitoring.skills.trends")
def nb_skills_trends(
    request: Request,
    scope: Annotated[Selection, Depends(selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Skill usage trends for the calling partner's tenant."""
    return skill_trends(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.post("/skills/refresh", status_code=202)
@nb_exposed("monitoring.skills.refresh")
def nb_skills_refresh(
    request: Request,
    scope: RefreshSelection,
    _guard: Annotated[None, Depends(nb_action_guard)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Queue a skill monitoring recompute for the calling partner's tenant."""
    return refresh_skills(request, scope, principal)


@nb_monitoring_router.get("/skills/refreshes/{refresh_id}")
@nb_exposed("monitoring.skills.refresh_status")
def nb_skills_refresh_status(
    request: Request,
    refresh_id: str,
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Resolve one refresh token issued to the calling partner's tenant."""
    return skill_refresh_status(request, refresh_id, principal)


@nb_monitoring_router.get("/agents")
@nb_exposed("monitoring.agents.list")
def nb_agents(
    request: Request,
    scope: Annotated[AgentSelection, Depends(agent_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str, Query(max_length=100)] = "",
    sort_by: AgentMetric | Literal["name"] = "execution_count",
    descending: bool = True,
):
    """List agent monitoring for the calling partner's tenant."""
    return agents(request, scope, principal, page=page, page_size=page_size,
                  search=search, sort_by=sort_by, descending=descending)


@nb_monitoring_router.get("/agents/summary")
@nb_exposed("monitoring.agents.summary")
def nb_agents_summary(
    request: Request,
    scope: Annotated[AgentSelection, Depends(agent_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Agent monitoring summary (incl. token usage) for the calling partner's tenant."""
    return agent_summary(request, scope, principal)


@nb_monitoring_router.get("/agents/trends")
@nb_exposed("monitoring.agents.trends")
def nb_agents_trends(
    request: Request,
    scope: Annotated[AgentSelection, Depends(agent_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Agent execution trends for the calling partner's tenant."""
    return agent_trends(request, scope, principal)


@nb_monitoring_router.get("/agents/rankings")
@nb_exposed("monitoring.agents.rankings")
def nb_agents_rankings(
    request: Request,
    scope: Annotated[AgentSelection, Depends(agent_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    metric: Literal["execution_count", "total_tokens", "success_rate"] = "execution_count",
):
    """Top 5 agents for the calling partner's tenant."""
    return agent_rankings(request, scope, principal, metric=metric)


@nb_monitoring_router.get("/mcp-tools")
@nb_exposed("monitoring.mcp_tools.list")
def nb_mcp_tools(
    request: Request,
    scope: Annotated[ToolSelection, Depends(tool_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    dimension: Literal["tools", "services"] = "services",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str, Query(max_length=100)] = "",
    sort_by: ToolMetric | Literal["name"] = "request_count",
    descending: bool = True,
):
    """List MCP tool monitoring (tools/services dimension) for the calling partner's tenant."""
    return mcp_tools(request, scope, ops_scoped_tenant(principal, scope.tenant_id),
                     dimension=dimension, page=page, page_size=page_size,
                     search=search, sort_by=sort_by, descending=descending)


@nb_monitoring_router.get("/mcp-tools/summary")
@nb_exposed("monitoring.mcp_tools.summary")
def nb_mcp_tools_summary(
    request: Request,
    scope: Annotated[ToolSelection, Depends(tool_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """MCP monitoring summary for the calling partner's tenant."""
    return mcp_tools_summary(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.get("/mcp-tools/rankings")
@nb_exposed("monitoring.mcp_tools.rankings")
def nb_mcp_tools_rankings(
    request: Request,
    scope: Annotated[ToolSelection, Depends(tool_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    dimension: Literal["tools", "services"] = "services",
    metric: ToolMetric = "request_count",
):
    """Top 5 MCP tools for the calling partner's tenant."""
    return mcp_tools_rankings(request, scope, ops_scoped_tenant(principal, scope.tenant_id),
                              dimension=dimension, metric=metric)


@nb_monitoring_router.get("/mcp-tools/trends")
@nb_exposed("monitoring.mcp_tools.trends")
def nb_mcp_tools_trends(
    request: Request,
    scope: Annotated[ToolSelection, Depends(tool_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """MCP call trends for the calling partner's tenant."""
    return mcp_tools_trends(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.get("/mcp-tools/catalog")
@nb_exposed("monitoring.mcp_tools.catalog")
def nb_mcp_tools_catalog(
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
    tenant_id: Annotated[str | None, Query(max_length=100)] = None,
    group_ids: Annotated[list[int] | None, Query(max_length=100)] = None,
):
    """MCP service catalog filter options for the calling partner's tenant."""
    return mcp_tools_catalog(principal, tenant_id=tenant_id, group_ids=group_ids)


@nb_monitoring_router.get("/mcp-tools/overview")
@nb_exposed("monitoring.mcp_tools.overview")
def nb_mcp_tools_overview(
    request: Request,
    scope: Annotated[ToolSelection, Depends(tool_selection)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Per-tenant inventory and call trend for the calling partner's tenant."""
    return mcp_tools_overview(request, scope, ops_scoped_tenant(principal, scope.tenant_id))


@nb_monitoring_router.post("/mcp-tools/refresh", status_code=202)
@nb_exposed("monitoring.mcp_tools.refresh")
def nb_mcp_tools_refresh(
    request: Request,
    scope: RefreshSelection,
    _guard: Annotated[None, Depends(nb_action_guard)],
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Queue an MCP monitoring recompute for the calling partner's tenant."""
    return refresh_mcp_tools(request, scope, principal)


@nb_monitoring_router.get("/mcp-tools/refreshes/{refresh_id}")
@nb_exposed("monitoring.mcp_tools.refresh_status")
def nb_mcp_tools_refresh_status(
    request: Request,
    refresh_id: str,
    principal: Annotated[OpsPrincipal, Depends(ops_principal)],
):
    """Resolve one refresh token issued to the calling partner's tenant."""
    return mcp_tool_refresh_status(request, refresh_id, principal)
