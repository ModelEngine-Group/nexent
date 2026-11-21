# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology rule routes."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.apps.aidp_ontology_common import (
    _rule_summary,
)
from ext_components.aidp.apps.aidp_ontology_models import (
    OntologyRulePayload,
)
from ext_components.aidp.apps.aidp_ontology_validation import (
    _domain_id_path,
    _require_ontology_manager,
)
from ext_components.aidp.services.aidp_ontology_rule_service import (
    count_ontology_rules_impl,
    create_ontology_rule_impl,
    delete_ontology_rule_impl,
    get_ontology_rule_impl,
    list_ontology_rules_impl,
    update_ontology_rule_impl,
)


logger = logging.getLogger("aidp_ontology_rule_routes")
aidp_ontology_rule_router = APIRouter()


@aidp_ontology_rule_router.get("/domains/{domain_id}/rules")
async def list_ontology_rules(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    enabled_only: Annotated[bool, Query()] = False,
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-rule-list",
        list_ontology_rules_impl,
        server_url,
        api_key,
        domain_id,
        page=page,
        size=size,
        enabled_only=enabled_only,
        lane="control-io",
        owner="config",
    )
    result["value"] = [_rule_summary(item) for item in result["value"]]
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_ontology_rule_router.get("/domains/{domain_id}/rules/count")
async def count_ontology_rules(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    count = await run_blocking(
        "aidp-ontology-rule-count",
        count_ontology_rules_impl,
        server_url,
        api_key,
        domain_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"count": count})


@aidp_ontology_rule_router.put("/domains/{domain_id}/rules")
async def create_ontology_rule(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyRulePayload,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-rule-create",
        create_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        body.model_dump(exclude_none=True),
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_rule_summary(result))


@aidp_ontology_rule_router.get("/domains/{domain_id}/rules/{rule_id}")
async def get_ontology_rule(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    rule_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-rule-get",
        get_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        rule_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_rule_summary(result))


@aidp_ontology_rule_router.patch("/domains/{domain_id}/rules/{rule_id}")
async def update_ontology_rule(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    rule_id: Annotated[str, Path(..., min_length=1, max_length=64)],
    body: OntologyRulePayload,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-rule-update",
        update_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        rule_id,
        body.model_dump(exclude_none=True),
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_rule_summary(result))


@aidp_ontology_rule_router.delete("/domains/{domain_id}/rules/{rule_id}")
async def delete_ontology_rule(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    rule_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    await run_blocking(
        "aidp-ontology-rule-delete",
        delete_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        rule_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})
