# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SQLAlchemy model for the single system configuration table."""

from infrastructure.rdb.base import SCHEMA, TableBase
from sqlalchemy import Column, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB


RESOURCE_DENYLIST_KEY = "NL2AGENT_RESOURCE_DENYLIST"


class SystemConfiguration(TableBase):
    __tablename__ = "sys_configuration_t"
    __table_args__ = (
        Index(
            "ix_sys_configuration_active_key",
            "configuration_key",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    configuration_id = Column(
        Integer, primary_key=True, comment="System configuration record identifier"
    )
    configuration_key = Column(
        String(100),
        nullable=False,
        comment="Stable managed configuration key",
    )
    configuration_value = Column(
        JSONB,
        nullable=False,
        comment="Validated configuration value",
    )
