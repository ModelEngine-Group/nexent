import logging
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import AgentEvaluation, AgentEvaluationCase

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
        return as_dict(rec)


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
        q = (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.agent_id == agent_id,
                AgentEvaluation.delete_flag == "N",
            )
            .order_by(AgentEvaluation.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return [as_dict(x) for x in q.all()]


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
    updated_by: Optional[str] = None,
) -> None:
    updates: Dict[str, Any] = {"status": status, "updated_by": updated_by}
    if predict is not None:
        updates["predict"] = predict
    if score is not None:
        updates["score"] = score
    if reason is not None:
        updates["reason"] = reason
    if error_message is not None:
        updates["error_message"] = error_message

    with get_db_session() as session:
        session.query(AgentEvaluationCase).filter(
            AgentEvaluationCase.agent_evaluation_case_id == agent_evaluation_case_id,
            AgentEvaluationCase.tenant_id == tenant_id,
            AgentEvaluationCase.delete_flag == "N",
        ).update(updates, synchronize_session=False)


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
