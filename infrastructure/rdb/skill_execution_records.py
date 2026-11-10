# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Skill persistence and read-only authorization for Runtime execution."""

from sqlalchemy import JSON, Boolean, Column, Index, Integer, Sequence, String, Text, select, text

from infrastructure.rdb.base import SCHEMA, TableBase


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
    ingroup_permission = Column(String(30), doc="In-group permission: EDIT, READ_ONLY, PRIVATE")


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


def read_bound_skills(agent_id: int, version_no: int, tenant_id: str) -> list[dict]:
    """Read enabled bindings scoped to the signed tenant and the selected Agent version."""
    from infrastructure.rdb.client import get_db_session

    statement = (
        select(
            SkillInstance.skill_instance_id, SkillInfo.skill_name, SkillInfo.skill_description,
            SkillInfo.config_values, SkillInstance.config_values,
        )
        .join(SkillInfo, SkillInfo.skill_id == SkillInstance.skill_id)
        .where(
            SkillInstance.agent_id == agent_id,
            SkillInstance.version_no == version_no,
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.enabled.is_(True),
            SkillInstance.delete_flag != "Y",
            SkillInfo.tenant_id == tenant_id,
            SkillInfo.delete_flag != "Y",
        )
    )
    with get_db_session() as session:
        return [
            {"instance_id": instance_id, "name": name, "description": description,
             "config": {**(defaults or {}), **(overrides or {})}}
            for instance_id, name, description, defaults, overrides in session.execute(statement)
        ]
