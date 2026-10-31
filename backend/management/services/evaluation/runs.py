# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.errors.codes import ErrorCode
from contracts.constants.constants import DEFAULT_PASS_THRESHOLD
from contracts.evaluation import EvalCaseStatus, EvalPassStatus, EvalRunStatus
from contracts.errors.exceptions import AppException
from contracts.agent import AgentRequest
from nexent.core.agents.prompt.auxiliary import AuxiliaryPrompt

try:
    from adapters.jiuwen_sdk_adapter import JiuwenSDKAdapter
except ModuleNotFoundError:
    JiuwenSDKAdapter = None
import ast
import asyncio
import json
import logging
import re
import uuid
from collections import defaultdict
from concurrent.futures import as_completed
from datetime import datetime
from math import isfinite
from statistics import mean

from adapters.exception import JiuwenSDKUnavailableError
from contracts.constants.constants import MAX_CONCURRENT_RUNS, MAX_EVALUATORS_PER_RUN, MAX_TOTAL_RUNS, MAX_TURNS_PER_SESSION
from contracts.constants.constants import MAX_FAILURE_EXAMPLES
from management.db.evaluation.runs import count_active_runs, count_total_runs, create_agent_evaluation, create_agent_evaluation_cases, get_agent_evaluation, get_evaluation_case_scores, hard_delete_agent_evaluation, list_agent_evaluation_cases, list_agent_evaluations_by_agent, update_agent_evaluation_analysis_report, update_agent_evaluation_case_result, update_agent_evaluation_status
from management.db.client import get_db_session
from management.db.models import ModelRecord
from management.db.evaluation.sets import get_evaluation_set_cases_all, materialize_virtual_evaluation_set_for_run
from management.db.evaluation.evaluator import get_evaluator
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from infrastructure.concurrency import config_thread_manager, runtime_thread_manager
from management.services.agent.service import prepare_agent_run
from management.services.evaluation.common import (
    _EVALUATOR_FILENAME,
    _EVENT_LABELS,
    _QUERY_FORMAT_ERR_MSG,
    _SKIP_TYPES,
    _TRIMMABLE_TYPES,
    ALLOWED_BUILTINS,
    agent_run_manager,
    logger,
)
from management.services.evaluation.sets import resolve_latest_published_version_no
from management.services.model.invocation import call_llm_for_system_prompt
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.agents.prompt.evaluation import (
    compose_analysis_report,
    compose_evaluator_run_prompt,
    render_analysis_failures,
    render_analysis_stats,
    render_evaluation_section,
)
from runtime.adapters.nexent.runner import agent_run
from nexent.core.agents.sandbox import _scan_shell_calls
from nexent.core.concurrency import ManagedTaskSpec


def _check_run_limits(tenant_id: str) -> None:
    active = count_active_runs(tenant_id)
    total = count_total_runs(tenant_id)
    if active >= MAX_CONCURRENT_RUNS:
        raise AppException(
            ErrorCode.COMMON_RATE_LIMIT_EXCEEDED,
            f"Active: {active}, max: {MAX_CONCURRENT_RUNS}",
        )
    if total >= MAX_TOTAL_RUNS:
        raise AppException(
            ErrorCode.COMMON_RATE_LIMIT_EXCEEDED,
            f"Total: {total}, max: {MAX_TOTAL_RUNS}",
        )


def _run_in_background(
    fn, *fn_args, tenant_id, user_id, agent_evaluation_id, language="zh"
):
    """Submit Config-owned preparation or dispatch work in the background."""
    execution = config_thread_manager.submit(
        "evaluation",
        ManagedTaskSpec(
            task_name="agent-evaluation-run",
            owner="config",
            run_id=str(agent_evaluation_id),
        ),
        fn,
        *fn_args,
    )
    future = execution.future
    future.add_done_callback(
        _make_background_done_callback(
            tenant_id, user_id, agent_evaluation_id, language
        )
    )


def _validate_and_freeze_evaluators(
    evaluator_ids: list | None,
    tenant_id: str,
    field_mappings: dict | None,
    language: str,
) -> dict[str, Any] | None:
    """Validate evaluators and freeze their config into an immutable snapshot.

    Returns ``None`` when no evaluator_ids are provided.
    Raises ``AppException`` when evaluators exceed the count limit, are not
    found, or are not in PUBLISHED status.
    """
    if not evaluator_ids:
        return None
    if len(evaluator_ids) > MAX_EVALUATORS_PER_RUN:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_EVALUATOR_COUNT,
            "Too many evaluators selected (max 5)",
        )
    for eid in evaluator_ids:
        ev = get_evaluator(eid, tenant_id)
        if not ev:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_FOUND,
                f"Evaluator not found: {eid}",
            )
        if ev.get("status") != "PUBLISHED":
            raise AppException(
                ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED,
                f"Evaluator not published: {ev.get('name')}",
            )
    return {
        "evaluator_ids": evaluator_ids,
        "field_mappings": field_mappings or {},
        "language": language,
    }


def _create_no_set_mode_run(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    judge_model_id: int,
    evaluator_ids: list | None,
    field_mappings: dict | None,
    query_count: int,
    language: str,
    evaluator_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create a placeholder evaluation run with no pre-built case set.

    AI query generation runs in the background via
    :func:`_setup_no_set_and_execute`.
    """
    if query_count < 1 or query_count > 50:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_COUNT_RANGE,
            "Query count must be between 1 and 50",
        )

    evaluator_config = {**(evaluator_config or {}), "no_set_mode": True}  # type: ignore[dict-item]
    run = create_agent_evaluation(
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_version_no=agent_version_no,
        evaluation_set_id=0,
        total=0,
        judge_model_id=judge_model_id,
        created_by=user_id,
        evaluator_config=evaluator_config,
    )
    _run_in_background(
        _setup_no_set_and_execute,
        tenant_id,
        user_id,
        agent_id,
        agent_version_no,
        judge_model_id,
        evaluator_ids,
        field_mappings,
        query_count,
        language,
        run["agent_evaluation_id"],
        tenant_id=tenant_id,
        user_id=user_id,
        agent_evaluation_id=run["agent_evaluation_id"],
        language=language,
    )
    return run


def create_agent_evaluation_run_impl(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    judge_model_id: int,
    evaluation_set_id: int | None = None,
    agent_version_no: int | None = None,
    evaluator_ids: list | None = None,
    field_mappings: dict | None = None,
    query_count: int = 10,
    language: str = "zh",
) -> dict[str, Any]:
    _check_run_limits(tenant_id)

    evaluator_config = _validate_and_freeze_evaluators(
        evaluator_ids, tenant_id, field_mappings, language
    )

    # Resolve the agent version once — both branches need it. Safe to hoist
    # before the set_id branch: resolve_* only reads agent_id/tenant_id and
    # surfaces a clearer error if the agent has no published version.
    if agent_version_no is None:
        agent_version_no = resolve_latest_published_version_no(
            agent_id=agent_id, tenant_id=tenant_id
        )

    if not evaluation_set_id:
        return _create_no_set_mode_run(
            tenant_id,
            user_id,
            agent_id,
            agent_version_no,
            judge_model_id,
            evaluator_ids,
            field_mappings,
            query_count,
            language,
            evaluator_config,
        )

    set_cases = get_evaluation_set_cases_all(
        evaluation_set_id=evaluation_set_id, tenant_id=tenant_id
    )
    if not set_cases:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_SET_EMPTY, "Evaluation set has no cases"
        )

    run = create_agent_evaluation(
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_version_no=agent_version_no,
        evaluation_set_id=evaluation_set_id,
        total=len(set_cases),
        judge_model_id=judge_model_id,
        created_by=user_id,
        evaluator_config=evaluator_config,
    )

    create_agent_evaluation_cases(
        tenant_id=tenant_id,
        agent_evaluation_id=run["agent_evaluation_id"],
        set_cases=set_cases,
        created_by=user_id,
    )
    _run_in_background(
        _dispatch_agent_evaluation_run,
        run["agent_evaluation_id"],
        user_id,
        tenant_id,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_evaluation_id=run["agent_evaluation_id"],
        language=language,
    )
    return run


async def trial_run_evaluator_impl(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    query: str,
    judge_model_id: int,
    evaluator_ids: list | None = None,
    language: str = "zh",
) -> dict:
    # Preload evaluators
    evaluators: dict[int, dict[str, Any]] = {}
    if evaluator_ids:
        for eid in evaluator_ids:
            ev = get_evaluator(eid, tenant_id)
            if ev and ev.get("status") == "PUBLISHED":
                evaluators[eid] = ev
    judge_system_prompt = compose_auxiliary_prompt(language, "evaluation_judge").system

    if JiuwenSDKAdapter is None:
        raise JiuwenSDKUnavailableError("Jiuwen SDK adapter is unavailable")
    adapter = JiuwenSDKAdapter(model_id=judge_model_id, tenant_id=tenant_id)

    answer_text, _runtime_events, score, reason = await _evaluate_query(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        agent_version_no=agent_version_no,
        query=query,
        judge_model_id=judge_model_id,
        adapter=adapter,
        evaluators=evaluators,
        judge_system_prompt=judge_system_prompt,
        language=language,
    )
    return {"query": query, "answer": answer_text, "scores": score, "reasons": reason}


from management.services.evaluation.analysis import (
    _build_analysis_failure_example,
    _call_analysis_llm_and_parse,
    _extract_nested_str,
    _load_evaluator_thresholds_from_config,
    _normalize_cases_response,
    _parse_case_reason,
    _render_analysis_failures_block,
    _render_analysis_stats_block,
    generate_analysis_report_impl,
)
from management.services.evaluation.case_generation import (
    _build_agent_profile_parts,
    _extract_cases_from_markdown_fence,
    _generate_test_queries,
    _parse_cases_from_llm_response,
)
from management.services.evaluation.execution import (
    _build_evaluator_thresholds,
    _compute_case_average_score,
    _determine_case_pass_status,
    _dispatch_agent_evaluation_run,
    _evaluate_query,
    _evaluation_conversation_id,
    _execute_single_case,
    _generate_friendly_error_message,
    _group_cases_by_session,
    _is_llm_related_error,
    _load_all_evaluation_cases,
    _make_background_done_callback,
    _preload_evaluators_for_run,
    _resolve_judge_context_window,
    _run_agent_to_final_answer,
    _setup_no_set_and_execute,
    execute_agent_evaluation_run,
)
from management.services.evaluation.queries import (
    _resolve_user_role,
    delete_agent_evaluation_run_impl,
    get_agent_evaluation_run_impl,
    get_evaluation_stats_impl,
    list_agent_evaluation_cases_impl,
    list_agent_evaluations_by_agent_impl,
)
from management.services.evaluation.scoring import (
    _build_evaluator_prompt,
    _call_one_llm_evaluator,
    _classify_step_event,
    _collect_llm_results,
    _distribute_budget_and_trim,
    _extract_runtime_stats,
    _extract_token_count,
    _format_conversation_history,
    _format_runtime_context,
    _format_stats_summary,
    _format_step_text,
    _group_events_by_step,
    _is_all_pass,
    _run_code_evaluators,
    _scan_evaluator_introspection,
    _score_with_evaluators,
    _trim_content,
    _truncate_actual_answer,
    validate_code_evaluator,
)
