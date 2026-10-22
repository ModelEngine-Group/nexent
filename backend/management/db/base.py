# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.constants.a2a import PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC, PROTOCOL_GRPC

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    text,
)


from sqlalchemy.dialects.postgresql import ARRAY, JSONB


from sqlalchemy.orm import DeclarativeBase


from sqlalchemy.sql import func


SCHEMA = "nexent"


_PRIMARY_KEY_DOC = "Primary key, auto-increment"


_TENANT_ID_DOC = "Tenant ID for multi-tenancy isolation"


_PUBLISHER_TENANT_ID_DOC = "Publisher tenant ID"


_PUBLISHER_USER_ID_DOC = "Publisher user ID"


_MCP_NAME_DOC = "MCP name"


_INGROUP_PERMISSION_DOC = "In-group permission: EDIT, READ_ONLY, PRIVATE"


class SimpleTableBase(DeclarativeBase):
    pass


class TableBase(DeclarativeBase):
    create_time = Column(TIMESTAMP(timezone=False),
                         server_default=func.now(), doc="Creation time")
    update_time = Column(TIMESTAMP(timezone=False), server_default=func.now(
    ), onupdate=func.now(), doc="Update time")
    created_by = Column(String(100), doc="Creator")
    updated_by = Column(String(100), doc="Updater")
    delete_flag = Column(String(1), default="N",
                         doc="Whether it is deleted. Optional values: Y/N")
    pass
