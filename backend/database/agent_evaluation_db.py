import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func, Integer
from database.client import as_dict, get_db_session
from database.db_models import AgentEvaluation, AgentEvaluationCase, EvaluationSet

logger = logging.getLogger("agent_evaluation_db")


def create_agent_evaluation(
    tenant_id: str,
    agent_id: int,
    agent_version_no: int,
    evaluation_set_id: int,
    total: int,
    created_by: Optional[str],
) -> Dict[str, Any]:
    with get_db_session() as session:
        rec = AgentEvaluation(
            tenant_id=tenant_id,
            agent_id=agent_id,
            agent_version_no=agent_version_no,
            evaluation_set_id=evaluation_set_id,
            status="PENDING",
            progress_total=total,
            progress_done=0,
            created_by=created_by,
            updated_by=created_by,
            delete_flag="N",
        )
        session.add(rec)
        session.flush()

        # Also fetch evaluation set name for the response
        es_row = (
            session.query(EvaluationSet.name)
            .filter(
                EvaluationSet.evaluation_set_id == evaluation_set_id,
                EvaluationSet.tenant_id == tenant_id,
            )
            .scalar()
        )

        result = as_dict(rec)
        result["evaluation_set_name"] = es_row
        return result


def update_agent_evaluation_status(
    agent_evaluation_id: int,
    tenant_id: str,
    status: str,
    updated_by: Optional[str] = None,
    error_message: Optional[str] = None,
    score_overall: Optional[float] = None,
    progress_done: Optional[int] = None,
) -> None:
    updates: Dict[str, Any] = {"status": status, "updated_by": updated_by}
    if error_message is not None:
        updates["error_message"] = error_message
    if score_overall is not None:
        updates["score_overall"] = score_overall
    if progress_done is not None:
        updates["progress_done"] = progress_done

    with get_db_session() as session:
        session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
            AgentEvaluation.delete_flag == "N",
        ).update(updates, synchronize_session=False)


def get_agent_evaluation(agent_evaluation_id: int, tenant_id: str) -> Dict[str, Any]:
    with get_db_session() as session:
        rec = session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
            AgentEvaluation.delete_flag == "N",
        ).first()
        if not rec:
            raise ValueError("agent evaluation not found")
        return as_dict(rec)


def list_agent_evaluations_by_agent(
    agent_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        pass_count_expr = func.sum(
            func.cast(
                AgentEvaluationCase.pass_status == "pass",
                Integer,
            )
        ).label("pass_count")

        q = (
            session.query(
                AgentEvaluation,
                EvaluationSet.name.label("evaluation_set_name"),
                func.count(AgentEvaluationCase.agent_evaluation_case_id).label("case_count"),
                pass_count_expr,
            )
            .outerjoin(
                EvaluationSet,
                (AgentEvaluation.evaluation_set_id == EvaluationSet.evaluation_set_id)
                & (AgentEvaluation.tenant_id == EvaluationSet.tenant_id),
            )
            .outerjoin(
                AgentEvaluationCase,
                AgentEvaluation.agent_evaluation_id == AgentEvaluationCase.agent_evaluation_id,
            )
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.agent_id == agent_id,
                AgentEvaluation.delete_flag == "N",
            )
            .group_by(AgentEvaluation.agent_evaluation_id, EvaluationSet.name)
            .order_by(AgentEvaluation.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = q.all()
        results = []
        for eval_row, evaluation_set_name, case_count, pass_count in rows:
            rec = as_dict(eval_row)
            rec["evaluation_set_name"] = evaluation_set_name
            rec["case_count"] = case_count or 0
            rec["pass_count"] = pass_count or 0
            rec["fail_count"] = (case_count or 0) - (pass_count or 0)
            results.append(rec)
        return results


def create_agent_evaluation_cases(
    tenant_id: str,
    agent_evaluation_id: int,
    set_cases: List[Dict[str, Any]],
    created_by: Optional[str],
) -> int:
    with get_db_session() as session:
        inserted = 0
        for sc in set_cases:
            rec = AgentEvaluationCase(
                tenant_id=tenant_id,
                agent_evaluation_id=agent_evaluation_id,
                evaluation_set_case_id=sc["evaluation_set_case_id"],
                inputs=sc["inputs"],
                label=sc["label"],
                predict=None,
                score=None,
                reason=None,
                status="PENDING",
                error_message=None,
                created_by=created_by,
                updated_by=created_by,
                delete_flag="N",
            )
            session.add(rec)
            inserted += 1
        session.flush()
        return inserted


def update_agent_evaluation_case_result(
    agent_evaluation_case_id: int,
    tenant_id: str,
    status: str,
    predict: Optional[Dict[str, Any]] = None,
    score: Optional[float] = None,
    reason: Optional[str] = None,
    error_message: Optional[str] = None,
    pass_status: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> None:
    """Update a case result.

    Storage policy: when a case is judged as ``pass`` (either via an explicit
    ``pass_status="pass"`` argument or an observed ``score == 1``), the heavy
    detail fields (``predict``, ``reason``, ``label.answer``) are cleared to
    save space. Only failed cases retain the full detail for debugging.
    """
    updates: Dict[str, Any] = {"status": status, "updated_by": updated_by}

    is_pass = (pass_status == "pass") or (score == 1)

    if not is_pass:
        if predict is not None:
            updates["predict"] = predict
        if reason is not None:
            updates["reason"] = reason
    else:
        # Pass case: trim heavy fields regardless of what was passed in.
        updates["predict"] = None
        updates["reason"] = None
        updates["label"] = {"answer": ""}

    if score is not None:
        updates["score"] = score
    if pass_status is not None:
        updates["pass_status"] = pass_status
    if error_message is not None:
        updates["error_message"] = error_message

    with get_db_session() as session:
        rows = session.query(AgentEvaluationCase).filter(
            AgentEvaluationCase.agent_evaluation_case_id == agent_evaluation_case_id,
            AgentEvaluationCase.tenant_id == tenant_id,
            AgentEvaluationCase.delete_flag == "N",
        ).update(updates, synchronize_session=False)
        if rows == 0:
            logger.warning(
                "agent_evaluation_case not updated: id=%s, tenant=%s",
                agent_evaluation_case_id,
                tenant_id,
            )


def list_agent_evaluation_cases(
    agent_evaluation_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        q = (
            session.query(AgentEvaluationCase)
            .filter(
                AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluationCase.tenant_id == tenant_id,
                AgentEvaluationCase.delete_flag == "N",
            )
            .order_by(AgentEvaluationCase.agent_evaluation_case_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return [as_dict(x) for x in q.all()]


def get_agent_evaluation_case(agent_evaluation_case_id: int, tenant_id: str) -> Dict[str, Any]:
    with get_db_session() as session:
        rec = session.query(AgentEvaluationCase).filter(
            AgentEvaluationCase.agent_evaluation_case_id == agent_evaluation_case_id,
            AgentEvaluationCase.tenant_id == tenant_id,
            AgentEvaluationCase.delete_flag == "N",
        ).first()
        if not rec:
            raise ValueError("agent evaluation case not found")
        return as_dict(rec)


def soft_delete_agent_evaluation(
    agent_evaluation_id: int,
    tenant_id: str,
    deleted_by: str,
) -> None:
    """Soft-delete an evaluation run by setting delete_flag='Y'.

    Raises ``ValueError`` when the run is not found or has already been deleted.
    """
    with get_db_session() as session:
        rows = session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
            AgentEvaluation.delete_flag == "N",
        ).update(
            {"delete_flag": "Y", "updated_by": deleted_by},
            synchronize_session=False,
        )
        if rows == 0:
            raise ValueError("agent evaluation not found or already deleted")
