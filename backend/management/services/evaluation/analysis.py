# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from typing import Any

from consts.error_code import ErrorCode
from consts.evaluation_limits import DEFAULT_PASS_THRESHOLD
from consts.evaluation_status import MAX_FAILURE_EXAMPLES, EvalPassStatus, EvalRunStatus
from consts.exceptions import AppException
from database.agent_evaluation_db import (
    get_agent_evaluation,
    list_agent_evaluation_cases,
    update_agent_evaluation_analysis_report,
)
from database.evaluator_db import get_evaluator
from management.services.evaluation.common import (
    logger,
)
from management.services.model.invocation import call_llm_for_system_prompt
from nexent.core.agents.prompt.auxiliary import AuxiliaryPrompt
from nexent.core.agents.prompt.evaluation import (
    compose_analysis_report,
    render_analysis_failures,
    render_analysis_stats,
)


def _normalize_cases_response(cases: Any) -> list:
    """Normalize the ``list_agent_evaluation_cases`` response to a list.

    The DB helper returns either a list of case dicts or a paginated dict
    of shape ``{"items": [...]}``; this collapses both shapes (plus
    ``None``) into a plain list for downstream iteration.
    """
    if isinstance(cases, dict):
        return cases.get("items", [])
    return cases or []


def _load_evaluator_thresholds_from_config(raw_config: Any, tenant_id: str) -> dict:
    """Build ``{name: pass_threshold}`` map from the run's evaluator_config.

    Skips non-dict / blank entries so legacy evaluator rows with null
    thresholds fall through to the global DEFAULT inside ``_is_all_pass``.
    This is the same map consumed by ``_execute_single_case`` so the
    analysis's "why did this fail" logic matches the pass/fail decision
    recorded in the DB.
    """
    thresholds: dict[str, float] = {}
    if not (
        isinstance(raw_config, dict)
        and isinstance(raw_config.get("evaluator_ids"), list)
    ):
        return thresholds
    for eid in raw_config["evaluator_ids"]:
        try:
            ev = get_evaluator(int(eid), tenant_id)
        except (ValueError, TypeError):
            ev = None
        if isinstance(ev, dict) and ev.get("name"):
            thresholds[str(ev["name"])] = float(
                ev.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
            )
    return thresholds


def _parse_case_reason(reason_raw: str) -> dict:
    """Parse a case ``reason`` field into a dict.

    The field is TEXT storing a ``json.dumps`` string. When it cannot be
    parsed, the raw text is wrapped under the ``"reason"`` key.
    """
    if not reason_raw:
        return {}
    try:
        parsed = json.loads(reason_raw)
        return parsed if isinstance(parsed, dict) else {"reason": reason_raw}
    except (ValueError, TypeError):
        return {"reason": reason_raw}


def _extract_nested_str(c: dict, field: str, key: str) -> str:
    """Extract a string from a nested dict field (``c[field][key]``)."""
    nested = c.get(field) or {}
    if isinstance(nested, dict):
        return str(nested.get(key) or "")
    return ""


def _build_analysis_failure_example(c: dict) -> dict:
    """Build a compact failure-payload dict for the analysis LLM prompt.

    ``score`` is JSONB (already a dict); ``reason`` is TEXT storing a
    ``json.dumps`` string, decoded here so per-evaluator reasons can be
    joined.  Each value is clamped to 4000 chars for LLM context limits.
    """
    score = c.get("score")
    score_dict = score if isinstance(score, dict) else {}
    reason_dict = _parse_case_reason(c.get("reason") or "")
    predict_answer = _extract_nested_str(c, "predict", "answer")
    query_text = _extract_nested_str(c, "inputs", "query")

    # Compact score: single-evaluator score → scalar, multi-evaluator → keep dict
    if len(score_dict) == 1:
        _score_val = next(iter(score_dict.values()))
    else:
        _score_val = score_dict

    # Compact reason: multi-evaluator dict → joined string, scalar → keep string
    if reason_dict:
        _reason_str = " | ".join(f"{k}: {v}" for k, v in reason_dict.items())
    else:
        _reason_str = ""

    return {
        "case_id": c.get("agent_evaluation_case_id"),
        "query": query_text,
        "answer": predict_answer[:4000],
        "score": _score_val,
        "reason": _reason_str[:4000],
    }


def _render_analysis_stats_block(total: int, passed: int, thresholds: dict) -> str:
    """Render the one-line stats header for the analysis prompt.

    Includes the evaluator threshold map when present so the LLM knows the
    pass/fail rules for every score column.
    """
    return render_analysis_stats(total, passed, thresholds)


def _render_analysis_failures_block(failure_examples: list) -> str:
    """Render the per-case failure details section for the analysis prompt.

    Clamps to ``MAX_FAILURE_EXAMPLES`` entries (SDK constant, typically
    ~20).  Each case is compacted onto one readable line per block so
    token counts stay low and the model can parse cleanly.
    """
    return render_analysis_failures(failure_examples, MAX_FAILURE_EXAMPLES)


def _call_analysis_llm_and_parse(
    run: dict, prompt: AuxiliaryPrompt, tenant_id: str
) -> dict:
    """Call the analysis LLM and parse the JSON response.

    Raises ``AppException`` with ``AGENT_EVALUATION_ANALYSIS_FAILED`` if the
    parsed response is not a dict; the caller is responsible for catching
    and logging the underlying ``Exception`` for observability.
    """
    response = call_llm_for_system_prompt(
        model_id=int(run["judge_model_id"]),
        user_prompt=prompt.user,
        system_prompt=prompt.system,
        tenant_id=tenant_id,
    )
    data = json.loads(response) if isinstance(response, str) else response
    if not isinstance(data, dict):
        raise AppException(ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED)
    return data


def generate_analysis_report_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    language: str = "zh",
    force: bool = False,
) -> dict[str, Any]:
    """Generate (or re-generate) the LLM root-cause analysis report.

    Output is a structured dict stored in ``agent_evaluation_t.analysis_report``
    (JSONB) so the detail page can render it instantly on a second visit.
    ``force=True`` skips the cached copy and re-runs the full LLM call; it
    is used when a user clicks "Regenerate report" after annotating cases
    or adjusting evaluator thresholds.

    Pipeline
    --------
    1. Cache gate: return immediately if ``analysis_report`` exists and the
       caller did not request regeneration.
    2. Readiness gate: the run must be ``COMPLETED`` or ``FAILED`` — mid-run
       stats are inconsistent and trigger confusing partial analyses.
    3. Fetch all cases (unpaginated, capped at 5000) and load evaluator
       metadata **once** into a ``{name: pass_threshold}`` map — this is the
       same map used by ``_execute_single_case`` so the analysis's "why did
       this fail" logic matches the pass/fail decision recorded in the DB.
    4. Walk every FAIL case and build compacted failure payloads.  For each
       case we compute:
       * ``low_scores`` — evaluator scores STRICTLY below the per-evaluator
         threshold (the real reason it was marked FAIL).
       * ``borderline_scores`` — scores within 0.1 of the threshold so the
         LLM can highlight "almost passed" evaluators as secondary issues.
       * ``expected`` vs ``actual`` side-by-side answers (4000 char cap each
         to stay inside LLM context windows).
       Historically this step filtered on "any evaluator < 0.5" which
       silently dropped failures where the evaluator had a custom threshold
       (e.g. threshold 0.8 and score 0.6);  the new code uses pass_status as
       the source of truth and only uses thresholds *inside* each case to
       surface the weakest evaluator names.
    5. Render the final LLM prompt: a stats summary + per-case failure
       details clamped to ``MAX_FAILURE_EXAMPLES`` entries (SDK constant,
       typically ~20).  Every prompt starts with a compact one-line stats
       block and the evaluator threshold map so the LLM knows the
       pass/fail rules for every score column.
    6. Call LLM, parse JSON, persist the cache row, return structured dict.

    Logging: one INFO log per generation (with context keys) and no per-case
    logs.  If the LLM returns non-JSON the error is logged at WARNING with
    the full prompt size so operators can estimate cost.
    """
    run = get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )
    if not run:
        raise AppException(
            ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Agent evaluation not found"
        )

    # ── Cache gate ───────────────────────────────────────────────────────
    # ``analysis_report`` is a JSONB column; a non-empty dict means the
    # report was already generated and persisted during a previous call.
    cached = run.get("analysis_report")
    if cached and not force:
        return cached

    # ── Readiness gate ───────────────────────────────────────────────────
    # PENDING / RUNNING produce incomplete sample sets — refuse until done.
    if run["status"] not in (EvalRunStatus.COMPLETED, EvalRunStatus.FAILED):
        raise AppException(ErrorCode.AGENT_EVALUATION_ANALYSIS_NOT_READY)

    # ── Load corpus + evaluator metadata ─────────────────────────────────
    cases = list_agent_evaluation_cases(
        agent_evaluation_id=agent_evaluation_id,
        tenant_id=tenant_id,
        limit=5000,
        offset=0,
    )
    cases = _normalize_cases_response(cases)

    raw_config = run.get("evaluator_config") or {}
    thresholds = _load_evaluator_thresholds_from_config(raw_config, tenant_id)

    # ── Basic run stats ──────────────────────────────────────────────────
    total = len(cases)
    passed = sum(1 for c in cases if c.get("pass_status") == EvalPassStatus.PASS)
    failed_cases = [c for c in cases if c.get("pass_status") == EvalPassStatus.FAIL]

    # ── Collect failure details for the LLM prompt ──────────────────────
    failure_examples = [_build_analysis_failure_example(c) for c in failed_cases]

    # ── Render prompt blocks ─────────────────────────────────────────────
    prompt = compose_analysis_report(
        language,
        total=total,
        passed=passed,
        thresholds=thresholds,
        failure_examples=failure_examples,
        max_examples=MAX_FAILURE_EXAMPLES,
    )
    prompt_chars = len(prompt.user)

    # ── LLM call + cache write ───────────────────────────────────────────
    try:
        data = _call_analysis_llm_and_parse(run, prompt, tenant_id)
    except Exception as exc:
        # WARNING so ops can see the LLM failure independently of the stack
        # trace.  prompt_chars is an approximation of token consumption
        # (model-dependent; real tokens are roughly prompt_chars/4 for ASCII).
        logger.warning(
            "Analysis generation FAILED run_id=%s tenant=%s judge_model=%s force=%s prompt_chars=%s failure=%r",
            agent_evaluation_id,
            tenant_id,
            run.get("judge_model_id"),
            force,
            prompt_chars,
            exc,
        )
        logger.exception("Analysis generation stack trace: %s", exc)
        raise AppException(ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED)

    update_agent_evaluation_analysis_report(agent_evaluation_id, tenant_id, data)
    # Single summary INFO log per regeneration.
    evaluator_count_in_thresholds = len(thresholds)
    logger.info(
        "generate_analysis_report_impl: run_id=%s tenant=%s judge_model=%s force=%s "
        "total_cases=%s passed=%s failed_cases=%s failure_examples_sent=%s "
        "evaluator_thresholds=%s prompt_chars=%s cached=%s",
        agent_evaluation_id,
        tenant_id,
        run.get("judge_model_id"),
        force,
        total,
        passed,
        len(failed_cases),
        min(len(failure_examples), MAX_FAILURE_EXAMPLES),
        evaluator_count_in_thresholds,
        prompt_chars,
        bool(cached and not force),
    )
    return data
