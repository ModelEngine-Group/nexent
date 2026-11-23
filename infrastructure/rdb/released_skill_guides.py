# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Version-specific read-only Skill packages mounted by published business Agents."""

from sqlalchemy import Column, Integer, BigInteger, String, Table, insert, select

from infrastructure.rdb.base import SCHEMA, TableBase
from infrastructure.rdb.client import get_db_session

release_guide = Table(
    "evolution_release_guide_t",
    TableBase.metadata,
    Column("tenant_id", String(100), primary_key=True),
    Column("agent_id", Integer, primary_key=True),
    Column("version_no", Integer, primary_key=True),
    Column("name", String(80), primary_key=True),
    Column("candidate_id", BigInteger, nullable=False),
    Column("digest", String(64), nullable=False),
    schema=SCHEMA,
)


def guides_for_version(session, tenant, agent, version):
    c = release_guide.c
    rows = session.execute(
        select(c.name, c.candidate_id, c.digest)
        .where(c.tenant_id == tenant, c.agent_id == agent, c.version_no == version)
        .order_by(c.name)
    ).mappings()
    return [dict(row) for row in rows]


def read_released_guides(tenant, agent, version):
    with get_db_session() as session:
        return guides_for_version(session, tenant, agent, version)


def publish_guides(session, tenant, agent, base, version, added):
    guides = guides_for_version(session, tenant, agent, base)
    if added:
        if any(row["name"] == added["name"] for row in guides):
            raise ValueError("A released Skill already has this name")
        guides.append(added)
    if guides:
        session.execute(
            insert(release_guide),
            [dict(tenant_id=tenant, agent_id=agent, version_no=version, **ref) for ref in guides],
        )
