# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.constants.constants import PROTOCOL_GRPC, PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _extract_base_url(url: str) -> str:
    """Extract base URL (scheme + host + port) from a full URL.

    Args:
        url: Full URL, e.g., http://example.com/path/to/agent.json

    Returns:
        Base URL, e.g., http://example.com
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.port:
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}"


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    return f"task_{uuid4().hex}"


def _generate_message_id() -> str:
    """Generate a unique message ID."""
    return f"msg_{uuid4().hex}"


def _generate_endpoint_id(agent_id: int) -> str:
    """Generate a unique endpoint ID for A2A Server agents."""
    return f"a2a_{agent_id}_{uuid4().hex[:8]}"


def _extract_primary_interface(supported_interfaces: List[Dict[str, Any]]) -> tuple[str, str]:
    """Extract the primary interface (first one) from supported interfaces.

    Args:
        supported_interfaces: List of interface objects with protocolBinding, url, protocolVersion.

    Returns:
        Tuple of (agent_url, protocol_version).
        Returns empty string for url if no interfaces found.
    """
    if not supported_interfaces:
        return "", "1.0"

    # Return the first interface to ensure URL and protocol are from the same interface
    first = supported_interfaces[0]
    return (first.get("url", ""), first.get("protocolVersion", "1.0"))


def _get_interface_by_protocol(
    supported_interfaces: Optional[List[Dict[str, Any]]], protocol_binding: str
) -> Optional[Dict[str, Any]]:
    """Get a specific interface by protocol binding.

    Args:
        supported_interfaces: List of interface objects.
        protocol_binding: Protocol binding to find (e.g., 'http-json-rpc', 'rest', 'grpc').

    Returns:
        Interface dict or None if not found.
    """
    if not supported_interfaces:
        return None

    for iface in supported_interfaces:
        if iface.get("protocolBinding") == protocol_binding:
            return iface

    return None


def _extract_protocol_type(supported_interfaces: Optional[List[Dict[str, Any]]]) -> str:
    """Extract protocol type from supportedInterfaces.

    Args:
        supported_interfaces: List of interface objects.

    Returns:
        Protocol type: JSONRPC, HTTP+JSON, or GRPC.
        Defaults to JSONRPC if not found.
    """
    if not supported_interfaces:
        return PROTOCOL_JSONRPC

    # Map protocol bindings to standard values
    protocol_map = {
        "http-json-rpc": PROTOCOL_JSONRPC,
        "jsonrpc": PROTOCOL_JSONRPC,
        "httpjsonrpc": PROTOCOL_JSONRPC,
        "http+json": PROTOCOL_HTTP_JSON,
        "httprest": PROTOCOL_HTTP_JSON,
        "rest": PROTOCOL_HTTP_JSON,
        "grpc": PROTOCOL_GRPC,
    }

    for iface in supported_interfaces:
        protocol_binding = iface.get("protocolBinding", "").lower()
        return protocol_map.get(protocol_binding, PROTOCOL_JSONRPC)

    return PROTOCOL_JSONRPC


def _configured_security_scheme_ids(security_credentials: Optional[Dict[str, str]]) -> List[str]:
    """Return credential scheme IDs without exposing their secret values."""
    return sorted(scheme_id for scheme_id, value in (security_credentials or {}).items() if value)


def _get_protocol_binding_mapping() -> Dict[str, List[str]]:
    """Get mapping of protocol type to protocol bindings.

    Returns:
        Dict mapping protocol type to list of possible bindings.
    """
    return {
        PROTOCOL_JSONRPC: ["http-json-rpc", "jsonrpc", "httpjsonrpc"],
        PROTOCOL_HTTP_JSON: ["httprest", "rest", "http+json"],
        PROTOCOL_GRPC: ["grpc"],
    }


def _find_interface_by_protocol_type(
    supported_interfaces: Optional[List[Dict[str, Any]]], protocol_type: str
) -> Optional[Dict[str, Any]]:
    """Find an interface by protocol type.

    Args:
        supported_interfaces: List of interface objects.
        protocol_type: Protocol type (JSONRPC, HTTP+JSON, or GRPC).

    Returns:
        Interface dict or None if not found.
    """
    if not supported_interfaces:
        return None

    binding_mapping = _get_protocol_binding_mapping()
    target_bindings = binding_mapping.get(protocol_type, [])

    for iface in supported_interfaces:
        binding = iface.get("protocolBinding", "").lower()
        if binding in target_bindings:
            return iface

    return None


def _make_default_interfaces(endpoint_id: str) -> List[Dict[str, Any]]:
    """Build default supportedInterfaces with correct A2A 1.0 format."""
    return [
        {"protocolBinding": PROTOCOL_JSONRPC, "url": f"/nb/a2a/{endpoint_id}/v1", "protocolVersion": "1.0"},
        {"protocolBinding": PROTOCOL_HTTP_JSON, "url": f"/nb/a2a/{endpoint_id}", "protocolVersion": "1.0"},
    ]
