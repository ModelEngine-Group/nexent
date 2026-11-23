# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the frozen packages only for the released Agent's authorized Skill binding."""

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def read_bound_skill_candidate(tenant_id, agent_id, version_no, candidate_id):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT c.skill_id, c.base_digest, c.result_digest, i.skill_instance_id AS instance_id
            FROM nexent.evolution_skill_candidate_t c
            JOIN nexent.ag_skill_instance_t i ON i.tenant_id=c.tenant_id AND i.skill_id=c.skill_id
            JOIN nexent.ag_skill_info_t s ON s.tenant_id=i.tenant_id AND s.skill_id=i.skill_id
            WHERE c.candidate_id=:candidate AND c.tenant_id=:tenant AND i.agent_id=:agent
              AND i.version_no=:version AND i.enabled AND i.delete_flag='N'
              AND s.skill_name=c.skill_name AND s.delete_flag='N'
        """), dict(tenant=tenant_id, agent=agent_id, version=version_no, candidate=candidate_id)).mappings().one_or_none()
        return dict(row) if row else None
