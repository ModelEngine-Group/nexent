import json
import logging
import re
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

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


def create_evaluation_set_from_cases(
    tenant_id: str,
    name: str,
    description: str | None,
    source_filename: str | None,
    cases: list[dict[str, Any]],
    created_by: str | None,
) -> dict[str, Any]:
    # ── Multi-turn / count validations ────────────────────────────
    if not cases:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "cases is empty")
    if len(cases) > MAX_CASES_PER_SET:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Case count {len(cases)} exceeds limit {MAX_CASES_PER_SET}",
        )

    sessions: dict[str, list[int]] = defaultdict(list)
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


def create_empty_evaluation_set(
    tenant_id: str,
    name: str,
    description: str | None,
    source_filename: str | None,
    created_by: str | None,
) -> dict[str, Any]:
    """Create an evaluation set with no cases (``case_count = 0``).

    Used by the generate-cases-async flow and the create endpoint when no
    cases are provided up-front.  Cases are added later via
    :func:`insert_evaluation_set_cases`.
    """
    meta = create_evaluation_set(
        tenant_id=tenant_id,
        name=name,
        description=description,
        source_filename=source_filename,
        created_by=created_by,
    )
    meta["case_count"] = 0
    return meta


def list_evaluation_sets_impl(
    tenant_id: str, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    return list_evaluation_sets(tenant_id=tenant_id, limit=limit, offset=offset)


def get_evaluation_set_impl(evaluation_set_id: int, tenant_id: str) -> dict[str, Any]:
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
    query: str | None = None,
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
    excel_bytes = build_evaluation_set_export_bytes(cases)
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
    user_id: str,  # reserved for future audit logging
) -> None:
    """Hard-delete an evaluation set.

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


def _validate_turn_continuity(
    evaluation_set_id: int,
    case_id: int,
    new_session_id: str | None,
    new_turn_order: int | None,
    session_changed: bool,
    turn_changed: bool,
) -> None:
    """Validate multi-turn session continuity after a case update.

    Skipped when *new_session_id* is empty or when neither session_id nor
    turn_order changed (content-only edit).
    """
    if not new_session_id:
        return
    if not (session_changed or turn_changed):
        return

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

    original_session_id = row.get("session_id")
    original_turn_order = row.get("turn_order")
    session_changed = (new_session_id or "") != (original_session_id or "")
    turn_changed = (new_turn_order or 0) != (original_turn_order or 0)

    _validate_turn_continuity(
        evaluation_set_id, case_id, new_session_id, new_turn_order,
        session_changed, turn_changed,
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

    n = batch_delete_evaluation_set_cases([case_id], tenant_id, set_id)
    if n > 0:
        _recount_set_cases(set_id)
    return n > 0


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
    from management.services.knowledge_base.service import get_vector_db_core

    if not kb_info or not queries:
        return ""

    logger.debug("[KB-ES-ENTER] kb_info=%s queries=%s", kb_info, queries)
    es_core = get_vector_db_core()
    parts: list[str] = []
    for kb in kb_info:
        parts.append(f"\n### {kb['display_name']}")
        embedding_model = _get_kb_embedding_model(tenant_id, kb)
        if embedding_model is None:
            continue
        for q in queries:
            hits = _search_kb_for_query(es_core, kb, q, embedding_model, top_k)
            parts.extend(hits)
    return "\n".join(parts) if len(parts) > 1 else ""


def _get_kb_embedding_model(tenant_id: str, kb: dict) -> Any:
    """Resolve the embedding model for a knowledge base.

    Returns ``None`` (with a warning log) when the model is unavailable.
    """
    from management.services.knowledge_base.service import get_embedding_model_by_index_name

    try:
        embedding_model, _, _ = get_embedding_model_by_index_name(
            tenant_id, kb["index_name"]
        )
        if embedding_model is None:
            logger.warning("No embedding model for KB %s", kb["index_name"])
        return embedding_model
    except Exception as exc:
        logger.warning("No embedding model for KB %s: %s", kb["index_name"], exc)
        return None


def _search_kb_for_query(
    es_core, kb: dict, query: str, embedding_model: Any, top_k: int
) -> list[str]:
    """Execute a single KB search and return formatted hit lines.

    Returns an empty list on failure (logged as a warning).
    """
    try:
        logger.debug(
            "[KB-ES] Searching KB=%s query=%s model=%s",
            kb["display_name"],
            query,
            type(embedding_model).__name__,
        )
        query_vector = embedding_model.get_embeddings([query])[0]
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
        return [
            line
            for hit in resp.get("hits", {}).get("hits", [])
            for line in [_format_kb_hit(hit, query)]
            if line
        ]
    except Exception as exc:
        logger.warning(
            "Search failed for KB %s query '%s': %s\n%s",
            kb["display_name"],
            query,
            exc,
            traceback.format_exc(),
        )
        return []


def _format_kb_hit(hit: dict, query: str) -> str:
    """Format one KB search hit as a bullet line.

    Returns ``""`` when the hit has no content.
    """
    src = hit.get("_source", {})
    if isinstance(src, str):
        try:
            src = json.loads(src)
        except Exception:
            logger.debug("Failed to parse KB hit source", exc_info=True)
            src = {}
    content = src.get("content", "") if isinstance(src, dict) else ""
    if not content.strip():
        return ""
    score = hit.get("_score", 0)
    normalized = max(0.0, min(1.0, (score + 1.0) / 2.0))
    return f"- [{query}] (score={normalized:.2f}) {content.strip()[:400]}"


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


def _build_agent_context_block(agent_id, tenant_id) -> str:
    """Fetch and format the agent profile block for case generation.

    Returns ``""`` when *agent_id* is falsy or the profile cannot be loaded.
    """
    if not agent_id:
        return ""
    try:
        from utils.agent_profile_utils import (
            fetch_agent_profile,
            format_agent_profile_context,
        )

        profile = fetch_agent_profile(agent_id, tenant_id)
        ctx = format_agent_profile_context(profile)
        return ctx or ""
    except Exception as e:
        logger.warning("Agent config failed: %s", e)
        return ""


def _format_kb_name(name: str, tenant_id: str) -> str:
    """Format a single KB name with its description (truncated to 150 chars)."""
    info = _resolve_kb_info([name], tenant_id)
    if info and info[0].get("description"):
        return f"{name}（{info[0]['description'][:150]}）"
    return name


def _build_kb_context_block(kb_context, knowledge_base_names, tenant_id) -> str:
    """Build the knowledge-base block for the prompt.

    When *kb_context* has search results, they are included directly.
    Otherwise, the KB names are listed with descriptions and a "no results"
    note.  Returns ``""`` when neither is available.
    """
    if kb_context:
        return f"## 知识库检索到的真实内容\n{kb_context}"
    if not knowledge_base_names:
        return ""
    kb_desc_parts = [_format_kb_name(name, tenant_id) for name in knowledge_base_names]
    return f"## 关联知识库: {'; '.join(kb_desc_parts)}\n(未检索到内容)"


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
    context_blocks: list[str] = []

    agent_block = _build_agent_context_block(agent_id, tenant_id)
    if agent_block:
        context_blocks.append(agent_block)

    context_blocks.append(f"## 场景描述\n{description}")

    kb_block = _build_kb_context_block(kb_context, knowledge_base_names, tenant_id)
    if kb_block:
        context_blocks.append(kb_block)

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


def _parse_llm_cases_response(resp) -> list:
    """Parse the LLM response into a list, with markdown-fence fallback."""
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
    return data


def _normalize_one_generated_case(d) -> dict | None:
    """Validate and normalize one LLM-generated case dict.

    Returns ``None`` when the case is missing required ``inputs.query`` or
    ``label.answer``.  Multi-turn fields (``session_id``, ``turn_order``)
    are preserved when present.
    """
    if not (
        isinstance(d, dict)
        and "inputs" in d
        and "label" in d
        and d["inputs"].get("query")
        and d["label"].get("answer")
    ):
        return None
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
    return case


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
    data = _parse_llm_cases_response(resp)

    cases = []
    for d in data:
        case = _normalize_one_generated_case(d)
        if case:
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
            "Case gen prompt length=%d, has_agent=%s, has_kb=%s, has_file=%s, head=%s",
            len(user_prompt),
            bool(agent_id),
            bool(kb_context),
            bool(file_content),
            user_prompt[:200],
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
