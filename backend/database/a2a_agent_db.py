"""
Database operations for A2A agent management.
Includes external agent discovery, server agent registration, and task management.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from database.db_models import (
    A2AExternalAgent,
    A2AExternalAgentRelation,
    A2ANacosConfig,
    A2AServerAgent,
    A2ATask,
    A2AMessage,
    A2AArtifact,
)

# Import session factory - kept at function level to avoid triggering module-level import
# of db_models.client, which would cause circular dependency at import time.
def _get_db_session():
    from database.client import get_db_session as _gds
    return _gds()

logger = logging.getLogger("a2a_agent_db")

# Default cache TTL in seconds (24 hours)
DEFAULT_CACHE_TTL_HOURS = 24

# Standard human-readable protocol label
PROTOCOL_HTTP_JSON = "HTTP+JSON"
PROTOCOL_JSONRPC = "JSONRPC"
PROTOCOL_GRPC = "GRPC"


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
    """Extract the primary interface (HTTP+JSON) from supported interfaces.

    Args:
        supported_interfaces: List of interface objects with protocolBinding, url, protocolVersion.

    Returns:
        Tuple of (agent_url, protocol_version).
        Falls back to first interface if HTTP+JSON not found.
    """
    if not supported_interfaces:
        return "", "1.0"

    # Prefer HTTP+JSON
    for iface in supported_interfaces:
        if iface.get("protocolBinding", "").upper() in (PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC, PROTOCOL_GRPC):
            return (
                iface.get("url", ""),
                iface.get("protocolVersion", "1.0")
            )

    # Fall back to first interface
    first = supported_interfaces[0]
    return (
        first.get("url", ""),
        first.get("protocolVersion", "1.0")
    )


def _get_interface_by_protocol(
    supported_interfaces: Optional[List[Dict[str, Any]]],
    protocol_binding: str
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


# =============================================================================
# External Agent Operations (Client Role)
# =============================================================================

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


def create_external_agent_from_url(
    source_url: str,
    name: str,
    description: Optional[str],
    agent_url: str,
    tenant_id: str,
    user_id: str,
    raw_card: Optional[Dict[str, Any]] = None,
    version: Optional[str] = None,
    streaming: bool = False,
    supported_interfaces: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create or update an external A2A agent discovered from URL.

    Args:
        source_url: Direct URL to the agent card (used as unique identifier).
        name: Agent name.
        description: Agent description.
        agent_url: A2A endpoint URL for calling this agent (http-json-rpc by default).
        tenant_id: Tenant ID for isolation.
        user_id: User who discovered this agent.
        raw_card: Full original Agent Card JSON.
        version: Agent version from Agent Card.
        streaming: Whether this agent supports SSE streaming.
        supported_interfaces: All supported protocol interfaces.

    Returns:
        Created agent information dict.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=DEFAULT_CACHE_TTL_HOURS)
    protocol_type = _extract_protocol_type(supported_interfaces)

    with _get_db_session() as session:
        # Check if agent already exists by source_url
        existing = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.source_url == source_url,
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        ).first()

        if existing:
            # Update existing record
            existing.name = name
            existing.description = description
            existing.version = version
            existing.agent_url = agent_url
            existing.protocol_type = protocol_type
            existing.streaming = streaming
            existing.supported_interfaces = supported_interfaces
            existing.raw_card = raw_card
            existing.cached_at = now
            existing.cache_expires_at = expires_at
            existing.updated_by = user_id
            agent = existing
        else:
            # Create new record
            agent = A2AExternalAgent(
                name=name,
                description=description,
                version=version,
                agent_url=agent_url,
                protocol_type=protocol_type,
                streaming=streaming,
                supported_interfaces=supported_interfaces,
                source_type="url",
                source_url=source_url,
                tenant_id=tenant_id,
                created_by=user_id,
                updated_by=user_id,
                raw_card=raw_card,
                cached_at=now,
                cache_expires_at=expires_at,
                delete_flag='N'
            )
            session.add(agent)

        session.flush()

        return {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "version": agent.version,
            "agent_url": agent.agent_url,
            "protocol_type": agent.protocol_type,
            "streaming": agent.streaming,
            "supported_interfaces": agent.supported_interfaces,
            "source_type": agent.source_type,
            "is_available": agent.is_available,
            "cached_at": agent.cached_at.isoformat() if agent.cached_at else None,
            "cache_expires_at": agent.cache_expires_at.isoformat() if agent.cache_expires_at else None,
        }


def create_external_agent_from_nacos(
    name: str,
    description: Optional[str],
    agent_url: str,
    nacos_config_id: str,
    nacos_agent_name: str,
    tenant_id: str,
    user_id: str,
    raw_card: Optional[Dict[str, Any]] = None,
    version: Optional[str] = None,
    streaming: bool = False,
    supported_interfaces: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create or update an external A2A agent discovered from Nacos.

    Args:
        name: Agent name.
        description: Agent description.
        agent_url: A2A endpoint URL for calling this agent (http-json-rpc by default).
        nacos_config_id: Nacos config ID used for discovery.
        nacos_agent_name: Original name used for Nacos query.
        tenant_id: Tenant ID for isolation.
        user_id: User who discovered this agent.
        raw_card: Full original Agent Card JSON.
        version: Agent version from Agent Card.
        streaming: Whether this agent supports SSE streaming.
        supported_interfaces: All supported protocol interfaces.

    Returns:
        Created agent information dict.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=DEFAULT_CACHE_TTL_HOURS)
    protocol_type = _extract_protocol_type(supported_interfaces)

    with _get_db_session() as session:
        # Check if agent already exists by nacos_config_id + nacos_agent_name
        existing = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.nacos_config_id == nacos_config_id,
            A2AExternalAgent.nacos_agent_name == nacos_agent_name,
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        ).first()

        if existing:
            existing.name = name
            existing.description = description
            existing.version = version
            existing.agent_url = agent_url
            existing.protocol_type = protocol_type
            existing.streaming = streaming
            existing.supported_interfaces = supported_interfaces
            existing.raw_card = raw_card
            existing.cached_at = now
            existing.cache_expires_at = expires_at
            existing.updated_by = user_id
            agent = existing
        else:
            agent = A2AExternalAgent(
                name=name,
                description=description,
                version=version,
                agent_url=agent_url,
                protocol_type=protocol_type,
                streaming=streaming,
                supported_interfaces=supported_interfaces,
                source_type="nacos",
                nacos_config_id=nacos_config_id,
                nacos_agent_name=nacos_agent_name,
                tenant_id=tenant_id,
                created_by=user_id,
                updated_by=user_id,
                raw_card=raw_card,
                cached_at=now,
                cache_expires_at=expires_at,
                delete_flag='N'
            )
            session.add(agent)

        session.flush()

        return {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "version": agent.version,
            "agent_url": agent.agent_url,
            "protocol_type": agent.protocol_type,
            "streaming": agent.streaming,
            "supported_interfaces": agent.supported_interfaces,
            "source_type": agent.source_type,
            "is_available": agent.is_available,
            "cached_at": agent.cached_at.isoformat() if agent.cached_at else None,
            "cache_expires_at": agent.cache_expires_at.isoformat() if agent.cache_expires_at else None,
        }


def get_external_agent_by_id(external_agent_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get an external agent by its id.

    Args:
        external_agent_id: The external agent database ID.
        tenant_id: Tenant ID for isolation.

    Returns:
        Agent information dict or None if not found.
    """
    with _get_db_session() as session:
        agent = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.id == external_agent_id,
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return None

        return {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "version": agent.version,
            "agent_url": agent.agent_url,
            "streaming": agent.streaming,
            "protocol_type": agent.protocol_type,
            "supported_interfaces": agent.supported_interfaces,
            "source_type": agent.source_type,
            "source_url": agent.source_url,
            "nacos_config_id": agent.nacos_config_id,
            "nacos_agent_name": agent.nacos_agent_name,
            "raw_card": agent.raw_card,
            "is_available": agent.is_available,
            "last_check_at": agent.last_check_at.isoformat() if agent.last_check_at else None,
            "last_check_result": agent.last_check_result,
            "cached_at": agent.cached_at.isoformat() if agent.cached_at else None,
            "cache_expires_at": agent.cache_expires_at.isoformat() if agent.cache_expires_at else None,
            "create_time": agent.create_time.isoformat() if agent.create_time else None,
        }


def list_external_agents(
    tenant_id: str,
    source_type: Optional[str] = None,
    is_available: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """List all external agents for a tenant.

    Args:
        tenant_id: Tenant ID for isolation.
        source_type: Filter by source type (url or nacos).
        is_available: Filter by availability status.
        limit: Maximum number of results.
        offset: Number of results to skip.

    Returns:
        List of agent information dicts.
    """
    with _get_db_session() as session:
        query = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        )

        if source_type:
            query = query.filter(A2AExternalAgent.source_type == source_type)

        if is_available is not None:
            query = query.filter(A2AExternalAgent.is_available == is_available)

        agents = query.order_by(A2AExternalAgent.create_time.desc()).offset(offset).limit(limit).all()

        return [
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "version": agent.version,
                "agent_url": agent.agent_url,
                "streaming": agent.streaming,
                "protocol_type": agent.protocol_type,
                "supported_interfaces": agent.supported_interfaces,
                "source_type": agent.source_type,
                "is_available": agent.is_available,
                "last_check_result": agent.last_check_result,
                "create_time": agent.create_time.isoformat() if agent.create_time else None,
            }
            for agent in agents
        ]


def delete_external_agent(external_agent_id: int, tenant_id: str) -> bool:
    """Soft delete an external agent.

    Args:
        external_agent_id: The external agent database ID.
        tenant_id: Tenant ID for isolation.

    Returns:
        True if deleted, False if not found.
    """
    with _get_db_session() as session:
        agent = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.id == external_agent_id,
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return False

        agent.delete_flag = 'Y'
        return True


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
    supported_interfaces: Optional[List[Dict[str, Any]]],
    protocol_type: str
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


def update_external_agent_protocol(
    external_agent_id: int,
    tenant_id: str,
    protocol_type: str,
) -> Optional[Dict[str, Any]]:
    """Update the protocol type for an external agent.

    Args:
        external_agent_id: The external agent database ID.
        tenant_id: Tenant ID for isolation.
        protocol_type: New protocol type (JSONRPC, HTTP+JSON, or GRPC).

    Returns:
        Updated agent information dict or None if not found.
    """
    valid_protocols = [PROTOCOL_JSONRPC, PROTOCOL_HTTP_JSON, PROTOCOL_GRPC]
    if protocol_type not in valid_protocols:
        raise ValueError(f"Invalid protocol type: {protocol_type}. Must be one of {valid_protocols}")

    with _get_db_session() as session:
        agent = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.id == external_agent_id,
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return None

        agent.protocol_type = protocol_type

        # Update agent_url based on the selected protocol
        interface = _find_interface_by_protocol_type(
            agent.supported_interfaces,
            protocol_type
        )
        if interface:
            agent.agent_url = interface.get("url", agent.agent_url)

        agent.updated_time = datetime.now(timezone.utc)

        return {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "version": agent.version,
            "agent_url": agent.agent_url,
            "protocol_type": agent.protocol_type,
            "streaming": agent.streaming,
            "supported_interfaces": agent.supported_interfaces,
            "source_type": agent.source_type,
            "source_url": agent.source_url,
            "nacos_config_id": agent.nacos_config_id,
            "nacos_agent_name": agent.nacos_agent_name,
            "raw_card": agent.raw_card,
            "is_available": agent.is_available,
            "last_check_at": agent.last_check_at.isoformat() if agent.last_check_at else None,
            "last_check_result": agent.last_check_result,
            "cached_at": agent.cached_at.isoformat() if agent.cached_at else None,
            "cache_expires_at": agent.cache_expires_at.isoformat() if agent.cache_expires_at else None,
            "create_time": agent.create_time.isoformat() if agent.create_time else None,
            "update_time": agent.update_time.isoformat() if agent.update_time else None,
        }


def refresh_external_agent_cache(
    external_agent_id: int,
    tenant_id: str,
    user_id: str,
    new_raw_card: Optional[Dict[str, Any]] = None,
    new_agent_url: Optional[str] = None,
    new_name: Optional[str] = None,
    new_description: Optional[str] = None,
    new_version: Optional[str] = None,
    new_streaming: Optional[bool] = None,
    new_supported_interfaces: Optional[List[Dict[str, Any]]] = None,
    new_protocol_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Refresh the cache for an external agent.

    Args:
        external_agent_id: The external agent database ID.
        tenant_id: Tenant ID for isolation.
        user_id: User who requested the refresh.
        new_raw_card: Updated Agent Card JSON (if fetched).
        new_agent_url: Updated A2A endpoint URL.
        new_name: Updated agent name.
        new_description: Updated agent description.
        new_version: Updated agent version.
        new_streaming: Updated streaming capability.
        new_supported_interfaces: Updated supported interfaces.
        new_protocol_type: Updated protocol type (JSONRPC, HTTP+JSON, or GRPC).

    Returns:
        Updated agent information dict or None if not found.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=DEFAULT_CACHE_TTL_HOURS)

    with _get_db_session() as session:
        agent = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.id == external_agent_id,
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return None

        if new_raw_card is not None:
            agent.raw_card = new_raw_card
        if new_agent_url is not None:
            agent.agent_url = new_agent_url
        if new_name is not None:
            agent.name = new_name
        if new_description is not None:
            agent.description = new_description
        if new_version is not None:
            agent.version = new_version
        if new_streaming is not None:
            agent.streaming = new_streaming
        if new_supported_interfaces is not None:
            agent.supported_interfaces = new_supported_interfaces
        if new_protocol_type is not None:
            agent.protocol_type = new_protocol_type
            # Update agent_url based on the selected protocol type
            interface = _find_interface_by_protocol_type(
                agent.supported_interfaces,
                new_protocol_type
            )
            if interface:
                agent.agent_url = interface.get("url", agent.agent_url)

        agent.cached_at = now
        agent.cache_expires_at = expires_at
        agent.updated_by = user_id
        agent.last_check_at = now

        session.flush()

        return {
            "id": agent.id,
            "name": agent.name,
            "agent_url": agent.agent_url,
            "version": agent.version,
            "streaming": agent.streaming,
            "supported_interfaces": agent.supported_interfaces,
            "cached_at": agent.cached_at.isoformat() if agent.cached_at else None,
            "cache_expires_at": agent.cache_expires_at.isoformat() if agent.cache_expires_at else None,
        }


def update_agent_availability(
    external_agent_id: int,
    tenant_id: str,
    is_available: bool,
    check_result: Optional[str] = None
) -> bool:
    """Update the availability status of an external agent.

    Args:
        external_agent_id: The external agent database ID.
        tenant_id: Tenant ID for isolation.
        is_available: New availability status.
        check_result: Health check result (OK, ERROR, TIMEOUT).

    Returns:
        True if updated, False if not found.
    """
    with _get_db_session() as session:
        agent = session.query(A2AExternalAgent).filter(
            A2AExternalAgent.id == external_agent_id,
            A2AExternalAgent.tenant_id == tenant_id,
            A2AExternalAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return False

        agent.is_available = is_available
        agent.last_check_at = datetime.now(timezone.utc)
        if check_result:
            agent.last_check_result = check_result

        return True


# =============================================================================
# External Agent Relation Operations (Sub-agent)
# =============================================================================

def add_external_agent_relation(
    local_agent_id: int,
    external_agent_id: int,
    tenant_id: str,
    user_id: str
) -> Dict[str, Any]:
    """Add a relation between a local agent and an external A2A agent.

    Args:
        local_agent_id: Local parent agent ID.
        external_agent_id: External A2A agent database ID.
        tenant_id: Tenant ID for isolation.
        user_id: User who created the relation.

    Returns:
        Created relation information dict.

    Raises:
        ValueError: If relation already exists.
    """
    with _get_db_session() as session:
        # Check if relation already exists (not soft-deleted)
        existing = session.query(A2AExternalAgentRelation).filter(
            A2AExternalAgentRelation.local_agent_id == local_agent_id,
            A2AExternalAgentRelation.external_agent_id == external_agent_id,
            A2AExternalAgentRelation.tenant_id == tenant_id,
            A2AExternalAgentRelation.delete_flag != 'Y'
        ).first()

        if existing:
            raise ValueError("Relation already exists")

        # Check if there's a soft-deleted record and restore it
        deleted_record = session.query(A2AExternalAgentRelation).filter(
            A2AExternalAgentRelation.local_agent_id == local_agent_id,
            A2AExternalAgentRelation.external_agent_id == external_agent_id,
            A2AExternalAgentRelation.tenant_id == tenant_id,
            A2AExternalAgentRelation.delete_flag == 'Y'
        ).first()

        if deleted_record:
            # Restore the soft-deleted record
            deleted_record.delete_flag = 'N'
            deleted_record.is_enabled = True
            deleted_record.updated_by = user_id
            session.flush()
            return {
                "id": deleted_record.id,
                "local_agent_id": deleted_record.local_agent_id,
                "external_agent_id": deleted_record.external_agent_id,
                "is_enabled": deleted_record.is_enabled,
            }

        relation = A2AExternalAgentRelation(
            local_agent_id=local_agent_id,
            external_agent_id=external_agent_id,
            tenant_id=tenant_id,
            created_by=user_id,
            delete_flag='N'
        )
        session.add(relation)
        session.flush()

        return {
            "id": relation.id,
            "local_agent_id": relation.local_agent_id,
            "external_agent_id": relation.external_agent_id,
            "is_enabled": relation.is_enabled,
        }


def remove_external_agent_relation(
    local_agent_id: int,
    external_agent_id: int,
    tenant_id: str
) -> bool:
    """Remove a relation between a local agent and an external A2A agent.

    Args:
        local_agent_id: Local parent agent ID.
        external_agent_id: External A2A agent database ID.
        tenant_id: Tenant ID for isolation.

    Returns:
        True if removed, False if not found.
    """
    with _get_db_session() as session:
        relation = session.query(A2AExternalAgentRelation).filter(
            A2AExternalAgentRelation.local_agent_id == local_agent_id,
            A2AExternalAgentRelation.external_agent_id == external_agent_id,
            A2AExternalAgentRelation.tenant_id == tenant_id,
            A2AExternalAgentRelation.delete_flag != 'Y'
        ).first()

        if not relation:
            return False

        relation.delete_flag = 'Y'
        return True


def query_external_sub_agents(
    local_agent_id: int,
    tenant_id: str,
    version_no: int = 0
) -> List[Dict[str, Any]]:
    """Query external A2A agents configured as sub-agents for a local agent.

    Args:
        local_agent_id: Local parent agent ID.
        tenant_id: Tenant ID for isolation.
        version_no: Version number (currently not used, relations are global).

    Returns:
        List of external agent details with relation metadata.
    """
    with _get_db_session() as session:
        results = session.query(
            A2AExternalAgentRelation,
            A2AExternalAgent
        ).join(
            A2AExternalAgent,
            A2AExternalAgent.id == A2AExternalAgentRelation.external_agent_id
        ).filter(
            A2AExternalAgentRelation.local_agent_id == local_agent_id,
            A2AExternalAgentRelation.tenant_id == tenant_id,
            A2AExternalAgentRelation.delete_flag != 'Y',
            A2AExternalAgentRelation.is_enabled == True,
            A2AExternalAgent.delete_flag != 'Y',
            A2AExternalAgent.is_available == True
        ).all()

        return [
            {
                "id": agent.id,
                "relation_id": relation.id,
                "external_agent_id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "version": agent.version,
                "agent_url": agent.agent_url,
                "protocol_type": agent.protocol_type,
                "streaming": agent.streaming,
                "supported_interfaces": agent.supported_interfaces,
                "raw_card": agent.raw_card,
                "is_enabled": relation.is_enabled,
            }
            for relation, agent in results
        ]


def list_external_relations_by_local_agent(
    local_agent_id: int,
    tenant_id: str
) -> List[Dict[str, Any]]:
    """List all external agent relations for a local agent.

    Args:
        local_agent_id: Local parent agent ID.
        tenant_id: Tenant ID for isolation.

    Returns:
        List of relation information dicts.
    """
    with _get_db_session() as session:
        relations = session.query(
            A2AExternalAgentRelation,
            A2AExternalAgent
        ).join(
            A2AExternalAgent,
            A2AExternalAgent.id == A2AExternalAgentRelation.external_agent_id,
            isouter=True
        ).filter(
            A2AExternalAgentRelation.local_agent_id == local_agent_id,
            A2AExternalAgentRelation.tenant_id == tenant_id,
            A2AExternalAgentRelation.delete_flag != 'Y'
        ).all()

        return [
            {
                "id": relation.id,
                "local_agent_id": relation.local_agent_id,
                "external_agent_id": relation.external_agent_id,
                "is_enabled": relation.is_enabled,
                "external_agent_name": agent.name if agent else None,
                "external_agent_url": agent.agent_url if agent else None,
                "protocol_type": agent.protocol_type if agent else None,
                "create_time": relation.create_time.isoformat() if relation.create_time else None,
            }
            for relation, agent in relations
        ]


# =============================================================================
# A2A Server Agent Operations
# =============================================================================

def _make_default_interfaces(endpoint_id: str) -> List[Dict[str, Any]]:
    """Build default supportedInterfaces with correct A2A 1.0 format."""
    return [
        {"protocolBinding": PROTOCOL_JSONRPC, "url": f"/nb/a2a/{endpoint_id}/v1", "protocolVersion": "1.0"},
        {"protocolBinding": PROTOCOL_HTTP_JSON, "url": f"/nb/a2a/{endpoint_id}", "protocolVersion": "1.0"},
    ]


def _apply_server_agent_fields(
    agent,
    name: Optional[str],
    description: Optional[str],
    version: Optional[str],
    agent_url: Optional[str],
    streaming: bool,
    supported_interfaces: Optional[List[Dict[str, Any]]],
    card_overrides: Optional[Dict[str, Any]],
) -> None:
    """Apply optional fields to an existing A2AServerAgent instance."""
    if name is not None:
        agent.name = name
    if description is not None:
        agent.description = description
    if version is not None:
        agent.version = version
    if agent_url is not None:
        agent.agent_url = agent_url
    agent.streaming = streaming
    if supported_interfaces is not None:
        agent.supported_interfaces = supported_interfaces
    if card_overrides is not None:
        agent.card_overrides = card_overrides


def _serialize_server_agent(
    agent,
    include_unpublished: bool = False,
    include_user_info: bool = False,
) -> Dict[str, Any]:
    """Serialize an A2AServerAgent model to dict."""
    result = {
        "id": agent.id,
        "agent_id": agent.agent_id,
        "endpoint_id": agent.endpoint_id,
        "name": agent.name,
        "description": agent.description,
        "version": agent.version,
        "agent_url": agent.agent_url,
        "streaming": agent.streaming,
        "supported_interfaces": agent.supported_interfaces,
        "card_overrides": agent.card_overrides,
        "is_enabled": agent.is_enabled,
        "published_at": agent.published_at.isoformat() if agent.published_at else None,
    }
    if include_unpublished:
        result["unpublished_at"] = agent.unpublished_at.isoformat() if agent.unpublished_at else None
    if include_user_info:
        result["user_id"] = agent.user_id
        result["tenant_id"] = agent.tenant_id
    return result


def create_server_agent(
    agent_id: int,
    user_id: str,
    tenant_id: str,
    name: str,
    description: Optional[str] = None,
    version: Optional[str] = None,
    agent_url: Optional[str] = None,
    streaming: bool = False,
    supported_interfaces: Optional[List[Dict[str, Any]]] = None,
    card_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create or update an A2A Server agent registration.

    Args:
        agent_id: Local agent ID.
        user_id: Owner user ID.
        tenant_id: Tenant ID.
        name: Agent name exposed in Agent Card.
        description: Agent description exposed in Agent Card.
        version: Agent version exposed in Agent Card.
        agent_url: Primary A2A endpoint URL.
        streaming: Whether this agent supports SSE streaming.
        supported_interfaces: All supported interfaces array. If None, will be auto-generated.
        card_overrides: Optional Agent Card customizations.

    Returns:
        Created server agent information dict.
    """
    from datetime import datetime
    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        existing = session.query(A2AServerAgent).filter(
            A2AServerAgent.agent_id == agent_id,
            A2AServerAgent.tenant_id == tenant_id,
            A2AServerAgent.delete_flag != 'Y'
        ).first()

        if existing:
            endpoint_id = existing.endpoint_id
            if supported_interfaces is None:
                supported_interfaces = _make_default_interfaces(endpoint_id)
            _apply_server_agent_fields(
                existing, name, description, version, agent_url,
                streaming, supported_interfaces, card_overrides
            )
            existing.is_enabled = True
            existing.published_at = now
            existing.updated_by = user_id
            agent = existing
        else:
            endpoint_id = _generate_endpoint_id(agent_id)
            if supported_interfaces is None:
                supported_interfaces = _make_default_interfaces(endpoint_id)
            agent = A2AServerAgent(
                agent_id=agent_id,
                user_id=user_id,
                tenant_id=tenant_id,
                endpoint_id=endpoint_id,
                name=name,
                description=description,
                version=version,
                agent_url=agent_url,
                streaming=streaming,
                supported_interfaces=supported_interfaces,
                card_overrides=card_overrides,
                is_enabled=True,
                published_at=now,
                created_by=user_id,
                updated_by=user_id,
                delete_flag='N'
            )
            session.add(agent)

        session.flush()
        return _serialize_server_agent(agent, include_user_info=True)

def get_server_agent_by_endpoint(endpoint_id: str) -> Optional[Dict[str, Any]]:
    """Get an A2A Server agent by endpoint_id.

    Args:
        endpoint_id: The unique endpoint ID.

    Returns:
        Server agent information dict or None.
    """
    with _get_db_session() as session:
        agent = session.query(A2AServerAgent).filter(
            A2AServerAgent.endpoint_id == endpoint_id,
            A2AServerAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return None

        return _serialize_server_agent(agent, include_unpublished=True, include_user_info=True)


def get_server_agent_by_agent_id(agent_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get an A2A Server agent by local agent_id.

    Args:
        agent_id: Local agent ID.
        tenant_id: Tenant ID.

    Returns:
        Server agent information dict or None.
    """
    with _get_db_session() as session:
        agent = session.query(A2AServerAgent).filter(
            A2AServerAgent.agent_id == agent_id,
            A2AServerAgent.tenant_id == tenant_id,
            A2AServerAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return None

        return _serialize_server_agent(agent, include_user_info=True)


def enable_server_agent(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    version: Optional[str] = None,
    agent_url: Optional[str] = None,
    streaming: bool = False,
    supported_interfaces: Optional[List[Dict[str, Any]]] = None,
    card_overrides: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Enable A2A Server for an agent.

    Args:
        agent_id: Local agent ID.
        tenant_id: Tenant ID.
        user_id: User requesting the enable.
        name: Agent name exposed in Agent Card.
        description: Agent description exposed in Agent Card.
        version: Agent version exposed in Agent Card.
        agent_url: Primary A2A endpoint URL.
        streaming: Whether this agent supports SSE streaming.
        supported_interfaces: All supported interfaces array.
        card_overrides: Optional Agent Card customizations.

    Returns:
        Updated server agent information dict or None.
    """
    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        agent = session.query(A2AServerAgent).filter(
            A2AServerAgent.agent_id == agent_id,
            A2AServerAgent.tenant_id == tenant_id,
            A2AServerAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            endpoint_id = _generate_endpoint_id(agent_id)
            if supported_interfaces is None:
                supported_interfaces = _make_default_interfaces(endpoint_id)
            agent = A2AServerAgent(
                agent_id=agent_id,
                user_id=user_id,
                tenant_id=tenant_id,
                endpoint_id=endpoint_id,
                name=name or "Nexent Agent",
                description=description,
                version=version,
                agent_url=agent_url,
                streaming=streaming,
                supported_interfaces=supported_interfaces,
                card_overrides=card_overrides,
                is_enabled=True,
                published_at=now,
                created_by=user_id,
                updated_by=user_id,
                delete_flag='N'
            )
            session.add(agent)
        else:
            _apply_server_agent_fields(
                agent, name, description, version, agent_url,
                streaming, supported_interfaces, card_overrides
            )
            agent.is_enabled = True
            agent.published_at = now
            agent.unpublished_at = None
            agent.updated_by = user_id

        session.flush()
        return _serialize_server_agent(agent)


def disable_server_agent(agent_id: int, tenant_id: str, user_id: str) -> bool:
    """Disable A2A Server for an agent.

    Args:
        agent_id: Local agent ID.
        tenant_id: Tenant ID.
        user_id: User requesting the disable.

    Returns:
        True if disabled, False if not found.
    """
    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        agent = session.query(A2AServerAgent).filter(
            A2AServerAgent.agent_id == agent_id,
            A2AServerAgent.tenant_id == tenant_id,
            A2AServerAgent.delete_flag != 'Y'
        ).first()

        if not agent:
            return False

        agent.is_enabled = False
        agent.unpublished_at = now
        agent.updated_by = user_id
        return True


def list_server_agents(tenant_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all A2A Server agents for a tenant.

    Args:
        tenant_id: Tenant ID.
        user_id: Optional filter by owner.

    Returns:
        List of server agent information dicts.
    """
    with _get_db_session() as session:
        query = session.query(A2AServerAgent).filter(
            A2AServerAgent.tenant_id == tenant_id,
            A2AServerAgent.delete_flag != 'Y'
        )

        if user_id:
            query = query.filter(A2AServerAgent.user_id == user_id)

        agents = query.order_by(A2AServerAgent.create_time.desc()).all()

        return [
            {
                "id": agent.id,
                "agent_id": agent.agent_id,
                "endpoint_id": agent.endpoint_id,
                "user_id": agent.user_id,
                "name": agent.name,
                "description": agent.description,
                "version": agent.version,
                "agent_url": agent.agent_url,
                "streaming": agent.streaming,
                "supported_interfaces": agent.supported_interfaces,
                "is_enabled": agent.is_enabled,
                "published_at": agent.published_at.isoformat() if agent.published_at else None,
                "unpublished_at": agent.unpublished_at.isoformat() if agent.unpublished_at else None,
            }
            for agent in agents
        ]


def get_server_agent_ids(tenant_id: str) -> set[int]:
    """Get all agent IDs that are registered as A2A Server agents.

    Args:
        tenant_id: Tenant ID.

    Returns:
        Set of agent IDs that have A2A Server registration.
    """
    with _get_db_session() as session:
        agent_ids = session.query(A2AServerAgent.agent_id).filter(
            A2AServerAgent.tenant_id == tenant_id,
            A2AServerAgent.delete_flag != 'Y'
        ).all()
        return {row[0] for row in agent_ids}


# =============================================================================
# A2A Task Operations (Server Role)
# =============================================================================

def create_task(
    task_id: Optional[str],
    endpoint_id: str,
    caller_user_id: Optional[str],
    caller_tenant_id: Optional[str],
    raw_request: Dict[str, Any],
    context_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new A2A task.

    Args:
        task_id: Optional task ID (generated if not provided).
        endpoint_id: The endpoint ID.
        caller_user_id: User ID of the caller.
        caller_tenant_id: Tenant ID of the caller.
        raw_request: Original A2A request payload.
        context_id: Optional context ID for grouping related tasks.

    Returns:
        Created task information dict.
    """
    if not task_id:
        task_id = _generate_task_id()

    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        task = A2ATask(
            id=task_id,
            endpoint_id=endpoint_id,
            caller_user_id=caller_user_id,
            caller_tenant_id=caller_tenant_id,
            raw_request=raw_request,
            task_state="TASK_STATE_SUBMITTED",
            state_timestamp=now,
            context_id=context_id,
            create_time=now,
            update_time=now
        )
        session.add(task)
        session.flush()

        return {
            "id": task.id,
            "endpoint_id": task.endpoint_id,
            "caller_user_id": task.caller_user_id,
            "caller_tenant_id": task.caller_tenant_id,
            "context_id": task.context_id,
            "task_state": task.task_state,
            "create_time": task.create_time.isoformat() if task.create_time else None,
        }


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Get an A2A task by ID.

    Args:
        task_id: The task ID.

    Returns:
        Task information dict or None.
    """
    with _get_db_session() as session:
        task = session.query(A2ATask).filter(A2ATask.id == task_id).first()

        if not task:
            return None

        return {
            "id": task.id,
            "endpoint_id": task.endpoint_id,
            "caller_user_id": task.caller_user_id,
            "caller_tenant_id": task.caller_tenant_id,
            "context_id": task.context_id,
            "raw_request": task.raw_request,
            "task_state": task.task_state,
            "state_timestamp": task.state_timestamp.isoformat() if task.state_timestamp else None,
            "result_data": task.result_data,
            "create_time": task.create_time.isoformat() if task.create_time else None,
            "update_time": task.update_time.isoformat() if task.update_time else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }


def update_task_state(
    task_id: str,
    task_state: str,
    result_data: Optional[Dict[str, Any]] = None
) -> bool:
    """Update the state of an A2A task.

    Args:
        task_id: The task ID.
        task_state: New task state (TASK_STATE_SUBMITTED, TASK_STATE_WORKING, TASK_STATE_COMPLETED, TASK_STATE_FAILED, TASK_STATE_CANCELED, TASK_STATE_INPUT_REQUIRED, TASK_STATE_REJECTED, TASK_STATE_AUTH_REQUIRED).
        result_data: Optional task result data.

    Returns:
        True if updated, False if not found.
    """
    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        task = session.query(A2ATask).filter(A2ATask.id == task_id).first()

        if not task:
            return False

        task.task_state = task_state
        task.state_timestamp = now
        task.update_time = now

        if result_data is not None:
            task.result_data = result_data

        # Mark completion time if task is done
        if task_state in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED"):
            task.completed_at = now

        return True


def list_tasks(
    endpoint_id: Optional[str] = None,
    caller_user_id: Optional[str] = None,
    caller_tenant_id: Optional[str] = None,
    task_state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """List A2A tasks with optional filters.

    Args:
        endpoint_id: Filter by endpoint.
        caller_user_id: Filter by caller.
        caller_tenant_id: Filter by tenant.
        task_state: Filter by task state.
        limit: Maximum number of results.
        offset: Number of results to skip.

    Returns:
        List of task information dicts.
    """
    with _get_db_session() as session:
        query = session.query(A2ATask)

        if endpoint_id:
            query = query.filter(A2ATask.endpoint_id == endpoint_id)
        if caller_user_id:
            query = query.filter(A2ATask.caller_user_id == caller_user_id)
        if caller_tenant_id:
            query = query.filter(A2ATask.caller_tenant_id == caller_tenant_id)
        if task_state:
            query = query.filter(A2ATask.task_state == task_state)

        tasks = query.order_by(A2ATask.create_time.desc()).offset(offset).limit(limit).all()

        return [
            {
                "id": task.id,
                "endpoint_id": task.endpoint_id,
                "caller_user_id": task.caller_user_id,
                "caller_tenant_id": task.caller_tenant_id,
                "context_id": task.context_id,
                "task_state": task.task_state,
                "result_data": task.result_data,
                "create_time": task.create_time.isoformat() if task.create_time else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            }
            for task in tasks
        ]


def list_tasks_paginated(
    endpoint_id: Optional[str] = None,
    caller_user_id: Optional[str] = None,
    caller_tenant_id: Optional[str] = None,
    task_state: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[Dict[str, Any]] = None
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    """List A2A tasks with cursor-based pagination.

    Args:
        endpoint_id: Filter by endpoint.
        caller_user_id: Filter by caller.
        caller_tenant_id: Filter by tenant.
        task_state: Filter by task state.
        limit: Maximum number of results.
        cursor: Optional cursor dict with update_time.

    Returns:
        Tuple of (tasks list, next_page_token or None).
    """
    import base64
    with _get_db_session() as session:
        query = session.query(A2ATask)

        if endpoint_id:
            query = query.filter(A2ATask.endpoint_id == endpoint_id)
        if caller_user_id:
            query = query.filter(A2ATask.caller_user_id == caller_user_id)
        if caller_tenant_id:
            query = query.filter(A2ATask.caller_tenant_id == caller_tenant_id)
        if task_state:
            query = query.filter(A2ATask.task_state == task_state)

        if cursor:
            cursor_time = cursor.get("update_time")
            if cursor_time:
                query = query.filter(A2ATask.update_time < cursor_time)

        tasks = query.order_by(A2ATask.update_time.desc()).limit(limit + 1).all()

        next_token = None
        if len(tasks) > limit:
            tasks = tasks[:limit]
            last_task = tasks[-1]
            next_token = base64.b64encode(json.dumps({
                "update_time": last_task.update_time.isoformat() if last_task.update_time else None
            }).encode()).decode()

        return (
            [
                {
                    "id": task.id,
                    "endpoint_id": task.endpoint_id,
                    "caller_user_id": task.caller_user_id,
                    "caller_tenant_id": task.caller_tenant_id,
                    "context_id": task.context_id,
                    "task_state": task.task_state,
                    "result_data": task.result_data,
                    "create_time": task.create_time.isoformat() if task.create_time else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                }
                for task in tasks
            ],
            next_token
        )


def cancel_task(task_id: str) -> bool:
    """Cancel an A2A task.

    Args:
        task_id: The task ID.

    Returns:
        True if canceled, False if not found or already completed.
    """
    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        task = session.query(A2ATask).filter(A2ATask.id == task_id).first()

        if not task:
            return False

        # Check if task is in terminal state
        if task.task_state in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED"):
            return False

        # Update task state to canceled
        task.task_state = "TASK_STATE_CANCELED"
        task.state_timestamp = now
        task.update_time = now
        task.completed_at = now

        return True


# =============================================================================
# A2A Message Operations
# =============================================================================

def create_message(
    task_id: Optional[str],
    role: str,
    parts: List[Dict[str, Any]],
    message_index: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    extensions: Optional[List[str]] = None,
    reference_task_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Create a new A2A message.

    Args:
        task_id: The task ID this message belongs to (can be None for simple requests).
        role: Message sender role ('user' or 'agent').
        parts: Message parts following A2A Part structure.
        message_index: Optional sequence index (auto-generated if not provided).
        metadata: Optional message metadata.
        extensions: Optional extension URI list.
        reference_task_ids: Optional referenced task IDs for multi-turn scenarios.

    Returns:
        Created message information dict.
    """
    message_id = _generate_message_id()
    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        # Auto-generate message_index if not provided
        if message_index is None:
            if task_id:
                max_index = session.query(A2AMessage).filter(
                    A2AMessage.task_id == task_id
                ).count()
            else:
                # For messages without task_id, use a separate counter
                # Get max message_index where task_id is also NULL
                max_result = session.query(A2AMessage.message_index).filter(
                    A2AMessage.task_id.is_(None)
                ).order_by(A2AMessage.message_index.desc()).first()
                max_index = max_result[0] + 1 if max_result else 0
            message_index = max_index

        message = A2AMessage(
            message_id=message_id,
            task_id=task_id,
            message_index=message_index,
            role=role,
            parts=parts,
            meta_data=metadata,
            extensions=extensions,
            reference_task_ids=reference_task_ids,
            create_time=now
        )
        session.add(message)
        session.flush()

        return {
            "message_id": message.message_id,
            "task_id": message.task_id,
            "message_index": message.message_index,
            "role": message.role,
            "parts": message.parts,
            "metadata": message.meta_data,
            "extensions": message.extensions,
            "reference_task_ids": message.reference_task_ids,
            "create_time": message.create_time.isoformat() if message.create_time else None,
        }


def get_messages_by_task(task_id: str) -> List[Dict[str, Any]]:
    """Get all messages for a task, ordered by message_index.

    Args:
        task_id: The task ID.

    Returns:
        List of message information dicts.
    """
    with _get_db_session() as session:
        messages = session.query(A2AMessage).filter(
            A2AMessage.task_id == task_id
        ).order_by(A2AMessage.message_index).all()

        return [
            {
                "message_id": msg.message_id,
                "task_id": msg.task_id,
                "message_index": msg.message_index,
                "role": msg.role,
                "parts": msg.parts,
                "metadata": msg.meta_data,
                "extensions": msg.extensions,
                "reference_task_ids": msg.reference_task_ids,
                "create_time": msg.create_time.isoformat() if msg.create_time else None,
            }
            for msg in messages
        ]


def get_message(message_id: str) -> Optional[Dict[str, Any]]:
    """Get a message by ID.

    Args:
        message_id: The message ID.

    Returns:
        Message information dict or None.
    """
    with _get_db_session() as session:
        message = session.query(A2AMessage).filter(
            A2AMessage.message_id == message_id
        ).first()

        if not message:
            return None

        return {
            "message_id": message.message_id,
            "task_id": message.task_id,
            "message_index": message.message_index,
            "role": message.role,
            "parts": message.parts,
            "metadata": message.meta_data,
            "extensions": message.extensions,
            "reference_task_ids": message.reference_task_ids,
            "create_time": message.create_time.isoformat() if message.create_time else None,
        }


# =============================================================================
# Nacos Config Operations
# =============================================================================

def create_nacos_config(
    name: str,
    nacos_addr: str,
    tenant_id: str,
    user_id: str,
    nacos_username: Optional[str] = None,
    nacos_password: Optional[str] = None,
    namespace_id: str = "public",
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Nacos configuration for external A2A agent discovery.

    Args:
        name: Display name.
        nacos_addr: Nacos server address.
        tenant_id: Tenant ID.
        user_id: User who created this config.
        nacos_username: Optional Nacos username.
        nacos_password: Optional Nacos password (encrypted).
        namespace_id: Nacos namespace.
        description: Optional description.

    Returns:
        Created config information dict.
    """
    import uuid
    config_id = f"nacos_{uuid.uuid4().hex[:16]}"

    with _get_db_session() as session:
        config = A2ANacosConfig(
            config_id=config_id,
            name=name,
            nacos_addr=nacos_addr,
            nacos_username=nacos_username,
            nacos_password=nacos_password,
            namespace_id=namespace_id,
            description=description,
            tenant_id=tenant_id,
            created_by=user_id,
            updated_by=user_id,
            delete_flag='N'
        )
        session.add(config)
        session.flush()

        return {
            "id": config.id,
            "config_id": config.config_id,
            "name": config.name,
            "nacos_addr": config.nacos_addr,
            "namespace_id": config.namespace_id,
            "is_active": config.is_active,
        }


def get_nacos_config_by_id(config_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get a Nacos config by config_id.

    Args:
        config_id: The config ID.
        tenant_id: Tenant ID for isolation.

    Returns:
        Config information dict or None.
    """
    with _get_db_session() as session:
        config = session.query(A2ANacosConfig).filter(
            A2ANacosConfig.config_id == config_id,
            A2ANacosConfig.tenant_id == tenant_id,
            A2ANacosConfig.delete_flag != 'Y'
        ).first()

        if not config:
            return None

        return {
            "id": config.id,
            "config_id": config.config_id,
            "name": config.name,
            "nacos_addr": config.nacos_addr,
            "nacos_username": config.nacos_username,
            "namespace_id": config.namespace_id,
            "description": config.description,
            "is_active": config.is_active,
            "last_scan_at": config.last_scan_at.isoformat() if config.last_scan_at else None,
        }


def list_nacos_configs(tenant_id: str, is_active: Optional[bool] = None) -> List[Dict[str, Any]]:
    """List all Nacos configs for a tenant.

    Args:
        tenant_id: Tenant ID.
        is_active: Optional filter by active status.

    Returns:
        List of config information dicts.
    """
    with _get_db_session() as session:
        query = session.query(A2ANacosConfig).filter(
            A2ANacosConfig.tenant_id == tenant_id,
            A2ANacosConfig.delete_flag != 'Y'
        )

        if is_active is not None:
            query = query.filter(A2ANacosConfig.is_active == is_active)

        configs = query.order_by(A2ANacosConfig.create_time.desc()).all()

        return [
            {
                "id": config.id,
                "config_id": config.config_id,
                "name": config.name,
                "nacos_addr": config.nacos_addr,
                "namespace_id": config.namespace_id,
                "is_active": config.is_active,
                "last_scan_at": config.last_scan_at.isoformat() if config.last_scan_at else None,
            }
            for config in configs
        ]


def update_nacos_config_last_scan(config_id: str, tenant_id: str) -> bool:
    """Update the last scan timestamp for a Nacos config.

    Args:
        config_id: The config ID.
        tenant_id: Tenant ID.

    Returns:
        True if updated, False if not found.
    """
    with _get_db_session() as session:
        config = session.query(A2ANacosConfig).filter(
            A2ANacosConfig.config_id == config_id,
            A2ANacosConfig.tenant_id == tenant_id,
            A2ANacosConfig.delete_flag != 'Y'
        ).first()

        if not config:
            return False

        config.last_scan_at = datetime.now(timezone.utc)
        return True


def delete_nacos_config(config_id: str, tenant_id: str) -> bool:
    """Soft delete a Nacos config.

    Args:
        config_id: The config ID.
        tenant_id: Tenant ID.

    Returns:
        True if deleted, False if not found.
    """
    with _get_db_session() as session:
        config = session.query(A2ANacosConfig).filter(
            A2ANacosConfig.config_id == config_id,
            A2ANacosConfig.tenant_id == tenant_id,
            A2ANacosConfig.delete_flag != 'Y'
        ).first()

        if not config:
            return False

        config.delete_flag = 'Y'
        return True


# =============================================================================
# A2A Artifact Operations
# =============================================================================

def _generate_artifact_id() -> str:
    """Generate a unique artifact ID."""
    return f"artifact_{uuid4().hex}"


def create_artifact(
    task_id: str,
    parts: List[Dict[str, Any]],
    artifact_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    extensions: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Create a new A2A artifact for a task.

    Args:
        task_id: The task ID this artifact belongs to (required, no standalone artifacts).
        parts: Artifact parts following A2A Part structure.
        artifact_id: Optional artifact ID (generated if not provided).
        name: Optional human-readable artifact name.
        description: Optional artifact description.
        metadata: Optional artifact metadata.
        extensions: Optional extension URI list.

    Returns:
        Created artifact information dict.
    """
    if not artifact_id:
        artifact_id = _generate_artifact_id()

    artifact_pk = _generate_artifact_id()
    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        artifact = A2AArtifact(
            id=artifact_pk,
            artifact_id=artifact_id,
            task_id=task_id,
            name=name,
            description=description,
            parts=parts,
            meta_data=metadata,
            extensions=extensions,
            create_time=now
        )
        session.add(artifact)
        session.flush()

        return {
            "id": artifact.id,
            "artifact_id": artifact.artifact_id,
            "task_id": artifact.task_id,
            "name": artifact.name,
            "description": artifact.description,
            "parts": artifact.parts,
            "metadata": artifact.meta_data,
            "extensions": artifact.extensions,
            "create_time": artifact.create_time.isoformat() if artifact.create_time else None,
        }


def get_artifacts_by_task(task_id: str) -> List[Dict[str, Any]]:
    """Get all artifacts for a task.

    Args:
        task_id: The task ID.

    Returns:
        List of artifact information dicts.
    """
    with _get_db_session() as session:
        artifacts = session.query(A2AArtifact).filter(
            A2AArtifact.task_id == task_id
        ).order_by(A2AArtifact.create_time).all()

        return [
            {
                "id": art.id,
                "artifact_id": art.artifact_id,
                "task_id": art.task_id,
                "name": art.name,
                "description": art.description,
                "parts": art.parts,
                "metadata": art.meta_data,
                "extensions": art.extensions,
                "create_time": art.create_time.isoformat() if art.create_time else None,
            }
            for art in artifacts
        ]


def get_artifact(artifact_id: str) -> Optional[Dict[str, Any]]:
    """Get an artifact by artifact_id.

    Args:
        artifact_id: The artifact ID.

    Returns:
        Artifact information dict or None.
    """
    with _get_db_session() as session:
        artifact = session.query(A2AArtifact).filter(
            A2AArtifact.artifact_id == artifact_id
        ).first()

        if not artifact:
            return None

        return {
            "id": artifact.id,
            "artifact_id": artifact.artifact_id,
            "task_id": artifact.task_id,
            "name": artifact.name,
            "description": artifact.description,
            "parts": artifact.parts,
            "metadata": artifact.meta_data,
            "extensions": artifact.extensions,
            "create_time": artifact.create_time.isoformat() if artifact.create_time else None,
        }
