"""
Database operations for external KB adapter registry (external_kb_adapter_t).
Provides CRUD helpers used by ExternalKnowledgeBaseService.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import ExternalKBAdapter

logger = logging.getLogger("external_kb_adapter_db")


def create_adapter(data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a new adapter record and return it as a dict.

    ``name`` defaults to the platform name if not provided.
    ``status`` defaults to 'running' (in-process adapters are always ready).
    ``service_host``, ``image_url``, ``container_name`` are stored as-is
    from the input dict (for backward compatibility).
    """
    platform = data.get("platform", "").lower()

    with get_db_session() as session:
        record = ExternalKBAdapter(
            name=data.get("name") or platform,
            platform=platform,
            image_url=data.get("image_url", ""),
            container_name=data.get("container_name", ""),
            service_host=data.get("service_host", ""),
            api_key=data.get("api_key", ""),
            capabilities=data.get("capabilities"),
            external_kb_config=data.get("external_kb_config"),
            tenant_id=data["tenant_id"],
            enabled=data.get("enabled", True),
            status=data.get("status", "running"),
            health_status=data.get("health_status", "unknown"),
            created_by=data.get("user_id"),
            updated_by=data.get("user_id"),
        )
        session.add(record)
        session.flush()
        return as_dict(record)


def get_adapter_by_id(adapter_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return a single adapter record or None."""
    with get_db_session() as session:
        record = (
            session.query(ExternalKBAdapter)
            .filter(
                ExternalKBAdapter.adapter_id == adapter_id,
                ExternalKBAdapter.tenant_id == tenant_id,
                ExternalKBAdapter.delete_flag == "N",
            )
            .first()
        )
        return as_dict(record) if record else None


def query_adapters_by_tenant(
    tenant_id: str, enabled_only: bool = False
) -> List[Dict[str, Any]]:
    """Return all adapter records for a tenant, optionally filtered by enabled."""
    with get_db_session() as session:
        q = session.query(ExternalKBAdapter).filter(
            ExternalKBAdapter.tenant_id == tenant_id,
            ExternalKBAdapter.delete_flag == "N",
        )
        if enabled_only:
            q = q.filter(ExternalKBAdapter.enabled == True)  # noqa: E712
        records = q.order_by(ExternalKBAdapter.adapter_id.asc()).all()
        return [as_dict(r) for r in records]


def update_adapter(
    adapter_id: int, tenant_id: str, updates: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Apply a partial update dict to an existing adapter record."""
    with get_db_session() as session:
        record = (
            session.query(ExternalKBAdapter)
            .filter(
                ExternalKBAdapter.adapter_id == adapter_id,
                ExternalKBAdapter.tenant_id == tenant_id,
                ExternalKBAdapter.delete_flag == "N",
            )
            .first()
        )
        if record is None:
            return None
        allowed = {
            "name", "platform", "image_url", "container_name", "service_host",
            "api_key", "capabilities", "external_kb_config", "enabled",
            "status", "health_status", "last_health_check", "updated_by",
        }
        for key, value in updates.items():
            if key in allowed:
                setattr(record, key, value)
        session.flush()
        return as_dict(record)


def update_adapter_status(
    adapter_id: int,
    tenant_id: str,
    status: str,
    health_status: Optional[str] = None,
) -> None:
    """Convenience wrapper to update container status and optional health_status."""
    updates: Dict[str, Any] = {"status": status}
    if health_status is not None:
        updates["health_status"] = health_status
        updates["last_health_check"] = datetime.utcnow()
    update_adapter(adapter_id, tenant_id, updates)


def delete_adapter(adapter_id: int, tenant_id: str) -> bool:
    """Soft-delete an adapter record. Returns True if found and deleted."""
    with get_db_session() as session:
        record = (
            session.query(ExternalKBAdapter)
            .filter(
                ExternalKBAdapter.adapter_id == adapter_id,
                ExternalKBAdapter.tenant_id == tenant_id,
                ExternalKBAdapter.delete_flag == "N",
            )
            .first()
        )
        if record is None:
            return False
        record.delete_flag = "Y"
        session.flush()
        return True


def upsert_adapter_by_platform(
    tenant_id: str, platform: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """Idempotent upsert: ensure exactly one adapter record exists for the
    given (tenant_id, platform) combination.

    Soft-deleted records (``delete_flag == 'Y'``) are resurrected: their
    delete flag is flipped back to 'N' and fields are refreshed from ``data``.
    Live records get a soft field refresh (name, status, enabled, capabilities,
    health_status, updated_by); ``external_kb_config`` is preserved so that
    operator-configured credentials are never clobbered by auto-provisioning.
    """
    platform = platform.lower()
    with get_db_session() as session:
        record = (
            session.query(ExternalKBAdapter)
            .filter(
                ExternalKBAdapter.tenant_id == tenant_id,
                ExternalKBAdapter.platform == platform,
            )
            .order_by(ExternalKBAdapter.adapter_id.asc())
            .first()
        )

        if record is not None:
            # Restore soft-deleted row
            if record.delete_flag == "Y":
                record.delete_flag = "N"

            # Refresh bookkeeping fields; preserve external_kb_config so that
            # operator edits to credentials/tenant settings survive re-provisioning.
            for attr in ("name", "status", "enabled", "capabilities",
                         "health_status", "updated_by"):
                if attr in data:
                    setattr(record, attr, data[attr])

            session.flush()
            return as_dict(record)

        # No row at all → insert a fresh record
        new_record = ExternalKBAdapter(
            name=data.get("name") or platform,
            platform=platform,
            image_url=data.get("image_url", ""),
            container_name=data.get("container_name", ""),
            service_host=data.get("service_host", ""),
            api_key=data.get("api_key", ""),
            capabilities=data.get("capabilities"),
            external_kb_config=data.get("external_kb_config"),
            tenant_id=tenant_id,
            enabled=data.get("enabled", True),
            status=data.get("status", "running"),
            health_status=data.get("health_status", "unknown"),
            created_by=data.get("user_id"),
            updated_by=data.get("user_id"),
        )
        session.add(new_record)
        session.flush()
        return as_dict(new_record)

