"""Fail-closed resource resolution for future tag-assignment operations.

This module deliberately owns no tag persistence.  It turns a resource reference
from an already-authenticated caller into a canonical, tenant-scoped resource
identity with the resource's *existing* read/edit policy attached.  Consumers
must treat an unresolved result as not found and must not retry it with a
different tenant.
"""

from __future__ import annotations

import base64
import inspect
import json
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TypeVar

from consts.const import PERMISSION_EDIT, PERMISSION_READ
from database.agent_db import search_agent_info_by_agent_id
from database.agent_repository_db import get_agent_repository_by_id
from database.knowledge_db import get_knowledge_record
from database.market_mcp_db import get_mcp_market_record_by_id
from database.remote_mcp_db import get_mcp_record_by_id_and_tenant
from database.skill_db import get_skill_by_id
from database.tool_db import query_all_tools
from services.asset_owner_visibility import resolve_agent_list_permission
from services.remote_mcp_service import get_remote_mcp_server_list

# Imported only when a knowledge-base or document adapter is used.  Keeping the
# slot patchable preserves the existing isolated adapter test seam.
ElasticSearchService: Any | None = None

DEFAULT_RESOURCE_LIBRARY_CODE = "default_resource"
KNOWLEDGE_CONTENT_LIBRARY_CODE = "knowledge_content"
LOCAL_DOCUMENT_PROVIDER = "local"
AIDP_DOCUMENT_PROVIDER = "aidp"


class ResourceType(str, Enum):
    """Resource types bound to the tenant's default resource library."""

    AGENT = "agent"
    SKILL = "skill"
    TOOL = "tool"
    MCP_SERVICE = "mcp_service"
    KNOWLEDGE_BASE = "knowledge_base"
    KNOWLEDGE_DOCUMENT = "knowledge_document"


class ResourceOrigin(str, Enum):
    """The record which supplied a resource reference, not its tag identity."""

    CANONICAL = "canonical"
    MARKETPLACE = "marketplace"
    COMMUNITY = "community"


@dataclass(frozen=True, slots=True)
class AuthenticatedCaller:
    """Server-derived caller facts; none of these values may come from a request body."""

    user_id: str
    authenticated_tenant_id: str
    role: str = ""
    group_ids: Collection[str | int] = field(default_factory=tuple)
    can_edit_all: bool = False

    def normalized_group_ids(self) -> frozenset[str]:
        return frozenset(str(group_id) for group_id in self.group_ids)


@dataclass(frozen=True, slots=True)
class ResourceReference:
    """Untrusted resource identifier; tenant scope is intentionally absent."""

    resource_type: ResourceType | str
    resource_id: int | str
    origin: ResourceOrigin | str = ResourceOrigin.CANONICAL
    provider: str | None = None
    knowledge_base_id: str | None = None

    def normalized_type(self) -> ResourceType | None:
        try:
            return ResourceType(self.resource_type)
        except (TypeError, ValueError):
            return None

    def normalized_origin(self) -> ResourceOrigin | None:
        try:
            return ResourceOrigin(self.origin)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class ResourceCapabilities:
    can_read: bool = False
    can_edit: bool = False


@dataclass(frozen=True, slots=True)
class ResourceDisplayMetadata:
    name: str
    description: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalResourceIdentity:
    """Stable source identity used for tag assignments and cleanup."""

    resource_type: ResourceType
    resource_id: str
    publisher_tenant_id: str
    library_code: str = DEFAULT_RESOURCE_LIBRARY_CODE
    provider: str | None = None
    knowledge_base_id: str | None = None
    provider_document_id: str | None = None

    @property
    def tenant_id(self) -> str:
        """Return the tenant which owns this canonical resource."""

        return self.publisher_tenant_id

    @property
    def key(self) -> str:
        return f"{self.resource_type.value}:{self.resource_id}"


@dataclass(frozen=True, slots=True)
class TagAssignmentCleanupDescriptor:
    """Input for a later tag-assignment deletion implementation."""

    identity: CanonicalResourceIdentity


class TagAssignmentCleanupCallback(Protocol):
    """Contract the future tag-assignment service must implement."""

    def __call__(
        self,
        descriptor: TagAssignmentCleanupDescriptor,
    ) -> Awaitable[None] | None: ...


async def run_tag_assignment_cleanup(
    descriptor: TagAssignmentCleanupDescriptor,
    callback: TagAssignmentCleanupCallback,
) -> None:
    """Invoke a future assignment-cleanup callback without coupling to its storage."""

    result = callback(descriptor)
    if inspect.isawaitable(result):
        await result


@dataclass(frozen=True, slots=True)
class ResolvedTagResource:
    """The only successful output accepted by a future tag-assignment service."""

    found: bool
    identity: CanonicalResourceIdentity | None = None
    display: ResourceDisplayMetadata | None = None
    capabilities: ResourceCapabilities = ResourceCapabilities()
    cleanup: TagAssignmentCleanupDescriptor | None = None

    @classmethod
    def not_found(cls) -> ResolvedTagResource:
        """Return one indistinguishable result for unknown and cross-tenant resources."""

        return cls(found=False)


@dataclass(slots=True)
class ResourceAdapterDependencies:
    """Dependency-injection seam for tests and for isolated service integration."""

    get_agent: Callable[..., Mapping[str, Any]] = search_agent_info_by_agent_id
    get_agent_repository: Callable[..., Mapping[str, Any] | None] = get_agent_repository_by_id
    resolve_agent_permission: Callable[..., str | None] = resolve_agent_list_permission
    get_skill: Callable[..., Mapping[str, Any] | None] = get_skill_by_id
    get_tools: Callable[..., list[Mapping[str, Any]]] = query_all_tools
    resolve_tool_edit_permission: Callable[..., bool] | None = None
    get_local_mcp: Callable[..., Mapping[str, Any] | None] = get_mcp_record_by_id_and_tenant
    list_local_mcps: Callable[..., Awaitable[list[Mapping[str, Any]]] | list[Mapping[str, Any]]] = get_remote_mcp_server_list
    get_market_mcp: Callable[..., Mapping[str, Any] | None] = get_mcp_market_record_by_id
    get_knowledge_base: Callable[..., Mapping[str, Any]] = get_knowledge_record
    resolve_knowledge_permission: Callable[..., str | None] = field(
        default_factory=lambda: _resolve_local_knowledge_permission
    )
    require_knowledge_edit_permission: Callable[..., str] = field(
        default_factory=lambda: _require_local_knowledge_edit_permission
    )
    resolve_document: Callable[..., Mapping[str, Any] | None] = field(
        default_factory=lambda: _resolve_provider_document
    )
    get_document_knowledge_base: Callable[..., Mapping[str, Any] | None] = field(
        default_factory=lambda: _get_provider_knowledge_base
    )
    resolve_document_permission: Callable[..., str | None] = field(
        default_factory=lambda: _resolve_provider_document_permission
    )
    require_document_edit_permission: Callable[..., object] = field(
        default_factory=lambda: _require_provider_document_edit_permission
    )


T = TypeVar("T")


async def _call(callback: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    result = callback(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _resolve_local_knowledge_permission(
    knowledge_base_id: str, user_id: str, tenant_id: str
) -> str | None:
    """Resolve local knowledge permissions without importing vector code at startup."""

    return _get_elasticsearch_service().resolve_knowledge_base_permission(
        knowledge_base_id, user_id, tenant_id
    )


def _require_local_knowledge_edit_permission(
    knowledge_base_id: str, user_id: str, tenant_id: str
) -> str:
    """Enforce local knowledge edit permission on the document-only path."""

    return _get_elasticsearch_service().require_knowledge_base_edit_permission(
        knowledge_base_id, user_id, tenant_id
    )


def _get_elasticsearch_service() -> Any:
    """Load the vector service only for local knowledge/document operations."""

    if ElasticSearchService is not None:
        return ElasticSearchService

    from management.services.knowledge_base.service import ElasticSearchService as service

    return service


async def _resolve_provider_document(
    *,
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
    tenant_id: str,
) -> Mapping[str, Any] | None:
    """Prove a provider document exists before its canonical tag identity is used."""

    normalized_provider = provider.strip().lower()
    if normalized_provider == LOCAL_DOCUMENT_PROVIDER:
        from management.services.knowledge_base.service import get_vector_db_core

        files = await _get_elasticsearch_service().list_files(
            knowledge_base_id,
            include_chunks=False,
            vdb_core=get_vector_db_core(),
        )
        for file_info in files.get("files", []):
            if str(file_info.get("path_or_url") or "") == provider_document_id:
                return {
                    "tenant_id": tenant_id,
                    "provider": LOCAL_DOCUMENT_PROVIDER,
                    "knowledge_base_id": knowledge_base_id,
                    "provider_document_id": provider_document_id,
                    "document_name": file_info.get("file") or file_info.get("filename"),
                }
        return None

    if normalized_provider == AIDP_DOCUMENT_PROVIDER:
        from consts.const import AIDP_API_KEY, AIDP_SERVER_URL
        from ext_components.aidp.services.aidp_service import list_aidp_docs_impl

        page = 1
        while True:
            result = list_aidp_docs_impl(
                AIDP_SERVER_URL,
                AIDP_API_KEY,
                knowledge_base_id,
                page=page,
                page_size=100,
            )
            documents = result.get("value", []) if isinstance(result, Mapping) else []
            for document in documents:
                if not isinstance(document, Mapping):
                    continue
                if str(document.get("file_ino_no") or "") == provider_document_id:
                    return {
                        "tenant_id": tenant_id,
                        "provider": AIDP_DOCUMENT_PROVIDER,
                        "knowledge_base_id": knowledge_base_id,
                        "provider_document_id": provider_document_id,
                        "document_name": document.get("file_name") or document.get("name"),
                    }
            if not result.get("next_link") or not documents:
                return None
            page += 1

    return None


def _get_provider_knowledge_base(
    *, provider: str, knowledge_base_id: str, tenant_id: str
) -> Mapping[str, Any] | None:
    """Resolve a document's parent through the provider's tenant-scoped ownership store."""

    normalized_provider = provider.strip().lower()
    if normalized_provider == LOCAL_DOCUMENT_PROVIDER:
        return get_knowledge_record({"index_name": knowledge_base_id, "tenant_id": tenant_id})
    if normalized_provider == AIDP_DOCUMENT_PROVIDER:
        from ext_components.aidp.database.aidp_permission_db import (
            get_permission_by_kb_id,
        )

        return get_permission_by_kb_id(kb_id=knowledge_base_id, tenant_id=tenant_id)
    return None


def _resolve_provider_document_permission(
    *, provider: str, knowledge_base_id: str, user_id: str, tenant_id: str
) -> str | None:
    """Return an existing provider permission after enforcing its tenant boundary."""

    normalized_provider = provider.strip().lower()
    if normalized_provider == LOCAL_DOCUMENT_PROVIDER:
        return _resolve_local_knowledge_permission(knowledge_base_id, user_id, tenant_id)
    if normalized_provider == AIDP_DOCUMENT_PROVIDER:
        from ext_components.aidp.consts.aidp_exceptions import (
            AidpKbNotFoundError,
            AidpKbPermissionDeniedError,
        )
        from ext_components.aidp.services.aidp_permission_service import (
            REQUIRE_READ,
            require_permission,
        )

        try:
            return require_permission(knowledge_base_id, user_id, tenant_id, REQUIRE_READ).permission
        except (AidpKbNotFoundError, AidpKbPermissionDeniedError) as error:
            raise ValueError("AIDP knowledge base is unavailable") from error
    raise ValueError("Unsupported document provider")


def _require_provider_document_edit_permission(
    *, provider: str, knowledge_base_id: str, user_id: str, tenant_id: str
) -> None:
    """Apply the provider's existing edit policy without granting tag-specific access."""

    normalized_provider = provider.strip().lower()
    if normalized_provider == LOCAL_DOCUMENT_PROVIDER:
        _require_local_knowledge_edit_permission(knowledge_base_id, user_id, tenant_id)
        return
    if normalized_provider == AIDP_DOCUMENT_PROVIDER:
        from ext_components.aidp.consts.aidp_exceptions import (
            AidpKbNotFoundError,
            AidpKbPermissionDeniedError,
        )
        from ext_components.aidp.services.aidp_permission_service import (
            REQUIRE_EDIT,
            require_permission,
        )

        try:
            require_permission(knowledge_base_id, user_id, tenant_id, REQUIRE_EDIT)
        except AidpKbNotFoundError as error:
            raise ValueError("AIDP knowledge base is unavailable") from error
        except AidpKbPermissionDeniedError as error:
            raise PermissionError("AIDP knowledge base is read-only") from error
        return
    raise ValueError("Unsupported document provider")


def _as_int(value: int | str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _encode_document_resource_id(
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
) -> str:
    """Encode the provider document tuple as a stable, reversible resource ID."""

    payload = json.dumps(
        [provider, knowledge_base_id, provider_document_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _tenant_matches(record: Mapping[str, Any] | None, tenant_id: str, field: str = "tenant_id") -> bool:
    """Require an explicit tenant match; empty legacy ownership is never inferred."""

    return bool(record and tenant_id and str(record.get(field) or "") == str(tenant_id))


def _permission_capabilities(permission: str | None, *, creator_is_edit: bool = False) -> ResourceCapabilities:
    normalized = str(permission or "").upper()
    can_edit = normalized == PERMISSION_EDIT or (creator_is_edit and normalized == "CREATOR")
    can_read = normalized in {str(PERMISSION_EDIT).upper(), str(PERMISSION_READ).upper(), "CREATOR"}
    return ResourceCapabilities(can_read=can_read, can_edit=can_edit)


def _display(record: Mapping[str, Any], *name_fields: str) -> ResourceDisplayMetadata:
    name = next((str(record[field]) for field in name_fields if record.get(field)), "")
    return ResourceDisplayMetadata(
        name=name,
        description=record.get("description") or record.get("knowledge_describe"),
        source=record.get("source"),
    )


def _group_ids(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, Collection):
        return frozenset(str(item) for item in value if str(item))
    return frozenset()


def _tenant_scoped_capabilities(record: Mapping[str, Any], caller: AuthenticatedCaller) -> ResourceCapabilities:
    """Use existing tenant-scoped records without elevating tag-library management."""

    if caller.can_edit_all:
        return ResourceCapabilities(can_read=True, can_edit=True)

    owner = record.get("created_by") or record.get("user_id")
    if owner is not None and str(owner) == str(caller.user_id):
        return ResourceCapabilities(can_read=True, can_edit=True)

    allowed_groups = _group_ids(record.get("group_ids"))
    if not allowed_groups:
        return ResourceCapabilities(can_read=True, can_edit=True)

    if not (allowed_groups & caller.normalized_group_ids()):
        return ResourceCapabilities()

    permission = str(record.get("ingroup_permission") or PERMISSION_READ).upper()
    return _permission_capabilities(permission)


class TagResourceAdapter(Protocol):
    resource_type: ResourceType

    async def resolve(
        self,
        reference: ResourceReference,
        caller: AuthenticatedCaller,
    ) -> ResolvedTagResource: ...


class _BaseAdapter:
    def __init__(self, dependencies: ResourceAdapterDependencies) -> None:
        self._dependencies = dependencies

    @staticmethod
    def _resolved(
        resource_type: ResourceType,
        source_id: str,
        tenant_id: str,
        display: ResourceDisplayMetadata,
        capabilities: ResourceCapabilities,
    ) -> ResolvedTagResource:
        identity = CanonicalResourceIdentity(
            resource_type=resource_type,
            resource_id=source_id,
            publisher_tenant_id=tenant_id,
        )
        return ResolvedTagResource(
            found=True,
            identity=identity,
            display=display,
            capabilities=capabilities,
            cleanup=TagAssignmentCleanupDescriptor(identity=identity),
        )


class AgentTagResourceAdapter(_BaseAdapter):
    resource_type = ResourceType.AGENT

    async def resolve(self, reference: ResourceReference, caller: AuthenticatedCaller) -> ResolvedTagResource:
        agent_id = _as_int(reference.resource_id)
        if agent_id is None:
            return ResolvedTagResource.not_found()

        if reference.normalized_origin() is ResourceOrigin.MARKETPLACE:
            repository = await _call(
                self._dependencies.get_agent_repository,
                agent_id,
                caller.authenticated_tenant_id,
            )
            if not _tenant_matches(repository, caller.authenticated_tenant_id, "publisher_tenant_id"):
                return ResolvedTagResource.not_found()
            source_agent_id = _as_int(repository.get("agent_id"))
            if source_agent_id is None:
                return ResolvedTagResource.not_found()
            agent_id = source_agent_id
        elif reference.normalized_origin() is not ResourceOrigin.CANONICAL:
            return ResolvedTagResource.not_found()

        try:
            agent = await _call(self._dependencies.get_agent, agent_id, caller.authenticated_tenant_id)
        except ValueError:
            return ResolvedTagResource.not_found()

        if not _tenant_matches(agent, caller.authenticated_tenant_id):
            return ResolvedTagResource.not_found()

        permission = await _call(
            self._dependencies.resolve_agent_permission,
            caller.role,
            dict(agent),
            caller.user_id,
            caller.can_edit_all,
        )

        return self._resolved(
            self.resource_type,
            str(agent_id),
            caller.authenticated_tenant_id,
            _display(agent, "display_name", "name"),
            _permission_capabilities(permission),
        )


class SkillTagResourceAdapter(_BaseAdapter):
    resource_type = ResourceType.SKILL

    async def resolve(self, reference: ResourceReference, caller: AuthenticatedCaller) -> ResolvedTagResource:
        skill_id = _as_int(reference.resource_id)
        if skill_id is None or reference.normalized_origin() is not ResourceOrigin.CANONICAL:
            return ResolvedTagResource.not_found()

        skill = await _call(self._dependencies.get_skill, skill_id, caller.authenticated_tenant_id)
        if not _tenant_matches(skill, caller.authenticated_tenant_id):
            return ResolvedTagResource.not_found()

        return self._resolved(
            self.resource_type,
            str(skill_id),
            caller.authenticated_tenant_id,
            _display(skill, "skill_name", "name"),
            _tenant_scoped_capabilities(skill, caller),
        )


class ToolTagResourceAdapter(_BaseAdapter):
    resource_type = ResourceType.TOOL

    async def resolve(self, reference: ResourceReference, caller: AuthenticatedCaller) -> ResolvedTagResource:
        tool_id = _as_int(reference.resource_id)
        if tool_id is None or reference.normalized_origin() is not ResourceOrigin.CANONICAL:
            return ResolvedTagResource.not_found()

        tools = await _call(self._dependencies.get_tools, caller.authenticated_tenant_id)
        tool = next((item for item in tools if _as_int(item.get("tool_id")) == tool_id), None)
        if not tool or not _tenant_matches(tool, caller.authenticated_tenant_id, "author"):
            return ResolvedTagResource.not_found()

        # The legacy local ToolInfo policy is admin-or-creator after the tenant
        # ownership check. An injected resolver remains the authoritative seam.
        created_by = tool.get("created_by")
        can_edit = caller.role == "ADMIN" or (
            bool(created_by) and str(created_by) == str(caller.user_id)
        )
        if self._dependencies.resolve_tool_edit_permission is not None:
            try:
                can_edit = bool(
                    await _call(self._dependencies.resolve_tool_edit_permission, dict(tool), caller)
                )
            except (LookupError, PermissionError, ValueError):
                can_edit = False
        return self._resolved(
            self.resource_type,
            str(tool_id),
            caller.authenticated_tenant_id,
            _display(tool, "tool_name", "name"),
            ResourceCapabilities(can_read=True, can_edit=can_edit),
        )


class McpServiceTagResourceAdapter(_BaseAdapter):
    resource_type = ResourceType.MCP_SERVICE

    async def resolve(self, reference: ResourceReference, caller: AuthenticatedCaller) -> ResolvedTagResource:
        mcp_id = _as_int(reference.resource_id)
        origin = reference.normalized_origin()
        if mcp_id is None or origin is None:
            return ResolvedTagResource.not_found()

        if origin is ResourceOrigin.CANONICAL:
            return await self._resolve_local(mcp_id, caller)
        if origin in (ResourceOrigin.COMMUNITY, ResourceOrigin.MARKETPLACE):
            return await self._resolve_marketplace(mcp_id, caller)
        return ResolvedTagResource.not_found()

    async def _resolve_local(self, mcp_id: int, caller: AuthenticatedCaller) -> ResolvedTagResource:
        record = await _call(self._dependencies.get_local_mcp, mcp_id, caller.authenticated_tenant_id)
        if not _tenant_matches(record, caller.authenticated_tenant_id):
            return ResolvedTagResource.not_found()
        records = await _call(
            self._dependencies.list_local_mcps,
            tenant_id=caller.authenticated_tenant_id,
            user_id=caller.user_id,
            is_need_auth=False,
        )

        visible = next((item for item in records if _as_int(item.get("mcp_id")) == mcp_id), None)
        if not visible:
            return ResolvedTagResource.not_found()
        capabilities = _permission_capabilities(visible.get("permission"))
        return self._resolved(
            self.resource_type,
            str(mcp_id),
            caller.authenticated_tenant_id,
            _display(record, "mcp_name", "name"),
            capabilities,
        )

    async def _resolve_marketplace(self, market_id: int, caller: AuthenticatedCaller) -> ResolvedTagResource:
        """Map market records only through their recorded local MCP source."""

        market = await _call(self._dependencies.get_market_mcp, market_id)
        if not _tenant_matches(market, caller.authenticated_tenant_id):
            return ResolvedTagResource.not_found()
        source_mcp_id = _as_int(market.get("source_mcp_id"))
        if source_mcp_id is None:
            return ResolvedTagResource.not_found()
        return await self._resolve_local(source_mcp_id, caller)


class KnowledgeBaseTagResourceAdapter(_BaseAdapter):
    resource_type = ResourceType.KNOWLEDGE_BASE

    async def resolve(self, reference: ResourceReference, caller: AuthenticatedCaller) -> ResolvedTagResource:
        if reference.normalized_origin() is not ResourceOrigin.CANONICAL:
            return ResolvedTagResource.not_found()
        index_name = str(reference.resource_id)
        if not index_name:
            return ResolvedTagResource.not_found()

        record = await _call(
            self._dependencies.get_knowledge_base,
            {"index_name": index_name, "tenant_id": caller.authenticated_tenant_id},
        )
        if not _tenant_matches(record, caller.authenticated_tenant_id):
            return ResolvedTagResource.not_found()

        try:
            permission = await _call(
                self._dependencies.resolve_knowledge_permission,
                index_name,
                caller.user_id,
                caller.authenticated_tenant_id,
            )
        except ValueError:
            return ResolvedTagResource.not_found()
        try:
            await _call(
                self._dependencies.require_knowledge_edit_permission,
                index_name,
                caller.user_id,
                caller.authenticated_tenant_id,
            )
            can_edit = True
        except PermissionError:
            can_edit = False

        resolved = _permission_capabilities(permission, creator_is_edit=True)
        capabilities = ResourceCapabilities(can_read=resolved.can_read, can_edit=can_edit)
        return self._resolved(
            self.resource_type,
            index_name,
            caller.authenticated_tenant_id,
            _display(record, "knowledge_name", "index_name"),
            capabilities,
        )


class DocumentTagResourceAdapter(_BaseAdapter):
    """Resolve provider-backed documents only through an explicit stable source."""

    resource_type = ResourceType.KNOWLEDGE_DOCUMENT

    async def resolve(self, reference: ResourceReference, caller: AuthenticatedCaller) -> ResolvedTagResource:
        provider = str(reference.provider or "").strip().lower()
        knowledge_base_id = str(reference.knowledge_base_id or "").strip()
        provider_document_id = str(reference.resource_id or "").strip()
        if (
            reference.normalized_origin() is not ResourceOrigin.CANONICAL
            or not provider
            or not knowledge_base_id
            or not provider_document_id
        ):
            return ResolvedTagResource.not_found()

        knowledge_base = await _call(
            self._dependencies.get_document_knowledge_base,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
            tenant_id=caller.authenticated_tenant_id,
        )
        if not _tenant_matches(knowledge_base, caller.authenticated_tenant_id):
            return ResolvedTagResource.not_found()

        try:
            permission = await _call(
                self._dependencies.resolve_document_permission,
                provider=provider,
                knowledge_base_id=knowledge_base_id,
                user_id=caller.user_id,
                tenant_id=caller.authenticated_tenant_id,
            )
        except (LookupError, PermissionError, ValueError):
            return ResolvedTagResource.not_found()

        try:
            await _call(
                self._dependencies.require_document_edit_permission,
                provider=provider,
                knowledge_base_id=knowledge_base_id,
                user_id=caller.user_id,
                tenant_id=caller.authenticated_tenant_id,
            )
            can_edit = True
        except PermissionError:
            can_edit = False
        except (LookupError, ValueError):
            return ResolvedTagResource.not_found()

        try:
            document = await _call(
                self._dependencies.resolve_document,
                provider=provider,
                knowledge_base_id=knowledge_base_id,
                provider_document_id=provider_document_id,
                tenant_id=caller.authenticated_tenant_id,
            )
        except (LookupError, PermissionError, ValueError):
            return ResolvedTagResource.not_found()
        if (
            not _tenant_matches(document, caller.authenticated_tenant_id)
            or str(document.get("provider") or "") != provider
            or str(document.get("knowledge_base_id") or "") != knowledge_base_id
            or str(document.get("provider_document_id") or "") != provider_document_id
        ):
            return ResolvedTagResource.not_found()

        read_capability = _permission_capabilities(permission, creator_is_edit=True).can_read
        resource_id = _encode_document_resource_id(provider, knowledge_base_id, provider_document_id)
        identity = CanonicalResourceIdentity(
            resource_type=self.resource_type,
            resource_id=resource_id,
            publisher_tenant_id=caller.authenticated_tenant_id,
            library_code=KNOWLEDGE_CONTENT_LIBRARY_CODE,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
            provider_document_id=provider_document_id,
        )
        return ResolvedTagResource(
            found=True,
            identity=identity,
            display=_display(document, "document_name", "file_name", "name"),
            capabilities=ResourceCapabilities(can_read=read_capability, can_edit=can_edit),
            cleanup=TagAssignmentCleanupDescriptor(identity=identity),
        )


class TagResourceAdapterRegistry:
    """Registry for the fixed v1 default-resource-library adapter set."""

    def __init__(self, dependencies: ResourceAdapterDependencies | None = None) -> None:
        resolved_dependencies = dependencies or ResourceAdapterDependencies()
        self._adapters: dict[ResourceType, TagResourceAdapter] = {
            ResourceType.AGENT: AgentTagResourceAdapter(resolved_dependencies),
            ResourceType.SKILL: SkillTagResourceAdapter(resolved_dependencies),
            ResourceType.TOOL: ToolTagResourceAdapter(resolved_dependencies),
            ResourceType.MCP_SERVICE: McpServiceTagResourceAdapter(resolved_dependencies),
            ResourceType.KNOWLEDGE_BASE: KnowledgeBaseTagResourceAdapter(resolved_dependencies),
            ResourceType.KNOWLEDGE_DOCUMENT: DocumentTagResourceAdapter(resolved_dependencies),
        }

    async def resolve(
        self,
        reference: ResourceReference,
        caller: AuthenticatedCaller,
    ) -> ResolvedTagResource:
        resource_type = reference.normalized_type()
        if resource_type is None or not caller.authenticated_tenant_id:
            return ResolvedTagResource.not_found()
        adapter = self._adapters.get(resource_type)
        if adapter is None:
            return ResolvedTagResource.not_found()
        return await adapter.resolve(reference, caller)


DEFAULT_TAG_RESOURCE_ADAPTER_REGISTRY = TagResourceAdapterRegistry()
