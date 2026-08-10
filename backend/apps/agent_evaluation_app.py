import logging
from http import HTTPStatus
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from consts.error_code import ErrorCode
from consts.exceptions import AppException, UnauthorizedError

# AppException is caught by global middleware (maps ErrorCode to HTTP status)
from database.agent_evaluation_db import update_annotation_schema_ids
from services.agent_evaluation_service import (
    create_agent_evaluation_run_impl,
    delete_agent_evaluation_run_impl,
    generate_analysis_report_impl,
    get_agent_evaluation_run_impl,
    get_evaluation_stats_impl,
    list_agent_evaluation_cases_impl,
    list_agent_evaluations_by_agent_impl,
    trial_run_evaluator_impl,
)
from services.evaluation_report_service import generate_agent_evaluation_report_impl
from utils.auth_utils import get_current_user_id, get_current_user_info


logger = logging.getLogger("agent_evaluation_app")


def _ok(data=None):
    """Standard success response."""
    return JSONResponse(
        status_code=HTTPStatus.OK, content={"message": "Success", "data": data}
    )


router = APIRouter(prefix="/agent-evaluations")

# ── Pydantic models ─────────────────────────────────────────────────
# Grouped at the top per Nexent convention — easier to find and maintain
# than interleaving with endpoint functions.


class CreateEvaluationRequest(BaseModel):
    agent_id: int
    judge_model_id: int
    evaluator_ids: Optional[list] = None
    field_mappings: Optional[dict] = None
    # With-set mode
    evaluation_set_id: Optional[int] = None
    # No-set mode (AI generates test queries)
    agent_version_no: Optional[int] = None
    query_count: int = 10


class TrialRunRequest(BaseModel):
    agent_id: int
    agent_version_no: int = 1
    query: str
    judge_model_id: int
    evaluator_ids: Optional[List[int]] = None
    field_mappings: Optional[Dict[str, Any]] = None


# Module-level constants for Sonar python:S1192 — duplicated string
# literals (10x _AUTH_REQUIRED_MSG, 4x _UNKNOWN_ID) drag the
# New Code Reliability Rating from A to C when flagged as Critical.
_AUTH_REQUIRED_MSG = "Authentication required"
_UNKNOWN_ID = "<unknown>"


# ── Endpoints ───────────────────────────────────────────────────────
# Error-handling convention across endpoints:
# * AppException / UnauthorizedError are re-raised verbatim — the global
#   middleware is responsible for translating them to HTTP + JSON.
# * Unexpected ``Exception`` branches log CONTEXT keys
#   (tenant_id / user_id / agent_evaluation_id / payload_field_count)
#   BEFORE re-raising as SYSTEM_INTERNAL_ERROR.  This lets operators
#   reproduce the failing request without re-reading every access log.
# * Read-only GET endpoints emit only ERROR-level exceptions (no INFO
#   per fetch);  mutating endpoints (POST/PUT/DELETE) emit a single INFO
#   summary on success so audit trails are reconstructable.


@router.post("")
async def create_agent_evaluation_api(
    payload: CreateEvaluationRequest,
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """Create and queue a new agent-evaluation run.

    Two mutually exclusive execution modes are supported, selected by
    which fields the caller fills in:

    * **With-set mode** — ``evaluation_set_id`` is provided.  The runner
      uses cases from that evaluation set verbatim (no AI-generated
      queries).  This is the default for regression / release testing.
    * **No-set mode** — ``agent_version_no`` and ``query_count`` are
      provided and ``evaluation_set_id`` is left empty.  The runner asks
      the judge LLM to synthesize ``query_count`` test queries that are
      expected to exercise the agent's declared tool surface.  This mode
      exists for rapid experimentation before a real set is curated.

    Both modes share the same downstream pipeline; the call to
    ``create_agent_evaluation_run_impl`` freezes the evaluator IDs,
    judge model, field mappings, and language into a single immutable
    ``agent_evaluation_t`` row which the background worker then picks up.
    """
    try:
        user_id, tenant_id, language = get_current_user_info(authorization, request)
        run = create_agent_evaluation_run_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=payload.agent_id,
            judge_model_id=payload.judge_model_id,
            evaluation_set_id=payload.evaluation_set_id,
            agent_version_no=payload.agent_version_no,
            evaluator_ids=payload.evaluator_ids,
            field_mappings=payload.field_mappings,
            query_count=payload.query_count,
            language=language,
        )
        # Audit log: mode is derived from whether evaluation_set_id was
        # supplied.  Evaluator count and the query count (for no-set runs)
        # are included in case a later support ticket asks "what config
        # generated run #X?".
        mode = "with_set" if payload.evaluation_set_id is not None else "no_set"
        logger.info(
            "create_agent_evaluation_api OK: tenant=%s user=%s run_id=%s "
            "agent_id=%s mode=%s evaluator_count=%s query_count=%s judge_model=%s",
            tenant_id,
            user_id,
            run.get("agent_evaluation_id"),
            payload.agent_id,
            mode,
            len(payload.evaluator_ids or []),
            payload.query_count,
            payload.judge_model_id,
        )
        return _ok(run)

    except AppException:
        raise
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "create_agent_evaluation_api ERROR: tenant=%s user=%s agent_id=%s "
            "set_id=%s evaluator_count=%s query_count=%s err=%r",
            _safe_extract_tenant(authorization),
            _safe_extract_user(authorization),
            getattr(payload, "agent_id", None),
            getattr(payload, "evaluation_set_id", None),
            len(getattr(payload, "evaluator_ids", None) or []),
            getattr(payload, "query_count", None),
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to create agent evaluation"
        )


@router.get("")
async def list_agent_evaluations_by_agent_api(
    agent_id: int = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    """List evaluation runs belonging to a specific agent (most-recent first).

    Used by the agent detail page's "Evaluations" tab.  Result rows are
    pre-sorted by the DB layer and are tenant-scoped: callers never see
    rows created by a different tenant even if they can guess the
    ``agent_id``.

    ``limit`` is hard-clamped to [1, 200] at the FastAPI level (``le=200``)
    so no second clamp is needed inside the handler.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_agent_evaluations_by_agent_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
        return _ok(data)
    except AppException:
        raise
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "list_agent_evaluations_by_agent_api ERROR: tenant=%s agent_id=%s window=%s..%s err=%r",
            _safe_extract_tenant(authorization),
            agent_id,
            offset,
            offset + limit,
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list agent evaluations"
        )


@router.get("/{agent_evaluation_id}")
async def get_agent_evaluation_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
):
    """Fetch the top-level metadata row for a single evaluation run.

    The returned dict carries everything the detail header needs:
    status, overall score, pass/fail counts (via ``total_cases`` +
    ``completed_cases``), evaluator-config preview, created-by +
    started-at + finished-at timestamps, and (when ready) the cached
    ``analysis_report`` JSON blob rendered in the right-hand panel.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = get_agent_evaluation_run_impl(
            agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
        )
        return _ok(data)
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "get_agent_evaluation_api ERROR: tenant=%s run_id=%s err=%r",
            _safe_extract_tenant(authorization),
            agent_evaluation_id,
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to get agent evaluation"
        )


@router.get("/{agent_evaluation_id}/cases")
async def list_agent_evaluation_cases_api(
    agent_evaluation_id: int,
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: Optional[str] = Query(None),
    sort_order: str = Query("asc"),
    pass_filter: Optional[str] = Query(None),
    anno_schema_id: List[int] = Query([]),
    anno_value: List[str] = Query([]),
    authorization: Optional[str] = Header(None),
):
    """Return a paginated window of cases for an evaluation run.

    Query parameter semantics (see ``list_agent_evaluation_cases`` in
    ``agent_evaluation_db.py`` for full behaviour):

    * ``sort_by`` — a valid evaluator name OR the empty default (which
      triggers the session-aware default ordering for multi-turn agents).
    * ``pass_filter`` — "pass"/"fail"/``None``; ``None`` returns all rows.
    * ``anno_schema_id`` / ``anno_value`` — **parallel paired arrays**.
      The i-th schema id is matched against the i-th value.  Length
      mismatches are reported by the DB layer as an HTTP 400.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_agent_evaluation_cases_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            pass_filter=pass_filter,
            anno_schema_ids=anno_schema_id,
            anno_values=anno_value,
        )
        return _ok(data)
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "list_agent_evaluation_cases_api ERROR: tenant=%s run_id=%s "
            "sort=%s pass=%s anno_pairs=%s window=%s..%s err=%r",
            _safe_extract_tenant(authorization),
            agent_evaluation_id,
            sort_by or "<default>",
            pass_filter or "<all>",
            min(len(anno_schema_id), len(anno_value)),
            offset,
            offset + limit,
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list agent evaluation cases"
        )


@router.get("/{agent_evaluation_id}/stats")
async def get_evaluation_stats_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
):
    """Return chart-ready aggregates for the detail-page widgets.

    Payload shape (see ``get_evaluation_stats_impl`` for specifics):

    * ``per_evaluator`` — per-evaluator ``{name, avg, count, min, max}``
      rows feeding the score bar / polar chart.
    * ``histogram`` — 5 fixed 0.2-wide buckets feeding the bar chart.
    * ``pass_count`` / ``fail_count`` / ``total`` — hero-card counters.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = get_evaluation_stats_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
        )
        return _ok(data)
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "get_evaluation_stats_api ERROR: tenant=%s run_id=%s err=%r",
            _safe_extract_tenant(authorization),
            agent_evaluation_id,
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to get evaluation stats"
        )


@router.get("/{agent_evaluation_id}/report")
async def download_agent_evaluation_report_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """Stream the localized PDF report for a completed (or partial) evaluation run.

    The filename header encodes the run id so the user's browser download
    tray shows a stable name even when re-downloading.  ``_fail_count``
    from the report builder is intentionally discarded here; it is only
    useful for downstream pipelines that retry on fully-failed runs.
    """
    try:
        _, tenant_id, language = get_current_user_info(authorization, request)
        data, _fail_count = generate_agent_evaluation_report_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            language=language,
        )
        return StreamingResponse(
            iter([data]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=evaluation_report_{agent_evaluation_id}.pdf"
            },
        )
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "download_agent_evaluation_report_api ERROR: tenant=%s run_id=%s language=%s err=%r",
            _safe_extract_tenant(authorization),
            agent_evaluation_id,
            _safe_extract_language(request),
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR,
            "Failed to download agent evaluation report",
        )


@router.post("/{agent_evaluation_id}/analyze")
async def analyze_agent_evaluation_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
    force: bool = Query(False),
):
    """Generate or regenerate the LLM-powered root-cause analysis report.

    ``force=False`` (default) reads from the run's cached
    ``analysis_report`` JSONB column — the happy path is instant.
    ``force=True`` discards the cache and re-runs the LLM call against
    the latest case state (used after human annotations have changed
    pass/fail outcomes or after evaluator thresholds were adjusted mid-run).

    The underlying service returns HTTP 409 when the run is not yet
    COMPLETED / FAILED — ``AGENT_EVALUATION_ANALYSIS_NOT_READY`` — so the
    UI can render a friendly "wait or refresh" tooltip.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = generate_analysis_report_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            force=force,
        )
        logger.info(
            "analyze_agent_evaluation_api OK: tenant=%s run_id=%s force=%s",
            tenant_id,
            agent_evaluation_id,
            force,
        )
        return _ok(data)
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "analyze_agent_evaluation_api ERROR: tenant=%s run_id=%s force=%s err=%r",
            _safe_extract_tenant(authorization),
            agent_evaluation_id,
            force,
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to generate analysis report"
        )


@router.put("/{agent_evaluation_id}/annotation-schemas")
async def update_annotation_schemas_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
    schema_ids: List[int] = Body(..., embed=True),
):
    """Persist the set of annotation schemas enabled for this run.

    The stored list controls what appears in the case-table filter chips
    AND which subsections render in the PDF report's annotation section.
    Passing an empty list clears the selection (equivalent to "do not
    annotate anything").  ``embed=True`` means the raw JSON body must be
    ``{"schema_ids": [1, 2, 3]}`` — this mirrors what the React form
    sends via ``Form.setFieldValue``.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        update_annotation_schema_ids(agent_evaluation_id, tenant_id, schema_ids)
        logger.info(
            "update_annotation_schemas_api OK: tenant=%s run_id=%s schema_ids=%s",
            tenant_id,
            agent_evaluation_id,
            sorted(schema_ids),
        )
        return _ok(schema_ids)
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "update_annotation_schemas_api ERROR: tenant=%s run_id=%s schema_count=%s err=%r",
            _safe_extract_tenant(authorization),
            agent_evaluation_id,
            len(schema_ids) if schema_ids else 0,
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to update annotation schemas"
        )


@router.delete("/{agent_evaluation_id}")
async def delete_agent_evaluation_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
):
    """Soft-delete an evaluation run.  Only the creating user can delete.

    ``delete_agent_evaluation_run_impl`` also cascades into the attached
    one-shot evaluation set (when the run was created in ``no_set`` mode)
    because that set is not user-visible anywhere else and would
    otherwise be a permanent orphan.  Regular evaluation-set runs do NOT
    cascade — only the run row itself is flipped to deleted.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        delete_agent_evaluation_run_impl(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        logger.info(
            "delete_agent_evaluation_api OK: tenant=%s user=%s run_id=%s",
            tenant_id,
            user_id,
            agent_evaluation_id,
        )
        return _ok()
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "delete_agent_evaluation_api ERROR: tenant=%s user=%s run_id=%s err=%r",
            _safe_extract_tenant(authorization),
            _safe_extract_user(authorization),
            agent_evaluation_id,
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete agent evaluation"
        )


@router.post("/trial-run")
async def trial_run_api(
    payload: TrialRunRequest,
    authorization: Optional[str] = Header(None),
):
    """Run a single ad-hoc evaluation without creating a persistent run.

    Primary use case: the evaluator-builder UI's "Try it out" button.  A
    trial run (1) executes the latest agent on ``payload.query``, (2)
    runs every named evaluator in ``evaluator_ids`` against the
    resulting answer, and (3) returns a compact payload with the agent
    reply, per-evaluator score/reason, and an overall pass/fail flag.

    No row is written to ``agent_evaluation_t``; callers that want a
    persistent record after trying should hit the regular
    ``POST /agent-evaluations`` create endpoint.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await trial_run_evaluator_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=payload.agent_id,
            agent_version_no=payload.agent_version_no,
            query=payload.query,
            judge_model_id=payload.judge_model_id,
            evaluator_ids=payload.evaluator_ids,
            field_mappings=payload.field_mappings,
        )
        logger.info(
            "trial_run_api OK: tenant=%s user=%s agent_id=%s version=%s "
            "evaluator_count=%s judge_model=%s query_len=%s",
            tenant_id,
            user_id,
            payload.agent_id,
            payload.agent_version_no,
            len(payload.evaluator_ids or []),
            payload.judge_model_id,
            len(payload.query or ""),
        )
        return _ok(result)
    except AppException:
        raise

    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _AUTH_REQUIRED_MSG)
    except Exception as exc:
        logger.exception(
            "trial_run_api ERROR: tenant=%s user=%s agent_id=%s version=%s "
            "evaluator_count=%s judge_model=%s query_len=%s err=%r",
            _safe_extract_tenant(authorization),
            _safe_extract_user(authorization),
            getattr(payload, "agent_id", None),
            getattr(payload, "agent_version_no", None),
            len(getattr(payload, "evaluator_ids", None) or []),
            getattr(payload, "judge_model_id", None),
            len(getattr(payload, "query", "") or ""),
            exc,
        )
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to run trial evaluation"
        )


# ── tiny helpers to extract a best-effort tenant_id / user_id when
#    the auth header fails parse early.  They swallow exceptions so an
#    ERROR log about "X failed" does not itself raise during format.


def _safe_extract_tenant(authorization: Optional[str]) -> str:
    try:
        _, tenant_id = get_current_user_id(authorization)
        return str(tenant_id) if tenant_id else _UNKNOWN_ID
    except Exception:
        return _UNKNOWN_ID


def _safe_extract_user(authorization: Optional[str]) -> str:
    try:
        user_id, _ = get_current_user_id(authorization)
        return str(user_id) if user_id else _UNKNOWN_ID
    except Exception:
        return _UNKNOWN_ID


def _safe_extract_language(request: Optional[Request]) -> str:
    if request is None:
        return "zh"
    try:
        from utils.auth_utils import parse_language_from_request

        return str(parse_language_from_request(request) or "zh")
    except Exception:
        return "zh"
