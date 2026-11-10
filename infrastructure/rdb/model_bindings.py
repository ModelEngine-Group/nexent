# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import select

from contracts.constants.constants import MODEL_CONFIG_MAPPING
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.model_records import get_model_by_model_id
from infrastructure.rdb.tenant_config_record import TenantConfig


def get_bound_model(tenant_id: str, slot: str) -> dict | None:
    """Resolve a tenant model binding without importing Management."""
    if not tenant_id:
        return None
    with get_db_session() as session:
        model_id = session.scalar(
            select(TenantConfig.config_value).where(
                TenantConfig.tenant_id == tenant_id,
                TenantConfig.config_key == MODEL_CONFIG_MAPPING[slot],
                TenantConfig.delete_flag == "N",
            ).limit(1)
        )
    try:
        model_id = int(model_id)
    except (TypeError, ValueError):
        return None
    return get_model_by_model_id(model_id, tenant_id)
