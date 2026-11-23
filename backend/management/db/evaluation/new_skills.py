# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from sqlalchemy import text
from infrastructure.rdb.client import get_db_session


def matching_candidate(tenant, user, fid, model_id, revision):
    with get_db_session() as session:
        return session.scalar(
            text("""SELECT candidate_id FROM nexent.evolution_new_skill_candidate_t
            WHERE tenant_id=:tenant AND created_by=:user AND feedback_id=:fid AND model_id=:model AND model_revision=:revision"""),
            dict(tenant=tenant, user=user, fid=fid, model=model_id, revision=revision),
        )


def save_candidate(tenant, user, fid, feedback, description, digest, model):
    params = dict(
        tenant=tenant,
        user=user,
        fid=fid,
        agent=feedback["agent_id"],
        version=feedback["version_no"],
        name=feedback["brief"]["name"],
        description=description,
        digest=digest,
        model=model.model_id,
        revision=model.revision,
    )
    with get_db_session() as session:
        candidate = session.scalar(
            text("""INSERT INTO nexent.evolution_new_skill_candidate_t
            (tenant_id,agent_id,version_no,feedback_id,name,description,digest,model_id,model_revision,created_by)
            VALUES (:tenant,:agent,:version,:fid,:name,:description,:digest,:model,:revision,:user)
            ON CONFLICT DO NOTHING RETURNING candidate_id"""),
            params,
        )
        if candidate is None:
            candidate = session.execute(
                text("""SELECT candidate_id FROM nexent.evolution_new_skill_candidate_t
                WHERE tenant_id=:tenant AND created_by=:user AND feedback_id=:fid AND model_id=:model
                AND model_revision=:revision"""),
                params,
            ).scalar_one()
        return candidate


def find_candidate(tenant, cid):
    with get_db_session() as session:
        row = (
            session.execute(
                text("""SELECT candidate_id,agent_id,version_no,feedback_id,name,description,digest,
            model_id,model_revision,created_by FROM nexent.evolution_new_skill_candidate_t
            WHERE tenant_id=:tenant AND candidate_id=:cid"""),
                dict(tenant=tenant, cid=cid),
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None
