# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistence for reported public scores, outside business trial and nomination data."""

from sqlalchemy import select, text

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution_sources import task_digest
from infrastructure.rdb.client import get_db_session
from management.db.evaluation.models import EvolutionPublicBenchmark as Report


def _reports(tenant, experiment):
    return select(Report).where(
        Report.tenant_id == tenant, Report.experiment_id == experiment, Report.delete_flag == "N"
    )


def _view(row):
    return {
        "report_id": row.report_id,
        "experiment_id": row.experiment_id,
        "base_snapshot_digest": row.base_snapshot_digest,
        "candidate_snapshot_digest": row.candidate_snapshot_digest,
        "created_by": row.created_by,
        "create_time": row.create_time,
        **row.report,
    }


def add_report(tenant, user, experiment, report):
    digest = task_digest(report)
    with get_db_session() as session:
        # Serialize idempotent submissions without changing the experiment or its frozen plan.
        snapshots = session.scalar(text("""
            SELECT plan->'snapshots' FROM nexent.evolution_experiment_t
            WHERE tenant_id=:tenant AND experiment_id=:eid FOR UPDATE
        """), {"tenant": tenant, "eid": experiment})
        if snapshots is None:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        if not snapshots.get("base") or not snapshots.get("result"):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select a comparison with a baseline and a candidate")
        prior = session.scalar(_reports(tenant, experiment).where(Report.report_digest == digest))
        if prior is not None:
            return _view(prior)
        row = Report(tenant_id=tenant, experiment_id=experiment, report=report, report_digest=digest,
                     base_snapshot_digest=snapshots["base"], candidate_snapshot_digest=snapshots["result"],
                     created_by=user, updated_by=user, delete_flag="N")
        session.add(row)
        session.flush()
        return _view(row)


def list_reports(tenant, experiment, before, limit):
    with get_db_session() as session:
        query = _reports(tenant, experiment)
        if before is not None:
            query = query.where(Report.report_id < before)
        rows = session.scalars(query.order_by(Report.report_id.desc()).limit(limit + 1)).all()
        return {
            "items": [_view(row) for row in rows[:limit]],
            "next_before": rows[limit - 1].report_id if len(rows) > limit else None,
        }
