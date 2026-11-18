# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Administrator trajectory directories on the existing conversation URL contract."""

from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from ops.api.trajectory import PrivateRoute, dispatch
from ops.services.trajectory.directory import directory

router = APIRouter(prefix="/conversation", route_class=PrivateRoute)


@router.get("/agent_groups")
async def list_agent_groups_endpoint(
    request: Request,
    authorization: str | None = Header(None),
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    search: Annotated[str, Query(max_length=200)] = "",
    include_agent_id: Annotated[list[int] | None, Query()] = None,
    include_other: bool = False,
    view: Literal["trajectory"] = "trajectory",
    target_user_id: str | None = None,
    tenant_id: str | None = None,
    category: Literal["agent_chat", "workbench"] = "agent_chat",
):
    if "include_agent_id" in request.query_params and (
        len(include_agent_id or ()) > 100
        or any(value <= 0 for value in (include_agent_id or ()))
    ):
        raise HTTPException(status_code=422, detail={"code": "invalid_included_agents"})
    return await dispatch(
        request,
        authorization,
        lambda service, actor: directory(
            service,
            actor,
            target_user_id=target_user_id,
            tenant_id=tenant_id,
            category=category,
            group_key=None,
            limit=limit if "limit" in request.query_params else 20,
            cursor=cursor,
            search=search,
        ),
    )


@router.get("/agent_groups/{group_key}/conversations")
async def list_agent_group_conversations_endpoint(
    request: Request,
    group_key: str,
    authorization: str | None = Header(None),
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    search: Annotated[str, Query(max_length=200)] = "",
    view: Literal["trajectory"] = "trajectory",
    target_user_id: str | None = None,
    tenant_id: str | None = None,
    category: Literal["agent_chat", "workbench"] = "agent_chat",
):
    return await dispatch(
        request,
        authorization,
        lambda service, actor: directory(
            service,
            actor,
            target_user_id=target_user_id,
            tenant_id=tenant_id,
            category=category,
            group_key=group_key,
            limit=limit if "limit" in request.query_params else 20,
            cursor=cursor,
            search=search,
        ),
    )
