from typing import Any, Dict, List, Optional

from database.client import filter_property, get_db_session
from database.db_models import MemoryProviderConfig


def _to_dict(item: MemoryProviderConfig) -> Dict[str, Any]:
    return {
        "provider_config_id": item.provider_config_id,
        "tenant_id": item.tenant_id,
        "provider_name": item.provider_name,
        "connection_type": item.connection_type,
        "enabled": item.enabled,
        "timeout_seconds": item.timeout_seconds,
        "last_error_code": item.last_error_code,
        "create_time": item.create_time.isoformat() if item.create_time else None,
        "update_time": item.update_time.isoformat() if item.update_time else None,
        "created_by": item.created_by,
        "updated_by": item.updated_by,
        "delete_flag": item.delete_flag,
    }


def get_provider_config(provider_config_id: int) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        item = session.query(MemoryProviderConfig).filter(
            MemoryProviderConfig.provider_config_id == provider_config_id,
            MemoryProviderConfig.delete_flag == "N",
        ).first()
        return _to_dict(item) if item else None


def get_provider_config_by_name(tenant_id: str, provider_name: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        item = session.query(MemoryProviderConfig).filter(
            MemoryProviderConfig.tenant_id == tenant_id,
            MemoryProviderConfig.provider_name == provider_name,
            MemoryProviderConfig.delete_flag == "N",
        ).first()
        return _to_dict(item) if item else None


def list_provider_configs(tenant_id: str, enabled_only: bool = False) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        query = session.query(MemoryProviderConfig).filter(
            MemoryProviderConfig.tenant_id == tenant_id,
            MemoryProviderConfig.delete_flag == "N",
        )
        if enabled_only:
            query = query.filter(MemoryProviderConfig.enabled == True)  # noqa: E712
        result = query.all()
        return [_to_dict(item) for item in result]


def insert_provider_config(data: Dict[str, Any]) -> Optional[int]:
    with get_db_session() as session:
        try:
            data = filter_property(data, MemoryProviderConfig)
            obj = MemoryProviderConfig(**data)
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj.provider_config_id
        except Exception:
            session.rollback()
            return None


def update_provider_config(provider_config_id: int, data: Dict[str, Any]) -> bool:
    with get_db_session() as session:
        try:
            data = filter_property(data, MemoryProviderConfig)
            session.query(MemoryProviderConfig).filter(
                MemoryProviderConfig.provider_config_id == provider_config_id,
                MemoryProviderConfig.delete_flag == "N",
            ).update(data)
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False


def soft_delete_provider_config(provider_config_id: int, updated_by: str) -> bool:
    with get_db_session() as session:
        try:
            session.query(MemoryProviderConfig).filter(
                MemoryProviderConfig.provider_config_id == provider_config_id,
                MemoryProviderConfig.delete_flag == "N",
            ).update({
                "delete_flag": "Y",
                "updated_by": updated_by,
            })
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False


def disable_provider_config(provider_config_id: int) -> bool:
    with get_db_session() as session:
        try:
            session.query(MemoryProviderConfig).filter(
                MemoryProviderConfig.provider_config_id == provider_config_id,
                MemoryProviderConfig.delete_flag == "N",
            ).update({"enabled": False})
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False
