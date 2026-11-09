# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.constants.constants import PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC, PROTOCOL_GRPC

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


from sqlalchemy.sql import func

from infrastructure.rdb.base import SCHEMA as SCHEMA, SimpleTableBase as SimpleTableBase, TableBase as TableBase


_PRIMARY_KEY_DOC = "Primary key, auto-increment"


_TENANT_ID_DOC = "Tenant ID for multi-tenancy isolation"


_PUBLISHER_TENANT_ID_DOC = "Publisher tenant ID"


_PUBLISHER_USER_ID_DOC = "Publisher user ID"


_MCP_NAME_DOC = "MCP name"


_INGROUP_PERMISSION_DOC = "In-group permission: EDIT, READ_ONLY, PRIVATE"
