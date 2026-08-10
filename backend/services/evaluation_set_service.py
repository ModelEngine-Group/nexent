import json
import logging
import re
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from consts.error_code import ErrorCode
from consts.evaluation_limits import MAX_CASES_PER_SET
from consts.evaluation_status import EvalRunStatus
from consts.exceptions import AppException
from database.agent_version_db import query_version_list
from database.client import get_db_session
from database.db_models import (
    AgentEvaluation,
    EvaluationSet,
    EvaluationSetCase,
    KnowledgeRecord,
)
from database.evaluation_set_db import (
    batch_delete_evaluation_set_cases,
    count_evaluation_set_cases,
    count_evaluation_sets,
    create_evaluation_set,
    get_cases_by_ids,
    get_evaluation_set,
    get_evaluation_set_cases_all,
    hard_delete_evaluation_set,
    insert_evaluation_set_cases,
    list_case_turn_orders_by_session,
    list_evaluation_set_cases,
    list_evaluation_sets,
    update_evaluation_set_case_count,
)
from database.knowledge_db import get_index_name_by_knowledge_name
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import get_prompt_template


logger = logging.getLogger(__name__)

MAX_TURNS_PER_SESSION = 100


def _validate_single_turn_case(obj: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "case must be an object")

    inputs = obj.get("inputs")
    label = obj.get("label")

    if not isinstance(inputs, dict):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "inputs must be an object"
        )
    if not isinstance(label, dict):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "label must be an object")

    query = inputs.get("query")
    if not isinstance(query, str) or not query.strip():
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "inputs.query must be a non-empty string"
        )

    context = inputs.get("context")
    if context is not None and not isinstance(context, str):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            "inputs.context must be a string when provided",
        )

    answer = label.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "label.answer must be a non-empty string"
        )

    case_id = obj.get("case_id")
    if case_id is not None and not isinstance(case_id, str):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "case_id must be a string when provided"
        )

    result: Dict[str, Any] = {
        "case_id": case_id,
        "inputs": {
            "query": query,
            **({"context": context} if context is not None else {}),
        },
        "label": {"answer": answer},
    }
    sid = obj.get("session_id")
    if sid:
        result["session_id"] = sid
        result["turn_order"] = obj.get("turn_order", 0)
    return result


def parse_jsonl_cases(jsonl_text: str) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for idx, line in enumerate((jsonl_text or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception as exc:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_GENERATION_BAD_FORMAT,
                f"Invalid JSON at line {idx}",
            ) from exc

        normalized = _validate_single_turn_case(obj)
        normalized["order_no"] = len(cases)
        cases.append(normalized)

    if not cases:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "JSONL contains no cases")
    return cases


def create_evaluation_set_from_cases(
    tenant_id: str,
    name: str,
    description: Optional[str],
    source_filename: Optional[str],
    cases: List[Dict[str, Any]],
    created_by: Optional[str],
) -> Dict[str, Any]:
    # ── Multi-turn / count validations ────────────────────────────
    if not cases:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "cases is empty")
    if len(cases) > MAX_CASES_PER_SET:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Case count {len(cases)} exceeds limit {MAX_CASES_PER_SET}",
        )

    sessions: Dict[str, List[int]] = defaultdict(list)
    for case in cases:
        sid = case.get("session_id")
        if sid:
            turn = case.get("turn_order", 0)
            try:
                sessions[sid].append(int(turn))
            except (ValueError, TypeError):
                sessions[sid].append(0)

    for sid, turns in sessions.items():
        if len(turns) > MAX_TURNS_PER_SESSION:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                f"Session {sid} has {len(turns)} turns, max {MAX_TURNS_PER_SESSION}",
            )
        sorted_turns = sorted(turns)
        if sorted_turns != list(range(min(sorted_turns), max(sorted_turns) + 1)):
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                f"Session {sid}: turn orders are not consecutive",
            )

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

    update_evaluation_set_case_count(
        meta["evaluation_set_id"], inserted, updated_by=created_by
    )
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


def list_evaluation_sets_impl(
    tenant_id: str, limit: int = 50, offset: int = 0
) -> List[Dict[str, Any]]:
    return list_evaluation_sets(tenant_id=tenant_id, limit=limit, offset=offset)


def get_evaluation_set_impl(evaluation_set_id: int, tenant_id: str) -> Dict[str, Any]:
    data = get_evaluation_set(evaluation_set_id=evaluation_set_id, tenant_id=tenant_id)
    if not data:
        raise AppException(
            ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluation set not found"
        )
    return data


def count_evaluation_sets_impl(tenant_id: str) -> int:
    return count_evaluation_sets(tenant_id=tenant_id)


def list_evaluation_set_cases_impl(
    evaluation_set_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    query: Optional[str] = None,
) -> dict:
    cases = list_evaluation_set_cases(
        evaluation_set_id=evaluation_set_id,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        query=query,
    )
    total = count_evaluation_set_cases(evaluation_set_id, tenant_id, query=query)
    return {"data": cases, "total": total}


def resolve_latest_published_version_no(agent_id: int, tenant_id: str) -> int:
    """Return latest published version_no for the agent.

    Raises ValueError if no published version exists.
    """
    versions = query_version_list(agent_id, tenant_id)
    if not versions:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_AGENT_NOT_FOUND,
            "Agent has no published versions",
        )
    # query_version_list returns latest first in existing code usage
    latest = versions[0].get("version_no")
    if latest is None:
        raise AppException(
            ErrorCode.COMMON_RESOURCE_NOT_FOUND,
            "Failed to resolve latest published version",
        )
    return int(latest)


def export_evaluation_set_impl(evaluation_set_id: int, tenant_id: str) -> tuple:
    """Export an evaluation set as Excel bytes.

    Returns (filename, excel_bytes).
    Raises NotFoundException when the set is not found.
    """
    from utils.evaluation_set_excel_utils import build_evaluation_set_export_bytes

    meta = get_evaluation_set_impl(evaluation_set_id, tenant_id)
    cases = get_evaluation_set_cases_all(evaluation_set_id, tenant_id)
    filename = f"{meta['name']}.xlsx"
    excel_bytes = build_evaluation_set_export_bytes(meta["name"], cases)
    return filename, excel_bytes


def count_active_runs_using_set(evaluation_set_id: int, tenant_id: str) -> int:
    """Return the number of PENDING/RUNNING evaluation runs referencing the set.

    COMPLETED and FAILED runs are excluded — they don't prevent deletion.
    """
    with get_db_session() as session:
        return (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.evaluation_set_id == evaluation_set_id,
                AgentEvaluation.tenant_id == tenant_id,
                AgentEvaluation.delete_flag == "N",
                AgentEvaluation.status.in_(
                    [EvalRunStatus.PENDING, EvalRunStatus.RUNNING]
                ),
            )
            .count()
        )


def _check_set_not_in_use(evaluation_set_id: int, tenant_id: str) -> None:
    """Raise AppException if any active evaluation run references this set."""
    n = count_active_runs_using_set(evaluation_set_id, tenant_id)
    if n > 0:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_SET_IN_USE,
            f"Evaluation set is referenced by {n} active evaluation run(s) and cannot be modified",
        )


def delete_evaluation_set_impl(
    evaluation_set_id: int,
    tenant_id: str,
    user_id: str,
) -> None:
    """Soft-delete an evaluation set.

    Blocked when any active evaluation run still references the set, so historical
    runs never lose their context. Use ``count_active_runs_using_set`` first if
    the caller wants to surface the referenced count to the user before deletion.
    """
    referenced = count_active_runs_using_set(evaluation_set_id, tenant_id)
    if referenced > 0:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_SET_IN_USE,
            f"Evaluation set is referenced by {referenced} active evaluation run(s) and cannot be deleted",
        )
    hard_delete_evaluation_set(evaluation_set_id, tenant_id)


# ── Case CRUD ──────────────────────────────────────────────────────


def add_evaluation_set_case_impl(
    evaluation_set_id,
    tenant_id,
    inputs,
    label,
    created_by,
    session_id=None,
    turn_order=None,
):
    _check_set_not_in_use(evaluation_set_id, tenant_id)

    # Validate multi-turn session continuity (turn_order starts from 1)
    if session_id:
        existing_turns = list_case_turn_orders_by_session(evaluation_set_id, session_id)
        max_turn = max(existing_turns) if existing_turns else 0
        expected_turn = max_turn + 1
        if turn_order is None:
            turn_order = expected_turn
        elif turn_order != expected_turn:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_TURN_ORDER_MISMATCH,
                f"Session {session_id}: expected turn_order {expected_turn}, got {turn_order}",
                details={
                    "session_id": session_id,
                    "expected": expected_turn,
                    "actual": turn_order,
                },
            )

    case = {
        "inputs": inputs,
        "label": label,
        "order_no": 0,
        "session_id": session_id,
        "turn_order": turn_order or 0,
    }
    n = insert_evaluation_set_cases(
        tenant_id=tenant_id,
        evaluation_set_id=evaluation_set_id,
        cases=[case],
        created_by=created_by,
    )
    if n > 0:
        _recount_set_cases(evaluation_set_id)
    return n


def update_evaluation_set_case_impl(
    evaluation_set_id,
    case_id,
    tenant_id,
    inputs,
    label,
    session_id=None,
    turn_order=None,
):
    _check_set_not_in_use(evaluation_set_id, tenant_id)

    cases = get_cases_by_ids([case_id], tenant_id, evaluation_set_id)
    if not cases:
        return False
    row = cases[0]

    new_session_id = session_id if session_id is not None else row.get("session_id")
    new_turn_order = turn_order if turn_order is not None else row.get("turn_order")

    # Validate multi-turn session continuity after update (turn_order starts from 1).
    # Skip validation when session_id and turn_order are unchanged (content-only edit).
    original_session_id = row.get("session_id")
    original_turn_order = row.get("turn_order")
    session_changed = (new_session_id or "") != (original_session_id or "")
    turn_changed = (new_turn_order or 0) != (original_turn_order or 0)

    if new_session_id and (session_changed or turn_changed):
        other_turns = list_case_turn_orders_by_session(
            evaluation_set_id, new_session_id, exclude_case_ids=[case_id]
        )
        other_max = max(other_turns) if other_turns else 0
        expected = other_max + 1
        if new_turn_order != expected:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_TURN_ORDER_MISMATCH,
                f"Session {new_session_id}: expected turn_order {expected}, got {new_turn_order}",
                details={
                    "session_id": new_session_id,
                    "expected": expected,
                    "actual": new_turn_order,
                },
            )

    with get_db_session() as s:
        r = (
            s.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_case_id == case_id,
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.delete_flag == "N",
            )
            .first()
        )
        r.inputs = inputs
        r.label = label
        if session_id is not None:
            r.session_id = session_id
        if turn_order is not None:
            r.turn_order = turn_order
        s.commit()
    return True


def delete_evaluation_set_case_impl(case_id, tenant_id):
    cases = get_cases_by_ids([case_id], tenant_id, evaluation_set_id=None)
    if not cases:
        return False
    row = cases[0]
    set_id = row["evaluation_set_id"]
    _check_set_not_in_use(set_id, tenant_id)

    # Multi-turn: only allow deletion from the tail (last turn first)
    if row.get("session_id"):
        all_turns = list_case_turn_orders_by_session(set_id, row["session_id"])
        max_turn = max(all_turns) if all_turns else -1
        if max_turn > (row.get("turn_order") or 0):
            raise AppException(
                ErrorCode.AGENT_EVALUATION_TURN_DELETE_NOT_LAST,
                f"Cannot delete turn {row['turn_order']} of session {row['session_id']}: must delete from the last turn first",
                details={
                    "session_id": row["session_id"],
                    "turn_order": row["turn_order"],
                },
            )

    with get_db_session() as s:
        r = (
            s.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_case_id == case_id,
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.delete_flag == "N",
            )
            .first()
        )
        r.delete_flag = "Y"
        s.commit()
    _recount_set_cases(set_id)
    return True


def _recount_set_cases(evaluation_set_id):
    with get_db_session() as s:
        n = (
            s.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
                EvaluationSetCase.delete_flag == "N",
            )
            .count()
        )
        s.query(EvaluationSet).filter(
            EvaluationSet.evaluation_set_id == evaluation_set_id,
        ).update({"case_count": n}, synchronize_session=False)
        s.commit()


def batch_delete_evaluation_set_cases_impl(evaluation_set_id, case_ids, tenant_id):
    _check_set_not_in_use(evaluation_set_id, tenant_id)

    # Fetch cases to delete and group by session
    cases_to_delete = get_cases_by_ids(case_ids, tenant_id, evaluation_set_id)
    to_delete_by_session: dict = {}
    for case in cases_to_delete:
        sid = case.get("session_id")
        if sid:
            to_delete_by_session.setdefault(sid, []).append(
                case["evaluation_set_case_id"]
            )

    # Validate: after deletion, remaining turns in each session must stay contiguous from 1
    for sid, delete_ids in to_delete_by_session.items():
        remaining = list_case_turn_orders_by_session(
            evaluation_set_id, sid, exclude_case_ids=delete_ids
        )
        if remaining:
            expected = list(range(1, len(remaining) + 1))
            if remaining != expected:
                raise AppException(
                    ErrorCode.AGENT_EVALUATION_TURN_DELETE_NOT_CONTIGUOUS,
                    f"Cannot delete turns from session {sid}: remaining turns {remaining} would not be contiguous (expected {expected})",
                    details={
                        "session_id": sid,
                        "remaining": remaining,
                        "expected": expected,
                    },
                )

    n = batch_delete_evaluation_set_cases(case_ids, tenant_id, evaluation_set_id)
    if n > 0:
        _recount_set_cases(evaluation_set_id)
    return n


# ── KB-aware helpers ─────────────────────────────────────────────────


def _resolve_kb_info(kb_names, tenant_id):
    resolved = []
    for name in kb_names:
        idx = get_index_name_by_knowledge_name(name, tenant_id)
        if idx:
            resolved.append({"display_name": name, "index_name": idx})
        else:
            logger.warning("KB not found: '%s' for tenant %s", name, tenant_id)
    return resolved


def _build_kb_descriptions(kb_info, tenant_id):
    lines = []
    with get_db_session() as session:
        for kb in kb_info:
            rec = (
                session.query(KnowledgeRecord.knowledge_describe)
                .filter(
                    KnowledgeRecord.index_name == kb["index_name"],
                    KnowledgeRecord.tenant_id == tenant_id,
                )
                .first()
            )
            desc = (rec[0] or "").strip() if rec else ""
            desc_text = f" - {desc}" if desc else " (no description)"
            lines.append(f"- {kb['display_name']}{desc_text}")
    return "\n".join(lines) if lines else ""


def _plan_search_queries(kb_info, description, model_id, tenant_id):
    kb_desc_block = _build_kb_descriptions(kb_info, tenant_id)
    if not kb_desc_block:
        return []
    user_prompt = (
        f"Scene description: {description}\n\n"
        f"Available knowledge bases:\n{kb_desc_block}\n\n"
        f"Plan search queries to retrieve relevant content. Only query topics that appear in the KB descriptions above."
    )
    try:
        template = get_prompt_template("evaluation_plan_kb_queries", "zh")
        response = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=user_prompt,
            system_prompt=template["SYSTEM_PROMPT"],
            tenant_id=tenant_id,
        )
        data = json.loads(response) if isinstance(response, str) else response
        queries = data.get("queries", []) if isinstance(data, dict) else []
        logger.info("Planned %d search queries: %s", len(queries), queries[:10])
        return queries
    except Exception as exc:
        logger.warning("KB query planning failed: %s", exc)
        fallback_queries = []
        for kb in kb_info:
            fallback_queries.append(kb["display_name"])
        fallback_queries.extend(["overview", "policy", "process", "rule"])
        return fallback_queries


def _execute_kb_searches(kb_info, queries, tenant_id, top_k=3):
    from services.vectordatabase_service import (
        get_embedding_model_by_index_name,
        get_vector_db_core,
    )

    if not kb_info or not queries:
        return ""

    logger.debug("[KB-ES-ENTER] kb_info=%s queries=%s", kb_info, queries)
    es_core = get_vector_db_core()
    parts = []
    for kb in kb_info:
        parts.append(f"\n### {kb['display_name']}")
        try:
            embedding_model, _, _ = get_embedding_model_by_index_name(
                tenant_id, kb["index_name"]
            )
            if embedding_model is None:
                logger.warning("No embedding model for KB %s", kb["index_name"])
                continue
        except Exception as exc:
            logger.warning("No embedding model for KB %s: %s", kb["index_name"], exc)
            continue
        for q in queries:
            try:
                logger.debug(
                    "[KB-ES] Searching KB=%s query=%s model=%s",
                    kb["display_name"],
                    q,
                    type(embedding_model).__name__,
                )
                query_vector = embedding_model.get_embeddings([q])[0]
                logger.debug(
                    "[KB-ES] encode returned type=%s", type(query_vector).__name__
                )
                search_body = {
                    "size": top_k,
                    "query": {
                        "script_score": {
                            "query": {"match_all": {}},
                            "script": {
                                "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                                "params": {"query_vector": query_vector},
                            },
                        }
                    },
                    "_source": ["content", "metadata"],
                }
                resp = es_core.search(index_name=kb["index_name"], query=search_body)
                logger.debug(
                    "[KB-ES] ES search returned %d hits",
                    len(resp.get("hits", {}).get("hits", [])),
                )
                for hit in resp["hits"]["hits"]:
                    src = hit.get("_source", {})
                    if isinstance(src, str):
                        try:
                            src = json.loads(src)
                        except Exception:
                            logger.debug("Failed to parse KB hit source", exc_info=True)
                            src = {}
                    content = src.get("content", "") if isinstance(src, dict) else ""
                    score = hit.get("_score", 0)
                    normalized = max(0.0, min(1.0, (score + 1.0) / 2.0))
                    if content.strip():
                        parts.append(
                            f"- [{q}] (score={normalized:.2f}) {content.strip()[:400]}"
                        )
            except Exception as exc:
                logger.warning(
                    "Search failed for KB %s query '%s': %s\n%s",
                    kb["display_name"],
                    q,
                    exc,
                    traceback.format_exc(),
                )
    return "\n".join(parts) if len(parts) > 1 else ""


def _update_generation_status(set_id, tenant_id, status, progress=0):
    try:
        with get_db_session() as s:
            s.query(EvaluationSet).filter(
                EvaluationSet.evaluation_set_id == set_id,
                EvaluationSet.tenant_id == tenant_id,
            ).update(
                {"generation_status": status, "generation_progress": progress},
                synchronize_session=False,
            )
            s.commit()
    except Exception as e:
        logger.warning("Failed to update generation status: %s", e)


# ── AI case generation (shared helpers) ──────────────────────────────


def _do_kb_search(knowledge_base_names, description, model_id, tenant_id) -> str:
    """Resolve KBs → plan queries → execute searches.  Returns KB context text."""
    if not knowledge_base_names:
        return ""
    kb_info = _resolve_kb_info(knowledge_base_names, tenant_id)
    if not kb_info:
        return ""
    queries = _plan_search_queries(kb_info, description, model_id, tenant_id)
    if not queries:
        return ""
    kb_context = _execute_kb_searches(kb_info, queries, tenant_id)
    if kb_context:
        logger.info("KB search returned %d chars", len(kb_context))
    else:
        logger.warning("KB search returned no results")
    return kb_context


def _build_case_gen_context_blocks(
    agent_id,
    tenant_id,
    description,
    kb_context,
    knowledge_base_names,
    file_content,
    file_name,
):
    """Build prompt context blocks for case generation.  Order: Agent → Scene → KB → File."""
    context_blocks = []
    if agent_id:
        try:
            from utils.agent_profile_utils import (
                fetch_agent_profile,
                format_agent_profile_context,
            )

            profile = fetch_agent_profile(agent_id, tenant_id)
            ctx = format_agent_profile_context(profile)
            if ctx:
                context_blocks.append(ctx)
        except Exception as e:
            logger.warning("Agent config failed: %s", e)
    context_blocks.append(f"## 场景描述\n{description}")
    if kb_context:
        context_blocks.append(f"## 知识库检索到的真实内容\n{kb_context}")
    elif knowledge_base_names:
        kb_desc_parts = []
        for name in knowledge_base_names:
            info = _resolve_kb_info([name], tenant_id)
            if info and info[0].get("description"):
                kb_desc_parts.append(f"{name}（{info[0]['description'][:150]}）")
            else:
                kb_desc_parts.append(name)
        context_blocks.append(
            f"## 关联知识库: {'; '.join(kb_desc_parts)}\n(未检索到内容)"
        )
    if file_content and file_name:
        context_blocks.append(f"## 上传文档: {file_name}\n{file_content[:3000]}")
    return context_blocks


def _build_case_gen_user_prompt(
    context_blocks, count, kb_context, agent_id, file_content
):
    """Append generation instructions from YAML template to assembled context."""
    user_prompt = "\n\n".join(context_blocks)
    sources = ["场景描述"]
    if kb_context:
        sources.append("知识库检索内容")
    if agent_id:
        sources.append("Agent 配置（含工具、技能、子智能体）")
    if file_content:
        sources.append("上传的参考文档")
    source_list = "、".join(sources)

    template = get_prompt_template("evaluation_generate_cases_system", "zh")
    instruction = (
        (template.get("USER_PROMPT_INSTRUCTION") or "")
        .replace("{{sources}}", source_list)
        .replace("{{count}}", str(count))
        .replace("{{max_turns}}", str(MAX_TURNS_PER_SESSION))
    )
    return user_prompt + "\n\n" + instruction if instruction else user_prompt


def _call_llm_and_extract_cases(model_id, user_prompt, tenant_id) -> list:
    """Call LLM for case generation, parse JSON response, return normalized case list."""
    resp = call_llm_for_system_prompt(
        model_id=model_id,
        user_prompt=user_prompt,
        system_prompt=get_prompt_template("evaluation_generate_cases_system", "zh")[
            "SYSTEM_PROMPT"
        ].replace("{{max_turns}}", str(MAX_TURNS_PER_SESSION)),
        tenant_id=tenant_id,
    )
    data = None
    try:
        data = json.loads(resp) if isinstance(resp, str) else resp
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", resp, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
        else:
            raise AppException(ErrorCode.AGENT_EVALUATION_CASE_GENERATION_FORMAT)
    if not isinstance(data, list):
        raise AppException(ErrorCode.AGENT_EVALUATION_CASE_GENERATION_FORMAT)

    cases = []
    for d in data:
        if not (
            isinstance(d, dict)
            and "inputs" in d
            and "label" in d
            and d["inputs"].get("query")
            and d["label"].get("answer")
        ):
            continue
        case = {
            "inputs": {"query": str(d["inputs"]["query"]).strip()},
            "label": {"answer": str(d["label"]["answer"]).strip()},
        }
        # Preserve multi-turn fields if LLM provided them
        sid = d.get("session_id")
        if isinstance(sid, str) and sid.strip():
            case["session_id"] = sid.strip()
        to = d.get("turn_order")
        if isinstance(to, int) or (
            isinstance(to, str) and to.strip().lstrip("-").isdigit()
        ):
            case["turn_order"] = int(to)
        cases.append(case)
    logger.info(
        "Extracted %d valid cases from LLM response (raw=%d)", len(cases), len(data)
    )
    if not cases:
        raise AppException(ErrorCode.AGENT_EVALUATION_CASE_GENERATION_EMPTY)
    return cases


# ── Public API ───────────────────────────────────────────────────────


def generate_cases_by_llm_impl(
    description,
    count,
    tenant_id,
    model_id,
    knowledge_base_names=None,
    agent_id=None,
    agent_version_no=None,
    file_content=None,
    file_name=None,
):
    logger.info("Generating %d cases, KBs=%s", count, knowledge_base_names)

    kb_context = _do_kb_search(knowledge_base_names, description, model_id, tenant_id)
    context_blocks = _build_case_gen_context_blocks(
        agent_id,
        tenant_id,
        description,
        kb_context,
        knowledge_base_names,
        file_content,
        file_name,
    )
    user_prompt = _build_case_gen_user_prompt(
        context_blocks,
        count,
        kb_context,
        agent_id,
        file_content,
    )
    try:
        cases = _call_llm_and_extract_cases(model_id, user_prompt, tenant_id)
    except AppException:
        raise
    except Exception as exc:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, f"Case generation failed: {exc}"
        ) from exc
    return cases[:count]


def _report_progress(set_id, tenant_id, progress):
    """Update generation progress on the evaluation set."""
    _update_generation_status(set_id, tenant_id, "GENERATING", progress)


def _insert_generated_cases(cases, set_id, tenant_id, user_id):
    """Validate and insert AI-generated cases, reporting progress per case."""
    total = len(cases)
    written = 0
    for i, item in enumerate(cases):
        if (
            isinstance(item, dict)
            and "inputs" in item
            and "label" in item
            and item["inputs"].get("query")
            and item["label"].get("answer")
        ):
            case = {
                "inputs": {"query": str(item["inputs"]["query"]).strip()},
                "label": {"answer": str(item["label"]["answer"]).strip()},
                "order_no": written + 1,
            }
            # Preserve multi-turn fields from LLM output
            if item.get("session_id"):
                case["session_id"] = str(item["session_id"]).strip()
            if isinstance(item.get("turn_order"), int):
                case["turn_order"] = item["turn_order"]
            insert_evaluation_set_cases(
                tenant_id=tenant_id,
                evaluation_set_id=set_id,
                cases=[case],
                created_by=user_id,
            )
            written += 1
        p = min(70 + int((i + 1) / max(total, 1) * 30), 99)
        _report_progress(set_id, tenant_id, p)
    return written


def _finalize_generation(set_id, tenant_id, user_id):
    """Update case_count and mark generation as DONE."""
    _recount_set_cases(set_id)
    _update_generation_status(set_id, tenant_id, "DONE", 100)


def _handle_generation_failure(set_id, tenant_id, user_id, is_new_set, start):
    """Mark generation as FAILED and clean up residual data."""
    try:
        _update_generation_status(set_id, tenant_id, "FAILED", 0)
    except Exception:
        logger.warning(
            "Failed to update generation status to FAILED for set %d",
            set_id,
            exc_info=True,
        )
    if is_new_set:
        try:
            hard_delete_evaluation_set(set_id, tenant_id)
        except Exception:
            logger.warning(
                "Cleanup soft-delete failed for set %d", set_id, exc_info=True
            )
    else:
        try:
            with get_db_session() as s:
                s.query(EvaluationSetCase).filter(
                    EvaluationSetCase.evaluation_set_id == set_id,
                    EvaluationSetCase.tenant_id == tenant_id,
                    EvaluationSetCase.created_by == user_id,
                    EvaluationSetCase.create_time >= start,
                ).delete(synchronize_session=False)
                s.commit()
        except Exception as ce:
            logger.warning("Cleanup rollback failed for set %d: %s", set_id, ce)


def _generate_cases_async(
    set_id,
    tenant_id,
    user_id,
    description,
    count,
    model_id,
    file_content,
    file_name,
    agent_id,
    is_new_set=False,
    knowledge_base_names=None,
):
    """Orchestrate async case generation: KB search → prompt → LLM → insert → finalize."""
    start = datetime.now(timezone.utc)
    try:
        _report_progress(set_id, tenant_id, 0)

        kb_context = _do_kb_search(
            knowledge_base_names, description, model_id, tenant_id
        )
        _report_progress(set_id, tenant_id, 8)

        context_blocks = _build_case_gen_context_blocks(
            agent_id,
            tenant_id,
            description,
            kb_context,
            knowledge_base_names,
            file_content,
            file_name,
        )
        user_prompt = _build_case_gen_user_prompt(
            context_blocks,
            count,
            kb_context,
            agent_id,
            file_content,
        )
        logger.info(
            "Case gen prompt length=%d, has_agent=%s, has_kb=%s, has_file=%s, preview=%s",
            len(user_prompt),
            bool(agent_id),
            bool(kb_context),
            bool(file_content),
            user_prompt[-500:],
        )
        _report_progress(set_id, tenant_id, 10)

        cases = _call_llm_and_extract_cases(model_id, user_prompt, tenant_id)
        _report_progress(set_id, tenant_id, 50)

        # Enforce requested count (LLM may return more than asked)
        cases = cases[:count]

        _insert_generated_cases(cases, set_id, tenant_id, user_id)
        _finalize_generation(set_id, tenant_id, user_id)
    except Exception as exc:
        logger.exception("Async generation failed: %s", exc)
        _handle_generation_failure(set_id, tenant_id, user_id, is_new_set, start)
