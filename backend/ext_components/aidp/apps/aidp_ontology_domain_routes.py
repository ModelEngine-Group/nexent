# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology domain, entity and relation routes."""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from contracts.errors.exceptions import AppException
from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.apps.aidp_ontology_common import (
    _binding_count,
    _domain_summary,
    _enrich_entity_rows,
    _entity_summary,
    _optional_count,
    _reconcile_entity_relations,
)
from ext_components.aidp.apps.aidp_ontology_models import (
    OntologyDomainRequest,
    OntologyDomainUpdateRequest,
    OntologyEntityCreateRequest,
    OntologyEntityUpdateRequest,
    OntologyRelationRequest,
)
from ext_components.aidp.apps.aidp_ontology_validation import (
    _bad_request,
    _domain_id_path,
    _require_ontology_manager,
)
from ext_components.aidp.services.aidp_ontology_binding_service import (
    list_ontology_bindings_impl,
)
from ext_components.aidp.services.aidp_ontology_domain_service import (
    create_ontology_domain_impl,
    create_ontology_entity_impl,
    create_ontology_relation_impl,
    delete_ontology_domain_impl,
    delete_ontology_entity_impl,
    delete_ontology_relation_impl,
    get_ontology_domain_impl,
    get_ontology_entity_impl,
    list_ontology_domains_impl,
    list_ontology_entities_impl,
    list_ontology_relations_impl,
    update_ontology_domain_impl,
    update_ontology_entity_impl,
)
from ext_components.aidp.services.aidp_ontology_metadata_service import (
    list_ontology_metadata_fields_impl,
)


logger = logging.getLogger("aidp_ontology_domain_routes")
aidp_ontology_domain_router = APIRouter()


@aidp_ontology_domain_router.get("/domains")
async def list_ontology_domains(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=128)] = None,
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-ontology-domain-list",
        list_ontology_domains_impl,
        server_url,
        api_key,
        page=page,
        page_size=page_size,
        search=search,
        lane="control-io",
        owner="config",
    )
    domains = envelope["value"]
    if domains:
        # AIDP has no all-bindings endpoint; resolve the trusted count per
        # visible domain. Failures degrade that one row to "—" instead of
        # blocking the page.
        server_url, api_key = _credentials()
        semaphore = asyncio.Semaphore(5)

        async def load_count(item: dict[str, Any]) -> int | None:
            raw_id = item.get("od_id") or item.get("domain_id") or item.get("id")
            if raw_id is None:
                return None
            async with semaphore:
                try:
                    rows = await run_blocking(
                        "aidp-ontology-binding-count-row",
                        list_ontology_bindings_impl,
                        server_url,
                        api_key,
                        domain_id=str(raw_id),
                        lane="control-io",
                        owner="config",
                    )
                    return len(rows)
                except AppException as error:
                    logger.warning(
                        "AIDP binding count unavailable for domain %s: %s",
                        raw_id,
                        error,
                    )
                    return None

        counts = await asyncio.gather(*(load_count(item) for item in domains))
        envelope["value"] = [
            _domain_summary(item, count) for item, count in zip(domains, counts)
        ]
    else:
        envelope["value"] = []
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_domain_router.post("/domains")
async def create_ontology_domain(
    request: Request,
    body: OntologyDomainRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-domain-create",
        create_ontology_domain_impl,
        server_url,
        api_key,
        {"name": body.name, "description": body.description},
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_domain_summary(result, 0))


@aidp_ontology_domain_router.get("/domains/{domain_id}")
async def get_ontology_domain(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()

    async def load_entity_count() -> int | None:
        try:
            envelope = await run_blocking(
                "aidp-ontology-domain-entity-count",
                list_ontology_entities_impl,
                server_url,
                api_key,
                domain_id,
                page=1,
                page_size=1,
                lane="control-io",
                owner="config",
            )
            return _optional_count(envelope.get("total_count"))
        except AppException as error:
            logger.warning("AIDP entity count unavailable for %s: %s", domain_id, error)
            return None

    async def load_metadata_count() -> int | None:
        try:
            envelope = await run_blocking(
                "aidp-ontology-domain-metadata-count",
                list_ontology_metadata_fields_impl,
                server_url,
                api_key,
                domain_id,
                page=1,
                page_size=1,
                lane="control-io",
                owner="config",
            )
            return _optional_count(envelope.get("total_count"))
        except AppException as error:
            logger.warning(
                "AIDP metadata count unavailable for %s: %s", domain_id, error
            )
            return None

    result, count, entity_count, metadata_count = await asyncio.gather(
        run_blocking(
            "aidp-ontology-domain-get",
            get_ontology_domain_impl,
            server_url,
            api_key,
            domain_id,
            lane="control-io",
            owner="config",
        ),
        _binding_count(domain_id),
        load_entity_count(),
        load_metadata_count(),
    )
    summary = _domain_summary(result, count)
    # The single-domain GET has no counts; fill them best-effort from list
    # totals so the detail header can show real numbers instead of "—".
    summary["metadata_count"] = metadata_count
    summary["entity_count"] = entity_count
    return JSONResponse(status_code=HTTPStatus.OK, content=summary)


@aidp_ontology_domain_router.patch("/domains/{domain_id}")
async def update_ontology_domain(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyDomainUpdateRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    payload = body.model_dump(exclude_none=True)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-domain-update",
        update_ontology_domain_impl,
        server_url,
        api_key,
        domain_id,
        payload,
        lane="control-io",
        owner="config",
    )
    count = await _binding_count(domain_id)
    return JSONResponse(
        status_code=HTTPStatus.OK, content=_domain_summary(result, count)
    )


@aidp_ontology_domain_router.delete("/domains/{domain_id}")
async def delete_ontology_domain(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    success = await run_blocking(
        "aidp-ontology-domain-delete",
        delete_ontology_domain_impl,
        server_url,
        api_key,
        domain_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})


@aidp_ontology_domain_router.get("/domains/{domain_id}/entities")
async def list_ontology_entities(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    size: Annotated[int | None, Query(ge=1, le=100)] = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    kind: Annotated[Literal["type", "entity"] | None, Query()] = None,
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    page_size = size or page_size
    envelope = await run_blocking(
        "aidp-ontology-entity-list",
        list_ontology_entities_impl,
        server_url,
        api_key,
        domain_id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        kind=kind,
        lane="control-io",
        owner="config",
    )
    envelope["value"] = [_entity_summary(item) for item in envelope["value"]]
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_domain_router.post("/domains/{domain_id}/entities")
async def create_ontology_entity(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyEntityCreateRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()

    payload: dict[str, Any] = {
        "kind": body.kind,
        "api_name": body.api_name,
        "display_name": (body.display_name or "").strip() or body.api_name,
        "description": body.description or "",
        "properties": [
            {
                "api_name": item.api_name,
                "data_type": item.data_type or "string",
                "value": item.value if item.value is not None else "",
                **({"range": item.range} if item.range else {}),
            }
            for item in body.properties
        ],
        "primary_properties": body.primary_properties,
    }

    if body.kind == "entity" and body.type_id:
        types = await run_blocking(
            "aidp-ontology-entity-types",
            list_ontology_entities_impl,
            server_url,
            api_key,
            domain_id,
            page=1,
            page_size=100,
            kind="type",
            lane="control-io",
            owner="config",
        )
        type_ids = {
            str(item.get("entity_id") or item.get("id")) for item in types["value"]
        }
        type_names = {str(item.get("api_name")) for item in types["value"]}
        if body.type_id not in type_ids and body.type_id not in type_names:
            raise _bad_request("所属 Type 不存在于当前本体库")
        payload["type_id"] = int(body.type_id)
    parent_ids: list[int] = []
    if body.kind == "entity" and body.parent_entities:
        parent_ids = [int(item) for item in body.parent_entities]
        # type_id already creates the is-a to the assigned type; never create
        # the same endpoint twice through both fields.
        if body.type_id:
            parent_ids = [
                parent_id
                for parent_id in parent_ids
                if str(parent_id) != str(body.type_id)
            ]
    if body.kind == "entity" and body.synonym_entities:
        payload["synonym_entities"] = [int(item) for item in body.synonym_entities]

    result = await run_blocking(
        "aidp-ontology-entity-create",
        create_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        payload,
        lane="control-io",
        owner="config",
    )
    entity_id = result.get("entity_id") or result.get("id") or result.get("type_id")
    # The create contract has no child list, and its auto-created parent links
    # have an empty display_name. Write both relation sets explicitly so an
    # export -> import round trip keeps a valid relation name. A failed
    # writeback must not hide the fact that the entity itself was created.
    relation_error: str | None = None
    if (
        body.kind == "entity"
        and entity_id is not None
        and (parent_ids or body.child_entities)
    ):
        try:
            await _reconcile_entity_relations(
                server_url,
                api_key,
                domain_id,
                str(entity_id),
                "entity",
                parent_ids=[str(item) for item in parent_ids] or None,
                child_ids=body.child_entities or None,
            )
        except Exception as exc:  # noqa: BLE001 - surface a partial success
            logger.warning(
                "AIDP relation writeback failed for entity %s: %s",
                entity_id,
                exc,
            )
            relation_error = str(exc)
    summary = _entity_summary(
        result,
        entity_id=str(entity_id) if entity_id is not None else None,
        kind=body.kind,
    )
    summary["relation_error"] = relation_error
    return JSONResponse(status_code=HTTPStatus.OK, content=summary)


@aidp_ontology_domain_router.get("/domains/{domain_id}/entities/{entity_id}")
async def get_ontology_entity(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    entity_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-entity-get",
        get_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        entity_id,
        lane="control-io",
        owner="config",
    )
    row = dict(result)
    row["entity_id"] = entity_id
    enriched = await _enrich_entity_rows(
        server_url,
        api_key,
        domain_id,
        [row],
        "entity",
        detail_by_id={str(entity_id): result},
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content=_entity_summary(enriched[0], entity_id=entity_id),
    )


@aidp_ontology_domain_router.patch("/domains/{domain_id}/entities/{entity_id}")
async def update_ontology_entity(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    entity_id: Annotated[str, Path(..., min_length=1, max_length=64)],
    body: OntologyEntityUpdateRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    payload = body.model_dump(exclude_none=True)
    parent_ids = payload.pop("parent_entities", None)
    child_ids = payload.pop("child_entities", None)
    synonyms = payload.pop("synonym_entities", None)
    if "properties" in payload:
        payload["properties"] = [
            {
                "api_name": item.get("api_name"),
                "data_type": item.get("data_type") or "string",
                "value": item.get("value") if item.get("value") is not None else "",
                **({"range": item.get("range")} if item.get("range") else {}),
            }
            for item in payload["properties"]
        ]
    if synonyms is not None:
        # AIDP has no synonym write field; synonyms live in a `synonym`
        # property and are replaced together with the other properties.
        properties = [
            item
            for item in payload.get("properties") or []
            if item.get("api_name") != "synonym"
        ]
        if synonyms:
            properties.append(
                {
                    "api_name": "synonym",
                    "data_type": "string",
                    "value": "、".join(str(item) for item in synonyms),
                }
            )
        payload["properties"] = properties
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-entity-update",
        update_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        entity_id,
        payload,
        lane="control-io",
        owner="config",
    )
    await _reconcile_entity_relations(
        server_url,
        api_key,
        domain_id,
        entity_id,
        "entity",
        parent_ids=parent_ids,
        child_ids=child_ids,
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content=_entity_summary(result, entity_id=entity_id),
    )


@aidp_ontology_domain_router.delete("/domains/{domain_id}/entities/{entity_id}")
async def delete_ontology_entity(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    entity_id: Annotated[str, Path(..., min_length=1, max_length=64)],
    kind: Annotated[Literal["type", "entity"] | None, Query()] = None,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    success = await run_blocking(
        "aidp-ontology-entity-delete",
        delete_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        entity_id,
        kind=kind,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})


@aidp_ontology_domain_router.get("/domains/{domain_id}/relations")
async def list_ontology_relations(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=500)] = 100,
    relation_type: Annotated[Literal["is", "is-a"] | None, Query()] = None,
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-ontology-relation-list",
        list_ontology_relations_impl,
        server_url,
        api_key,
        domain_id,
        page=page,
        size=size,
        relation_type=relation_type,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_domain_router.put("/domains/{domain_id}/relations")
async def create_ontology_relation(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyRelationRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-relation-create",
        create_ontology_relation_impl,
        server_url,
        api_key,
        domain_id,
        {
            "api_name": body.api_name,
            "display_name": body.display_name,
            "source_kind": body.source_kind,
            "source_id": int(body.source_id),
            "object_kind": body.object_kind,
            "object_id": int(body.object_id),
        },
        lane="control-io",
        owner="config",
    )
    relation_id = result.get("relation_id") or result.get("id")
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "relation_id": str(relation_id) if relation_id is not None else None,
            "message": result.get("message"),
        },
    )


@aidp_ontology_domain_router.delete("/domains/{domain_id}/relations/{relation_id}")
async def delete_ontology_relation(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    relation_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    success = await run_blocking(
        "aidp-ontology-relation-delete",
        delete_ontology_relation_impl,
        server_url,
        api_key,
        domain_id,
        relation_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})
