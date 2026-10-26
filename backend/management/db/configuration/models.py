# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    Column,
    Integer,
    Sequence,
    String,
    Text,
)


from management.db.base import SCHEMA, TableBase


class TenantConfig(TableBase):
    """
    Tenant configuration information table
    """
    __tablename__ = "tenant_config_t"
    __table_args__ = {"schema": SCHEMA}

    tenant_config_id = Column(Integer, Sequence(
        "tenant_config_t_tenant_config_id_seq", schema=SCHEMA), primary_key=True, nullable=False, doc="ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    user_id = Column(String(100), doc="User ID")
    value_type = Column(String(
        100), doc=" the data type of config_value, optional values: single/multi", default="single")
    config_key = Column(String(100), doc="the key of the config")
    config_value = Column(Text, doc="the value of the config")
