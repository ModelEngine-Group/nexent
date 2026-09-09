import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import case as sql_case, func
from database.client import as_dict, get_db_session
from database.db_models import (
    AgentEvaluation, AgentEvaluationCase, AgentInfo, EvaluationSet,
    EvaluationSetCase, ModelMonitoringRecord, ModelRecord,
)

logger = logging.getLogger("agent_evaluation_db")


def create_agent_evaluation(
    tenant_id: str,
    agent_id: int,
    agent_version_no: int,
    evaluation_set_id: int,
    total: int,
    judge_model_id: Optional[int],
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
            judge_model_id=judge_model_id,
            created_by=created_by,
            updated_by=created_by,
            delete_flag="N",
        )
        session.add(rec)
        session.flush()

        es_row = (
            session.query(EvaluationSet.name)
            .filter(
                EvaluationSet.evaluation_set_id == evaluation_set_id,
                EvaluationSet.tenant_id == tenant_id,
            )
            .scalar()
        )

        judge_model_name = None
        if judge_model_id is not None:
            judge_model_name = (
                session.query(ModelRecord.display_name)
                .filter(
                    ModelRecord.model_id == judge_model_id,
                    ModelRecord.tenant_id == tenant_id,
                )
                .scalar()
            )

        result = as_dict(rec)
        result["evaluation_set_name"] = es_row
        result["judge_model_name"] = judge_model_name
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
        result = as_dict(rec)

        evaluation_set_name = (
            session.query(EvaluationSet.name)
            .filter(
                EvaluationSet.evaluation_set_id == rec.evaluation_set_id,
                EvaluationSet.tenant_id == tenant_id,
            )
            .scalar()
        )
        result["evaluation_set_name"] = evaluation_set_name

        agent_name = (
            session.query(AgentInfo.display_name, AgentInfo.name)
            .filter(
                AgentInfo.agent_id == rec.agent_id,
                AgentInfo.tenant_id == tenant_id,
            )
            .order_by(AgentInfo.version_no.desc())
            .first()
        )
        if agent_name is not None:
            display_name, programmatic_name = agent_name
            result["agent_name"] = display_name or programmatic_name or ""
        else:
            result["agent_name"] = ""

        judge_model_name = None
        if rec.judge_model_id is not None:
            judge_model_name = (
                session.query(ModelRecord.display_name, ModelRecord.model_name)
                .filter(
                    ModelRecord.model_id == rec.judge_model_id,
                    ModelRecord.tenant_id == tenant_id,
                )
                .first()
            )
            if judge_model_name is not None:
                judge_display, judge_repo = judge_model_name
                judge_model_name = judge_display or judge_repo
        result["judge_model_name"] = judge_model_name
        return result


def list_agent_evaluations_by_agent(
    agent_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        # ``case((<bool_expr>, 1), else_=0)`` translates to SQL
        # ``CASE WHEN <bool_expr> THEN 1 ELSE 0 END``, which is summed per row.
        # The previous ``func.cast(<bool_expr>, Integer)`` produced a single
        # constant (the Python-side truthiness of the whole comparison), making
        # every pass_count return 0. See CRITICAL-1 in the audit report.
        pass_count_expr = func.sum(
            sql_case(
                (AgentEvaluationCase.pass_status == "pass", 1),
                else_=0,
            )
        ).label("pass_count")

        # Monitoring has no evaluation ID; restrict matching to this run's offline calls.
        def monitoring_metric(expression):
            return session.query(expression).filter(
                ModelMonitoringRecord.tenant_id == AgentEvaluation.tenant_id,
                ModelMonitoringRecord.agent_id == AgentEvaluation.agent_id,
                ModelMonitoringRecord.user_id == AgentEvaluation.created_by,
                ModelMonitoringRecord.conversation_id == 0,
                ModelMonitoringRecord.delete_flag == "N",
                ModelMonitoringRecord.create_time >= AgentEvaluation.create_time,
                ModelMonitoringRecord.create_time <= AgentEvaluation.update_time,
            ).correlate(AgentEvaluation).scalar_subquery()

        q = (
            session.query(
                AgentEvaluation,
                EvaluationSet.name.label("evaluation_set_name"),
                ModelRecord.display_name.label("judge_model_name"),
                func.count(AgentEvaluationCase.agent_evaluation_case_id).label("case_count"),
                pass_count_expr,
                monitoring_metric(func.avg(ModelMonitoringRecord.request_duration_ms)),
                monitoring_metric(func.sum(ModelMonitoringRecord.total_tokens)),
                func.sum(sql_case(
                    (AgentEvaluationCase.status.in_(["COMPLETED", "FAILED"]), func.ceil((
                        func.length(func.coalesce(AgentEvaluationCase.inputs["query"].astext, ""))
                        + func.length(func.coalesce(AgentEvaluationCase.predict["answer"].astext, ""))
                    ) / 2.0)),
                    else_=0,
                )).label("estimated_tokens"),
            )
            .outerjoin(
                EvaluationSet,
                (AgentEvaluation.evaluation_set_id == EvaluationSet.evaluation_set_id)
                & (AgentEvaluation.tenant_id == EvaluationSet.tenant_id),
            )
            .outerjoin(
                ModelRecord,
                (AgentEvaluation.judge_model_id == ModelRecord.model_id)
                & (AgentEvaluation.tenant_id == ModelRecord.tenant_id),
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
            .group_by(
                AgentEvaluation.agent_evaluation_id,
                EvaluationSet.name,
                ModelRecord.display_name,
            )
            .order_by(AgentEvaluation.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = q.all()
        results = []
        for (
            eval_row, evaluation_set_name, judge_model_name, case_count,
            pass_count, duration_ms, tokens, estimated_tokens,
        ) in rows:
            rec = as_dict(eval_row)
            rec["evaluation_set_name"] = evaluation_set_name
            rec["judge_model_name"] = judge_model_name
            rec["case_count"] = case_count or 0
            rec["pass_count"] = pass_count or 0
            rec["fail_count"] = (case_count or 0) - (pass_count or 0)
            rec["total_tokens"] = int(tokens if tokens is not None else estimated_tokens or 0)
            rec["tokens_from_monitoring"] = tokens is not None
            rec["duration_from_monitoring"] = duration_ms is not None
            rec["avg_duration_seconds"] = None
            done = rec.get("progress_done") or 0
            started = rec.get("create_time")
            finished = rec.get("update_time")
            # Run timestamps include queueing and judging; this is an estimate per case.
            if duration_ms is not None:
                rec["avg_duration_seconds"] = round(float(duration_ms) / 1000, 2)
            elif done > 0 and started and finished:
                started = datetime.fromisoformat(started)
                finished = datetime.fromisoformat(finished)
                rec["avg_duration_seconds"] = round(max(0, (finished - started).total_seconds()) / done, 2)
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
    """Persist result details for both passed and failed cases."""
    updates: Dict[str, Any] = {"status": status, "updated_by": updated_by}
    if predict is not None:
        updates["predict"] = predict
    if reason is not None:
        updates["reason"] = reason

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
        results = [as_dict(x) for x in q.all()]
        missing_ids = [r["evaluation_set_case_id"] for r in results if not (r.get("label") or {}).get("answer")]
        if missing_ids:
            originals = session.query(EvaluationSetCase).filter(
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.evaluation_set_case_id.in_(missing_ids),
            ).all()
            labels = {c.evaluation_set_case_id: c.label for c in originals}
            for result in results:
                if not (result.get("label") or {}).get("answer"):
                    result["label"] = labels.get(result["evaluation_set_case_id"], result.get("label"))
        return results


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


def revise_agent_evaluation_case(
    agent_evaluation_id: int,
    agent_evaluation_case_id: int,
    tenant_id: str,
    user_id: str,
    pass_status: str,
) -> None:
    """Revise a terminal case and aggregate score in one serialized transaction."""
    if pass_status not in ("pass", "fail"):
        raise ValueError("Invalid pass status")
    with get_db_session() as session:
        run = session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
            AgentEvaluation.delete_flag == "N",
        ).with_for_update().first()
        if run is None:
            raise ValueError("Evaluation not found")
        if run.status not in ("COMPLETED", "FAILED"):
            raise ValueError("Evaluation is still running")
        record = session.query(AgentEvaluationCase).filter(
            AgentEvaluationCase.agent_evaluation_case_id == agent_evaluation_case_id,
            AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluationCase.tenant_id == tenant_id,
            AgentEvaluationCase.delete_flag == "N",
        ).first()
        if record is None:
            raise ValueError("Evaluation case not found")
        if record.status not in ("COMPLETED", "FAILED"):
            raise ValueError("Evaluation case has not finished")
        record.pass_status = pass_status
        record.score = 1.0 if pass_status == "pass" else 0.0
        record.updated_by = user_id
        session.flush()
        run.score_overall = session.query(func.avg(AgentEvaluationCase.score)).filter(
            AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluationCase.tenant_id == tenant_id,
            AgentEvaluationCase.delete_flag == "N",
        ).scalar() or 0.0
        run.updated_by = user_id
