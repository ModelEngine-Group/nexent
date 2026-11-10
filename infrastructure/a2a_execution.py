# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build A2A execution configs and bind snapshots without exporting credentials."""

import hmac
import json
from typing import Optional

from contracts.constants import environment
from contracts.constants.constants import PROTOCOL_JSONRPC
from nexent.core.agents.agent_model import ExternalA2AAgentConfig


def extract_url_from_card(raw_card: Optional[dict]) -> str:
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


def build_external_agent_config(agent: dict, agent_url: str) -> ExternalA2AAgentConfig:
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
        timeout=300.0,
        ssl_verify=agent.get("ssl_verify", True),
        raw_card=agent.get("raw_card"),
        custom_headers=_build_security_headers(agent) or None,
    )


def external_agent_execution_revision(config: ExternalA2AAgentConfig, tenant_id: str, parent_id: int) -> str:
    """Pin the resolved configuration, including credentials, with an opaque keyed digest."""
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/a2a-execution/v1", "sha256")
    value = [tenant_id, parent_id, config.model_dump(mode="json")]
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.digest(key, payload, "sha256").hex()
