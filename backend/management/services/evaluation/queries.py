# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from collections import defaultdict
from math import isfinite
from typing import Any

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.errors.codes import ErrorCode
from contracts.evaluation import EvalPassStatus
from contracts.errors.exceptions import AppException
from management.db.evaluation.runs import get_agent_evaluation, get_evaluation_case_scores, hard_delete_agent_evaluation, list_agent_evaluation_cases, list_agent_evaluations_by_agent
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.services.evaluation.common import (
    logger,
)


def get_agent_evaluation_run_impl(
    agent_evaluation_id: int, tenant_id: str
) -> dict[str, Any]:
    return get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )


def list_agent_evaluations_by_agent_impl(
    agent_ids: list[int],
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return list_agent_evaluations_by_agent(
        agent_ids=agent_ids, tenant_id=tenant_id, limit=limit, offset=offset
    )


def list_agent_evaluation_cases_impl(
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
    return list_agent_evaluation_cases(
        agent_evaluation_id=agent_evaluation_id,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        pass_filter=pass_filter,
        anno_schema_ids=anno_schema_ids,
        anno_values=anno_values,
        session_id=session_id,
    )


def get_evaluation_stats_impl(
    agent_evaluation_id: int,
    tenant_id: str,
) -> dict[str, Any]:
    """Compute chart-ready aggregates for an evaluation run.

    The frontend detail page renders **three** distinct widgets from the
    returned payload:

    1. **Per-evaluator summary table / polar chart** — ``per_evaluator``
       list, each entry carrying ``{name, avg, count, min, max}``.  ``avg``
       is the arithmetic mean across ALL cases (including empty/missing
       values) so averages are comparable between evaluators with sparse
       rows.
    2. **Histogram bar chart** — five fixed buckets (0.0–0.2 → 0.8–1.0).
       Bucket index is ``min(4, int(value * 5))``; clamping to index 4 is
       required because some evaluators emit 1.0 exactly (1.0 * 5 = 5 →
       would overflow the 5-slot list).
    3. **Pass/fail counters** — a running tally on the full case list,
       used for the hero card and summary section.

    Input is the full case corpus via ``get_evaluation_case_scores``
    (unpaginated, but stripped to only ``pass_status / score / reason``
    columns so payload stays tight).  ``score`` is JSONB and reads back
    as a Python dict, so per-evaluator aggregation iterates it directly.

    No per-row logging; a single INFO summary is emitted after aggregation
    so operators can reconcile dashboards with DB state.
    """
    case_scores = get_evaluation_case_scores(
        agent_evaluation_id=agent_evaluation_id,
        tenant_id=tenant_id,
    )

    if not case_scores:
        return {
            "per_evaluator": [],
            "histogram": [],
            "pass_count": 0,
            "fail_count": 0,
            "total": 0,
        }

    eval_scores: dict[str, list[float]] = defaultdict(list)
    # Five 0.2-wide buckets: indexes map directly to the five coloured
    # slots in the detail page (red → orange → yellow → light-green → green).
    histogram_buckets = [0, 0, 0, 0, 0]
    pass_count = 0
    fail_count = 0
    for cs in case_scores:
        if cs["pass_status"] == EvalPassStatus.PASS:
            pass_count += 1
        elif cs["pass_status"] == EvalPassStatus.FAIL:
            fail_count += 1

        score_dict = cs.get("score")
        if not isinstance(score_dict, dict):
            continue
        for name, v in score_dict.items():
            if not isinstance(v, (int, float)) or not isfinite(v):
                continue
            eval_scores[name].append(v)
            # bucket = floor(value * 5), saturate at bucket index 4.
            # Scores > 1.0 (from custom ranges that are NOT yet normalised
            # in the DB layer) still bucket to the top-green slot so the
            # page never displays negative/overflow counts.
            bucket_idx = min(4, max(0, int(v * 5)))
            histogram_buckets[bucket_idx] += 1

    per_evaluator = []
    for name, scores in sorted(eval_scores.items()):
        avg = sum(scores) / len(scores)
        per_evaluator.append(
            {
                "name": name,
                "avg": round(avg, 4),
                "count": len(scores),
                "min": round(min(scores), 4),
                "max": round(max(scores), 4),
            }
        )

    histogram = [
        {"name": "0.0-0.2", "count": histogram_buckets[0], "fill": "#ff4d4f"},
        {"name": "0.2-0.4", "count": histogram_buckets[1], "fill": "#ff7a45"},
        {"name": "0.4-0.6", "count": histogram_buckets[2], "fill": "#faad14"},
        {"name": "0.6-0.8", "count": histogram_buckets[3], "fill": "#a0d911"},
        {"name": "0.8-1.0", "count": histogram_buckets[4], "fill": "#52c41a"},
    ]
    total = len(case_scores)
    logger.info(
        "get_evaluation_stats_impl: run_id=%s tenant=%s total_cases=%s "
        "pass_count=%s fail_count=%s evaluator_count=%s "
        "histogram_buckets=%s",
        agent_evaluation_id,
        tenant_id,
        total,
        pass_count,
        fail_count,
        len(per_evaluator),
        histogram_buckets,
    )
    return {
        "per_evaluator": per_evaluator,
        "histogram": histogram,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "total": total,
    }


def _resolve_user_role(user_id: str) -> str:
    """Return the caller's tenant role; unknown callers fall back to USER."""
    record = get_user_tenant_by_user_id(user_id)
    return str((record or {}).get("user_role") or "USER").upper()


def delete_agent_evaluation_run_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    user_id: str,
) -> None:
    run = get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )
    is_creator = run.get("created_by") == user_id
    if not is_creator and _resolve_user_role(user_id) not in CAN_EDIT_ALL_USER_ROLES:
        raise AppException(ErrorCode.AGENT_EVALUATION_ONLY_CREATOR_CAN_DELETE)

    evaluator_config_raw = run.get("evaluator_config")
    if isinstance(evaluator_config_raw, dict) and evaluator_config_raw.get(
        "no_set_mode"
    ):
        try:
            from management.db.evaluation.sets import hard_delete_evaluation_set

            hard_delete_evaluation_set(run["evaluation_set_id"], tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to clean up virtual evaluation set %d for run %d: %s",
                run["evaluation_set_id"],
                agent_evaluation_id,
                exc,
            )
    hard_delete_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )
