# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP ontology, binding and Metadata management endpoints (AIDP-UI-09/10).

Every handler resolves the caller through :func:`_auth`; ontology definition
writes additionally require a management role, while knowledge-base binding and
chunk annotation enforce the target knowledge base's READ/EDIT permission. AIDP
remains the single source of truth: no ontology, binding, field definition or
chunk metadata is stored in the Nexent database.
"""
from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.constants.environment import AIDP_MOCK_MODE
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.apps.aidp_mgmt_app import _auth, _credentials
from ext_components.aidp.database import aidp_permission_db
from ext_components.aidp.services import aidp_ontology_service as ontology_service
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_ontology_transform import (
    OntologyImportValidationError,
    async_task_summary,
    build_import_request,
    is_async_task_payload,
    normalize_export_result,
    normalize_import_errors,
    normalize_import_result,
    sanitize_export_filename,
)
from ext_components.aidp.services.aidp_service import get_aidp_kb_impl
from management.db.identity.user_tenant import get_user_role_by_tenant


logger = logging.getLogger("aidp_ontology_app")

aidp_ontology_router = APIRouter(prefix="/aidp-mgmt/ontology", tags=["aidp-ontology"])

_DOMAIN_NAME_MAX_BYTES = 64
_DOMAIN_DESCRIPTION_MAX_BYTES = 512
_METADATA_FIELD_NAME_MAX_CHARS = 63
_METADATA_FIELD_NAME_MAX_BYTES = 64
_ENTITY_NAME_MAX_CHARS = 64
_ENTITY_DESCRIPTION_MAX_CHARS = 512


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _bad_request(message: str, errors: list[dict[str, Any]] | None = None) -> AppException:
    return AppException(
        ErrorCode.COMMON_PARAMETER_INVALID,
        message,
        details={"errors": errors} if errors else None,
    )


def _forbidden(message: str) -> AppException:
    return AppException(ErrorCode.COMMON_FORBIDDEN, message)


def _require_ontology_manager(user_id: str, tenant_id: str) -> None:
    """Only existing management roles may change ontology definitions.

    Knowledge-base binding and chunk annotation are gated separately by the
    target KB permission so a KB owner can bind or annotate without acquiring
    platform-wide ontology rights.
    """
    role = (get_user_role_by_tenant(user_id, tenant_id) or "USER").upper()
    if role not in CAN_EDIT_ALL_USER_ROLES:
        raise _forbidden("当前用户没有本体库管理权限")


def _clean_required(value: Any, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _bad_request(message)
    return value.strip()


def _validate_domain_name(value: str) -> str:
    name = _clean_required(value, "本体库名称不能为空")
    if _utf8_size(name) > _DOMAIN_NAME_MAX_BYTES:
        raise _bad_request(f"本体库名称不能超过 {_DOMAIN_NAME_MAX_BYTES} 字节")
    return name


def _validate_domain_description(value: str | None) -> str:
    description = (value or "").strip()
    if _utf8_size(description) > _DOMAIN_DESCRIPTION_MAX_BYTES:
        raise _bad_request(f"本体库描述不能超过 {_DOMAIN_DESCRIPTION_MAX_BYTES} 字节")
    return description


def _validate_field_name(value: str, *, message: str = "字段名不能为空") -> str:
    """Apply the conservative AIDP field-name limits.

    The documentation states an upper bound of 64 but also notes that the
    deployed check rejects ``len() >= 64``, so the usable limit is 63
    characters. A separate 64-byte key limit applies to non-ASCII names.
    """
    name = _clean_required(value, message)
    if len(name) > _METADATA_FIELD_NAME_MAX_CHARS:
        raise _bad_request(
            f"字段名不能超过 {_METADATA_FIELD_NAME_MAX_CHARS} 个字符"
        )
    if _utf8_size(name) > _METADATA_FIELD_NAME_MAX_BYTES:
        raise _bad_request(
            f"字段名不能超过 {_METADATA_FIELD_NAME_MAX_BYTES} 字节"
        )
    return name


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class OntologyDomainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Ontology domain name (<= 64 UTF-8 bytes)")
    description: str = Field("", description="Ontology domain description (<= 512 UTF-8 bytes)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_domain_name(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _validate_domain_description(value)


class OntologyDomainUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, description="New ontology domain name")
    description: str | None = Field(None, description="New ontology domain description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _validate_domain_name(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return _validate_domain_description(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.description is None:
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class EntityPropertyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_name: str = Field(..., min_length=1)
    display_name: str | None = None
    value: str | None = None


class OntologyEntityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["type", "entity"]
    api_name: str = Field(..., description="Stable AIDP entity API name")
    display_name: str | None = None
    description: str | None = None
    properties: list[EntityPropertyRequest] = Field(default_factory=list)
    primary_properties: list[str] = Field(default_factory=list)
    type_id: str | None = None

    @field_validator("api_name")
    @classmethod
    def validate_api_name(cls, value: str) -> str:
        api_name = _clean_required(value, "API 名称不能为空")
        if len(api_name) > _ENTITY_NAME_MAX_CHARS:
            raise ValueError(f"API 名称不能超过 {_ENTITY_NAME_MAX_CHARS} 个字符")
        return api_name

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        description = value.strip()
        if len(description) > _ENTITY_DESCRIPTION_MAX_CHARS:
            raise ValueError(f"实体描述不能超过 {_ENTITY_DESCRIPTION_MAX_CHARS} 个字符")
        return description

    @model_validator(mode="after")
    def validate_kind_rules(self):
        if self.kind == "type" and self.type_id:
            raise ValueError("Type 不能选择所属实体类型")
        property_names = [item.api_name.strip() for item in self.properties]
        if len(set(property_names)) != len(property_names):
            raise ValueError("属性 api_name 不能重复")
        missing = [name for name in self.primary_properties if name not in property_names]
        if missing:
            raise ValueError("主属性必须来自已配置的属性")
        return self


class OntologyEntityUpdateRequest(BaseModel):
    """Only fields the AIDP PATCH contract accepts for an existing entity.

    ``parent_entities``, ``synonym_entities`` and ``type_id`` are deliberately
    absent: the upstream contract marks them non-editable, so accepting them
    here would report a save that AIDP never applied.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    properties: list[EntityPropertyRequest] | None = None
    primary_properties: list[str] | None = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        description = value.strip()
        if len(description) > _ENTITY_DESCRIPTION_MAX_CHARS:
            raise ValueError(f"实体描述不能超过 {_ENTITY_DESCRIPTION_MAX_CHARS} 个字符")
        return description

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class OntologyBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str | None = Field(default=None, min_length=1, description="Target AIDP knowledge base ID")
    kds_id: str | None = Field(default=None, min_length=1, description="Legacy spelling for kb_id")

    @model_validator(mode="after")
    def require_kb_id(self):
        if not (self.kb_id or self.kds_id):
            raise ValueError("kb_id is required")
        return self

    @property
    def target_kb_id(self) -> str:
        return (self.kb_id or self.kds_id or "").strip()


class OntologyMetadataFieldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(..., description="Field name, at most 63 characters and 64 UTF-8 bytes")
    field_type: Literal["string", "number", "time"]

    @field_validator("field_name")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        return _validate_field_name(value)


class OntologyRulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    enabled: bool = True
    condition: dict[str, Any]
    action: dict[str, Any]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("规则名称不能为空")
        return stripped


class OntologyMetadataUnbindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata_ids: list[str] = Field(..., min_length=1)


class OntologyMetadataFieldRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_field_name: str = Field(..., description="New field name, at most 63 characters and 64 UTF-8 bytes")

    @field_validator("new_field_name")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        return _validate_field_name(value)


class ChunkMetadataUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str = Field(..., min_length=1, description="Ontology domain that owns the fields")
    metadata: dict[str, Any] = Field(..., min_length=1)
    chunk_ids: list[int | str] = Field(..., min_length=1)

    @field_validator("chunk_ids")
    @classmethod
    def validate_chunk_ids(cls, value: list[int | str]) -> list[int | str]:
        if len(value) > ontology_service.CHUNK_BATCH_MAX_IDS:
            raise ValueError(f"单次最多标注 {ontology_service.CHUNK_BATCH_MAX_IDS} 个 Chunk")
        return value


class OntologyExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_properties: bool = True
    include_relations: bool = True
    kind: Literal["type", "entity"] | None = None


class OntologyImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field("ontology.json", min_length=1, max_length=255)
    document: dict[str, Any] = Field(..., description="Parsed AIDP export JSON")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _domain_id_path() -> Any:
    return Path(..., min_length=1, max_length=20, pattern=r"^\d+$")


def _numeric_domain_id(domain_id: str) -> int:
    try:
        value = int(domain_id)
    except (TypeError, ValueError):
        raise _bad_request("本体库 ID 必须是数字") from None
    if value < 0:
        raise _bad_request("本体库 ID 不合法")
    return value


async def _load_bindings(
    user_id: str,
    tenant_id: str,
    *,
    domain_id: str | None = None,
    readable_only: bool = True,
) -> list[dict[str, Any]]:
    """Load binding rows and drop KBs the caller cannot read.

    The ontology page is shared by management roles and KB owners; filtering
    keeps names and identifiers of other tenants' knowledge bases out of the
    response without changing the upstream count used for the domain owner.
    """
    server_url, api_key = _credentials()
    rows = await run_blocking(
        "aidp-ontology-bindings",
        ontology_service.list_ontology_bindings_impl,
        server_url,
        api_key,
        domain_id=domain_id,
        lane="control-io",
        owner="config",
    )
    role = (get_user_role_by_tenant(user_id, tenant_id) or "USER").upper()
    # Ontology managers see every binding so the tab agrees with the trusted
    # binding count. Other callers only see knowledge bases they can read.
    if readable_only and rows and role not in CAN_EDIT_ALL_USER_ROLES:
        allowed = await run_blocking(
            "aidp-ontology-binding-access",
            perms.filter_accessible_kds,
            [row["kds_id"] for row in rows],
            user_id,
            tenant_id,
            lane="control-io",
            owner="config",
        )
        allowed_set = set(allowed)
        rows = [row for row in rows if row["kds_id"] in allowed_set]
    return rows


def _enrich_bindings_sync(
    rows: list[dict[str, Any]],
    tenant_id: str,
    domain_names: dict[str, str],
    server_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        record = aidp_permission_db.get_permission_by_kb_id(row["kds_id"], tenant_id) or {}
        kds_name = record.get("kds_name")
        if not kds_name:
            # A binding can outlive the local permission row (for example a
            # KB created outside Nexent). Read its display name from AIDP so
            # the management view does not degrade to bare identifiers.
            try:
                detail = get_aidp_kb_impl(server_url, api_key, row["kds_id"]) or {}
                kds_name = detail.get("kds_name") or detail.get("name")
            except Exception as error:  # noqa: BLE001 - name lookup is best effort
                logger.debug(
                    "AIDP binding KB name unavailable for %s: %s",
                    row["kds_id"],
                    error,
                )
        enriched.append(
            {
                "binding_id": row.get("binding_id"),
                "od_id": row["od_id"],
                "od_name": domain_names.get(row["od_id"]),
                "kds_id": row["kds_id"],
                "kds_name": kds_name,
                "create_time": row.get("create_time"),
            }
        )
    return enriched


async def _binding_count(domain_id: str) -> int | None:
    """Return the trusted binding count, or ``None`` when it cannot be read."""
    server_url, api_key = _credentials()
    try:
        rows = await run_blocking(
            "aidp-ontology-binding-count",
            ontology_service.list_ontology_bindings_impl,
            server_url,
            api_key,
            domain_id=domain_id,
            lane="control-io",
            owner="config",
        )
        return len(rows)
    except AppException as error:
        logger.warning("AIDP binding count unavailable for domain %s: %s", domain_id, error)
        return None


async def _domain_names(tenant_id: str) -> dict[str, str]:
    server_url, api_key = _credentials()
    try:
        envelope = await run_blocking(
            "aidp-ontology-domain-names",
            ontology_service.list_ontology_domains_impl,
            server_url,
            api_key,
            page=1,
            page_size=100,
            lane="control-io",
            owner="config",
        )
    except AppException as error:
        logger.warning("AIDP ontology domain names unavailable: %s", error)
        return {}
    names: dict[str, str] = {}
    for item in envelope.get("value", []):
        domain_id = item.get("od_id") or item.get("domain_id") or item.get("id")
        name = item.get("name") or item.get("display_name") or item.get("od_name")
        if domain_id is not None and isinstance(name, str):
            names[str(domain_id)] = name
    return names


def _optional_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _domain_summary(item: dict[str, Any], binding_count: int | None) -> dict[str, Any]:
    """Map the AIDP list row without inventing fields it does not return.

    The deployed list contract currently exposes only the domain id, name and
    description. Metadata/entity counts and audit fields are optional
    extensions; when absent they stay null so the browser can render "—".
    """
    domain_id = item.get("od_id") or item.get("domain_id") or item.get("id")
    return {
        "domain_id": str(domain_id) if domain_id is not None else None,
        "name": item.get("name") or item.get("display_name") or item.get("od_name"),
        "description": item.get("description") or "",
        "bound_kb_count": binding_count,
        "metadata_count": _optional_count(item.get("metadata_count")),
        "entity_count": _optional_count(item.get("entity_count")),
        "rule_count": _optional_count(item.get("rule_count")),
        "created_by": item.get("created_by")
        or item.get("creator_name")
        or item.get("create_user"),
        "create_time": item.get("create_time") or item.get("created_at"),
        "update_time": item.get("update_time") or item.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Ontology domain endpoints
# ---------------------------------------------------------------------------


@aidp_ontology_router.get("/demo-mode")
async def get_ontology_demo_mode(request: Request) -> JSONResponse:
    """Tell the browser whether this deployment uses the local demo data source."""
    await _auth(request)
    return JSONResponse(status_code=HTTPStatus.OK, content={"demo": bool(AIDP_MOCK_MODE)})


@aidp_ontology_router.get("/domains")
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
        ontology_service.list_ontology_domains_impl,
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
        counts: dict[str, int] = {}
        counts_available = True
        try:
            all_bindings = await run_blocking(
                "aidp-ontology-bindings-all",
                ontology_service.list_ontology_bindings_impl,
                server_url,
                api_key,
                lane="control-io",
                owner="config",
            )
            for binding in all_bindings:
                counts[binding["od_id"]] = counts.get(binding["od_id"], 0) + 1
        except AppException as error:
            logger.warning("AIDP binding counts unavailable for domain list: %s", error)
            counts_available = False
        envelope["value"] = [
            _domain_summary(
                item,
                (
                    counts.get(
                        str(
                            item.get("od_id")
                            or item.get("domain_id")
                            or item.get("id")
                        ),
                        0,
                    )
                    if counts_available
                    else None
                ),
            )
            for item in domains
        ]
    else:
        envelope["value"] = []
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_router.post("/domains")
async def create_ontology_domain(
    request: Request,
    body: OntologyDomainRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-domain-create",
        ontology_service.create_ontology_domain_impl,
        server_url,
        api_key,
        {"name": body.name, "description": body.description},
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_domain_summary(result, 0))


@aidp_ontology_router.get("/domains/{domain_id}")
async def get_ontology_domain(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-domain-get",
        ontology_service.get_ontology_domain_impl,
        server_url,
        api_key,
        domain_id,
        lane="control-io",
        owner="config",
    )
    count = await _binding_count(domain_id)
    return JSONResponse(status_code=HTTPStatus.OK, content=_domain_summary(result, count))


@aidp_ontology_router.patch("/domains/{domain_id}")
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
        ontology_service.update_ontology_domain_impl,
        server_url,
        api_key,
        domain_id,
        payload,
        lane="control-io",
        owner="config",
    )
    count = await _binding_count(domain_id)
    return JSONResponse(status_code=HTTPStatus.OK, content=_domain_summary(result, count))


@aidp_ontology_router.delete("/domains/{domain_id}")
async def delete_ontology_domain(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    success = await run_blocking(
        "aidp-ontology-domain-delete",
        ontology_service.delete_ontology_domain_impl,
        server_url,
        api_key,
        domain_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})


# ---------------------------------------------------------------------------
# Entity endpoints
# ---------------------------------------------------------------------------


def _entity_summary(item: dict[str, Any], binding_count: int | None) -> dict[str, Any]:
    entity_id = item.get("entity_id") or item.get("id")
    return {
        "entity_id": str(entity_id) if entity_id is not None else None,
        "api_name": item.get("api_name"),
        "display_name": item.get("display_name"),
        "description": item.get("description") or "",
        "kind": (item.get("kind") or "").lower() or None,
        "type_id": item.get("type_id"),
        "properties": item.get("properties") or [],
        "primary_properties": item.get("primary_properties") or [],
        "parent_entities": item.get("parent_entities") or [],
        "synonym_entities": item.get("synonym_entities") or [],
        "child_entities": item.get("child_entities")
        or item.get("children")
        or [],
        "chunk_count": item.get("chunk_count")
        if isinstance(item.get("chunk_count"), int)
        else None,
        "extended_properties": item.get("extended_properties") or [],
        "create_time": item.get("create_time") or item.get("createTime"),
        "update_time": item.get("update_time") or item.get("updateTime"),
        "bound_kb_count": binding_count,
    }


@aidp_ontology_router.get("/domains/{domain_id}/entities")
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
    envelope, count = await asyncio.gather(
        run_blocking(
            "aidp-ontology-entity-list",
            ontology_service.list_ontology_entities_impl,
            server_url,
            api_key,
            domain_id,
            page=page,
            page_size=page_size,
            keyword=keyword,
            kind=kind,
            lane="control-io",
            owner="config",
        ),
        _binding_count(domain_id),
    )
    envelope["value"] = [
        _entity_summary(item, count) for item in envelope["value"]
    ]
    envelope["bound_kb_count"] = count
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_router.post("/domains/{domain_id}/entities")
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
        "properties": [item.model_dump(exclude_none=True) for item in body.properties],
        "primary_properties": body.primary_properties,
    }

    if body.kind == "entity" and body.type_id:
        types = await run_blocking(
            "aidp-ontology-entity-types",
            ontology_service.list_ontology_entities_impl,
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
            str(item.get("entity_id") or item.get("id"))
            for item in types["value"]
        }
        type_names = {str(item.get("api_name")) for item in types["value"]}
        if body.type_id not in type_ids and body.type_id not in type_names:
            raise _bad_request("所属 Type 不存在于当前本体库")
        payload["type_id"] = body.type_id

    result = await run_blocking(
        "aidp-ontology-entity-create",
        ontology_service.create_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        payload,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content=_entity_summary(result, await _binding_count(domain_id)),
    )


@aidp_ontology_router.get("/domains/{domain_id}/entities/{entity_id}")
async def get_ontology_entity(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    entity_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-entity-get",
        ontology_service.get_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        entity_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content=_entity_summary(result, await _binding_count(domain_id)),
    )


@aidp_ontology_router.patch("/domains/{domain_id}/entities/{entity_id}")
async def update_ontology_entity(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    entity_id: Annotated[str, Path(..., min_length=1, max_length=64)],
    body: OntologyEntityUpdateRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    payload = body.model_dump(exclude_none=True)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-entity-update",
        ontology_service.update_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        entity_id,
        payload,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content=_entity_summary(result, await _binding_count(domain_id)),
    )


@aidp_ontology_router.delete("/domains/{domain_id}/entities/{entity_id}")
async def delete_ontology_entity(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    entity_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    success = await run_blocking(
        "aidp-ontology-entity-delete",
        ontology_service.delete_ontology_entity_impl,
        server_url,
        api_key,
        domain_id,
        entity_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})


# ---------------------------------------------------------------------------
# Binding endpoints
# ---------------------------------------------------------------------------


@aidp_ontology_router.get("/bindings")
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


@aidp_ontology_router.get("/domains/{domain_id}/bindings")
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


@aidp_ontology_router.post("/domains/{domain_id}/bindings")
@aidp_ontology_router.put("/domains/{domain_id}/bindings")
async def create_domain_binding(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyBindingRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    target_kb_id = body.target_kb_id
    perms.require_permission(target_kb_id, user_id, tenant_id, required="EDIT")

    # AIDP's design also requires mutual exclusion with jargon-library
    # bindings. Nexent currently has no jargon-binding API or local
    # representation, so this backend cannot query that relationship without
    # inventing an external contract. Keep the one-KB-one-ontology check and
    # track the jargon exclusion as a real-AIDP integration item.
    server_url, api_key = _credentials()
    await run_blocking(
        "aidp-ontology-domain-exists",
        ontology_service.get_ontology_domain_impl,
        server_url,
        api_key,
        domain_id,
        lane="control-io",
        owner="config",
    )
    existing = await run_blocking(
        "aidp-ontology-binding-check",
        ontology_service.list_ontology_bindings_impl,
        server_url,
        api_key,
        kds_id=target_kb_id,
        lane="control-io",
        owner="config",
    )
    for binding in existing:
        if binding["od_id"] != domain_id:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="该知识库已绑定其他本体库，一个知识库最多绑定一个本体库",
            )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "binding_id": binding.get("binding_id"),
                "od_id": binding["od_id"],
                "kds_id": binding["kds_id"],
                "unchanged": True,
            },
        )

    result = await run_blocking(
        "aidp-ontology-binding-create",
        ontology_service.create_ontology_binding_impl,
        server_url,
        api_key,
        domain_id=domain_id,
        kds_id=target_kb_id,
        lane="control-io",
        owner="config",
    )
    binding_id = result.get("id") or result.get("binding_id")
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "binding_id": str(binding_id) if binding_id is not None else None,
            "od_id": domain_id,
            "kds_id": target_kb_id,
            "result": result,
        },
    )


@aidp_ontology_router.delete("/domains/{domain_id}/bindings/{binding_id}")
async def delete_domain_binding(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    binding_id: Annotated[str, Path(..., min_length=1, max_length=128)],
    kds_id: Annotated[str | None, Query(max_length=128)] = None,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    if kds_id:
        perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    else:
        _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    success = await run_blocking(
        "aidp-ontology-binding-delete",
        ontology_service.delete_ontology_binding_impl,
        server_url,
        api_key,
        binding_id=binding_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})


@aidp_ontology_router.get("/knowledge-bases/{kds_id}/binding")
async def get_knowledge_base_binding(
    request: Request,
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
) -> JSONResponse:
    """Demo-only KB-side binding lookup.

    AIDP exposes no confirmed by-KB query yet. In real mode this endpoint
    refuses instead of scanning every ontology's bindings, which would be
    expensive and could silently miss records. Demo mode uses the mock's
    legacy all-bindings list so the UCD tab can be demonstrated.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    if not AIDP_MOCK_MODE:
        raise HTTPException(
            status_code=HTTPStatus.NOT_IMPLEMENTED,
            detail="AIDP 尚未提供按知识库查询当前绑定关系的对外接口",
        )
    rows = await _load_bindings(user_id, tenant_id)
    match = next((row for row in rows if row["kds_id"] == kds_id), None)
    if match is None:
        return JSONResponse(status_code=HTTPStatus.OK, content={"binding": None})
    names = await _domain_names(tenant_id)
    enriched = await run_blocking(
        "aidp-ontology-binding-enrich-kb",
        _enrich_bindings_sync,
        [match],
        tenant_id,
        names,
        _credentials()[0],
        _credentials()[1],
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"binding": enriched[0] if enriched else None},
    )


# ---------------------------------------------------------------------------
# Metadata field endpoints
# ---------------------------------------------------------------------------


def _rule_summary(item: dict[str, Any]) -> dict[str, Any]:
    rule_id = item.get("rule_id") or item.get("id")
    return {
        "rule_id": str(rule_id) if rule_id is not None else None,
        "name": item.get("name"),
        "description": item.get("description") or "",
        "enabled": bool(item.get("enabled", True)),
        "condition": item.get("condition"),
        "action": item.get("action"),
        "created_at": item.get("created_at") or item.get("create_time"),
        "updated_at": item.get("updated_at") or item.get("update_time"),
    }


def _find_metadata_field(fields: list[dict[str, Any]], field_ref: str) -> dict[str, Any] | None:
    for item in fields:
        if str(item.get("id")) == str(field_ref):
            return item
        if item.get("field_name") == field_ref:
            return item
    return None


async def _load_metadata_fields(domain_id: str) -> list[dict[str, Any]]:
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-ontology-metadata-list",
        ontology_service.list_ontology_metadata_fields_impl,
        server_url,
        api_key,
        domain_id,
        page=1,
        page_size=100,
        lane="control-io",
        owner="config",
    )
    return envelope["value"]


@aidp_ontology_router.get("/domains/{domain_id}/metadata-fields")
async def list_metadata_fields(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-ontology-metadata-fields",
        ontology_service.list_ontology_metadata_fields_impl,
        server_url,
        api_key,
        domain_id,
        page=page,
        page_size=page_size,
        lane="control-io",
        owner="config",
    )
    envelope["limit"] = ontology_service.METADATA_FIELD_LIMIT
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_router.post("/domains/{domain_id}/metadata-fields")
async def create_metadata_field(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyMetadataFieldRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    if len(fields) >= ontology_service.METADATA_FIELD_LIMIT:
        raise _bad_request(
            f"每个本体库最多定义 {ontology_service.METADATA_FIELD_LIMIT} 个 Metadata 字段"
        )
    if any(item.get("field_name") == body.field_name for item in fields):
        raise _bad_request("字段名在该本体库中已存在")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-create",
        ontology_service.create_ontology_metadata_field_impl,
        server_url,
        api_key,
        domain_id,
        field_name=body.field_name,
        field_type=body.field_type,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "id": result.get("id") or result.get("metadata_id"),
            "field_name": result.get("fieldName")
            or result.get("field_name")
            or body.field_name,
            "field_type": result.get("fieldType")
            or result.get("field_type")
            or body.field_type,
            "column_index": result.get("columnIndex")
            or result.get("column_index"),
        },
    )


@aidp_ontology_router.patch("/domains/{domain_id}/metadata-fields/{field_ref}")
async def rename_metadata_field(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    field_ref: Annotated[str, Path(..., min_length=1, max_length=63)],
    body: OntologyMetadataFieldRenameRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    current = _find_metadata_field(fields, field_ref)
    if current is None:
        raise _bad_request("要重命名的字段不存在")
    if body.new_field_name == current.get("field_name"):
        raise _bad_request("新字段名与当前字段名相同")
    if any(item.get("field_name") == body.new_field_name for item in fields):
        raise _bad_request("字段名在该本体库中已存在")
    metadata_id = current.get("id")
    if metadata_id is None:
        raise _bad_request("AIDP 没有返回该字段的 MetadataId，无法按真实契约改名")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-rename",
        ontology_service.rename_ontology_metadata_field_impl,
        server_url,
        api_key,
        domain_id,
        metadata_id=metadata_id,
        new_field_name=body.new_field_name,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(result):
        acknowledged = async_task_summary(result)
        acknowledged["field_name"] = body.new_field_name
        acknowledged["id"] = metadata_id
        return JSONResponse(status_code=HTTPStatus.OK, content=acknowledged)
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "id": metadata_id,
            "field_name": result.get("fieldName")
            or result.get("field_name")
            or body.new_field_name,
            "field_type": result.get("fieldType") or current.get("field_type"),
        },
    )


@aidp_ontology_router.post("/domains/{domain_id}/metadata-fields/batch-unbind")
async def batch_unbind_metadata_fields(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyMetadataUnbindRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    resolved: list[int] = []
    for field_ref in body.metadata_ids:
        current = _find_metadata_field(fields, field_ref)
        if current is None or current.get("id") is None:
            raise _bad_request("部分字段缺少 MetadataId，无法解绑")
        resolved.append(int(current["id"]))
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-unbind",
        ontology_service.batch_unbind_metadata_impl,
        server_url,
        api_key,
        domain_id,
        metadata_ids=resolved,
        creator=user_id,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(result):
        return JSONResponse(status_code=HTTPStatus.OK, content=async_task_summary(result))
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})


@aidp_ontology_router.delete("/domains/{domain_id}/metadata-fields/{field_ref}")
async def delete_metadata_field(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    field_ref: Annotated[str, Path(..., min_length=1, max_length=63)],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    current = _find_metadata_field(fields, field_ref)
    if current is None:
        raise _bad_request("要删除的字段不存在")
    metadata_id = current.get("id")
    if metadata_id is None:
        raise _bad_request("AIDP 没有返回该字段的 MetadataId，无法按真实契约删除")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-delete",
        ontology_service.delete_ontology_metadata_field_impl,
        server_url,
        api_key,
        domain_id,
        metadata_id,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(result):
        acknowledged = async_task_summary(result)
        acknowledged["id"] = metadata_id
        acknowledged["field_name"] = current.get("field_name")
        return JSONResponse(status_code=HTTPStatus.OK, content=acknowledged)
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})


# ---------------------------------------------------------------------------
# Ontology rule endpoints
# ---------------------------------------------------------------------------


@aidp_ontology_router.get("/domains/{domain_id}/rules")
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
        ontology_service.list_ontology_rules_impl,
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


@aidp_ontology_router.get("/domains/{domain_id}/rules/count")
async def count_ontology_rules(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    count = await run_blocking(
        "aidp-ontology-rule-count",
        ontology_service.count_ontology_rules_impl,
        server_url,
        api_key,
        domain_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"count": count})


@aidp_ontology_router.put("/domains/{domain_id}/rules")
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
        ontology_service.create_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        body.model_dump(exclude_none=True),
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_rule_summary(result))


@aidp_ontology_router.get("/domains/{domain_id}/rules/{rule_id}")
async def get_ontology_rule(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    rule_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-rule-get",
        ontology_service.get_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        rule_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_rule_summary(result))


@aidp_ontology_router.patch("/domains/{domain_id}/rules/{rule_id}")
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
        ontology_service.update_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        rule_id,
        body.model_dump(exclude_none=True),
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=_rule_summary(result))


@aidp_ontology_router.delete("/domains/{domain_id}/rules/{rule_id}")
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
        ontology_service.delete_ontology_rule_impl,
        server_url,
        api_key,
        domain_id,
        rule_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})


# ---------------------------------------------------------------------------
# Chunk endpoints
# ---------------------------------------------------------------------------


@aidp_ontology_router.patch("/knowledge-bases/{kds_id}/chunks/metadata")
async def batch_update_chunk_metadata(
    request: Request,
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
    body: ChunkMetadataUpdateRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    bindings = await run_blocking(
        "aidp-chunk-metadata-binding",
        ontology_service.list_ontology_bindings_impl,
        server_url,
        api_key,
        kds_id=kds_id,
        lane="control-io",
        owner="config",
    )
    if not any(binding["od_id"] == body.domain_id for binding in bindings):
        raise _bad_request("该知识库未绑定当前本体库，不能标注 Metadata")

    fields = await _load_metadata_fields(body.domain_id)
    field_types = {
        item.get("field_name"): item.get("field_type")
        for item in fields
        if item.get("field_name")
    }
    metadata = body.metadata
    if len(metadata) > ontology_service.METADATA_FIELD_LIMIT:
        raise _bad_request(
            f"单次最多标注 {ontology_service.METADATA_FIELD_LIMIT} 个字段"
        )
    errors: list[dict[str, Any]] = []
    for key, value in metadata.items():
        if len(key.encode("utf-8")) > ontology_service.METADATA_KEY_MAX_BYTES:
            errors.append(
                {
                    "field": key,
                    "message": f"字段键不能超过 {ontology_service.METADATA_KEY_MAX_BYTES} 字节",
                }
            )
            continue
        field_type = field_types.get(key)
        if field_type is None:
            errors.append({"field": key, "message": "字段未在当前本体库中定义"})
            continue
        value_error = ontology_service.metadata_value_error(key, field_type, value)
        if value_error:
            errors.append({"field": key, "message": value_error})
    if errors:
        raise _bad_request("Metadata 校验失败", errors)

    async def _check_chunk(chunk_id: int | str) -> dict[str, Any] | None:
        try:
            await run_blocking(
                "aidp-chunk-ownership",
                ontology_service.get_aidp_chunk_impl,
                server_url,
                api_key,
                kds_id,
                str(chunk_id),
                lane="control-io",
                owner="config",
            )
            return None
        except AppException as error:
            upstream_status = (error.details or {}).get("upstream_status")
            if upstream_status == HTTPStatus.NOT_FOUND:
                return {"chunk_id": chunk_id, "message": "Chunk 不属于该知识库"}
            raise

    ownership_errors = [
        error for error in await asyncio.gather(*[_check_chunk(item) for item in body.chunk_ids])
        if error is not None
    ]
    if ownership_errors:
        raise _bad_request("部分 Chunk 不属于该知识库", ownership_errors)

    result = await run_blocking(
        "aidp-chunk-metadata-batch",
        ontology_service.batch_set_chunk_metadata_impl,
        server_url,
        api_key,
        kds_id,
        domain_id=body.domain_id,
        metadata=metadata,
        chunk_ids=body.chunk_ids,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_ontology_router.get("/knowledge-bases/{kds_id}/chunks")
async def list_chunks(
    request: Request,
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
    file_uuid: Annotated[str, Query(min_length=1, max_length=128)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-chunk-list",
        ontology_service.list_aidp_chunks_impl,
        server_url,
        api_key,
        kds_id,
        file_uuid=file_uuid,
        page=page,
        page_size=page_size,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_router.get("/knowledge-bases/{kds_id}/chunks/{chunk_id}")
async def get_chunk(
    request: Request,
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
    chunk_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-chunk-get",
        ontology_service.get_aidp_chunk_impl,
        server_url,
        api_key,
        kds_id,
        chunk_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


# ---------------------------------------------------------------------------
# JSON import / export endpoints
# ---------------------------------------------------------------------------


@aidp_ontology_router.post("/domains/{domain_id}/export")
async def export_ontology(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyExportRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    _numeric_domain_id(domain_id)
    server_url, api_key = _credentials()
    payload = await run_blocking(
        "aidp-ontology-export",
        ontology_service.export_ontology_impl,
        server_url,
        api_key,
        domain_id,
        include_properties=body.include_properties,
        include_relations=body.include_relations,
        kind=body.kind,
        lane="control-io",
        owner="config",
    )
    try:
        normalized = normalize_export_result(payload)
    except ValueError as error:
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "AIDP 导出响应缺少本体库数据",
            details={"operation": "export-ontology"},
        ) from error
    if normalized.get("accepted"):
        return JSONResponse(status_code=HTTPStatus.OK, content=normalized)
    try:
        domain = await run_blocking(
            "aidp-ontology-export-domain",
            ontology_service.get_ontology_domain_impl,
            server_url,
            api_key,
            domain_id,
            lane="control-io",
            owner="config",
        )
    except AppException as error:
        logger.warning("AIDP export filename lookup failed for domain %s: %s", domain_id, error)
        domain = {}
    domain_name = domain.get("name") or domain.get("display_name") or ""
    normalized["filename"] = sanitize_export_filename(
        domain_name, fallback=f"ontology-{domain_id}"
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=normalized)


@aidp_ontology_router.post("/domains/{domain_id}/import")
async def import_ontology(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyImportRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    numeric_id = _numeric_domain_id(domain_id)
    try:
        import_body, counts = build_import_request(body.document, numeric_id)
    except OntologyImportValidationError as error:
        logger.info(
            "Ontology import file %s rejected before submit with %d validation errors",
            body.file_name,
            len(error.errors),
        )
        raise _bad_request("导入文件校验失败", error.errors) from error

    server_url, api_key = _credentials()
    payload = await run_blocking(
        "aidp-ontology-import",
        ontology_service.import_ontology_impl,
        server_url,
        api_key,
        domain_id,
        import_body,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(payload):
        result = async_task_summary(payload)
        result["counts"] = counts
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    result = normalize_import_result(payload)
    result["counts"] = counts
    result["errors"] = normalize_import_errors(payload)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)
