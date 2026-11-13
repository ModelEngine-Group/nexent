# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import TIMESTAMP, Boolean, Column, Index, Integer, Sequence, String, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import column_property

from infrastructure.rdb.base import SCHEMA, TableBase


class UserTenant(TableBase):
    """
    User and tenant relationship table
    """
    __tablename__ = "user_tenant_t"
    __table_args__ = {"schema": SCHEMA}

    user_tenant_id = Column(Integer, Sequence("user_tenant_t_user_tenant_id_seq", schema=SCHEMA),
                            primary_key=True, nullable=False, doc="User tenant relationship ID, unique primary key")
    user_id = Column(String(100), nullable=False, doc="User ID")
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")


class TenantGroupUser(TableBase):
    """
    Tenant group user membership table
    """
    __tablename__ = "tenant_group_user_t"
    __table_args__ = {"schema": SCHEMA}

    group_user_id = Column(Integer, Sequence("tenant_group_user_t_group_user_id_seq", schema=SCHEMA),
                           primary_key=True, nullable=False, doc="Group user ID, primary key")
    group_id = Column(Integer, nullable=False, doc="Group ID, foreign key")
    user_id = Column(String(100), nullable=False, doc="User ID, foreign key")


class TenantGroupInfo(TableBase):
    """
    Tenant group information table
    """
    __tablename__ = "tenant_group_info_t"
    __table_args__ = {"schema": SCHEMA}

    group_id = Column(Integer, Sequence("tenant_group_info_t_group_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, doc="Group ID, primary key")
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID, foreign key")
    group_name = Column(String(100), nullable=False, doc="Group name")
    group_description = Column(String(500), doc="Group description")


class UserAccount(TableBase):
    """Authentication identity independent of tenant membership and provider bindings."""

    __tablename__ = "user_account_t"
    __table_args__ = (
        Index("ix_user_account_user_id", "user_id"),
        Index("ix_user_account_email", "user_email"),
        {"schema": SCHEMA},
    )
    account_id = Column(Integer, Sequence("user_account_t_account_id_seq", schema=SCHEMA),
                        primary_key=True, comment="Technical account record identifier")
    user_id = Column(String(100), nullable=False, comment="Stable user identifier including legacy system IDs; service-serialized uniqueness")
    user_email = Column(String(255), comment="Normalized login email; null for passwordless identities")
    user_role = Column(String(30), comment="Canonical account role transferred from membership and maintained by identity services")
    password_hash = Column(String(512), comment="Encoded local or imported password hash; never returned to API callers")
    password_hash_scheme = Column(String(30), comment="Password encoding scheme: scrypt or imported bcrypt")
    password_login_enabled = Column(Boolean, nullable=False, server_default=text("false"),
                                    comment="Whether this identity permits password authentication")
    token_version = Column(Integer, nullable=False, server_default=text("0"),
                           comment="Credential revision; password changes invalidate earlier JWTs")
    email_confirmed_at = Column(TIMESTAMP(timezone=False), comment="UTC email confirmation time, null if unconfirmed")
    source_metadata = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"),
                             comment="Migration/provider provenance, API-only and system identity markers; never grants permissions")

# Read projections preserve established association query/response contracts.
# These expressions create no role/email columns on the association table.
UserTenant.user_role = column_property(
    select(UserAccount.user_role).where(UserAccount.user_id == UserTenant.user_id,
                                      UserAccount.delete_flag == "N").correlate_except(UserAccount).scalar_subquery().label("user_role")
)
UserTenant.user_email = column_property(
    select(UserAccount.user_email).where(UserAccount.user_id == UserTenant.user_id,
                                       UserAccount.delete_flag == "N").correlate_except(UserAccount).scalar_subquery().label("user_email")
)
