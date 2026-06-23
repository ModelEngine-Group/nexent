import asyncio
import io
import json
import logging
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from adapters.exception import JiuwenSDKError, JiuwenSDKUnavailableError

try:
    from adapters.jiuwen_sdk_adapter import JiuwenSDKAdapter
except ModuleNotFoundError:
    JiuwenSDKAdapter = None  # type: ignore[assignment, misc]
from consts.model import AgentRequest
from database.agent_evaluation_db import (
    create_agent_evaluation,
    create_agent_evaluation_cases,
    get_agent_evaluation,
    list_agent_evaluation_cases,
    list_agent_evaluations_by_agent,
    soft_delete_agent_evaluation,
    update_agent_evaluation_case_result,
    update_agent_evaluation_status,
)
from database.evaluation_set_db import get_evaluation_set_cases_all
from services.evaluation_set_service import resolve_latest_published_version_no
from services.agent_service import prepare_agent_run
from utils.thread_utils import submit
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

logger = logging.getLogger("agent_evaluation_service")


def _build_case_for_jiuwen(
    inputs: Dict[str, Any],
    label: Dict[str, Any],
) -> Dict[str, Any]:
    # Jiuwen Case(inputs, label) will accept arbitrary keys, but we keep the stable schema
    return {
        "inputs": {
            "query": inputs.get("query", ""),
            "context": inputs.get("context", ""),
        },
        "label": {"answer": label.get("answer", "")},
    }


async def _run_agent_to_final_answer(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    query: str,
    context: Optional[str],
    version_no: int,
) -> str:
    """Run agent once and aggregate final answer text."""

    # Build a single-turn AgentRequest. We do not persist messages for offline eval.
    agent_request = AgentRequest(
        query=(query if context is None else f"{query}\n\n[context]\n{context}"),
        conversation_id=0,
        history=None,
        minio_files=None,
        agent_id=agent_id,
        version_no=version_no,
        is_debug=True,
    )

    agent_run_info, memory_context = await prepare_agent_run(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        allow_memory_search=False,
    )

    # Stream chunks from core agent runner and extract final_answer content.
    from nexent.core.agents.run_agent import agent_run

    final_answer_parts: List[str] = []
    async for chunk in agent_run(agent_run_info):
        try:
            if isinstance(chunk, str):
                data = json.loads(chunk)
                if isinstance(data, dict) and data.get("type") == "final_answer":
                    content = data.get("content")
                    if isinstance(content, str):
                        final_answer_parts.append(content)
        except Exception:
            continue

    return "".join(final_answer_parts).strip()


def create_agent_evaluation_run_impl(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    evaluation_set_id: int,
    judge_model_id: int,
) -> Dict[str, Any]:
    set_cases = get_evaluation_set_cases_all(evaluation_set_id=evaluation_set_id, tenant_id=tenant_id)
    if not set_cases:
        raise ValueError("evaluation set has no cases")

    agent_version_no = resolve_latest_published_version_no(agent_id=agent_id, tenant_id=tenant_id)

    run = create_agent_evaluation(
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_version_no=agent_version_no,
        evaluation_set_id=evaluation_set_id,
        total=len(set_cases),
        created_by=user_id,
    )

    create_agent_evaluation_cases(
        tenant_id=tenant_id,
        agent_evaluation_id=run["agent_evaluation_id"],
        set_cases=set_cases,
        created_by=user_id,
    )

    # Kick off background execution
    submit(
        execute_agent_evaluation_run,
        tenant_id,
        user_id,
        run["agent_evaluation_id"],
        judge_model_id,
    )

    return run


def execute_agent_evaluation_run(
    tenant_id: str,
    user_id: str,
    agent_evaluation_id: int,
    judge_model_id: int,
):
    """Background execution entry point (sync)."""
    try:
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status="RUNNING",
            updated_by=user_id,
        )

        run = get_agent_evaluation(agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id)
        agent_id = int(run["agent_id"])
        agent_version_no = int(run["agent_version_no"])

        if JiuwenSDKAdapter is None:
            raise JiuwenSDKUnavailableError("Jiuwen SDK adapter is unavailable. Please install optional dependencies for openjiuwen.")

        adapter = JiuwenSDKAdapter(model_id=judge_model_id, tenant_id=tenant_id)

        cases = list_agent_evaluation_cases(agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id, limit=100000, offset=0)
        scores: List[float] = []

        for idx, c in enumerate(cases, start=1):
            case_id = c["agent_evaluation_case_id"]
            update_agent_evaluation_case_result(
                agent_evaluation_case_id=case_id,
                tenant_id=tenant_id,
                status="RUNNING",
                updated_by=user_id,
            )

            inputs = c["inputs"] or {}
            label = c["label"] or {}

            query = inputs.get("query", "")
            context = inputs.get("context")

            try:
                answer_text = asyncio.run(
                    _run_agent_to_final_answer(
                        agent_id=agent_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        query=query,
                        context=context,
                        version_no=agent_version_no,
                    )
                )

                predict = {"answer": answer_text}

                # Judge with openjiuwen LLM-as-judge metric (binary 1/0)
                expected = (label.get("answer") or "").strip()
                judge_question = query
                if context:
                    judge_question = f"{query}\n\nContext:\n{context}"

                score, reason = adapter.evaluate_semantic_consistency(
                    question=judge_question,
                    expected_answer=expected,
                    model_answer=answer_text,
                )

                update_agent_evaluation_case_result(
                    agent_evaluation_case_id=case_id,
                    tenant_id=tenant_id,
                    status="COMPLETED",
                    predict=predict,
                    score=score,
                    pass_status="pass" if score == 1 else "fail",
                    reason=reason,
                    updated_by=user_id,
                )

                scores.append(score)

            except Exception as exc:
                logger.exception("Evaluation case failed: %r", exc)
                update_agent_evaluation_case_result(
                    agent_evaluation_case_id=case_id,
                    tenant_id=tenant_id,
                    status="FAILED",
                    pass_status="fail",
                    error_message=str(exc),
                    updated_by=user_id,
                )

            update_agent_evaluation_status(
                agent_evaluation_id=agent_evaluation_id,
                tenant_id=tenant_id,
                status="RUNNING",
                updated_by=user_id,
                progress_done=idx,
            )

        overall = float(mean(scores)) if scores else 0.0
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status="COMPLETED",
            updated_by=user_id,
            score_overall=overall,
            progress_done=len(cases),
        )

    except Exception as exc:
        logger.exception("Evaluation run failed: %r", exc)
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status="FAILED",
            updated_by=user_id,
            error_message=str(exc),
        )


def get_agent_evaluation_run_impl(agent_evaluation_id: int, tenant_id: str) -> Dict[str, Any]:
    return get_agent_evaluation(agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id)


def list_agent_evaluations_by_agent_impl(
    agent_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    return list_agent_evaluations_by_agent(agent_id=agent_id, tenant_id=tenant_id, limit=limit, offset=offset)


def list_agent_evaluation_cases_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    return list_agent_evaluation_cases(agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id, limit=limit, offset=offset)


def delete_agent_evaluation_run_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    user_id: str,
) -> None:
    """Soft-delete an evaluation run.

    Only the creator can delete the run. Tenant admins are handled at the
    service layer when permissions are extended.
    """
    run = get_agent_evaluation(agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id)
    if run.get("created_by") != user_id:
        raise ValueError("Only the creator can delete this evaluation run")
    soft_delete_agent_evaluation(agent_evaluation_id, tenant_id, user_id)


def generate_agent_evaluation_report_impl(
    agent_evaluation_id: int,
    tenant_id: str,
) -> bytes:
    """Generate an Excel report containing only FAILED cases.

    Storage policy: passed cases in ``agent_evaluation_case_t`` already have
    ``predict`` / ``reason`` / ``label.answer`` cleared, so an "all pass" run
    will produce a Summary sheet plus an empty Failed Cases sheet.
    """
    run = get_agent_evaluation(agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id)
    all_cases = list_agent_evaluation_cases(
        agent_evaluation_id=agent_evaluation_id,
        tenant_id=tenant_id,
        limit=100000,
        offset=0,
    )

    failed_cases = [
        c for c in all_cases
        if c.get("status") == "FAILED"
        or c.get("score") == 0
        or c.get("pass_status") == "fail"
    ]
    pass_count = sum(
        1 for c in all_cases
        if c.get("status") != "FAILED" and c.get("score") == 1
    )
    fail_count = len(failed_cases)
    total = len(all_cases)
    pass_rate = f"{(pass_count / total * 100):.2f}%" if total else "-"

    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary"

    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="E8F4FD", end_color="E8F4FD", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center")

    summary_rows = [
        ("Agent Evaluation ID", run.get("agent_evaluation_id", "")),
        ("Agent ID", run.get("agent_id", "")),
        ("Agent Version", run.get("agent_version_no", "")),
        ("Evaluation Set ID", run.get("evaluation_set_id", "")),
        ("Status", run.get("status", "")),
        ("Total Cases", total),
        ("Passed Cases", pass_count),
        ("Failed Cases", fail_count),
        ("Pass Rate", pass_rate),
        ("Overall Score", f"{run.get('score_overall', 0):.4f}" if run.get('score_overall') is not None else "-"),
        ("Error Message", run.get("error_message") or "-"),
        ("Created At", run.get("create_time") or "-"),
        ("Report Scope", "Failed cases only"),
    ]

    ws_summary.append(["Field", "Value"])
    for cell in ws_summary[1]:
        cell.font = header_font
        cell.fill = header_fill

    for field, value in summary_rows:
        ws_summary.append([field, value])

    ws_summary.column_dimensions["A"].width = 24
    ws_summary.column_dimensions["B"].width = 60

    ws_cases = wb.create_sheet("Failed Cases")

    case_headers = [
        "Case ID",
        "Query",
        "Context",
        "Expected Answer",
        "Model Answer",
        "Score",
        "Judge Reason",
        "Case Status",
        "Error Message",
    ]
    ws_cases.append(case_headers)
    for cell in ws_cases[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    for c in failed_cases:
        inputs = c.get("inputs") or {}
        label = c.get("label") or {}
        predict = c.get("predict") or {}
        score = c.get("score")
        if score == 0:
            score_str = "0.0000"
        elif isinstance(score, (int, float)):
            score_str = f"{score:.4f}"
        elif score is not None:
            score_str = str(score)
        else:
            score_str = "-"

        ws_cases.append([
            c.get("agent_evaluation_case_id", ""),
            inputs.get("query", ""),
            inputs.get("context") or "",
            label.get("answer", ""),
            predict.get("answer", ""),
            score_str,
            c.get("reason") or "",
            c.get("status", ""),
            c.get("error_message") or "",
        ])

    widths = {"A": 14, "B": 50, "C": 40, "D": 40, "E": 40, "F": 10, "G": 50, "H": 12, "I": 40}
    for col, w in widths.items():
        ws_cases.column_dimensions[col].width = w

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
