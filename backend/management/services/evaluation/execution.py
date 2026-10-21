# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any

from contracts.error_code import ErrorCode
from contracts.evaluation_limits import DEFAULT_PASS_THRESHOLD
from contracts.evaluation_status import EvalCaseStatus, EvalPassStatus, EvalRunStatus
from contracts.exceptions import AppException
from contracts.models import AgentRequest

try:
    from adapters.jiuwen_sdk_adapter import JiuwenSDKAdapter
except ModuleNotFoundError:
    JiuwenSDKAdapter = None
import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime
from statistics import mean

from adapters.exception import JiuwenSDKUnavailableError
from contracts.evaluation_limits import MAX_TURNS_PER_SESSION
from management.db.evaluation.runs import create_agent_evaluation_cases, get_agent_evaluation, list_agent_evaluation_cases, update_agent_evaluation_case_result, update_agent_evaluation_status
from management.db.client import get_db_session
from management.db.models import ModelRecord
from management.db.evaluation.sets import get_evaluation_set_cases_all, materialize_virtual_evaluation_set_for_run
from management.db.evaluation.evaluator import get_evaluator
from infrastructure.concurrency import runtime_thread_manager
from management.services.agent.service import prepare_agent_run
from management.services.evaluation.common import (
    agent_run_manager,
    logger,
)
from management.services.model.invocation import call_llm_for_system_prompt
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.agents.run_agent import agent_run


def _is_llm_related_error(exc: Exception) -> bool:
    error_str = str(exc).lower()
    llm_keywords = [
        "openai",
        "api",
        "llm",
        "model",
        "completion",
        "chat",
        "connection",
        "timeout",
        "rate limit",
        "authentication",
        "invalid response",
        "async invoke",
        "jiuwen",
        "sdk",
        "schedule new futures",
        "interpreter shutdown",
    ]
    return any(keyword in error_str for keyword in llm_keywords)


def _generate_friendly_error_message(
    exc: Exception,
    default_msg: str,
    model_id: int | None = None,
    tenant_id: str | None = None,
    language: str = "zh",
) -> str:
    if not model_id or not _is_llm_related_error(exc):
        return default_msg
    try:
        prompt = compose_auxiliary_prompt(
            language, "evaluation_error", {"error_message": str(exc)[:500]}
        )
        response = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=prompt.user,
            system_prompt=prompt.system,
            tenant_id=tenant_id or "",
        )
        return (response or "").strip() or default_msg
    except Exception as llm_exc:
        logger.warning("Failed to generate friendly error message: %r", llm_exc)
        return default_msg


def _make_background_done_callback(
    tenant_id: str, user_id: str, agent_evaluation_id: int, language: str = "zh"
):
    def callback(future):
        exc = future.exception()
        if exc is not None:
            logger.exception(
                "Background evaluation run failed (id=%s): %r", agent_evaluation_id, exc
            )
            friendly_msg = _generate_friendly_error_message(
                exc, str(exc), language=language
            )
            try:
                update_agent_evaluation_status(
                    agent_evaluation_id=agent_evaluation_id,
                    tenant_id=tenant_id,
                    status=EvalRunStatus.FAILED,
                    updated_by=user_id,
                    error_message=friendly_msg,
                )
            except Exception as update_exc:
                logger.error(
                    "Failed to write FAILED status for run %d: %r",
                    agent_evaluation_id,
                    update_exc,
                )

    return callback


async def _run_agent_to_final_answer(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    query: str,
    version_no: int,
    history: list[dict[str, Any]] | None = None,
    conversation_id: int | None = None,
) -> tuple[str, list[dict]]:
    """Run agent once; return (final_answer_text, [all_observer_events])."""
    run_conversation_id = conversation_id if conversation_id is not None else 0
    agent_request = AgentRequest(
        query=query,
        conversation_id=run_conversation_id,
        history=history,
        minio_files=None,
        agent_id=agent_id,
        version_no=version_no,
        is_debug=True,
    )
    agent_run_info = None
    terminal_status = "failed"
    try:
        run_manager = agent_run_manager
        if run_manager is None:
            from agents.agent_run_manager import agent_run_manager as run_manager

        agent_run_info, _memory_context = await prepare_agent_run(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            allow_memory_search=False,
        )
        final_answer_parts: list[str] = []
        runtime_events: list[dict] = []
        async for chunk in agent_run(
            agent_run_info,
            thread_manager=runtime_thread_manager,
        ):
            try:
                data = json.loads(chunk)
                if isinstance(data, dict):
                    runtime_events.append(data)
                    if data.get("type") == "final_answer":
                        content = data.get("content")
                        if isinstance(content, str):
                            final_answer_parts.append(content)
            except Exception:
                logger.debug(
                    "Failed to parse observer chunk: %r", chunk[:200], exc_info=True
                )
        remaining = agent_run_info.observer.get_cached_message()
        for msg in remaining:
            try:
                data = json.loads(msg)
                if isinstance(data, dict):
                    runtime_events.append(data)
            except Exception:
                logger.debug(
                    "Failed to parse straggler observer message", exc_info=True
                )
        terminal_status = "completed"
        return "".join(final_answer_parts).strip(), runtime_events
    finally:
        if agent_run_info is not None:
            run_manager.unregister_agent_run(
                run_conversation_id,
                user_id,
                status=terminal_status,
                agent_run_info=agent_run_info,
            )


def _evaluation_conversation_id(agent_evaluation_id: int, case_id: int) -> int:
    """Return a stable, evaluation-only conversation key for run management."""
    # Evaluation runs do not represent user conversations.  A reserved
    # negative integer keeps each case isolated while preserving the existing
    # integer AgentRequest contract.
    return -((int(agent_evaluation_id) << 64) | int(case_id))


def _build_evaluator_thresholds(evaluators: dict) -> dict:
    """Build ``{name: pass_threshold}`` map from the per-run evaluator cache.

    Values are floats; non-numeric / blank entries are skipped so legacy
    evaluator rows with null thresholds fall through to the global DEFAULT
    inside ``_is_all_pass``.
    """
    return {
        str(ev["name"]): float(ev.get("pass_threshold", DEFAULT_PASS_THRESHOLD))
        for ev in evaluators.values()
        if isinstance(ev, dict) and ev.get("name")
    }


def _determine_case_pass_status(score: Any, thresholds: dict) -> str:
    """Map a per-case score to PASS / FAIL using the run's threshold map.

    Dict-score path delegates to ``_is_all_pass``; scalar legacy path
    (semantic_fallback returns score == 1 on success) treats scalar 1 as
    PASS; anything else → FAIL.
    """
    if not isinstance(score, dict):
        # Scalar legacy path (semantic_fallback returns score == 1 on
        # success).  Non-dict scalar 1 → PASS; anything else → FAIL.
        return EvalPassStatus.PASS if score == 1 else EvalPassStatus.FAIL
    if _is_all_pass(score, thresholds):
        return EvalPassStatus.PASS
    return EvalPassStatus.FAIL


def _compute_case_average_score(score: Any) -> float:
    """Compute the per-case average score for run-level aggregation.

    Dict scores: arithmetic mean of all numeric values (0.0 when empty).
    Scalar scores: pass through as float.
    """
    if not isinstance(score, dict):
        return float(score)
    vals = [v for v in score.values() if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else 0.0


def _execute_single_case(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    case: dict[str, Any],
    run: dict[str, Any],
    judge_model_id: int,
    adapter: Any,
    evaluators: dict[int, dict[str, Any]],
    judge_system_prompt: str,
    context_window: int = 4096,
    history: list[dict[str, Any]] | None = None,
) -> tuple[float, str, list[dict] | None]:
    """Run a single evaluation case end-to-end and persist the result.

    Pipeline
    --------
    1. Mark the case RUNNING (so the UI shows it as in-progress and subsequent
       scheduler sweeps do not re-pick it).
    2. Run the target agent via ``_evaluate_query``. The per-case managed
       worker is synchronous, so ``asyncio.run()`` provides its event loop.
       LLM evaluators fan out through the runtime evaluation lane.
    3. Build the ``{evaluator_name: pass_threshold}`` map from the evaluator
       rows already loaded for this run (one-time map per case, zero DB calls
       here).  Names missing from the map fall back to ``DEFAULT_PASS_THRESHOLD``
       inside ``_is_all_pass``.
    4. Write COMPLETED + score + pass_status + predict + reason back to the
       case row.  The score dict is passed RAW to SQLAlchemy because the
       column type is JSONB – ``json.dumps(score)`` before would store a
       JSON *string* inside JSONB and break every ``isinstance(score, dict)``
       downstream;  that bug is explicitly documented here to prevent regressions.
    5. Return ``(average_score, answer_text, events)`` — the average is
       consumed by the run-iteration wrapper for multi-turn session history
       and final overall score.

    Logging strategy: DEBUG logs only for per-case success (INFO-level would
    blow up at 1000+ case runs) and a full exception trace with structured
    context on any failure.  No logs sit inside per-evaluator loops.
    """
    case_id = case["agent_evaluation_case_id"]
    # Mark the row RUNNING BEFORE the call so a concurrent worker sweep never
    # claims the same case twice (see the scheduler's "pending only" filter).
    update_agent_evaluation_case_result(
        agent_evaluation_case_id=case_id,
        tenant_id=tenant_id,
        status=EvalCaseStatus.RUNNING,
        updated_by=user_id,
    )
    inputs = case["inputs"] or {}
    query = inputs.get("query", "")
    label = case.get("label") or {}
    expected_answer = label.get("answer", "") or ""

    try:
        # _evaluate_query is async so each case thread owns a private event
        # loop.  This avoids blocking the whole worker pool on one long agent
        # run, and keeps per-case errors isolated.
        answer_text, events, score, reason = asyncio.run(
            _evaluate_query(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                agent_version_no=agent_version_no,
                query=query,
                judge_model_id=judge_model_id,
                adapter=adapter,
                evaluators=evaluators,
                judge_system_prompt=judge_system_prompt,
                language=run.get("language", "zh"),
                context_window=context_window,
                history=history if history else None,
                expected=expected_answer,
                conversation_id=_evaluation_conversation_id(
                    run["agent_evaluation_id"], case_id
                ),
            )
        )
        predict = {"answer": answer_text}
        # Threshold map: build from the per-run evaluator cache (delegated to
        # ``_build_evaluator_thresholds`` so the same map can be reused by the
        # analysis-report path).
        thresholds = _build_evaluator_thresholds(evaluators)

        # CRITICAL: do NOT json.dumps(score).  agent_evaluation_case_t.score
        # is JSONB and SQLAlchemy serialises Python dicts for us.  Pre-
        # serialising would create a JSON-string-inside-JSONB double-wrap.
        pass_status = _determine_case_pass_status(score, thresholds)
        update_agent_evaluation_case_result(
            agent_evaluation_case_id=case_id,
            tenant_id=tenant_id,
            status=EvalCaseStatus.COMPLETED,
            predict=predict,
            score=score,
            pass_status=pass_status,
            reason=str(json.dumps(reason) if isinstance(reason, dict) else reason),
            updated_by=user_id,
        )
        avg = _compute_case_average_score(score)
        logger.debug(
            "_execute_single_case: case_id=%s run_id=%s agent_id=%s judge_model=%s "
            "score_avg=%s pass_status=%s evaluator_count=%s answer_len=%s",
            case_id,
            run.get("agent_evaluation_id"),
            agent_id,
            judge_model_id,
            avg,
            pass_status,
            len(thresholds),
            len(answer_text or ""),
        )
        return avg, answer_text, events

    except Exception as exc:
        # Structured error log so we can group by tenant / run / case in
        # log observability dashboards.  The traceback is kept via
        # logger.exception for the stack, and the user-facing case error
        # column stores a friendly non-stack version.
        logger.exception(
            "Evaluation case failed run_id=%s case_id=%s tenant=%s agent_id=%s judge_model=%s: %r",
            run.get("agent_evaluation_id"),
            case_id,
            tenant_id,
            agent_id,
            judge_model_id,
            exc,
        )
        friendly_msg = _generate_friendly_error_message(
            exc,
            str(exc),
            model_id=judge_model_id,
            tenant_id=tenant_id,
            language=run.get("language", "zh"),
        )
        update_agent_evaluation_case_result(
            agent_evaluation_case_id=case_id,
            tenant_id=tenant_id,
            status=EvalCaseStatus.FAILED,
            pass_status=EvalPassStatus.FAIL,
            error_message=friendly_msg,
            updated_by=user_id,
        )
        return 0.0, "", []


def _setup_no_set_and_execute(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    judge_model_id: int,
    evaluator_ids: list,
    field_mappings: dict,
    query_count: int,
    language: str,
    agent_evaluation_id: int,
):
    """Background task: generate test queries via LLM, create virtual set, then execute."""
    try:
        # Resolve a suitable LLM model for query generation
        gen_model_id = judge_model_id
        try:
            with get_db_session() as gs:
                models = (
                    gs.query(ModelRecord)
                    .filter(ModelRecord.tenant_id == tenant_id)
                    .all()
                )
                judge_is_llm = any(
                    m.model_id == judge_model_id
                    and getattr(m, "model_type", "") == "llm"
                    for m in models
                )
                if not judge_is_llm:
                    llm_models = sorted(
                        [m for m in models if getattr(m, "model_type", "") == "llm"],
                        key=lambda x: x.model_id or 0,
                        reverse=True,
                    )
                    if llm_models:
                        gen_model_id = llm_models[0].model_id
        except Exception as exc:
            logger.warning("Model fallback check failed: %s", exc)

        # AI generates test queries
        queries = _generate_test_queries(
            agent_id=agent_id,
            tenant_id=tenant_id,
            model_id=gen_model_id,
            query_count=query_count,
            language=language,
        )

        # Create virtual evaluation set
        timestamp = datetime.now().strftime("%m-%d %H:%M")
        set_name = f"[No-Set] {timestamp}-{uuid.uuid4().hex[:4]}"
        cases = [
            {"inputs": {"query": q.strip()}, "label": {"answer": ""}, "order_no": i}
            for i, q in enumerate(queries)
        ]
        evaluation_set_id = materialize_virtual_evaluation_set_for_run(
            tenant_id=tenant_id,
            name=set_name,
            cases=cases,
            created_by=user_id,
            agent_evaluation_id=agent_evaluation_id,
        )
        set_cases = get_evaluation_set_cases_all(
            evaluation_set_id=evaluation_set_id, tenant_id=tenant_id
        )

        # Create cases in agent_evaluation_case table
        create_agent_evaluation_cases(
            tenant_id=tenant_id,
            agent_evaluation_id=agent_evaluation_id,
            set_cases=set_cases,
            created_by=user_id,
        )

        # Execute in the runtime process, which owns the shared workspace
        # volume mounted by the sandbox container.
        _dispatch_agent_evaluation_run(
            agent_evaluation_id=agent_evaluation_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    except Exception:
        logger.exception("No-set setup failed for run %d", agent_evaluation_id)
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.FAILED,
            error_message="Failed to generate test queries",
            updated_by=user_id,
        )


def _preload_evaluators_for_run(run: dict, tenant_id: str) -> dict[int, dict[str, Any]]:
    """Preload PUBLISHED evaluators from the run's evaluator_config."""
    evaluators: dict[int, dict[str, Any]] = {}
    raw_config = run.get("evaluator_config")
    if isinstance(raw_config, dict) and raw_config.get("evaluator_ids"):
        for eid in raw_config["evaluator_ids"]:
            ev = get_evaluator(eid, tenant_id)
            if ev and ev.get("status") == "PUBLISHED":
                evaluators[eid] = ev
    return evaluators


def _resolve_judge_context_window(judge_model_id: int, tenant_id: str) -> int:
    """Resolve judge model context window, defaulting to 4096."""
    context_window = 4096
    with get_db_session() as s:
        model_row = (
            s.query(ModelRecord)
            .filter(
                ModelRecord.model_id == judge_model_id,
                ModelRecord.tenant_id == tenant_id,
            )
            .first()
        )
        if model_row and getattr(model_row, "context_window_tokens", None):
            context_window = model_row.context_window_tokens
    return context_window


def _load_all_evaluation_cases(agent_evaluation_id: int, tenant_id: str) -> list[dict]:
    """Load ALL evaluation cases with pagination (page size 200)."""
    all_cases: list[dict] = []
    offset = 0
    while True:
        batch = list_agent_evaluation_cases(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            limit=200,
            offset=offset,
        )
        page_items = (
            batch.get("items", []) if isinstance(batch, dict) else (batch or [])
        )
        if not page_items:
            break
        all_cases.extend(page_items)
        offset += len(page_items)
    return all_cases


def _group_cases_by_session(all_cases: list[dict]) -> dict[str, list[dict]]:
    """Group cases by session_id for multi-turn support."""
    sessions: dict[str, list[dict]] = defaultdict(list)
    for c in all_cases:
        sid = c.get("session_id") or f"__single__{c['agent_evaluation_case_id']}"
        sessions[sid].append(c)
    return sessions


def execute_agent_evaluation_run(
    tenant_id: str,
    user_id: str,
    agent_evaluation_id: int,
    judge_model_id: int | None = None,
):
    run: dict[str, Any] = {}
    try:
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.RUNNING,
            updated_by=user_id,
        )
        run = get_agent_evaluation(
            agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
        )
        agent_id = int(run["agent_id"])
        agent_version_no = int(run["agent_version_no"])
        if judge_model_id is None:
            judge_model_id = run.get("judge_model_id")
        if judge_model_id is None:
            raise AppException(ErrorCode.AGENT_EVALUATION_JUDGE_MODEL_REQUIRED)
        judge_model_id = int(judge_model_id)

        if JiuwenSDKAdapter is None:
            raise JiuwenSDKUnavailableError("Jiuwen SDK adapter is unavailable.")
        adapter = JiuwenSDKAdapter(model_id=judge_model_id, tenant_id=tenant_id)

        # Preload evaluators and judge template (loaded once, reused for all cases)
        evaluators = _preload_evaluators_for_run(run, tenant_id)
        judge_system_prompt = compose_auxiliary_prompt(
            run.get("language", "zh"), "evaluation_judge"
        ).system

        # Resolve judge model context window once (used for runtime_events trimming)
        context_window = _resolve_judge_context_window(judge_model_id, tenant_id)

        # Load ALL cases first, then group by session_id for multi-turn support.
        # This avoids splitting sessions across pages (which would reset history).
        all_cases = _load_all_evaluation_cases(agent_evaluation_id, tenant_id)
        sessions = _group_cases_by_session(all_cases)

        scores: list[float] = []
        done_count = 0

        for sid, session_cases in sorted(sessions.items()):
            if len(session_cases) > MAX_TURNS_PER_SESSION:
                logger.warning(
                    "Session %s has %d turns, exceeding max %d — truncating",
                    sid,
                    len(session_cases),
                    MAX_TURNS_PER_SESSION,
                )
                session_cases = session_cases[:MAX_TURNS_PER_SESSION]
            session_cases.sort(key=lambda c: c.get("turn_order", 0))
            history: list[dict[str, Any]] = []
            for c in session_cases:
                case_score, answer_text, _events = _execute_single_case(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    agent_version_no=agent_version_no,
                    case=c,
                    run=run,
                    judge_model_id=judge_model_id,
                    adapter=adapter,
                    evaluators=evaluators,
                    judge_system_prompt=judge_system_prompt,
                    context_window=context_window,
                    history=history if history else None,
                )
                scores.append(case_score)
                # Build conversation history for subsequent turns in this session
                inputs = c.get("inputs") or {}
                query = inputs.get("query", "")
                history.append({"role": "user", "content": query})
                history.append({"role": "assistant", "content": answer_text})
                done_count += 1
                update_agent_evaluation_status(
                    agent_evaluation_id=agent_evaluation_id,
                    tenant_id=tenant_id,
                    status=EvalRunStatus.RUNNING,
                    updated_by=user_id,
                    progress_done=done_count,
                )

        overall = float(mean(scores)) if scores else 0.0
        # pass_count here is a best-effort aggregate of per-case pass decisions
        # already written to the DB in _execute_single_case (which already uses
        # per-evaluator pass_threshold).  Using the per-case score average with
        # DEFAULT_PASS_THRESHOLD is consistent with run-level UI display while
        # not double-counting evaluators.
        pass_count = sum(1 for s in scores if s >= DEFAULT_PASS_THRESHOLD)
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.COMPLETED,
            updated_by=user_id,
            score_overall=overall,
            progress_done=done_count,
            pass_count=pass_count,
            fail_count=len(scores) - pass_count,
        )
    except Exception as exc:
        logger.exception("Evaluation run failed: %r", exc)
        friendly_msg = _generate_friendly_error_message(
            exc,
            str(exc),
            model_id=judge_model_id,
            tenant_id=tenant_id,
            language=run.get("language", "zh"),
        )
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.FAILED,
            updated_by=user_id,
            error_message=friendly_msg,
        )


from typing import Any

from management.services.evaluation.case_generation import _generate_test_queries
from management.services.evaluation.scoring import (
    _is_all_pass,
    _score_with_evaluators,
)


async def _evaluate_query(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    query: str,
    judge_model_id: int,
    adapter: Any,
    evaluators: dict[int, dict[str, Any]],
    judge_system_prompt: str,
    runtime_events: list[dict] | None = None,
    language: str = "zh",
    context_window: int = 4096,
    history: list[dict[str, Any]] | None = None,
    expected: str = "",
    conversation_id: int | None = None,
) -> tuple[str, list[dict] | None, dict, dict]:
    """Run agent + score with evaluators. Returns (answer, events, scores, reasons)."""
    answer_text, events = await _run_agent_to_final_answer(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        query=query,
        version_no=agent_version_no,
        history=history,
        conversation_id=conversation_id,
    )
    if evaluators:
        score, reason = _score_with_evaluators(
            evaluators=evaluators,
            judge_system_prompt=judge_system_prompt,
            tenant_id=tenant_id,
            query=query,
            expected=expected,
            actual=answer_text,
            judge_model_id=judge_model_id,
            runtime_events=runtime_events or events,
            context_window=context_window,
            conversation_history=history,
        )
    else:
        score, reason = adapter.evaluate_semantic_consistency(
            question=query,
            expected_answer="",
            model_answer=answer_text,
        )
        score = {"semantic_consistency": score}
        reason = {"semantic_consistency": reason}
    return answer_text, events, score, reason


def _dispatch_agent_evaluation_run(
    agent_evaluation_id: int,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Lazily import the config-to-runtime proxy to keep service imports light."""
    from management.services.agent.runtime_client import dispatch_agent_evaluation_run

    return dispatch_agent_evaluation_run(
        agent_evaluation_id=agent_evaluation_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )
