# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    Column,
    Index,
    Integer,
    Sequence,
    String,
    UniqueConstraint,
    text,
)


from sqlalchemy.dialects.postgresql import JSONB


from management.db.base import SCHEMA, SimpleTableBase, TableBase


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
    user_role = Column(
        String(30), doc="User role: SUPER_ADMIN, ADMIN, DEV, USER")
    user_email = Column(String(255), doc="User email address")


class PartnerMappingId(TableBase):
    """
    External-Internal ID mapping table for partners
    """
    __tablename__ = "partner_mapping_id_t"
    __table_args__ = {"schema": SCHEMA}

    mapping_id = Column(Integer, Sequence("partner_mapping_id_t_mapping_id_seq",
                        schema=SCHEMA), primary_key=True, nullable=False, doc="ID")
    external_id = Column(
        String(100), doc="The external id given by the outer partner")
    internal_id = Column(
        Integer, doc="The internal id of the other database table")
    mapping_type = Column(String(
        30), doc="Type of the external - internal mapping, value set: CONVERSATION")
    tenant_id = Column(String(100), doc="Tenant ID")
    user_id = Column(String(100), doc="User ID")


class TenantInvitationCode(TableBase):
    """
    Tenant invitation code information table
    """
    __tablename__ = "tenant_invitation_code_t"
    __table_args__ = {"schema": SCHEMA}

    invitation_id = Column(Integer, Sequence("tenant_invitation_code_t_invitation_id_seq", schema=SCHEMA),
                           primary_key=True, nullable=False, doc="Invitation ID, primary key")
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID, foreign key")
    invitation_code = Column(String(100), nullable=False,
                             unique=True, doc="Invitation code")
    group_ids = Column(String, doc="Associated group IDs list")
    capacity = Column(Integer, nullable=False, default=1,
                      doc="Invitation code capacity")
    expiry_date = Column(TIMESTAMP(timezone=False),
                         doc="Invitation code expiry date")
    status = Column(String(30), nullable=False,
                    doc="Invitation code status: IN_USE, EXPIRE, DISABLE, RUN_OUT")
    code_type = Column(String(30), nullable=False,
                       doc="Invitation code type: ADMIN_INVITE, DEV_INVITE, USER_INVITE")


class TenantInvitationRecord(TableBase):
    """
    Tenant invitation record table
    """
    __tablename__ = "tenant_invitation_record_t"
    __table_args__ = {"schema": SCHEMA}

    invitation_record_id = Column(Integer, Sequence("tenant_invitation_record_t_invitation_record_id_seq", schema=SCHEMA),
                                  primary_key=True, nullable=False, doc="Invitation record ID, primary key")
    invitation_id = Column(Integer, nullable=False,
                           doc="Invitation ID, foreign key")
    user_id = Column(String(100), nullable=False, doc="User ID")


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


class RolePermission(SimpleTableBase):
    """
    Role permission configuration table
    Note: This table does not have audit fields (create_time, update_time, etc.)
    """
    __tablename__ = "role_permission_t"
    __table_args__ = {"schema": SCHEMA}

    role_permission_id = Column(Integer, Sequence("role_permission_t_role_permission_id_seq", schema=SCHEMA),
                                primary_key=True, nullable=False, doc="Role permission ID, primary key")
    user_role = Column(String(30), nullable=False,
                       doc="User role: SU, ADMIN, DEV, USER")
    permission_category = Column(String(30), doc="Permission category")
    permission_type = Column(String(30), doc="Permission type")
    permission_subtype = Column(String(30), doc="Permission subtype")


class UserTokenInfo(TableBase):
    """
    User token (AK/SK) information table
    """
    __tablename__ = "user_token_info_t"
    __table_args__ = (
        Index("ux_user_token_access_key", "access_key", unique=True),
        Index("ix_user_token_user_active", "user_id", "delete_flag"),
        {"schema": SCHEMA},
    )

    token_id = Column(Integer, Sequence("user_token_info_t_token_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, doc="Token ID, unique primary key")
    access_key = Column(String(100), nullable=False, doc="Access Key (AK)")
    user_id = Column(String(100), nullable=False,
                     doc="User ID who owns this token")


class UserTokenUsageLog(TableBase):
    """
    User token usage log table
    """
    __tablename__ = "user_token_usage_log_t"
    __table_args__ = (
        Index(
            "ix_user_token_usage_active_token_time",
            "token_id",
            text("create_time DESC"),
            postgresql_include=["token_usage_id"],
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    token_usage_id = Column(Integer, Sequence("user_token_usage_log_t_token_usage_id_seq", schema=SCHEMA),
                            primary_key=True, nullable=False, doc="Token usage log ID, unique primary key")
    token_id = Column(Integer, nullable=False,
                      doc="Foreign key to user_token_info_t.token_id")
    call_function_name = Column(
        String(100), doc="API function name being called")
    related_id = Column(
        Integer, doc="Related resource ID (e.g., conversation_id)")
    meta_data = Column(
        JSONB, doc="Additional metadata for this usage log entry, stored as JSON")


class UserOAuthAccount(TableBase):
    __tablename__ = "user_oauth_account_t"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id",
                         name="uq_oauth_provider_user"),
        {"schema": SCHEMA},
    )

    oauth_account_id = Column(
        Integer,
        Sequence("user_oauth_account_t_oauth_account_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="OAuth account ID, primary key",
    )
    user_id = Column(String(100), nullable=False, doc="Supabase user UUID")
    provider = Column(
        String(30), nullable=False, doc="OAuth provider name: github, wechat, gde, link_app"
    )
    provider_user_id = Column(
        String(200), nullable=False, doc="User ID from the OAuth provider"
    )
    provider_email = Column(
        String(255), doc="Email address from the OAuth provider")
    provider_username = Column(
        String(200), doc="Display name from the OAuth provider")
    tenant_id = Column(String(100), doc="Tenant ID at time of linking")


class UserCasSession(TableBase):
    __tablename__ = "user_cas_session_t"
    __table_args__ = (
        Index("ix_user_cas_session_session_id", "session_id"),
        Index("ix_user_cas_session_user_id", "user_id"),
        Index("ix_user_cas_session_cas_user_id", "cas_user_id"),
        {"schema": SCHEMA},
    )

    cas_session_id = Column(
        Integer,
        Sequence("user_cas_session_t_cas_session_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="CAS session record ID",
    )
    session_id = Column(String(100), nullable=False, unique=True, doc="JWT session ID")
    user_id = Column(String(100), nullable=False, doc="Supabase user UUID")
    cas_user_id = Column(String(200), nullable=False, doc="User ID from CAS")
    cas_session_index = Column(String(500), doc="CAS SessionIndex or service ticket")
    status = Column(String(30), nullable=False, default="active", doc="active/revoked")
    expires_at = Column(TIMESTAMP(timezone=False), nullable=False, doc="Session expiration time")
    revoked_at = Column(TIMESTAMP(timezone=False), doc="Revocation time")
