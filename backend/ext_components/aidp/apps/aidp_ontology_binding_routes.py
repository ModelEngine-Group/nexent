# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology binding routes (domain list, bind and unbind)."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.apps.aidp_ontology_common import (
    _domain_names,
    _enrich_bindings_sync,
    _load_bindings,
)
from ext_components.aidp.apps.aidp_ontology_models import (
    OntologyBindingRequest,
)
from ext_components.aidp.apps.aidp_ontology_validation import (
    _domain_id_path,
)
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_ontology_binding_service import (
    create_ontology_binding_impl,
    delete_ontology_binding_impl,
)
from ext_components.aidp.services.aidp_ontology_domain_service import (
    get_ontology_domain_impl,
)
from ext_components.aidp.services.aidp_service import get_aidp_kb_impl


logger = logging.getLogger("aidp_ontology_binding_routes")
aidp_ontology_binding_router = APIRouter()


@aidp_ontology_binding_router.get("/bindings")
async def list_all_bindings(request: Request) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    rows = await _load_bindings(user_id, tenant_id)
    names = await _domain_names(tenant_id)
    enriched = await run_blocking(
        "aidp-ontology-binding-enrich",
        _enrich_bindings_sync,
        rows,
        tenant_id,
        names,
        _credentials()[0],
        _credentials()[1],
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "value": enriched,
            "total_count": len(enriched),
            "has_more": False,
            "total_reliable": True,
        },
    )


@aidp_ontology_binding_router.get("/domains/{domain_id}/bindings")
async def list_domain_bindings(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    rows = await _load_bindings(user_id, tenant_id, domain_id=domain_id)
    names = await _domain_names(tenant_id)
    enriched = await run_blocking(
        "aidp-ontology-binding-enrich-domain",
        _enrich_bindings_sync,
        rows,
        tenant_id,
        names,
        _credentials()[0],
        _credentials()[1],
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "value": enriched,
            "total_count": len(enriched),
            "has_more": False,
            "total_reliable": True,
        },
    )


@aidp_ontology_binding_router.post("/domains/{domain_id}/bindings")
@aidp_ontology_binding_router.put("/domains/{domain_id}/bindings")
async def create_domain_binding(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyBindingRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    target_kb_id = body.target_kb_id
    perms.require_permission(target_kb_id, user_id, tenant_id, required="EDIT")

    # One knowledge base can bind either one ontology domain or one jargon
    # library. The KDS detail exposes both through bind_lib_type/bind_lib_id,
    # so the pre-check is one request instead of scanning every domain.
    server_url, api_key = _credentials()
    await run_blocking(
        "aidp-ontology-domain-exists",
        get_ontology_domain_impl,
        server_url,
        api_key,
        domain_id,
        lane="control-io",
        owner="config",
    )
    kb_detail = await run_blocking(
        "aidp-ontology-kb-bind-state",
        get_aidp_kb_impl,
        server_url,
        api_key,
        target_kb_id,
        lane="control-io",
        owner="config",
    )
    bound_type = (
        kb_detail.get("bind_lib_type") if isinstance(kb_detail, dict) else None
    )
    bound_id = kb_detail.get("bind_lib_id") if isinstance(kb_detail, dict) else None
    if bound_type == "jargon":
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="该知识库已绑定术语库，请先解绑术语库再绑定本体库",
        )
    if bound_type == "ontology":
        if str(bound_id) != str(domain_id):
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="该知识库已绑定其他本体库，一个知识库最多绑定一个本体库",
            )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "od_id": domain_id,
                "kds_id": target_kb_id,
                "unchanged": True,
            },
        )

    await run_blocking(
        "aidp-ontology-binding-create",
        create_ontology_binding_impl,
        server_url,
        api_key,
        domain_id=domain_id,
        kds_id=target_kb_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "od_id": domain_id,
            "kds_id": target_kb_id,
            "unchanged": False,
        },
    )


@aidp_ontology_binding_router.delete("/domains/{domain_id}/bindings/{kds_id}")
async def delete_domain_binding(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
) -> JSONResponse:
    """Unbind one knowledge base from this ontology domain.

    AIDP has no BindingId to address a row; the pair (domain_id, kds_id) is the
    confirmed identifier and the unbind route is KB-side.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-binding-delete",
        delete_ontology_binding_impl,
        server_url,
        api_key,
        domain_id=domain_id,
        kds_id=kds_id,
        lane="control-io",
        owner="config",
    )
    task = result.get("tag_clear_task") if isinstance(result, dict) else None
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "success": True,
            "accepted": bool(task),
            "task_id": (task or {}).get("task_id") if isinstance(task, dict) else None,
            "task_type": (task or {}).get("task_type")
            if isinstance(task, dict)
            else None,
        },
    )
