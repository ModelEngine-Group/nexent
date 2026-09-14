import logging
from typing import Dict

from database.client import get_db_session
from database.db_models import MemoryProviderConfigParam


def get_params(provider_config_id: int) -> Dict[str, str]:
    with get_db_session() as session:
        rows = session.query(MemoryProviderConfigParam).filter(
            MemoryProviderConfigParam.provider_config_id == provider_config_id,
            MemoryProviderConfigParam.delete_flag == "N",
        ).all()
        return {row.param_name: row.param_value for row in rows}


def upsert_params(provider_config_id: int, params: Dict[str, str]) -> bool:
    with get_db_session() as session:
        try:
            session.query(MemoryProviderConfigParam).filter(
                MemoryProviderConfigParam.provider_config_id == provider_config_id,
                MemoryProviderConfigParam.delete_flag == "N",
            ).update({"delete_flag": "Y"})

            for name, value in params.items():
                session.add(MemoryProviderConfigParam(
                    provider_config_id=provider_config_id,
                    param_name=name,
                    param_value=value,
                ))

            session.commit()
            return True
        except Exception as e:
            logging.error(f"Failed to upsert params for provider_config_id={provider_config_id}: {e}", exc_info=True)
            session.rollback()
            return False


def delete_params(provider_config_id: int) -> bool:
    with get_db_session() as session:
        try:
            session.query(MemoryProviderConfigParam).filter(
                MemoryProviderConfigParam.provider_config_id == provider_config_id,
                MemoryProviderConfigParam.delete_flag == "N",
            ).update({"delete_flag": "Y"})
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False
