import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Float, select

from consts.error_code import ErrorCode
from consts.evaluation_status import EvalRunStatus
from consts.exceptions import AppException
from database.client import as_dict, get_db_session
from database.db_models import (
    AgentEvaluation,
    AgentEvaluationCase,
    AgentInfo,
    EvaluationSet,
    ModelRecord,
)


logger = logging.getLogger("agent_evaluation_db")


def create_agent_evaluation(
    tenant_id: str,
    agent_id: int,
    agent_version_no: int,
    evaluation_set_id: int,
    total: int,
    judge_model_id: int | None,
    created_by: str | None,
    evaluator_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with get_db_session() as session:
        rec = AgentEvaluation(
            tenant_id=tenant_id,
            agent_id=agent_id,
            agent_version_no=agent_version_no,
            evaluation_set_id=evaluation_set_id,
            status=EvalRunStatus.PENDING,
            progress_total=total,
            progress_done=0,
            judge_model_id=judge_model_id,
            evaluator_config=evaluator_config,
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
    updated_by: str | None = None,
    error_message: str | None = None,
    score_overall: float | None = None,
    progress_done: int | None = None,
    pass_count: int | None = None,
    fail_count: int | None = None,
) -> None:
    optional_fields = {
        "error_message": error_message,
        "score_overall": score_overall,
        "progress_done": progress_done,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }
    updates: dict[str, Any] = {
        "status": status,
        "updated_by": updated_by,
        **{k: v for k, v in optional_fields.items() if v is not None},
    }

    with get_db_session() as session:
        session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
        ).update(updates, synchronize_session=False)


def claim_agent_evaluation_run(
    agent_evaluation_id: int,
    tenant_id: str,
    updated_by: str | None = None,
) -> bool:
    """Atomically claim a pending evaluation for runtime execution.

    The conditional update makes dispatch idempotent when the config service
    retries an internal runtime request: only one runtime request can move a
    run from ``PENDING`` to ``RUNNING``.
    """
    with get_db_session() as session:
        updated = (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.status == EvalRunStatus.PENDING,
            )
            .update(
                {
                    "status": EvalRunStatus.RUNNING,
                    "updated_by": updated_by,
                },
                synchronize_session=False,
            )
        )
        session.commit()
        return updated == 1


def update_agent_evaluation_analysis_report(
    agent_evaluation_id: int,
    tenant_id: str,
    report: dict[str, Any],
) -> None:
    """Store the LLM-generated analysis report.

    Uses direct UPDATE to avoid triggering onupdate=func.now() on the row's
    update_time column, which represents the evaluation completion time.
    """
    with get_db_session() as session:
        session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
        ).update({"analysis_report": report}, synchronize_session=False)
        session.commit()


def get_agent_evaluation(agent_evaluation_id: int, tenant_id: str) -> dict[str, Any]:
    with get_db_session() as session:
        rec = (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
            )
            .first()
        )
        if not rec:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Agent evaluation not found"
            )
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
) -> list[dict[str, Any]]:
    """Return evaluation runs for an agent, most-recent first.

    ``limit == 0`` means "return all rows" (the caller has already narrowed
    the query to a single agent, so the window is bounded by the tenant's
    per-agent run count); otherwise ``limit``/``offset`` are applied as a
    normal pagination window.
    """
    with get_db_session() as session:
        q = (
            session.query(
                AgentEvaluation,
                EvaluationSet.name.label("evaluation_set_name"),
                ModelRecord.display_name.label("judge_model_name"),
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
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.agent_id == agent_id,
            )
            .order_by(AgentEvaluation.create_time.desc())
        )
        if limit > 0:
            q = q.offset(offset).limit(limit)
        rows = q.all()
        results = []
        for eval_row, evaluation_set_name, judge_model_name in rows:
            rec = as_dict(eval_row)
            rec["evaluation_set_name"] = evaluation_set_name
            rec["judge_model_name"] = judge_model_name
            rec["case_count"] = eval_row.progress_total or 0
            rec["pass_count"] = eval_row.pass_count or 0
            rec["fail_count"] = eval_row.fail_count or 0
            results.append(rec)
        return results


def create_agent_evaluation_cases(
    tenant_id: str,
    agent_evaluation_id: int,
    set_cases: list[dict[str, Any]],
    created_by: str | None,
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
                status=EvalRunStatus.PENDING,
                error_message=None,
                session_id=sc.get("session_id"),
                turn_order=int(sc.get("turn_order", 0)),
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
    predict: dict[str, Any] | None = None,
    score: Any = None,
    reason: str | None = None,
    error_message: str | None = None,
    pass_status: str | None = None,
    updated_by: str | None = None,
) -> None:
    """Update a case result.

    ``score`` may be float (single-eval), JSON string, or dict (multi-eval).
    The ``pass_status`` is determined by the caller (service layer).
    """
    optional_fields = {
        "predict": predict,
        "reason": reason,
        "score": score,
        "pass_status": pass_status,
        "error_message": error_message,
    }
    updates: dict[str, Any] = {
        "status": status,
        "updated_by": updated_by,
        **{k: v for k, v in optional_fields.items() if v is not None},
    }

    with get_db_session() as session:
        rows = (
            session.query(AgentEvaluationCase)
            .filter(
                AgentEvaluationCase.agent_evaluation_case_id
                == agent_evaluation_case_id,
                AgentEvaluationCase.tenant_id == tenant_id,
            )
            .update(updates, synchronize_session=False)
        )
        if rows == 0:
            logger.warning(
                "agent_evaluation_case not updated: id=%s, tenant=%s",
                agent_evaluation_case_id,
                tenant_id,
            )


def _apply_annotation_filters(
    base, session, anno_schema_ids, anno_values, tenant_id
):
    """Apply AND-combined annotation EXISTS/IN filters to *base*.

    Returns ``(base, anno_pairs)`` where *anno_pairs* is the number of
    (schema, value) pairs actually applied.  Mismatched-length lists are
    silently ignored.
    """
    from database.db_models import EvaluationAnnotation

    if not (
        anno_schema_ids
        and anno_values
        and len(anno_schema_ids) == len(anno_values)
    ):
        return base, 0
    for sid, val in zip(anno_schema_ids, anno_values):
        anno_subq = session.query(EvaluationAnnotation.case_id).filter(
            EvaluationAnnotation.tenant_id == tenant_id,
            EvaluationAnnotation.schema_id == sid,
        )
        # val == "" is used by the UI as a "not-null any-value" filter
        # so we intentionally do not add an equality predicate here.
        if val:
            anno_subq = anno_subq.filter(EvaluationAnnotation.value == val)
        base = base.filter(
            AgentEvaluationCase.agent_evaluation_case_id.in_(
                anno_subq.subquery()
            )
        )
    return base, len(anno_schema_ids)


def _apply_case_sorting(q, sort_by: str | None, sort_order: str):
    """Apply sorting to the case query.

    When *sort_by* is provided, sorts on the JSONB score field cast to float.
    Otherwise uses the session-aware default order that keeps multi-turn
    conversations clustered across pages.
    """
    if sort_by:
        # JSONB → text → float cast.  PostgreSQL returns NULL for missing
        # keys; the nullsfirst ordering keeps pending cases stable.
        score_field = AgentEvaluationCase.score[sort_by].astext.cast(Float)
        if sort_order == "desc":
            return q.order_by(score_field.desc().nullslast())
        return q.order_by(score_field.asc().nullsfirst())

    # Default: session-preserving order.
    #   1. Single-turn cases (no session_id) before any session bucket.
    #   2. By session_id ASC to keep a conversation's turns clustered.
    #   3. By turn_order ASC to sort turns chronologically inside a session.
    #   4. By PK as final tiebreaker when two rows share all fields.
    from sqlalchemy import case as sa_case

    return q.order_by(
        sa_case(
            (
                AgentEvaluationCase.session_id.is_(None)
                | (AgentEvaluationCase.session_id == ""),
                0,
            ),
            else_=1,
        ).asc(),
        AgentEvaluationCase.session_id.asc(),
        AgentEvaluationCase.turn_order.asc(),
        AgentEvaluationCase.agent_evaluation_case_id.asc(),
    )


def list_agent_evaluation_cases(
    agent_evaluation_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str | None = None,
    sort_order: str = "asc",
    pass_filter: str | None = None,
    anno_schema_ids: list[int] | None = None,
    anno_values: list[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Return paginated cases with total count for an evaluation run.

    Two mutually exclusive sort modes:

    * ``sort_by`` is provided — sort on a **single per-evaluator numeric score**
      extracted via JSONB subscript (e.g. ``sort_by = "accuracy"`` becomes
      ``score->>'accuracy'`` cast to float).  ``nullsfirst`` / ``nullslast``
      keeps the UI stable for partially-finished runs.
    * ``sort_by`` is **not** provided — use the **session-aware default order**.
      This is the critical ordering for multi-turn agents: single-turn cases
      (``session_id is NULL / ""``) float to the top followed by every
      multi-turn session clustered contiguously by
      ``(session_id, turn_order, agent_evaluation_case_id)``.  The ordering
      is applied **server side** (not in the client after fetch) so that
      paging across e.g. page 1 → page 2 cannot split a multi-turn session
      in the middle (which would otherwise break the conversation context
      in the case list UI).

    Filters (all AND-combined):

    * ``pass_filter`` — equality on ``pass_status`` ("pass" | "fail").
    * ``session_id`` — equality on ``session_id``.  The special sentinel
      ``"__single__"`` matches cases that have **no** session (``NULL`` or
      empty string), i.e. single-turn cases.  Combined with ``pass_filter``
      and the annotation pairs via AND.
    * ``anno_schema_ids[i] / anno_values[i]`` — zero or more annotation value
      pairs.  An empty value pair means "case has ANY value stored for this
      schema"; a non-empty pair means "stored value == anno_values[i]".
      Implemented via correlated IN-subqueries on ``evaluation_annotation_t``
      (tenant-scoped for isolation).  Only pairs of equal length are applied
      (mismatches are silently ignored — the caller gets the full unfiltered
      set and can investigate via logs).

    The per-row ``as_dict`` conversion intentionally has no per-row logging
    to avoid log storms on pages with hundreds of cases.
    """
    with get_db_session() as session:
        base = session.query(AgentEvaluationCase).filter(
            AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluationCase.tenant_id == tenant_id,
        )
        if pass_filter:
            base = base.filter(AgentEvaluationCase.pass_status == pass_filter)

        if session_id is not None:
            if session_id == "__single__":
                # Match cases WITHOUT a session (single-turn).  The column
                # stores NULL for legacy rows and "" for newer inserts.
                base = base.filter(
                    AgentEvaluationCase.session_id.is_(None)
                    | (AgentEvaluationCase.session_id == "")
                )
            else:
                base = base.filter(AgentEvaluationCase.session_id == session_id)

        base, anno_pairs = _apply_annotation_filters(
            base, session, anno_schema_ids, anno_values, tenant_id
        )

        total = base.count()
        q = _apply_case_sorting(base, sort_by, sort_order)

        items = [as_dict(x) for x in q.offset(offset).limit(limit).all()]
        logger.info(
            "list_agent_evaluation_cases: tenant=%s run=%s sort=%s pass=%s "
            "anno_pairs=%s total=%s window=%s..%s returned=%s",
            tenant_id,
            agent_evaluation_id,
            sort_by or "<session-default>",
            pass_filter or "<all>",
            anno_pairs,
            total,
            offset,
            offset + len(items),
            len(items),
        )
        return {"items": items, "total": total}


def get_evaluation_case_scores(
    agent_evaluation_id: int,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Return raw score/reason/pass rows for an evaluation run (ALL cases).

    **Unpaginated** on purpose.  The service layer consumes the full case
    corpus for:

    * Aggregate stats computation (per-evaluator mean / stdev / histogram buckets).
    * PDF report generation (every case appears in the case-detail table).
    * AI root-cause analysis (low-score case sampling by ``generate_analysis_report_impl``).

    Each returned dict carries only ``pass_status``, ``score`` and ``reason``
    — caller does not need the full ORM graph and stripping columns up front
    keeps payloads small for mid-sized evaluation sets.  The list-comprehension
    loop intentionally has no per-row logging.
    """
    with get_db_session() as session:
        rows = (
            session.query(AgentEvaluationCase)
            .filter(
                AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluationCase.tenant_id == tenant_id,
            )
            .all()
        )
        result = [
            {
                "pass_status": row.pass_status,
                "score": row.score,
                "reason": row.reason,
            }
            for row in rows
        ]
        logger.info(
            "get_evaluation_case_scores: tenant=%s run=%s total_cases=%s pass_count=%s fail_count=%s",
            tenant_id,
            agent_evaluation_id,
            len(result),
            sum(1 for r in result if r["pass_status"] == "pass"),
            sum(1 for r in result if r["pass_status"] == "fail"),
        )
        return result


def get_agent_evaluation_case(
    agent_evaluation_case_id: int, tenant_id: str
) -> dict[str, Any]:
    with get_db_session() as session:
        rec = (
            session.query(AgentEvaluationCase)
            .filter(
                AgentEvaluationCase.agent_evaluation_case_id
                == agent_evaluation_case_id,
                AgentEvaluationCase.tenant_id == tenant_id,
            )
            .first()
        )
        if not rec:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Agent evaluation case not found"
            )
        return as_dict(rec)


def update_annotation_schema_ids(
    agent_evaluation_id: int,
    tenant_id: str,
    schema_ids: list[int],
) -> int:
    """Save enabled annotation schema IDs for an evaluation run.

    Cascade-deletes annotation data for schemas that were removed from the list.
    Uses direct ``.update()`` to avoid resetting ``update_time`` via
    SQLAlchemy ``onupdate`` hook — same pattern as analysis_report.
    """
    with get_db_session() as session:
        from database.db_models import EvaluationAnnotation

        # Fetch old schema_ids to detect removals
        old_ids = (
            session.query(AgentEvaluation.annotation_schema_ids)
            .filter(
                AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
            )
            .scalar()
            or []
        )

        removed_ids = set(old_ids) - set(schema_ids)
        if removed_ids:
            session.query(EvaluationAnnotation).filter(
                EvaluationAnnotation.agent_evaluation_id == agent_evaluation_id,
                EvaluationAnnotation.tenant_id == tenant_id,
                EvaluationAnnotation.schema_id.in_(list(removed_ids)),
            ).delete(synchronize_session=False)

        affected = (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
            )
            .update(
                {"annotation_schema_ids": schema_ids},
                synchronize_session=False,
            )
        )
        session.commit()
        return affected


def count_active_runs_using_schema(schema_id: int, tenant_id: str) -> int:
    """Return the number of PENDING/RUNNING evaluation runs that have this schema enabled."""
    with get_db_session() as session:
        return (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.annotation_schema_ids.contains([schema_id]),
                AgentEvaluation.status.in_(
                    [EvalRunStatus.PENDING, EvalRunStatus.RUNNING]
                ),
            )
            .count()
        )


def hard_delete_agent_evaluation(
    agent_evaluation_id: int,
    tenant_id: str,
) -> None:
    """Hard-delete an evaluation run and its cases/annotations.

    The caller is responsible for cascade-deleting the virtual evaluation
    set (no-set mode) — see ``delete_agent_evaluation_run_impl``.
    """
    with get_db_session() as session:
        # Collect all case_ids belonging to this run before deleting them
        case_rows = (
            session.query(AgentEvaluationCase.agent_evaluation_case_id)
            .filter(
                AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluationCase.tenant_id == tenant_id,
            )
            .all()
        )
        case_ids = [row[0] for row in case_rows]

        # Cascade-delete annotations by case_id (more robust than by agent_evaluation_id
        # since agent_evaluation_id may be NULL on orphaned annotations)
        if case_ids:
            from database.db_models import EvaluationAnnotation

            session.query(EvaluationAnnotation).filter(
                EvaluationAnnotation.case_id.in_(case_ids),
                EvaluationAnnotation.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

        # Also delete any annotations directly linked by agent_evaluation_id
        from database.db_models import EvaluationAnnotation

        session.query(EvaluationAnnotation).filter(
            EvaluationAnnotation.agent_evaluation_id == agent_evaluation_id,
            EvaluationAnnotation.tenant_id == tenant_id,
        ).delete(synchronize_session=False)

        session.query(AgentEvaluationCase).filter(
            AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluationCase.tenant_id == tenant_id,
        ).delete(synchronize_session=False)
        session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
            AgentEvaluation.tenant_id == tenant_id,
        ).delete(synchronize_session=False)

        session.commit()


def cleanup_aged_evaluations(tenant_id: str, retention_days: int = 30) -> int:
    """Hard-delete evaluation runs older than retention_days. Returns count of deleted runs."""
    from database.evaluation_set_db import hard_delete_evaluation_set

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0
    with get_db_session() as session:
        aged = (
            session.query(
                AgentEvaluation.agent_evaluation_id,
                AgentEvaluation.evaluation_set_id,
                AgentEvaluation.evaluator_config,
            )
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.create_time < cutoff,
            )
            .all()
        )
        for eid, set_id, eval_config in aged:
            # Collect case_ids before deleting
            case_rows = (
                session.query(AgentEvaluationCase.agent_evaluation_case_id)
                .filter(
                    AgentEvaluationCase.agent_evaluation_id == eid,
                    AgentEvaluationCase.tenant_id == tenant_id,
                )
                .all()
            )
            case_ids = [row[0] for row in case_rows]

            # Cascade-delete annotations by case_id
            if case_ids:
                from database.db_models import EvaluationAnnotation

                session.query(EvaluationAnnotation).filter(
                    EvaluationAnnotation.case_id.in_(case_ids),
                    EvaluationAnnotation.tenant_id == tenant_id,
                ).delete(synchronize_session=False)

            # Also delete annotations by agent_evaluation_id
            from database.db_models import EvaluationAnnotation

            session.query(EvaluationAnnotation).filter(
                EvaluationAnnotation.agent_evaluation_id == eid,
                EvaluationAnnotation.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

            session.query(AgentEvaluationCase).filter(
                AgentEvaluationCase.agent_evaluation_id == eid,
            ).delete(synchronize_session=False)
            session.query(AgentEvaluation).filter(
                AgentEvaluation.agent_evaluation_id == eid,
            ).delete(synchronize_session=False)
            # Cascade hard-delete virtual evaluation sets created by no-set mode
            if isinstance(eval_config, dict) and eval_config.get("no_set_mode"):
                try:
                    hard_delete_evaluation_set(set_id, tenant_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to cascade-delete virtual set %d during cleanup: %s",
                        set_id,
                        exc,
                    )
            deleted += 1
        session.commit()
    return deleted


def reap_stale_runs(tenant_id: str, timeout_minutes: int = 10) -> int:
    """Mark RUNNING evaluations as FAILED if they haven't been updated recently.

    Handles the case where a server restart loses in-flight ``pool.submit()``
    tasks, leaving zombie RUNNING records.  Called on startup and periodically.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    count = 0
    with get_db_session() as session:
        stale = (
            session.query(AgentEvaluation.agent_evaluation_id)
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.status == EvalRunStatus.RUNNING,
                AgentEvaluation.update_time < cutoff,
            )
            .all()
        )
        stale_ids = [eid for (eid,) in stale]
        if stale_ids:
            error_message = "Server restarted — evaluation was interrupted"
            session.query(AgentEvaluationCase).filter(
                AgentEvaluationCase.agent_evaluation_id.in_(stale_ids),
                AgentEvaluationCase.tenant_id == tenant_id,
                AgentEvaluationCase.status.in_(("PENDING", "RUNNING")),
            ).update(
                {
                    "status": "FAILED",
                    "error_message": error_message,
                    "update_time": datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
            session.query(AgentEvaluation).filter(
                AgentEvaluation.agent_evaluation_id.in_(stale_ids),
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.status == EvalRunStatus.RUNNING,
            ).update(
                {
                    "status": EvalRunStatus.FAILED,
                    "error_message": error_message,
                    "update_time": datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
            count = len(stale_ids)
        session.commit()
    if count:
        logger.info(
            "Reaped %d stale RUNNING evaluations for tenant %s", count, tenant_id
        )
    return count


def list_evaluation_tenant_ids() -> list[str]:
    """Return tenants that currently own running evaluation work."""
    with get_db_session() as session:
        rows = (
            session.query(AgentEvaluation.tenant_id)
            .filter(
                AgentEvaluation.status == EvalRunStatus.RUNNING,
                AgentEvaluation.delete_flag == "N",
            )
            .distinct()
            .all()
        )
        return [str(tenant_id) for (tenant_id,) in rows if tenant_id is not None]


def fail_interrupted_no_set_runs_on_startup() -> int:
    """Fail no-set setup work that cannot be resumed after config restart.

    Regular pending runs already have a durable evaluation set and can be
    redispatched by evaluation maintenance. A no-set run with set ID ``0`` is
    still generating its temporary cases in process memory, so it has no
    durable continuation point.
    """
    with get_db_session() as session:
        pending_ids = [
            evaluation_id
            for (evaluation_id,) in session.query(
                AgentEvaluation.agent_evaluation_id
            )
            .filter(
                AgentEvaluation.status == EvalRunStatus.PENDING,
                AgentEvaluation.evaluation_set_id == 0,
                AgentEvaluation.delete_flag == "N",
            )
            .all()
        ]
        if not pending_ids:
            return 0

        error_message = "Server restarted before evaluation execution started"
        update_time = datetime.now(timezone.utc)
        session.query(AgentEvaluationCase).filter(
            AgentEvaluationCase.agent_evaluation_id.in_(pending_ids),
            AgentEvaluationCase.status == "PENDING",
        ).update(
            {
                "status": "FAILED",
                "error_message": error_message,
                "update_time": update_time,
            },
            synchronize_session=False,
        )
        session.query(AgentEvaluation).filter(
            AgentEvaluation.agent_evaluation_id.in_(pending_ids),
            AgentEvaluation.status == EvalRunStatus.PENDING,
            AgentEvaluation.delete_flag == "N",
        ).update(
            {
                "status": EvalRunStatus.FAILED,
                "error_message": error_message,
                "update_time": update_time,
            },
            synchronize_session=False,
        )
        session.commit()
        return len(pending_ids)


def list_dispatchable_pending_runs() -> list[dict[str, Any]]:
    """Return pending evaluations that already have a durable case set."""
    with get_db_session() as session:
        rows = (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.status == EvalRunStatus.PENDING,
                AgentEvaluation.evaluation_set_id > 0,
                AgentEvaluation.delete_flag == "N",
            )
            .order_by(AgentEvaluation.create_time.asc())
            .all()
        )
        return [as_dict(row) for row in rows]


def count_active_runs(tenant_id: str) -> int:
    """Acquire row-level lock on active runs, then count within the same tx."""
    with get_db_session() as session:
        session.execute(
            select(AgentEvaluation.agent_evaluation_id)
            .where(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.status.in_(
                    [EvalRunStatus.PENDING, EvalRunStatus.RUNNING]
                ),
            )
            .with_for_update()
        )
        return (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.status.in_(
                    [EvalRunStatus.PENDING, EvalRunStatus.RUNNING]
                ),
            )
            .count()
        )


def count_total_runs(tenant_id: str) -> int:
    """Count all non-deleted evaluation runs for a tenant."""
    with get_db_session() as session:
        return (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.tenant_id == tenant_id,
            )
            .count()
        )
