"""Catalog loading and sanitization for NL2AGENT sessions."""

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from consts.exceptions import (
    AgentRunException,
    Nl2AgentCatalogUnavailableError,
    Nl2AgentExternalServiceError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
)
from consts.model import SkillInstanceInfoRequest
from services.nl2agent_installation_runner import (
    DurableInstallationRunner,
    InstallationRunContext,
    InstallationRunRequest,
    fingerprint_installation_request,
    run_blocking_installation,
)
from utils.nl2agent_catalog_snapshot import mcp_recommendation_id

logger = logging.getLogger(__name__)


CatalogItem = Dict[str, Any]
SessionCatalogs = Dict[str, List[CatalogItem]]
_MARKETPLACE_PAGE_SIZE = 100
_MARKETPLACE_MAX_PAGES = 20
_MARKETPLACE_MAX_ITEMS = 2_000
_MARKETPLACE_MAX_BYTES = 5 * 1024 * 1024
_MARKETPLACE_TIMEOUT_SECONDS = 15.0
_LOCAL_CATALOG_MAX_ITEMS = 2_000


@dataclass(frozen=True)
class CatalogDependencies:
    """External catalog providers used while initializing a session."""

    list_all_tools: Callable[..., Awaitable[List[CatalogItem]]]
    list_tenant_skills: Callable[..., List[CatalogItem]]
    list_registry_mcp_services: Callable[..., Awaitable[Dict[str, Any]]]
    list_community_mcp_services: Callable[..., Awaitable[Dict[str, Any]]]
    get_official_skills_with_status: Callable[..., List[CatalogItem]]


@dataclass(frozen=True)
class SkillInstallationDependencies:
    """Trusted catalog and tenant installation operations for official Skills."""

    runner: DurableInstallationRunner
    get_owned_draft: Callable[..., Dict[str, Any]]
    get_session_catalogs: Callable[..., SessionCatalogs]
    install_by_name: Callable[..., List[str]]
    install_by_id: Callable[..., List[int]]
    get_installed_by_name: Callable[[str, str], Optional[CatalogItem]]
    get_installed_by_id: Callable[[int, str], Optional[CatalogItem]]
    get_official_configuration: Callable[[str, Optional[str]], CatalogItem]
    bind_skill: Callable[..., Any]


async def _load_marketplace_pages(
    provider: Callable[..., Awaitable[Dict[str, Any]]],
    *,
    items_key: str,
    nested_cursor_key: Optional[str] = None,
    max_pages: int = _MARKETPLACE_MAX_PAGES,
    max_items: int = _MARKETPLACE_MAX_ITEMS,
    max_bytes: int = _MARKETPLACE_MAX_BYTES,
    timeout_seconds: float = _MARKETPLACE_TIMEOUT_SECONDS,
) -> List[CatalogItem]:
    """Load bounded cursor pages while rejecting oversized provider responses."""
    items: List[CatalogItem] = []
    cursor: Optional[str] = None
    seen_cursors: set[str] = set()
    total_bytes = 0
    try:
        async with asyncio.timeout(timeout_seconds):
            for page_number in range(1, max_pages + 1):
                data = await provider(
                    search=None,
                    cursor=cursor,
                    limit=_MARKETPLACE_PAGE_SIZE,
                )
                if not isinstance(data, dict):
                    break
                page_items = data.get(items_key, [])
                valid_items = (
                    [item for item in page_items if isinstance(item, dict)]
                    if isinstance(page_items, list)
                    else []
                )
                if len(items) + len(valid_items) > max_items:
                    raise Nl2AgentExternalServiceError(
                        "Marketplace catalog exceeded the item budget."
                    )
                total_bytes += sum(
                    len(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            default=str,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                    for item in valid_items
                )
                if total_bytes > max_bytes:
                    raise Nl2AgentExternalServiceError(
                        "Marketplace catalog exceeded the byte budget."
                    )
                items.extend(valid_items)
                cursor_source = (
                    data.get(nested_cursor_key, {}) if nested_cursor_key else data
                )
                next_cursor = (
                    cursor_source.get("nextCursor")
                    if isinstance(cursor_source, dict)
                    else None
                )
                if not next_cursor or str(next_cursor) in seen_cursors:
                    break
                if page_number == max_pages:
                    raise Nl2AgentExternalServiceError(
                        "Marketplace catalog exceeded the page budget."
                    )
                seen_cursors.add(str(next_cursor))
                cursor = str(next_cursor)
    except TimeoutError as exc:
        raise Nl2AgentExternalServiceError(
            "Marketplace catalog exceeded the time budget."
        ) from exc
    return items


def recommendation_id(source: str, item: CatalogItem) -> str:
    """Build the stable recommendation identifier shared with MCP installation."""
    return mcp_recommendation_id(source, item)


def redact_mcp_marketplace_metadata(value: Any, parent_key: str = "") -> Any:
    """Remove credential defaults before marketplace metadata enters session state."""
    if isinstance(value, list):
        return [redact_mcp_marketplace_metadata(item, parent_key) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)

    declared_secret = bool(value.get("isSecret") or value.get("is_secret"))
    sanitized: Dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        secret_container_value = parent_key.lower() in {
            "env",
            "headers",
            "customheaders",
        } and bool(
            re.search(
                r"token|secret|password|api[_-]?key|authorization",
                key_text,
                re.I,
            )
        )
        if (
            declared_secret and key_text in {"value", "default"}
        ) or secret_container_value:
            sanitized[key_text] = None
        else:
            sanitized[key_text] = redact_mcp_marketplace_metadata(item, key_text)
    return sanitized


async def load_session_catalogs(
    tenant_id: str,
    dependencies: CatalogDependencies,
) -> tuple[SessionCatalogs, List[str]]:
    """Load required catalogs while distinguishing valid emptiness from failures."""
    try:
        all_tools = (
            await dependencies.list_all_tools(
                tenant_id=tenant_id,
                labels=None,
                limit=_LOCAL_CATALOG_MAX_ITEMS,
            )
            or []
        )
        tool_catalog = [
            {
                "tool_id": tool.get("tool_id"),
                "name": tool.get("name") or tool.get("origin_name") or "",
                "description": (tool.get("description") or "")[:400],
                "labels": tool.get("labels") or [],
                "source": str(tool.get("source") or "").lower(),
                "category": tool.get("category") or "",
                "usage": tool.get("usage") or "",
            }
            for tool in all_tools
            if str(tool.get("source") or "").lower() in {"local", "mcp", "langchain"}
        ]
    except Exception as exc:
        raise Nl2AgentCatalogUnavailableError(
            "NL2AGENT local Tool catalog is unavailable."
        ) from exc

    try:
        tenant_skills = (
            dependencies.list_tenant_skills(
                tenant_id=tenant_id,
                limit=_LOCAL_CATALOG_MAX_ITEMS,
            )
            or []
        )
        skill_catalog = [
            {
                "skill_id": skill.get("skill_id"),
                "name": skill.get("name") or skill.get("skill_name") or "",
                "description": (skill.get("description") or "")[:400],
                "tags": skill.get("tags") or [],
            }
            for skill in tenant_skills
        ]
    except Exception as exc:
        raise Nl2AgentCatalogUnavailableError(
            "NL2AGENT local Skill catalog is unavailable."
        ) from exc

    registry_result, community_result = await asyncio.gather(
        _load_marketplace_pages(
            dependencies.list_registry_mcp_services,
            items_key="servers",
            nested_cursor_key="metadata",
        ),
        _load_marketplace_pages(
            dependencies.list_community_mcp_services,
            items_key="items",
        ),
        return_exceptions=True,
    )
    if isinstance(registry_result, BaseException):
        logger.warning(
            "NL2AGENT Registry MCP catalog is unavailable: %s",
            registry_result,
        )
        registry_results = []
    else:
        registry_results = redact_mcp_marketplace_metadata(registry_result)
    if isinstance(community_result, BaseException):
        logger.warning(
            "NL2AGENT community MCP catalog is unavailable: %s",
            community_result,
        )
        community_results = []
    else:
        community_results = redact_mcp_marketplace_metadata(community_result)

    try:
        official_skill_catalog = (
            dependencies.get_official_skills_with_status(tenant_id=tenant_id) or []
        )
    except Exception as exc:
        raise Nl2AgentCatalogUnavailableError(
            "NL2AGENT official Skill catalog is unavailable."
        ) from exc

    resource_missing_names = [
        str(item.get("skill_name") or item.get("name") or "")
        for item in official_skill_catalog
        if item.get("status") == "resource_missing"
    ]
    resource_missing_keys = {
        _normalized_skill_name(name)
        for name in resource_missing_names
        if _normalized_skill_name(name)
    }
    skill_catalog = [
        item
        for item in skill_catalog
        if _normalized_skill_name(item.get("name")) not in resource_missing_keys
    ]
    official_skills = [
        item
        for item in official_skill_catalog
        if item.get("status") in {"installable", "resource_missing"}
    ]
    return {
        "tool_catalog": tool_catalog,
        "skill_catalog": skill_catalog,
        "registry_results": registry_results,
        "community_results": community_results,
        "official_skills": official_skills,
    }, resource_missing_names


def _normalized_skill_name(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _require_installable_skill(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    tenant_id: str,
    skill_id: Optional[int],
    skill_name: Optional[str],
) -> CatalogItem:
    if not skill_id and not _normalized_skill_name(skill_name):
        raise Nl2AgentValidationError(
            "Either skill_name or a positive skill_id is required."
        )
    catalogs = dependencies.get_session_catalogs(tenant_id, agent_id)
    normalized_name = _normalized_skill_name(skill_name)
    for item in catalogs.get("official_skills", []):
        item_name = _normalized_skill_name(item.get("skill_name") or item.get("name"))
        try:
            matches_id = not skill_id or int(item.get("skill_id")) == int(skill_id)
        except (TypeError, ValueError):
            matches_id = False
        matches_name = not normalized_name or item_name == normalized_name
        if not matches_id or not matches_name:
            continue
        if item.get("status") in {"installable", "installed", "resource_missing"}:
            return item
        break
    raise AgentRunException(
        "The requested Skill is not available for installation in this "
        "NL2AGENT session."
    )


def _skill_installation_keys(
    canonical_id: Optional[int],
    canonical_name: str,
) -> str:
    identity = f"{canonical_id or ''}:{_normalized_skill_name(canonical_name)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"skill:{digest}"


def _public_skill_install_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Remove workflow-only recommendation provenance from an API result."""
    return {
        key: deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_source_")
    }

def _bind_installed_skill(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    skill_id: int,
    tenant_id: str,
    user_id: str,
    skill_label: Any,
    config_values: Dict[str, Any],
) -> None:
    """Enable one tenant Skill on the draft agent."""
    try:
        dependencies.bind_skill(
            skill_info=SkillInstanceInfoRequest(
                skill_id=skill_id,
                agent_id=agent_id,
                enabled=True,
                version_no=0,
                config_values=config_values,
            ),
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=0,
        )
    except Exception as exc:
        raise Nl2AgentOperationError(
            f"Installed skill {skill_label} could not be bound to the draft."
        ) from exc


def _skill_parameter_is_secret(field: Dict[str, Any]) -> bool:
    name = str(field.get("name") or "")
    return bool(
        field.get("isSecret")
        or field.get("is_secret")
        or re.search(r"password|authorization|api[_-]?key|secret|token", name, re.I)
    )


def _normalize_skill_config_schemas(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [deepcopy(item) for item in value if isinstance(item, dict) and item.get("name")]
    if isinstance(value, dict):
        return [
            {"name": str(name), **deepcopy(metadata)}
            for name, metadata in value.items()
            if isinstance(metadata, dict)
        ]
    return []


def _public_skill_configuration(configuration: CatalogItem) -> Dict[str, Any]:
    schemas = _normalize_skill_config_schemas(configuration.get("config_schemas"))
    defaults = configuration.get("config_values")
    default_values = defaults if isinstance(defaults, dict) else {}
    public_defaults = {
        str(field["name"]): deepcopy(default_values[str(field["name"])])
        for field in schemas
        if not _skill_parameter_is_secret(field)
        and str(field["name"]) in default_values
    }
    return {
        "skill_id": configuration.get("skill_id"),
        "skill_name": configuration.get("skill_name"),
        "config_schemas": [
            {
                **field,
                **(
                    {"value": None, "default": None}
                    if _skill_parameter_is_secret(field)
                    else {}
                ),
            }
            for field in schemas
        ],
        "config_values": public_defaults,
    }


def get_web_skill_configuration(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    tenant_id: str,
    skill_id: Optional[int] = None,
    skill_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Return redacted configuration metadata for a trusted recommendation."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    canonical = _require_installable_skill(
        dependencies,
        agent_id=agent_id,
        tenant_id=tenant_id,
        skill_id=skill_id,
        skill_name=skill_name,
    )
    canonical_name = str(
        canonical.get("skill_name") or canonical.get("name") or ""
    ).strip()
    configuration = dependencies.get_official_configuration(canonical_name, tenant_id)
    configuration["skill_id"] = canonical.get("skill_id") or configuration.get("skill_id")
    configuration["skill_name"] = canonical_name
    return _public_skill_configuration(configuration)


_SKILL_VALUE_TYPES: Dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "optional": lambda value: True,
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


def _resolve_skill_config_values(
    skill_id: int,
    schemas: Any,
    defaults: Any,
    submitted: Dict[str, Any],
) -> Dict[str, Any]:
    fields = {
        str(field["name"]): field
        for field in _normalize_skill_config_schemas(schemas)
    }
    unknown = sorted(set(submitted) - set(fields))
    if unknown:
        raise Nl2AgentValidationError(
            f"Skill {skill_id} received unknown configuration fields: {', '.join(unknown)}."
        )
    if not fields and submitted:
        raise Nl2AgentValidationError(
            f"Skill {skill_id} does not accept configuration values."
        )

    resolved = deepcopy(defaults) if isinstance(defaults, dict) else {}
    resolved.update(deepcopy(submitted))
    for name, field in fields.items():
        dependency = str(field.get("depends_on") or "").strip()
        if dependency and not resolved.get(dependency):
            resolved.pop(name, None)
            continue
        value = resolved.get(name, field.get("value", field.get("default")))
        if value in (None, ""):
            if field.get("required") is True or field.get("optional") is False:
                raise Nl2AgentValidationError(
                    f"Skill {skill_id} requires configuration field: {name}."
                )
            resolved.pop(name, None)
            continue
        expected_type = str(field.get("type") or "string").lower()
        type_check = _SKILL_VALUE_TYPES.get(expected_type)
        if type_check and not type_check(value):
            raise Nl2AgentValidationError(
                f"Skill {skill_id} configuration field {name} must be {expected_type}."
            )
        resolved[name] = value
    return resolved


async def install_web_skill(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    skill_id: Optional[int],
    tenant_id: str,
    user_id: str,
    skill_name: Optional[str] = None,
    locale: Optional[str] = None,
    config_values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Install one recommendation resolved from the trusted session catalog."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    canonical = _require_installable_skill(
        dependencies,
        agent_id=agent_id,
        tenant_id=tenant_id,
        skill_id=skill_id,
        skill_name=skill_name,
    )
    canonical_id = int(canonical["skill_id"]) if canonical.get("skill_id") else None
    canonical_name = str(
        canonical.get("skill_name") or canonical.get("name") or ""
    ).strip()
    installation_key = _skill_installation_keys(canonical_id, canonical_name)
    request = InstallationRunRequest(
        installation_key=installation_key,
        request_fingerprint=fingerprint_installation_request(
            {
                "skill_id": canonical_id,
                "skill_name": canonical_name,
                "locale": locale,
                "config_values": config_values or {},
            }
        ),
        resource_type="skill",
        failure_code="skill_installation_failed",
        failure_message="Skill installation failed; retry is allowed.",
    )

    async def execute(
        context: InstallationRunContext,
        checkpoint: Dict[str, Any],
    ) -> Dict[str, Any]:
        static_configuration = dependencies.get_official_configuration(
            canonical_name, tenant_id
        )
        installed_skill = None
        checkpoint_skill_id = checkpoint.get("skill_id")
        if checkpoint.get("files_installed") and checkpoint_skill_id is not None:
            if skill_name:
                installed_skill = dependencies.get_installed_by_name(
                    canonical_name, tenant_id
                ) or dependencies.get_installed_by_id(
                    int(checkpoint_skill_id), tenant_id
                )
            else:
                installed_skill = dependencies.get_installed_by_id(
                    int(checkpoint_skill_id), tenant_id
                ) or dependencies.get_installed_by_name(canonical_name, tenant_id)
        if installed_skill is None:
            if skill_name:
                result = await run_blocking_installation(
                    _install_skill_by_name,
                    dependencies,
                    agent_id=agent_id,
                    canonical_name=canonical_name,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    locale=locale,
                )
            else:
                result = await run_blocking_installation(
                    _install_skill_by_id,
                    dependencies,
                    agent_id=agent_id,
                    canonical_id=canonical_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            installed_skill_id = int(result["skill_id"])
            if skill_name:
                installed_skill = dependencies.get_installed_by_name(
                    canonical_name, tenant_id
                ) or dependencies.get_installed_by_id(installed_skill_id, tenant_id)
            else:
                installed_skill = dependencies.get_installed_by_id(
                    installed_skill_id, tenant_id
                ) or dependencies.get_installed_by_name(canonical_name, tenant_id)
            await context.save_checkpoint(
                {
                    "files_installed": True,
                    "skill_id": installed_skill_id,
                }
            )
        else:
            installed_skill_id = int(installed_skill["skill_id"])
            result = {
                "skill_id": installed_skill_id,
                "installed": True,
                **(
                    {"installed_names": [canonical_name]}
                    if skill_name
                    else {"installed_ids": [installed_skill_id]}
                ),
            }
        if not installed_skill:
            raise Nl2AgentOperationError(
                f"Installed skill {canonical_name} could not be resolved for binding."
            )
        static_defaults = static_configuration.get("config_values")
        resolved_defaults = (
            deepcopy(static_defaults) if isinstance(static_defaults, dict) else {}
        )
        installed_defaults = installed_skill.get("config_values")
        if isinstance(installed_defaults, dict):
            resolved_defaults.update(deepcopy(installed_defaults))
        resolved_config = _resolve_skill_config_values(
            installed_skill_id,
            static_configuration.get("config_schemas"),
            resolved_defaults,
            config_values or {},
        )
        if not checkpoint.get("database_bound"):
            _bind_installed_skill(
                dependencies,
                agent_id=agent_id,
                skill_id=installed_skill_id,
                tenant_id=tenant_id,
                user_id=user_id,
                skill_label=canonical_name,
                config_values=resolved_config,
            )
            await context.save_checkpoint(
                {
                    "database_bound": True,
                    "skill_id": installed_skill_id,
                }
            )
        result["bound"] = True
        return {
            **deepcopy(result),
            "_source_skill_id": canonical_id,
            "_source_skill_name": canonical_name,
        }

    result = await dependencies.runner.run(request, execute)
    return _public_skill_install_result(result)


def _install_skill_by_name(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    canonical_name: str,
    tenant_id: str,
    user_id: str,
    locale: Optional[str],
) -> Dict[str, Any]:
    if not canonical_name:
        raise Nl2AgentValidationError("The requested Skill has no canonical name.")
    try:
        installed_names = dependencies.install_by_name(
            skill_names=[canonical_name],
            tenant_id=tenant_id,
            user_id=user_id,
            locale=locale,
        )
    except Exception as exc:
        logger.error("Failed to install web skill %s: %s", canonical_name, exc)
        raise Nl2AgentExternalServiceError(
            f"Failed to install skill {canonical_name}."
        ) from exc
    if not installed_names:
        raise Nl2AgentExternalServiceError(f"Failed to install skill {canonical_name}.")
    installed_skill = dependencies.get_installed_by_name(installed_names[0], tenant_id)
    if not installed_skill or not installed_skill.get("skill_id"):
        raise Nl2AgentOperationError(
            f"Installed skill {canonical_name} could not be resolved for binding."
        )
    bound_skill_id = int(installed_skill["skill_id"])
    return {
        "skill_id": bound_skill_id,
        "skill_name": canonical_name,
        "installed": True,
        "bound": False,
        "installed_ids": [],
        "installed_names": installed_names,
    }


def _install_skill_by_id(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    canonical_id: Optional[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    if canonical_id is None or canonical_id <= 0:
        raise Nl2AgentValidationError("The requested Skill has no canonical ID.")
    try:
        installed_ids = dependencies.install_by_id(
            skill_ids=[canonical_id],
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        logger.error("Failed to install web skill %s: %s", canonical_id, exc)
        raise Nl2AgentExternalServiceError(
            f"Failed to install skill {canonical_id}."
        ) from exc
    if not installed_ids:
        raise Nl2AgentExternalServiceError(f"Failed to install skill {canonical_id}.")
    installed_skill_id = int(installed_ids[0])
    return {
        "skill_id": installed_skill_id,
        "installed": True,
        "bound": False,
        "installed_ids": installed_ids,
    }
