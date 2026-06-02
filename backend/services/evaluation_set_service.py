import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from consts.model import AgentRequest
from database.agent_version_db import query_version_list
from database.evaluation_set_db import (
    create_evaluation_set,
    get_evaluation_set,
    get_evaluation_set_cases_all,
    insert_evaluation_set_cases,
    list_evaluation_set_cases,
    list_evaluation_sets,
    update_evaluation_set_case_count,
)

logger = logging.getLogger("evaluation_set_service")


def _validate_single_turn_case(obj: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("case must be an object")

    inputs = obj.get("inputs")
    label = obj.get("label")

    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")
    if not isinstance(label, dict):
        raise ValueError("label must be an object")

    query = inputs.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("inputs.query must be a non-empty string")

    context = inputs.get("context")
    if context is not None and not isinstance(context, str):
        raise ValueError("inputs.context must be a string when provided")

    answer = label.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("label.answer must be a non-empty string")

    case_id = obj.get("case_id")
    if case_id is not None and not isinstance(case_id, str):
        raise ValueError("case_id must be a string when provided")

    return {
        "case_id": case_id,
        "inputs": {"query": query, **({"context": context} if context is not None else {})},
        "label": {"answer": answer},
    }


def parse_jsonl_cases(jsonl_text: str) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for idx, line in enumerate((jsonl_text or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception as exc:
            raise ValueError(f"Invalid JSON at line {idx}: {exc}") from exc

        normalized = _validate_single_turn_case(obj)
        normalized["order_no"] = len(cases)
        cases.append(normalized)

    if not cases:
        raise ValueError("JSONL contains no cases")

    return cases


def create_evaluation_set_from_cases(
    tenant_id: str,
    name: str,
    description: Optional[str],
    source_filename: Optional[str],
    cases: List[Dict[str, Any]],
    created_by: Optional[str],
) -> Dict[str, Any]:
    if not cases:
        raise ValueError("cases is empty")

    meta = create_evaluation_set(
        tenant_id=tenant_id,
        name=name,
        description=description,
        source_filename=source_filename,
        created_by=created_by,
    )

    inserted = insert_evaluation_set_cases(
        tenant_id=tenant_id,
        evaluation_set_id=meta["evaluation_set_id"],
        cases=cases,
        created_by=created_by,
    )

    update_evaluation_set_case_count(meta["evaluation_set_id"], inserted, updated_by=created_by)
    meta["case_count"] = inserted
    return meta


def create_evaluation_set_from_jsonl(
    tenant_id: str,
    name: str,
    description: Optional[str],
    source_filename: Optional[str],
    jsonl_text: str,
    created_by: Optional[str],
) -> Dict[str, Any]:
    cases = parse_jsonl_cases(jsonl_text)
    return create_evaluation_set_from_cases(
        tenant_id=tenant_id,
        name=name,
        description=description,
        source_filename=source_filename,
        cases=cases,
        created_by=created_by,
    )


def list_evaluation_sets_impl(tenant_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    return list_evaluation_sets(tenant_id=tenant_id, limit=limit, offset=offset)


def get_evaluation_set_impl(evaluation_set_id: int, tenant_id: str) -> Dict[str, Any]:
    return get_evaluation_set(evaluation_set_id=evaluation_set_id, tenant_id=tenant_id)


def list_evaluation_set_cases_impl(
    evaluation_set_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    return list_evaluation_set_cases(
        evaluation_set_id=evaluation_set_id,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
    )


def resolve_latest_published_version_no(agent_id: int, tenant_id: str) -> int:
    """Return latest published version_no for the agent.

    Raises ValueError if no published version exists.
    """
    versions = query_version_list(agent_id, tenant_id)
    if not versions:
        raise ValueError("agent has no published versions")
    # query_version_list returns latest first in existing code usage
    latest = versions[0].get("version_no")
    if latest is None:
        raise ValueError("failed to resolve latest published version")
    return int(latest)
