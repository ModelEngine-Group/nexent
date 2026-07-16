"""Catalog loading and sanitization for NL2AGENT sessions."""

import logging
import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from consts.exceptions import AgentRunException
from consts.exceptions import Nl2AgentCatalogUnavailableError
from consts.model import SkillInstanceInfoRequest

logger = logging.getLogger(__name__)


CatalogItem = Dict[str, Any]
SessionCatalogs = Dict[str, List[CatalogItem]]


@dataclass(frozen=True)
class CatalogDependencies:
    """External catalog providers used while initializing a session."""

    list_all_tools: Callable[..., List[CatalogItem]]
    list_tenant_skills: Callable[..., List[CatalogItem]]
    list_registry_mcp_services: Callable[..., Awaitable[Dict[str, Any]]]
    list_community_mcp_services: Callable[..., Dict[str, Any]]
    get_official_skills_with_status: Callable[..., List[CatalogItem]]


@dataclass(frozen=True)
class SkillInstallationDependencies:
    """Trusted catalog and tenant installation operations for official Skills."""

    get_owned_draft: Callable[..., Dict[str, Any]]
    get_session_catalogs: Callable[..., SessionCatalogs]
    mutate_session_catalogs: Callable[..., Any]
    install_by_name: Callable[..., List[str]]
    install_by_id: Callable[..., List[int]]
    get_installed_by_name: Callable[[str, str], Optional[CatalogItem]]
    bind_skill: Callable[..., Any]


def recommendation_id(source: str, item: CatalogItem) -> str:
    """Build the stable recommendation identifier shared with MCP installation."""
    if source == "registry":
        server = item.get("server") if isinstance(item.get("server"), dict) else item
        identity = server.get("name") or server.get("id")
    else:
        identity = (
            item.get("communityId") or item.get("community_id") or item.get("name")
        )
    return f"{source}:{identity}"


def redact_mcp_marketplace_metadata(value: Any, parent_key: str = "") -> Any:
    """Remove credential defaults before marketplace metadata enters session state."""
    if isinstance(value, list):
        return [redact_mcp_marketplace_metadata(item, parent_key) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)

    declared_secret = bool(value.get("isSecret"))
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


def redact_tool_parameter_defaults(params: Any) -> Any:
    """Remove credential defaults before Tool schemas enter session state."""
    if not isinstance(params, list):
        return deepcopy(params)
    sanitized = deepcopy(params)
    for field in sanitized:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")
        if field.get("isSecret") or field.get("is_secret") or re.search(
            r"password|authorization|api[_-]?key|secret|token", name, re.I
        ):
            field["default"] = None
    return sanitized


async def load_session_catalogs(
    tenant_id: str,
    dependencies: CatalogDependencies,
) -> tuple[SessionCatalogs, List[str]]:
    """Load required catalogs while distinguishing valid emptiness from failures."""
    try:
        all_tools = dependencies.list_all_tools(tenant_id=tenant_id, labels=None) or []
        tool_catalog = [
            {
                "tool_id": tool.get("tool_id"),
                "name": tool.get("name") or tool.get("origin_name") or "",
                "description": (tool.get("description") or "")[:400],
                "labels": tool.get("labels") or [],
                "source": str(tool.get("source") or "").lower(),
                "category": tool.get("category") or "",
                "usage": tool.get("usage") or "",
                "params": redact_tool_parameter_defaults(tool.get("params") or []),
            }
            for tool in all_tools
            if str(tool.get("source") or "").lower() in {"local", "mcp", "langchain"}
        ]
    except Exception as exc:
        raise Nl2AgentCatalogUnavailableError(
            "NL2AGENT local Tool catalog is unavailable."
        ) from exc

    try:
        tenant_skills = dependencies.list_tenant_skills(tenant_id=tenant_id) or []
        skill_catalog = [
            {
                "skill_id": skill.get("skill_id"),
                "name": skill.get("name") or skill.get("skill_name") or "",
                "description": (skill.get("description") or "")[:400],
                "tags": skill.get("tags") or [],
                "config_schema": skill.get("config_schema") or {},
            }
            for skill in tenant_skills
        ]
    except Exception as exc:
        raise Nl2AgentCatalogUnavailableError(
            "NL2AGENT local Skill catalog is unavailable."
        ) from exc

    try:
        registry_data = await dependencies.list_registry_mcp_services(
            search=None,
            limit=30,
        )
        registry_results = (
            redact_mcp_marketplace_metadata(
                registry_data.get("servers", registry_data) or []
            )
            if isinstance(registry_data, dict)
            else []
        )
    except Exception as exc:
        raise Nl2AgentCatalogUnavailableError(
            "NL2AGENT Registry MCP catalog is unavailable."
        ) from exc

    try:
        community_data = dependencies.list_community_mcp_services(
            search=None,
            limit=30,
        )
        community_results = (
            redact_mcp_marketplace_metadata(
                community_data.get("items", community_data) or []
            )
            if isinstance(community_data, dict)
            else []
        )
    except Exception as exc:
        raise Nl2AgentCatalogUnavailableError(
            "NL2AGENT community MCP catalog is unavailable."
        ) from exc

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
    official_skills = [
        item for item in official_skill_catalog if item.get("status") == "installable"
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
        raise AgentRunException("Either skill_name or a positive skill_id is required.")
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
        if item.get("status") == "installable":
            return item
        break
    raise AgentRunException(
        "The requested Skill is not available for installation in this "
        "NL2AGENT session."
    )


def _remove_installed_skill(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    tenant_id: str,
    skill_id: Optional[int],
    skill_name: Optional[str],
    installed_ids: Optional[List[int]] = None,
) -> None:
    removed_ids = {int(value) for value in [skill_id, *(installed_ids or [])] if value}
    normalized_name = _normalized_skill_name(skill_name)

    def remove(catalogs: SessionCatalogs) -> None:
        retained = []
        for item in catalogs.get("official_skills", []):
            item_id = item.get("skill_id")
            try:
                matches_id = item_id is not None and int(item_id) in removed_ids
            except (TypeError, ValueError):
                matches_id = False
            item_name = _normalized_skill_name(
                item.get("skill_name") or item.get("name")
            )
            if not matches_id and not (
                normalized_name and item_name == normalized_name
            ):
                retained.append(item)
        catalogs["official_skills"] = retained

    dependencies.mutate_session_catalogs(tenant_id, agent_id, remove)


def _bind_installed_skill(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    skill_id: int,
    tenant_id: str,
    user_id: str,
    skill_label: Any,
) -> None:
    """Enable one tenant Skill on the draft agent."""
    try:
        dependencies.bind_skill(
            skill_info=SkillInstanceInfoRequest(
                skill_id=skill_id,
                agent_id=agent_id,
                enabled=True,
                version_no=0,
            ),
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=0,
        )
    except Exception as exc:
        raise AgentRunException(
            f"Installed skill {skill_label} could not be bound to the draft."
        ) from exc


async def install_web_skill(
    dependencies: SkillInstallationDependencies,
    *,
    agent_id: int,
    skill_id: Optional[int],
    tenant_id: str,
    user_id: str,
    skill_name: Optional[str] = None,
    locale: Optional[str] = None,
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
    if skill_name:
        if not canonical_name:
            raise AgentRunException("The requested Skill has no canonical name.")
        try:
            installed_names = dependencies.install_by_name(
                skill_names=[canonical_name],
                tenant_id=tenant_id,
                user_id=user_id,
                locale=locale,
            )
        except Exception as exc:
            logger.error("Failed to install web skill %s: %s", canonical_name, exc)
            raise AgentRunException(f"Failed to install skill {canonical_name}.") from exc
        if not installed_names:
            raise AgentRunException(f"Failed to install skill {canonical_name}.")
        installed_skill = dependencies.get_installed_by_name(
            installed_names[0], tenant_id
        )
        if not installed_skill or not installed_skill.get("skill_id"):
            raise AgentRunException(
                f"Installed skill {canonical_name} could not be resolved for binding."
            )
        bound_skill_id = int(installed_skill["skill_id"])
        _bind_installed_skill(
            dependencies,
            agent_id=agent_id,
            skill_id=bound_skill_id,
            tenant_id=tenant_id,
            user_id=user_id,
            skill_label=canonical_name,
        )
        result = {
            "skill_id": bound_skill_id,
            "skill_name": canonical_name,
            "installed": True,
            "bound": True,
            "installed_ids": [],
            "installed_names": installed_names,
        }
        try:
            _remove_installed_skill(
                dependencies,
                agent_id=agent_id,
                tenant_id=tenant_id,
                skill_id=canonical_id,
                skill_name=canonical_name,
            )
        except Exception:
            logger.exception(
                "Failed to refresh NL2AGENT Skill catalog after installation: "
                "tenant_id=%s draft_agent_id=%s skill_name=%s",
                tenant_id,
                agent_id,
                canonical_name,
            )
        return result

    if canonical_id is None or canonical_id <= 0:
        raise AgentRunException("The requested Skill has no canonical ID.")
    try:
        installed_ids = dependencies.install_by_id(
            skill_ids=[canonical_id],
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        logger.error("Failed to install web skill %s: %s", canonical_id, exc)
        raise AgentRunException(f"Failed to install skill {canonical_id}.") from exc
    if not installed_ids:
        raise AgentRunException(f"Failed to install skill {canonical_id}.")
    installed_skill_id = int(installed_ids[0])
    _bind_installed_skill(
        dependencies,
        agent_id=agent_id,
        skill_id=installed_skill_id,
        tenant_id=tenant_id,
        user_id=user_id,
        skill_label=canonical_id,
    )
    try:
        _remove_installed_skill(
            dependencies,
            agent_id=agent_id,
            tenant_id=tenant_id,
            skill_id=canonical_id,
            skill_name=None,
            installed_ids=installed_ids,
        )
    except Exception:
        logger.exception(
            "Failed to refresh NL2AGENT Skill catalog after installation: "
            "tenant_id=%s draft_agent_id=%s skill_id=%s",
            tenant_id,
            agent_id,
            canonical_id,
        )
    return {
        "skill_id": installed_skill_id,
        "installed": True,
        "bound": True,
        "installed_ids": installed_ids,
    }
