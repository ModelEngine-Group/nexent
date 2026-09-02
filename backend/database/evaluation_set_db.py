import logging
from typing import Any

from sqlalchemy import or_

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from database.client import as_dict, get_db_session
from database.db_models import AgentEvaluation, EvaluationSet, EvaluationSetCase


logger = logging.getLogger(__name__)


def create_evaluation_set(
    tenant_id: str,
    name: str,
    description: str | None,
    source_filename: str | None,
    created_by: str | None,
) -> dict[str, Any]:
    with get_db_session() as session:
        rec = EvaluationSet(
            tenant_id=tenant_id,
            name=name,
            description=description,
            source_filename=source_filename,
            created_by=created_by,
            updated_by=created_by,
            delete_flag="N",
        )
        session.add(rec)
        session.flush()
        return as_dict(rec)


def update_evaluation_set_case_count(
    evaluation_set_id: int, case_count: int, updated_by: str | None = None
) -> None:
    with get_db_session() as session:
        session.query(EvaluationSet).filter(
            EvaluationSet.evaluation_set_id == evaluation_set_id,
        ).update(
            {"case_count": case_count, "updated_by": updated_by},
            synchronize_session=False,
        )


def list_evaluation_sets(
    tenant_id: str, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    with get_db_session() as session:
        q = (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.tenant_id == tenant_id,
                # Hide virtual sets created by no-set evaluation mode.
                # - New virtual sets have source_filename='__no_set_virtual__'
                # - Old virtual sets (before the marker was added) have NULL source_filename
                #   but their names start with '运行时评测' or '[No-Set]'
                or_(
                    EvaluationSet.source_filename != "__no_set_virtual__",
                    EvaluationSet.source_filename.is_(None),
                ),
                ~EvaluationSet.name.startswith("运行时评测"),
                ~EvaluationSet.name.startswith("[No-Set]"),
            )
            .order_by(EvaluationSet.update_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return [as_dict(x) for x in q.all()]


def get_evaluation_set(evaluation_set_id: int, tenant_id: str) -> dict[str, Any] | None:
    with get_db_session() as session:
        rec = (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.evaluation_set_id == evaluation_set_id,
                EvaluationSet.tenant_id == tenant_id,
            )
            .first()
        )
        if not rec:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluation set not found"
            )
        return as_dict(rec)


def count_evaluation_sets(tenant_id: str) -> int:
    with get_db_session() as session:
        return (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.tenant_id == tenant_id,
            )
            .count()
        )


def insert_evaluation_set_cases(
    tenant_id: str,
    evaluation_set_id: int,
    cases: list[dict[str, Any]],
    created_by: str | None,
) -> int:
    """Insert cases. Each case must have: inputs(dict), label(dict), optional case_id(str).

    Returns inserted count.
    """
    with get_db_session() as session:
        inserted = 0
        for i, c in enumerate(cases):
            rec = EvaluationSetCase(
                tenant_id=tenant_id,
                evaluation_set_id=evaluation_set_id,
                case_id=c.get("case_id"),
                inputs=c["inputs"],
                label=c["label"],
                order_no=int(c.get("order_no", i)),
                session_id=c.get("session_id"),
                turn_order=int(c.get("turn_order", 0)),
                created_by=created_by,
                updated_by=created_by,
                delete_flag="N",
            )
            session.add(rec)
            inserted += 1
        session.flush()
        return inserted


def list_evaluation_set_cases(
    evaluation_set_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    query: str | None = None,
) -> list[dict[str, Any]]:
    with get_db_session() as session:
        q = session.query(EvaluationSetCase).filter(
            EvaluationSetCase.evaluation_set_id == evaluation_set_id,
            EvaluationSetCase.tenant_id == tenant_id,
            EvaluationSetCase.delete_flag == "N",
        )
        if query:
            q = q.filter(EvaluationSetCase.inputs["query"].astext.ilike(f"%{query}%"))
        q = (
            q.order_by(
                EvaluationSetCase.session_id.is_(None),
                EvaluationSetCase.session_id.asc(),
                EvaluationSetCase.turn_order.asc(),
                EvaluationSetCase.order_no.asc(),
                EvaluationSetCase.evaluation_set_case_id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return [as_dict(x) for x in q.all()]


def count_evaluation_set_cases(
    evaluation_set_id: int,
    tenant_id: str,
    query: str | None = None,
) -> int:
    with get_db_session() as session:
        q = session.query(EvaluationSetCase).filter(
            EvaluationSetCase.evaluation_set_id == evaluation_set_id,
            EvaluationSetCase.tenant_id == tenant_id,
            EvaluationSetCase.delete_flag == "N",
        )
        if query:
            q = q.filter(EvaluationSetCase.inputs["query"].astext.ilike(f"%{query}%"))
        return q.count()


def get_evaluation_set_cases_all(
    evaluation_set_id: int, tenant_id: str
) -> list[dict[str, Any]]:
    with get_db_session() as session:
        q = (
            session.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.delete_flag == "N",
            )
            .order_by(
                EvaluationSetCase.session_id.is_(None),
                EvaluationSetCase.session_id.asc(),
                EvaluationSetCase.turn_order.asc(),
                EvaluationSetCase.order_no.asc(),
                EvaluationSetCase.evaluation_set_case_id.asc(),
            )
        )
        return [as_dict(x) for x in q.all()]


def batch_delete_evaluation_set_cases(
    case_ids: list, tenant_id: str, evaluation_set_id: int
) -> int:
    """Hard-delete multiple cases in one query. Returns count of deleted rows."""
    if not case_ids:
        return 0
    with get_db_session() as session:
        rows = (
            session.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_case_id.in_(case_ids),
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
            )
            .delete(synchronize_session=False)
        )
        session.commit()
    return rows


def soft_delete_evaluation_set(
    evaluation_set_id: int,
    tenant_id: str,
    deleted_by: str | None = None,
) -> None:
    """Mark an evaluation set as deleted (soft delete via delete_flag='Y')."""
    with get_db_session() as session:
        rows = (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.evaluation_set_id == evaluation_set_id,
                EvaluationSet.tenant_id == tenant_id,
                EvaluationSet.delete_flag == "N",
            )
            .update(
                {"delete_flag": "Y", "updated_by": deleted_by},
                synchronize_session=False,
            )
        )
        if not rows:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND,
                "Evaluation set not found or already deleted",
            )
        session.commit()


def hard_delete_evaluation_set(evaluation_set_id: int, tenant_id: str) -> int:
    """Hard-delete an evaluation set and all its cases. Returns count of deleted rows."""
    deleted = 0
    with get_db_session() as session:
        session.query(EvaluationSetCase).filter(
            EvaluationSetCase.evaluation_set_id == evaluation_set_id,
            EvaluationSetCase.tenant_id == tenant_id,
        ).delete(synchronize_session=False)
        deleted += (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.evaluation_set_id == evaluation_set_id,
                EvaluationSet.tenant_id == tenant_id,
            )
            .delete(synchronize_session=False)
        )
        session.commit()
    return deleted


def recover_interrupted_generations() -> int:
    """Fail interrupted AI generations and remove only their appended cases.

    ``case_count`` is updated only when generation completes, so it is the
    durable pre-generation baseline. Generated rows are append-only; keeping
    the oldest baseline rows avoids adding a new generation-attempt column.
    """
    with get_db_session() as session:
        sets = (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.generation_status == "GENERATING",
                EvaluationSet.delete_flag == "N",
            )
            .with_for_update()
            .all()
        )
        for evaluation_set in sets:
            case_rows = (
                session.query(EvaluationSetCase.evaluation_set_case_id)
                .filter(
                    EvaluationSetCase.evaluation_set_id
                    == evaluation_set.evaluation_set_id,
                    EvaluationSetCase.tenant_id == evaluation_set.tenant_id,
                    EvaluationSetCase.delete_flag == "N",
                )
                .order_by(EvaluationSetCase.evaluation_set_case_id.asc())
                .all()
            )
            baseline_count = max(0, int(evaluation_set.case_count or 0))
            appended_ids = [case_id for (case_id,) in case_rows[baseline_count:]]
            if appended_ids:
                session.query(EvaluationSetCase).filter(
                    EvaluationSetCase.evaluation_set_case_id.in_(appended_ids)
                ).delete(synchronize_session=False)
            evaluation_set.generation_status = "FAILED"
            evaluation_set.generation_progress = 0
        return len(sets)


def cleanup_orphaned_virtual_evaluation_sets() -> int:
    """Delete no-set evaluation data that was never linked to a run."""
    with get_db_session() as session:
        referenced_set_ids = session.query(AgentEvaluation.evaluation_set_id).filter(
            AgentEvaluation.delete_flag == "N"
        )
        orphan_rows = (
            session.query(EvaluationSet.evaluation_set_id, EvaluationSet.tenant_id)
            .filter(
                EvaluationSet.source_filename == "__no_set_virtual__",
                EvaluationSet.delete_flag == "N",
                ~EvaluationSet.evaluation_set_id.in_(referenced_set_ids),
            )
            .all()
        )
        orphan_ids = [set_id for set_id, _ in orphan_rows]
        if orphan_ids:
            session.query(EvaluationSetCase).filter(
                EvaluationSetCase.evaluation_set_id.in_(orphan_ids)
            ).delete(synchronize_session=False)
            session.query(EvaluationSet).filter(
                EvaluationSet.evaluation_set_id.in_(orphan_ids)
            ).delete(synchronize_session=False)
        return len(orphan_ids)


def materialize_virtual_evaluation_set_for_run(
    *,
    tenant_id: str,
    name: str,
    cases: list[dict[str, Any]],
    created_by: str,
    agent_evaluation_id: int,
) -> int:
    """Atomically create a no-set dataset and attach it to a pending run."""
    with get_db_session() as session:
        run = (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.status == "PENDING",
                AgentEvaluation.delete_flag == "N",
            )
            .with_for_update()
            .first()
        )
        if run is None:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND,
                "Pending agent evaluation not found",
            )

        evaluation_set = EvaluationSet(
            tenant_id=tenant_id,
            name=name,
            description=None,
            source_filename="__no_set_virtual__",
            case_count=len(cases),
            generation_status="DONE",
            generation_progress=100,
            created_by=created_by,
            updated_by=created_by,
            delete_flag="N",
        )
        session.add(evaluation_set)
        session.flush()

        for index, case in enumerate(cases):
            session.add(
                EvaluationSetCase(
                    tenant_id=tenant_id,
                    evaluation_set_id=evaluation_set.evaluation_set_id,
                    inputs=case["inputs"],
                    label=case["label"],
                    order_no=int(case.get("order_no", index)),
                    session_id=case.get("session_id"),
                    turn_order=int(case.get("turn_order", 0)),
                    created_by=created_by,
                    updated_by=created_by,
                    delete_flag="N",
                )
            )

        run.evaluation_set_id = evaluation_set.evaluation_set_id
        run.progress_total = len(cases)
        run.updated_by = created_by
        session.flush()
        return int(evaluation_set.evaluation_set_id)


def list_case_turn_orders_by_session(
    evaluation_set_id: int,
    session_id: str,
    exclude_case_ids: list[int] | None = None,
) -> list[int]:
    """Return all turn_orders for a session, optionally excluding some case_ids."""
    with get_db_session() as session:
        q = session.query(EvaluationSetCase.turn_order).filter(
            EvaluationSetCase.evaluation_set_id == evaluation_set_id,
            EvaluationSetCase.session_id == session_id,
            EvaluationSetCase.delete_flag == "N",
        )
        if exclude_case_ids:
            q = q.filter(
                EvaluationSetCase.evaluation_set_case_id.notin_(exclude_case_ids)
            )
        rows = q.order_by(EvaluationSetCase.turn_order.asc()).all()
        return [r[0] for r in rows if r[0] is not None]


def get_case_ids_by_session(
    evaluation_set_id: int,
    session_id: str,
) -> list[int]:
    """Return all case_ids belonging to a session."""
    with get_db_session() as session:
        rows = (
            session.query(EvaluationSetCase.evaluation_set_case_id)
            .filter(
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
                EvaluationSetCase.session_id == session_id,
                EvaluationSetCase.delete_flag == "N",
            )
            .all()
        )
        return [r[0] for r in rows]


def get_cases_by_ids(
    case_ids: list[int],
    tenant_id: str,
    evaluation_set_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch case records by their IDs."""
    if not case_ids:
        return []
    with get_db_session() as session:
        q = session.query(EvaluationSetCase).filter(
            EvaluationSetCase.evaluation_set_case_id.in_(case_ids),
            EvaluationSetCase.tenant_id == tenant_id,
            EvaluationSetCase.delete_flag == "N",
        )
        if evaluation_set_id is not None:
            q = q.filter(EvaluationSetCase.evaluation_set_id == evaluation_set_id)
        rows = q.all()
        return [as_dict(r) for r in rows]
