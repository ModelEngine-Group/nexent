# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Build knowledge routing summaries and external Agent descriptors."""

import logging
from typing import List, Optional

from contracts.constants.constants import PROTOCOL_JSONRPC
from contracts.constants.environment import A2A_AGENT_INVOCATION_TIMEOUT_SECONDS
from management.services.knowledge_base.service import ElasticSearchService
from nexent.core.agents.agent_model import ExternalA2AAgentConfig, ToolConfig

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)


def _build_effective_knowledge_base_summary(
    tool_list: List[ToolConfig],
    include_empty_message: bool = True,
) -> tuple[list[dict[str, str]], bool]:
    """Collect selected summaries without formatting prompt prose."""
    summaries: list[dict[str, str]] = []
    try:
        for tool in tool_list:
            if tool.class_name != "KnowledgeBaseSearchTool":
                continue
            metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
            index_names = metadata.get("allowed_index_names") or []
            if not index_names:
                return [], include_empty_message
            display_map = metadata.get("index_name_to_display_map", {})
            for index_name in index_names:
                try:
                    display_name = display_map.get(index_name, index_name)
                    message = ElasticSearchService().get_summary(index_name=index_name)
                    summary = message.get("summary", "")
                    summaries.append(
                        {
                            "index_name": str(index_name),
                            "display_name": str(display_name),
                            "summary": str(summary),
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        f"Failed to get summary for knowledge base {index_name}: {exc}"
                    )
            break
    except Exception as exc:
        logger.error(f"Failed to build knowledge base summary: {exc}")
    return summaries, False


def _extract_url_from_card(raw_card: Optional[dict]) -> str:
    """Extract http-json-rpc URL from Agent Card supportedInterfaces."""
    if not raw_card:
        return ""

    supported_interfaces = raw_card.get("supportedInterfaces", [])
    if not supported_interfaces:
        return raw_card.get("url", "")

    # Prefer http-json-rpc protocol
    for iface in supported_interfaces:
        protocol_binding = iface.get("protocolBinding", "").lower()
        if protocol_binding in ("http-json-rpc", "jsonrpc", "httpjsonrpc"):
            url = iface.get("url", "")
            if url:
                return url

    # Fallback to first interface with a URL
    for iface in supported_interfaces:
        url = iface.get("url", "")
        if url:
            return url

    return raw_card.get("url", "")


def _resolve_scheme_field(scheme: dict, wrapper_key: str) -> Optional[dict]:
    """Get a security scheme field from wrapper or flat format."""
    field = scheme.get(wrapper_key)
    if isinstance(field, dict) and field:
        return field
    # Flat format fallback: scheme itself has the fields
    if wrapper_key == "httpAuthSecurityScheme" and isinstance(
        scheme.get("scheme"), str
    ):
        return scheme if scheme["scheme"].strip() else None
    if (
        wrapper_key == "apiKeySecurityScheme"
        and scheme.get("name")
        and scheme.get("location")
    ):
        return scheme
    return None


def _build_auth_header_for_scheme(scheme: dict, credential: str) -> Optional[tuple]:
    """Build a single (header_name, header_value) pair from a security scheme.

    Supports httpAuth (Bearer/basic) and apiKey (header location).
    """
    # HTTP auth (bearer, basic)
    http_auth = _resolve_scheme_field(scheme, "httpAuthSecurityScheme")
    if http_auth:
        auth_scheme = http_auth.get("scheme", "")
        if http_auth.get("bearerFormat", "").lower() == "jwt":
            auth_scheme = "Bearer"
        return ("Authorization", f"{auth_scheme} {credential}") if auth_scheme else None

    # API key in header
    api_key = _resolve_scheme_field(scheme, "apiKeySecurityScheme")
    if api_key:
        location = (api_key.get("location") or "").lower()
        name = api_key.get("name")
        if location == "header" and name:
            return (name, credential)

    return None


def _collect_auth_headers(requirements, schemes, credentials):
    """Collect (header_name, value) pairs from security requirements."""
    pairs = []
    for req in requirements:
        if not isinstance(req, dict):
            continue
        for scheme_id in req.get("schemes", {}):
            credential = credentials.get(scheme_id)
            scheme = schemes.get(scheme_id)
            if credential and isinstance(scheme, dict):
                pair = _build_auth_header_for_scheme(scheme, credential)
                if pair:
                    pairs.append(pair)
    return pairs


def _build_security_headers(agent: dict) -> dict:
    """Build auth headers from securitySchemes + security_credentials."""
    schemes = agent.get("security_schemes") or {}
    requirements = agent.get("security_requirements") or []
    credentials = agent.get("security_credentials") or {}
    if not requirements or not credentials:
        return {}
    return dict(_collect_auth_headers(requirements, schemes, credentials))


def _build_external_agent_config(agent: dict, agent_url: str) -> ExternalA2AAgentConfig:
    """Build an ExternalA2AAgentConfig from agent data."""
    return ExternalA2AAgentConfig(
        agent_id=str(agent.get("external_agent_id", "")),
        name=agent.get("name", "Unknown"),
        description=agent.get("description", "External A2A agent"),
        url=agent_url,
        api_key=None,
        transport_type=agent.get("transport_type", "http-streaming"),
        protocol_version=agent.get("protocol_version", "1.0"),
        protocol_type=agent.get("protocol_type", PROTOCOL_JSONRPC),
        timeout=A2A_AGENT_INVOCATION_TIMEOUT_SECONDS,
        ssl_verify=agent.get("ssl_verify", True),
        raw_card=agent.get("raw_card"),
        custom_headers=_build_security_headers(agent) or None,
    )


def _get_external_a2a_agents(
    agent_id: int, tenant_id: str, version_no: int = 0
) -> List[ExternalA2AAgentConfig]:
    """Get external A2A agent configurations for an agent.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number

    Returns:
        List of ExternalA2AAgentConfig for external A2A sub-agents
    """
    try:
        from management.db.a2a import repository as a2a_agent_db

        external_agents = a2a_agent_db.query_external_sub_agents(
            local_agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )

        result = []
        for agent in external_agents:
            agent_url = agent.get("agent_url", "") or _extract_url_from_card(
                agent.get("raw_card")
            )
            if not agent_url:
                logger.warning(
                    f"Skipping agent '{agent.get('name')}' - no URL available"
                )
                continue

            result.append(_build_external_agent_config(agent, agent_url))

        return result
    except Exception as e:
        logger.error(f"Get external A2A agents failed: {e}", exc_info=True)
        return []
