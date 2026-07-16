"""Catalog loading and sanitization for NL2AGENT sessions."""

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List

from consts.exceptions import Nl2AgentCatalogUnavailableError


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
                "params": tool.get("params") or [],
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
