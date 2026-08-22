from typing import Optional
from sqlalchemy.exc import SQLAlchemyError

from database.client import get_db_session
from database.db_models import PartnerMappingId


def add_mapping_id(
    internal_id: int,
    external_id: str,
    tenant_id: str,
    user_id: str,
    mapping_type: str = "CONVERSATION",
) -> None:
    """
    Add a mapping between internal_id and external_id.
    """
    try:
        with get_db_session() as session:
            session.add(PartnerMappingId(
                internal_id=internal_id,
                external_id=external_id,
                mapping_type=mapping_type,
                tenant_id=tenant_id,
                user_id=user_id,
                created_by=user_id,
                updated_by=user_id,
            ))
            session.commit()
    except Exception as e:
        raise e


def get_internal_id_by_external(
    external_id: str,
    mapping_type: str = "CONVERSATION",
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[int]:
    """
    Query internal_id by external_id with required mapping_type filter.
    Optionally filter by tenant_id and/or user_id.
    """
    try:
        with get_db_session() as session:
            query = session.query(PartnerMappingId).filter(
                PartnerMappingId.external_id == external_id,
                PartnerMappingId.mapping_type == mapping_type,
                PartnerMappingId.delete_flag != "Y",
            )
            if tenant_id is not None:
                query = query.filter(PartnerMappingId.tenant_id == tenant_id)
            if user_id is not None:
                query = query.filter(PartnerMappingId.user_id == user_id)

            record = query.first()
            return int(record.internal_id) if record and record.internal_id is not None else None
    except Exception as e:
        raise e


def get_external_id_by_internal(
    internal_id: int,
    mapping_type: str = "CONVERSATION",
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """
    Query external_id by internal_id with required mapping_type filter.
    Optionally filter by tenant_id and/or user_id.
    """
    try:
        with get_db_session() as session:
            query = session.query(PartnerMappingId).filter(
                PartnerMappingId.internal_id == internal_id,
                PartnerMappingId.mapping_type == mapping_type,
                PartnerMappingId.delete_flag != "Y",
            )
            if tenant_id is not None:
                query = query.filter(PartnerMappingId.tenant_id == tenant_id)
            if user_id is not None:
                query = query.filter(PartnerMappingId.user_id == user_id)

            record = query.first()
            return str(record.external_id) if record and record.external_id is not None else None
    except Exception as e:
        raise e
