# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    text,
)


from sqlalchemy.dialects.postgresql import ARRAY, JSONB


from management.db.base import (
    SCHEMA,
    TableBase,
    _INGROUP_PERMISSION_DOC,
    _PUBLISHER_TENANT_ID_DOC,
    _PUBLISHER_USER_ID_DOC,
)


class SkillRepository(TableBase):
    """
    Skill repository (marketplace) table. Frozen snapshot of a shared skill for installation.
    """
    __tablename__ = "ag_skill_repository_t"
    __table_args__ = {"schema": SCHEMA}

    skill_repository_id = Column(BigInteger, Sequence("ag_skill_repository_t_skill_repository_id_seq", schema=SCHEMA),
                                 primary_key=True, nullable=False, doc="Skill repository listing ID, unique primary key")
    publisher_tenant_id = Column(String(100), nullable=False, doc=_PUBLISHER_TENANT_ID_DOC)
    publisher_user_id = Column(String(100), nullable=False, doc=_PUBLISHER_USER_ID_DOC)
    skill_id = Column(Integer, nullable=False, doc="Source skill ID from ag_skill_info_t")
    name = Column(String(100), nullable=False, doc="Skill name for display and search")
    description = Column(Text, doc="Skill description")
    source = Column(String(30), doc="Skill source")
    submitted_by = Column(String(100), doc="Submitter email when listing enters pending_review")
    category_id = Column(Integer, doc="Optional marketplace category ID")
    tags = Column(ARRAY(Text), doc="Marketplace tags")
    icon = Column(String(100), doc="Marketplace card icon (emoji or URL)")
    downloads = Column(Integer, default=0, doc="Marketplace install count for card display")
    skill_info_json = Column(JSONB, nullable=False, doc="Frozen skill metadata snapshot")
    skill_zip_base64 = Column(Text, nullable=False, doc="Frozen skill ZIP payload encoded as base64")
    status = Column(String(30), default="not_shared",
                    doc="Listing status: not_shared / pending_review / rejected / shared")
    content = Column(Text, doc="Listing note on submit or review opinion on approve/reject")


class SkillInfo(TableBase):
    """
    Skill information table - stores skill metadata and content.
    """
    __tablename__ = "ag_skill_info_t"
    __table_args__ = (
        Index(
            "uq_skill_info_tenant_name_active",
            "tenant_id",
            "skill_name",
            unique=True,
            postgresql_where=text(
                "tenant_id IS NOT NULL AND delete_flag = 'N'"
            ),
        ),
        Index(
            "uq_skill_info_global_name_active",
            "skill_name",
            unique=True,
            postgresql_where=text(
                "tenant_id IS NULL AND delete_flag = 'N'"
            ),
        ),
        {"schema": SCHEMA},
    )

    skill_id = Column(Integer, Sequence("ag_skill_info_t_skill_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, autoincrement=True, doc="Skill ID")
    skill_name = Column(String(100), nullable=False,
                        doc="Skill name, unique among active skills within its tenant scope")
    tenant_id = Column(String(100), nullable=True,
                       doc="Tenant ID for multi-tenancy. NULL for pre-existing skills.")
    skill_description = Column(String(1000), doc="Skill description")
    skill_tags = Column(JSON, doc="Skill tags as JSON array")
    skill_content = Column(Text, doc="Skill content in markdown format")
    config_schemas = Column(
        JSON, doc="Parameter metadata from config/schema.yaml")
    config_values = Column(
        JSON, doc="Runtime parameter values from config/config.yaml")
    source = Column(String(30), nullable=False, default="official",
                    doc="Skill source: official, custom, etc.")
    group_ids = Column(String, doc="Skill group IDs list")
    ingroup_permission = Column(String(30), doc=_INGROUP_PERMISSION_DOC)


class SkillToolRelation(TableBase):
    """
    Skill-Tool relation table - many-to-many relationship between skills and tools.
    """
    __tablename__ = "ag_skill_tools_rel_t"
    __table_args__ = {"schema": SCHEMA}

    rel_id = Column(Integer, Sequence("ag_skill_tools_rel_t_rel_id_seq", schema=SCHEMA),
                    primary_key=True, nullable=False, autoincrement=True, doc="Relation ID")
    skill_id = Column(Integer, nullable=False,
                      doc="Foreign key to ag_skill_info_t.skill_id")
    tool_id = Column(Integer, nullable=False,
                     doc="Foreign key to ag_tool_info_t.tool_id")


class SkillInstance(TableBase):
    """
    Skill instance table - stores per-agent skill configuration.
    Similar to ToolInstance, stores skill settings for each agent version.
    Note: skill_description and skill_content removed - these are now retrieved from ag_skill_info_t.
    """
    __tablename__ = "ag_skill_instance_t"
    __table_args__ = {"schema": SCHEMA}

    skill_instance_id = Column(
        Integer,
        Sequence("ag_skill_instance_t_skill_instance_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Skill instance ID"
    )
    skill_id = Column(Integer, nullable=False,
                      doc="Foreign key to ag_skill_info_t.skill_id")
    agent_id = Column(Integer, nullable=False, doc="Agent ID")
    user_id = Column(String(100), doc="User ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    enabled = Column(Boolean, default=True,
                     doc="Whether this skill is enabled for the agent")
    version_no = Column(Integer, default=0, primary_key=True, nullable=False,
                        doc="Version number. 0 = draft/editing state, >=1 = published snapshot")
    config_values = Column(
        JSON, doc="Per-agent runtime parameter values (mirrors ag_tool_instance_t.params)")
    config_schemas = Column(
        JSON, doc="Per-agent parameter schema overrides from config/schema.yaml")
