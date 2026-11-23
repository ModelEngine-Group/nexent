# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    Sequence,
    String,
    Text,
)


from sqlalchemy.dialects.postgresql import ARRAY, JSONB


from management.db.base import (
    SCHEMA,
    TableBase,
    _PUBLISHER_TENANT_ID_DOC,
    _PUBLISHER_USER_ID_DOC,
)
from infrastructure.rdb.skill_execution_records import (
    SkillInfo as SkillInfo,
    SkillInstance as SkillInstance,
    SkillToolRelation as SkillToolRelation,
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
