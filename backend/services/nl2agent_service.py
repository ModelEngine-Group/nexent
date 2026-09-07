"""Business logic for the ephemeral NL2Agent runtime."""

import ast
import asyncio
import json
import logging
import re
import threading
import unicodedata
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urljoin

from nexent.core.agents.agent_model import AgentHistory, AgentRunInfo
from nexent.core.agents.context import (
    ContextItemInput,
    ContextItemType,
    ContextManagerConfig,
)
from nexent.core.agents.run_agent import agent_run
from nexent.core.utils.observer import MessageObserver, ProcessType
from rapidfuzz import fuzz

from agents.create_agent_info import (
    _resolve_input_budget,
    _resolve_safe_input_budget,
    create_model_config_list,
    join_minio_file_description_to_query,
)
from agents.nl2agent_agent import create_nl2agent_agent_config
from consts.const import LOCAL_MCP_SERVER, MODEL_CONFIG_MAPPING
from consts.model import HistoryItem, NL2AgentRunRequest, ToolSourceEnum
from database.agent_db import update_agent_draft_fields
from database.skill_db import query_enabled_skill_instances
from database.tool_db import query_all_enabled_tool_instances, query_all_tools
from services.agent_draft_permission_service import (
    AgentDraftEditError,
    require_agent_draft_edit,
)
from tool_collection.mcp.nl2agent_mcp_tools import (
    AgentDraftFields,
    INSTALLED_RESOURCE_SOURCES,
    InstalledMcpToolRecommendation,
    NL2AGENT_AGENT_ID_HEADER,
    NL2A_MCP_LEGACY_TOOL_NAMES,
    NL2A_MCP_TOOL_NAMES,
    RecommendResourcesOutput,
    RecommendedResource,
    ResourceCandidate,
    ResourceInstallationOption,
    ResourceRequirement,
    ResourceSearchOutput,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    UNINSTALLED_RESOURCE_SOURCES,
)
from utils.auth_utils import get_current_user_id
from utils.config_utils import tenant_config_manager
from utils.context_utils import build_authorized_context_input
from utils.http_client_utils import create_httpx_client

logger = logging.getLogger(__name__)

MINIMUM_RECOMMENDATION_SCORE = 0.45
MAX_RECOMMENDATIONS = 5
MAX_BINDING_CANDIDATES = 12
STRONG_RESOURCE_SCORE = 0.65
MINIMUM_RESOURCE_SCORE = 0.50
UNINSTALLED_SOURCE_PAGE_SIZE = 100
MAX_INTERNAL_SOURCE_ITEMS = 300
AGENT_DRAFT_FIELD_ORDER = (
    "name",
    "display_name",
    "description",
    "duty_prompt",
    "constraint_prompt",
    "few_shots_prompt",
    "greeting_message",
    "example_questions",
)


class _Nl2AgentBoundaryObserver(MessageObserver):
    """Stop an NL2Agent run after its first valid interactive payload."""

    _STOP_FINAL_ANSWER = "<user_break>"
    _STOP_ERROR = "Agent execution interrupted by external stop signal"

    def __init__(self, *, lang: str, stop_event: threading.Event):
        super().__init__(lang=lang, enable_nl2a_wrapper=True)
        self._boundary_stop_event = stop_event
        self._boundary_reached = False
        self._boundary_lock = threading.Lock()

    @property
    def boundary_reached(self) -> bool:
        with self._boundary_lock:
            return self._boundary_reached

    def add_message(self, agent_name, process_type, content, **kwargs):
        if self.boundary_reached and (
            (process_type == ProcessType.FINAL_ANSWER and content == self._STOP_FINAL_ANSWER)
            or (process_type == ProcessType.ERROR and content == self._STOP_ERROR)
        ):
            return

        nl2a_content = None
        if process_type == ProcessType.EXECUTION_LOGS:
            nl2a_content, _ = self._extract_nl2a_wrapper(content)

        super().add_message(agent_name, process_type, content, **kwargs)

        if nl2a_content is not None:
            with self._boundary_lock:
                if self._boundary_reached:
                    return
                self._boundary_reached = True
            self._boundary_stop_event.set()


class Nl2AgentDraftSaveError(Exception):
    """Stable service error consumed by the MCP boundary."""

    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class Nl2AgentCompletionError(Exception):
    """Stable persisted-state validation failure at generation completion."""

    def __init__(self, code: str, failed_fields: list[str] | None = None):
        super().__init__(code)
        self.code = code
        self.failed_fields = failed_fields or []


def _ordered_updated_fields(fields: AgentDraftFields) -> list[str]:
    return [name for name in AGENT_DRAFT_FIELD_ORDER if name in fields.model_fields_set]


def _update_agent_draft_from_fields(
    agent_id: int,
    fields: AgentDraftFields,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    try:
        require_agent_draft_edit(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except AgentDraftEditError as exc:
        raise Nl2AgentDraftSaveError(exc.code) from exc

    patch = fields.model_dump(mode="python", exclude_unset=True)
    try:
        rowcount = update_agent_draft_fields(
            agent_id=agent_id,
            tenant_id=tenant_id,
            fields=patch,
        )
    except Exception as exc:
        logger.exception("Failed to update NL2Agent AgentInfo draft")
        raise Nl2AgentDraftSaveError("draft_save_failed", retryable=True) from exc
    if rowcount != 1:
        raise Nl2AgentDraftSaveError("draft_save_failed", retryable=True)

    return {
        "status": "success",
        "agent_id": agent_id,
        "created": False,
        "updated_fields": _ordered_updated_fields(fields),
    }


def save_agent_draft_fields_impl(
    agent_id: int,
    fields: AgentDraftFields,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Partially update one existing tenant-owned AgentInfo draft."""
    return _update_agent_draft_from_fields(agent_id, fields, tenant_id, user_id)


def _normalize_search_text(value: Any) -> str:
    """Normalize catalog text before fuzzy matching."""

    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


def _normalize_labels(value: Any) -> list[str]:
    """Return a safe list of display labels."""

    if not isinstance(value, list):
        return []
    return [str(label) for label in value if label is not None]


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_input_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _collapse_whitespace(value)
    if isinstance(value, dict):
        return {
            key: _normalize_input_strings(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_input_strings(item) for item in value]
    return value


def _parse_tool_inputs(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return {}
    else:
        return {}

    if not isinstance(parsed, dict):
        return {}
    return _normalize_input_strings(parsed)


def _build_tool_document(tool: dict[str, Any]) -> str:
    labels = " ".join(_normalize_labels(tool.get("labels")))
    return _normalize_search_text(
        " ".join(
            str(part)
            for part in (
                tool.get("name") or "",
                tool.get("origin_name") or "",
                tool.get("description") or "",
                labels,
                tool.get("usage") or "",
            )
            if part
        )
    )


def search_installed_mcp_tools_by_query(
    tenant_id: str,
    query_text: str,
    limit: int = MAX_RECOMMENDATIONS,
) -> list[InstalledMcpToolRecommendation]:
    """Return the best installed MCP tool matches for normalized query text."""

    query = _normalize_search_text(query_text)
    scored_tools: list[tuple[float, int, dict[str, Any]]] = []

    for tool in query_all_tools(tenant_id=tenant_id):
        if tool.get("source") != ToolSourceEnum.MCP.value:
            continue
        if tool.get("is_available") is not True:
            continue

        document = _build_tool_document(tool)
        if not document:
            continue

        score = (
            max(
                fuzz.WRatio(query, document),
                fuzz.token_set_ratio(query, document),
            )
            / 100
        )
        if score < MINIMUM_RECOMMENDATION_SCORE:
            continue

        tool_id = int(tool["tool_id"])
        scored_tools.append((score, tool_id, tool))

    scored_tools.sort(key=lambda item: (-item[0], item[1]))
    result_limit = max(0, min(limit, MAX_RECOMMENDATIONS))

    return [
        InstalledMcpToolRecommendation(
            tool_id=tool_id,
            name=str(tool.get("name") or ""),
            origin_name=(
                str(tool["origin_name"])
                if tool.get("origin_name") is not None
                else None
            ),
            description=_collapse_whitespace(
                str(tool.get("description") or "")
            ),
            usage=str(tool.get("usage") or ""),
            labels=_normalize_labels(tool.get("labels")),
            inputs=_parse_tool_inputs(tool.get("inputs")),
            score=round(score, 4),
        )
        for score, tool_id, tool in scored_tools[:result_limit]
    ]


class Nl2AgentResourceError(Exception):
    """Stable resource workflow error consumed by the MCP boundary."""

    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _resource_text_variants(value: Any) -> tuple[str, str]:
    normalized = _normalize_search_text(value)
    normalized = re.sub(r"[_\-/\.:]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized, normalized.replace(" ", "")


def _resource_similarity(left: Any, right: Any) -> float:
    left_normalized, left_compact = _resource_text_variants(left)
    right_normalized, right_compact = _resource_text_variants(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return max(
        fuzz.ratio(left_compact, right_compact),
        fuzz.WRatio(left_normalized, right_normalized),
        fuzz.token_set_ratio(left_normalized, right_normalized),
    ) / 100


def _flatten_resource_text(value: Any, *, limit: int = 4000) -> list[str]:
    values: list[str] = []

    def visit(item: Any) -> None:
        if sum(len(value) for value in values) >= limit:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                values.append(str(key))
                visit(child)
        elif isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)
        elif item is not None:
            values.append(str(item))

    visit(value)
    return values


def _normalize_frontend_param_type(value: Any) -> str:
    return {
        "integer": "number",
        "float": "number",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
        "object": "object",
    }.get(str(value), "string")


def _normalize_tool_config(params: Any) -> list[dict[str, Any]]:
    if not isinstance(params, list):
        return []
    normalized: list[dict[str, Any]] = []
    for param in params:
        if not isinstance(param, dict) or not str(param.get("name") or "").strip():
            continue
        item = {
            "name": str(param["name"]),
            "type": _normalize_frontend_param_type(param.get("type")),
            "required": not bool(param.get("optional")),
            "value": param.get("default"),
            "description": str(param.get("description") or ""),
            "description_zh": str(param.get("description_zh") or ""),
        }
        if param.get("depends_on") is not None:
            item["depends_on"] = str(param["depends_on"])
        normalized.append(item)
    return normalized


def _normalize_skill_config(skill: dict[str, Any]) -> list[dict[str, Any]]:
    schemas = skill.get("config_schemas")
    defaults = skill.get("config_values")
    if not isinstance(schemas, list):
        return []
    default_values = defaults if isinstance(defaults, dict) else {}
    normalized: list[dict[str, Any]] = []
    for schema in schemas:
        if not isinstance(schema, dict) or not str(schema.get("name") or "").strip():
            continue
        item = dict(schema)
        item["name"] = str(schema["name"])
        item["type"] = _normalize_frontend_param_type(schema.get("type"))
        item["required"] = bool(
            schema.get("required", not bool(schema.get("optional")))
        )
        if item["name"] in default_values:
            item["value"] = default_values[item["name"]]
        elif "value" not in item and "default" in item:
            item["value"] = item["default"]
        item.pop("optional", None)
        item.pop("default", None)
        normalized.append(item)
    return normalized


async def _load_installed_resource_catalog(
    *,
    tenant_id: str,
    user_id: str,
) -> list[dict[str, Any]]:
    from management.services.skill.service import SkillService
    from services.tool_configuration_service import list_all_tools

    tools = await list_all_tools(tenant_id=tenant_id)
    skills = SkillService(tenant_id=tenant_id).list_visible_skills(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    internal_names = {
        *NL2A_MCP_LEGACY_TOOL_NAMES,
        *NL2A_MCP_TOOL_NAMES,
        SEARCH_UNINSTALLED_RESOURCES_NAME,
    }
    catalog: list[dict[str, Any]] = []
    for tool in tools:
        source = str(tool.get("source") or "")
        name = str(tool.get("name") or "")
        if (
            source not in {ToolSourceEnum.LOCAL.value, ToolSourceEnum.MCP.value}
            or tool.get("is_available") is not True
            or name in internal_names
        ):
            continue
        tool_id = tool.get("tool_id")
        if not isinstance(tool_id, int) or tool_id <= 0:
            continue
        inputs = _parse_tool_inputs(tool.get("inputs"))
        catalog.append({
            "candidate_ref": f"tool:{tool_id}",
            "resource_type": "tool",
            "source": "LOCAL_TOOL" if source == ToolSourceEnum.LOCAL.value else "MCP_TOOL",
            "name": name,
            "description": _collapse_whitespace(str(tool.get("description") or "")),
            "names": [name, str(tool.get("origin_name") or "")],
            "labels": _normalize_labels(tool.get("labels")),
            "descriptions": [
                str(tool.get("description") or ""),
                str(tool.get("description_zh") or ""),
            ],
            "interfaces": _flatten_resource_text({
                "usage": tool.get("usage"),
                "params": tool.get("params"),
                "inputs": inputs,
            }),
            "config": _normalize_tool_config(tool.get("params")),
            "form_kind": "TOOL_CONFIG",
            "inputs": inputs,
            "installed": True,
            "quality": 1.0,
        })

    for skill in skills:
        skill_id = skill.get("skill_id")
        name = str(skill.get("name") or "")
        if not isinstance(skill_id, int) or skill_id <= 0 or not name:
            continue
        catalog.append({
            "candidate_ref": f"skill:{skill_id}",
            "resource_type": "skill",
            "source": "INSTALLED_SKILL",
            "name": name,
            "description": _collapse_whitespace(str(skill.get("description") or "")),
            "names": [name],
            "labels": _normalize_labels(skill.get("tags")),
            "descriptions": [
                str(skill.get("description") or ""),
                str(skill.get("content") or "")[:4000],
            ],
            "interfaces": _flatten_resource_text({
                "config_schemas": skill.get("config_schemas"),
                "tool_ids": skill.get("tool_ids"),
            }),
            "config": _normalize_skill_config(skill),
            "form_kind": "SKILL_CONFIG",
            "inputs": {},
            "installed": True,
            "quality": 1.0,
        })
    return catalog


def _score_resource_requirement(
    requirement: ResourceRequirement,
    resource: dict[str, Any],
) -> float:
    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in [requirement.query, *requirement.search_terms]:
        normalized, _ = _resource_text_variants(raw_term)
        if normalized and normalized not in seen:
            seen.add(normalized)
            terms.append(raw_term)

    term_scores: list[float] = []
    for term in terms:
        term_scores.append(max(
            max((_resource_similarity(term, value) for value in resource["names"]), default=0) * 1.00,
            max((_resource_similarity(term, value) for value in resource["labels"]), default=0) * 0.95,
            max((_resource_similarity(term, value) for value in resource["descriptions"]), default=0) * 0.90,
            max((_resource_similarity(term, value) for value in resource["interfaces"]), default=0) * 0.80,
        ))
    top_scores = sorted(term_scores, reverse=True)[:3]
    capability_score = (
        0.65 * max(top_scores, default=0)
        + 0.35 * (sum(top_scores) / len(top_scores) if top_scores else 0)
    )
    name_terms = (
        [requirement.resource_name_hint]
        if requirement.resource_name_hint
        else terms
    )
    name_score = max(
        (
            _resource_similarity(term, name)
            for term in name_terms
            for name in resource["names"]
        ),
        default=0,
    )
    installed_bonus = 0.03 if resource.get("installed") else 0.0
    quality_bonus = 0.02 * max(
        0.0, min(1.0, float(resource.get("quality") or 0.0))
    )
    if requirement.resource_name_hint:
        score = (
            0.65 * capability_score
            + 0.30 * name_score
            + installed_bonus
            + quality_bonus
        )
    else:
        score = (
            0.82 * capability_score
            + 0.13 * name_score
            + installed_bonus
            + quality_bonus
        )
    return min(1.0, score)


def _rank_resource_catalog(
    *,
    requirements: list[ResourceRequirement],
    catalog: list[dict[str, Any]],
) -> ResourceSearchOutput:
    """Rank one normalized catalog and return a compact coverage set."""

    scored: list[dict[str, Any]] = []
    strong_requirement_ids: set[str] = set()
    for resource in catalog:
        relationships = {
            requirement.requirement_id: _score_resource_requirement(
                requirement, resource
            )
            for requirement in requirements
        }
        matched_ids = [
            requirement.requirement_id
            for requirement in requirements
            if relationships[requirement.requirement_id]
            >= MINIMUM_RESOURCE_SCORE
        ]
        if not matched_ids:
            continue
        strong_ids = {
            requirement_id
            for requirement_id, score in relationships.items()
            if score >= STRONG_RESOURCE_SCORE
        }
        strong_requirement_ids.update(strong_ids)
        candidate_score = min(
            1.0,
            max(relationships[requirement_id] for requirement_id in matched_ids)
            + 0.01 * max(0, len(strong_ids) - 1),
        )
        candidate = ResourceCandidate(
            candidate_ref=resource["candidate_ref"],
            resource_type=resource["resource_type"],
            source=resource["source"],
            name=resource["name"],
            description=resource["description"],
            requirement_ids=matched_ids,
            score=round(candidate_score, 4),
        )
        scored.append({
            "candidate": candidate,
            "relationships": relationships,
            "strong_ids": strong_ids,
        })

    selected: list[dict[str, Any]] = []
    selected_refs: set[str] = set()
    remaining = {requirement.requirement_id for requirement in requirements}
    while remaining:
        choices = [item for item in scored if item["strong_ids"] & remaining]
        if not choices:
            break
        choices.sort(key=lambda item: (
            -len(item["strong_ids"] & remaining),
            -item["candidate"].score,
            item["candidate"].candidate_ref,
        ))
        chosen = choices[0]
        selected.append(chosen)
        selected_refs.add(chosen["candidate"].candidate_ref)
        remaining -= chosen["strong_ids"]

    for requirement in requirements:
        alternatives = [
            item
            for item in scored
            if item["candidate"].candidate_ref not in selected_refs
            and item["relationships"][requirement.requirement_id]
            >= MINIMUM_RESOURCE_SCORE
        ]
        alternatives.sort(key=lambda item: (
            -item["relationships"][requirement.requirement_id],
            -item["candidate"].score,
            item["candidate"].candidate_ref,
        ))
        for item in alternatives[:2]:
            if len(selected) >= MAX_BINDING_CANDIDATES:
                break
            selected.append(item)
            selected_refs.add(item["candidate"].candidate_ref)

    uncovered = [
        requirement.requirement_id
        for requirement in requirements
        if requirement.requirement_id not in strong_requirement_ids
    ]
    return ResourceSearchOutput(
        candidates=[
            item["candidate"]
            for item in selected[:MAX_BINDING_CANDIDATES]
        ],
        uncovered_requirement_ids=uncovered,
    )


async def search_installed_resources_impl(
    *,
    requirements: list[ResourceRequirement],
    tenant_id: str,
    user_id: str,
) -> ResourceSearchOutput:
    """Search and rank installed resources visible to the current user."""

    catalog = await _load_installed_resource_catalog(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    return _rank_resource_catalog(
        requirements=requirements,
        catalog=catalog,
    )


def _redact_installation_snapshot(value: Any, *, parent_key: str = "") -> Any:
    """Remove persisted credentials while preserving a serializable form shape."""

    normalized_parent = parent_key.casefold().replace("_", "")
    if isinstance(value, dict):
        secret_object = value.get("isSecret") is True
        is_env_context = normalized_parent in {
            "env",
            "environment",
            "environmentvariables",
        }
        is_header_context = normalized_parent in {
            "headers",
            "customheaders",
        }
        is_field_descriptor = any(
            key in value
            for key in (
                "name",
                "key",
                "value",
                "default",
                "isRequired",
                "isSecret",
            )
        )
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).casefold().replace("_", "")
            is_secret_key = (
                normalized_key != "issecret"
                and any(
                    marker in normalized_key
                    for marker in ("password", "secret", "token", "apikey")
                )
            ) or normalized_key == "authorization"
            if (
                (is_env_context or is_header_context)
                and not is_field_descriptor
                and not isinstance(item, (dict, list))
            ):
                redacted[str(key)] = ""
            elif (
                (
                    is_secret_key
                    or is_env_context
                    or is_header_context
                    or secret_object
                )
                and normalized_key
                in {"value", "default", "authorization"}
            ):
                redacted[str(key)] = ""
            elif is_secret_key and not isinstance(item, (dict, list)):
                redacted[str(key)] = ""
            else:
                redacted[str(key)] = _redact_installation_snapshot(
                    item, parent_key=str(key)
                )
        return redacted
    if isinstance(value, list):
        return [
            _redact_installation_snapshot(item, parent_key=parent_key)
            for item in value
        ]
    if normalized_parent in {"env", "environment", "environmentvariables"}:
        return ""
    return value


async def _load_internal_uninstalled_resource_catalog(
    *,
    tenant_id: str,
    user_id: str,
) -> list[dict[str, Any]]:
    from services.mcp_management_service import list_community_mcp_services
    from services.skill_repository_service import (
        list_skill_repository_listings_impl,
    )
    from management.services.skill.service import get_official_skills_with_status

    catalog: list[dict[str, Any]] = []
    for skill in get_official_skills_with_status(tenant_id=tenant_id):
        name = str(skill.get("name") or "").strip()
        if skill.get("status") != "installable" or not name:
            continue
        option = ResourceInstallationOption(
            option_id="official",
            label="Install",
            form_kind="SKILL_CONFIG",
            config=[],
        )
        catalog.append({
            "candidate_ref": f"nexent_official_skill:{quote(name, safe='')}",
            "resource_type": "skill",
            "source": "NEXENT_OFFICIAL_SKILL",
            "name": name,
            "description": _collapse_whitespace(
                str(skill.get("description") or "")
            ),
            "names": [name],
            "labels": [],
            "descriptions": [str(skill.get("description") or "")],
            "interfaces": [],
            "installed": False,
            "quality": 1.0,
            "form_kind": option.form_kind,
            "config": option.config,
            "installation_options": [option],
            "default_option_id": option.option_id,
        })

    repository_items: list[dict[str, Any]] = []
    page = 1
    while len(repository_items) < MAX_INTERNAL_SOURCE_ITEMS:
        result = list_skill_repository_listings_impl(
            tenant_id,
            user_id=user_id,
            status="shared",
            page=page,
            page_size=UNINSTALLED_SOURCE_PAGE_SIZE,
        )
        items = result.get("items") if isinstance(result, dict) else []
        if not isinstance(items, list) or not items:
            break
        repository_items.extend(
            item for item in items if isinstance(item, dict)
        )
        pagination = result.get("pagination") or {}
        if page >= int(pagination.get("total_pages") or page):
            break
        page += 1
    for item in repository_items[:MAX_INTERNAL_SOURCE_ITEMS]:
        repository_id = item.get("skill_repository_id") or item.get("id")
        name = str(item.get("name") or "").strip()
        if not isinstance(repository_id, int) or repository_id <= 0 or not name:
            continue
        config = [{
            "name": "target_name",
            "type": "string",
            "required": False,
            "value": "",
            "description": "Optional installed Skill name",
        }]
        option = ResourceInstallationOption(
            option_id="repository",
            label="Install a copy",
            form_kind="SKILL_CONFIG",
            config=config,
        )
        catalog.append({
            "candidate_ref": f"tenant_skill_repository:{repository_id}",
            "resource_type": "skill",
            "source": "TENANT_SKILL_REPOSITORY",
            "name": name,
            "description": _collapse_whitespace(
                str(item.get("description") or "")
            ),
            "names": [name],
            "labels": _normalize_labels(item.get("tags")),
            "descriptions": [
                str(item.get("description") or ""),
                str(item.get("content") or "")[:4000],
            ],
            "interfaces": [],
            "installed": False,
            "quality": 1.0,
            "form_kind": option.form_kind,
            "config": option.config,
            "installation_options": [option],
            "default_option_id": option.option_id,
        })

    community_items: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(community_items) < MAX_INTERNAL_SOURCE_ITEMS:
        result = await list_community_mcp_services(
            tenant_id=tenant_id,
            user_id=user_id,
            cursor=cursor,
            limit=UNINSTALLED_SOURCE_PAGE_SIZE,
        )
        items = result.get("items") if isinstance(result, dict) else []
        if not isinstance(items, list) or not items:
            break
        community_items.extend(item for item in items if isinstance(item, dict))
        next_cursor = result.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        cursor = next_cursor
    for item in community_items[:MAX_INTERNAL_SOURCE_ITEMS]:
        market_id = item.get("marketId") or item.get("communityId")
        name = str(item.get("name") or "").strip()
        transport_type = str(item.get("transportType") or "").casefold()
        if not isinstance(market_id, int) or market_id <= 0 or not name:
            continue
        if transport_type == "container":
            if not isinstance(item.get("configJson"), dict):
                continue
            form_kind = "MCP_CONTAINER"
        else:
            server_url = str(item.get("serverUrl") or "").strip()
            if not server_url.lower().startswith(("http://", "https://")):
                continue
            form_kind = "MCP_REMOTE"
        draft = {
            "name": name,
            "description": str(item.get("description") or ""),
            "transportType": transport_type or "url",
            "serverUrl": str(item.get("serverUrl") or ""),
            "authorizationToken": "",
            "customHeaders": "",
            "containerConfigJson": json.dumps(
                _redact_installation_snapshot(item.get("configJson") or {}),
                ensure_ascii=False,
                indent=2,
            ),
            "containerPort": item.get("containerPort"),
            "tags": _normalize_labels(item.get("tags")),
            "version": item.get("version"),
            "registryJson": _redact_installation_snapshot(
                item.get("registryJson") or {}
            ),
            "marketId": market_id,
        }
        option = ResourceInstallationOption(
            option_id="repository",
            label="Install",
            form_kind=form_kind,
            config=draft,
        )
        catalog.append({
            "candidate_ref": f"tenant_mcp_repository:{market_id}",
            "resource_type": "mcp_server",
            "source": "TENANT_MCP_REPOSITORY",
            "name": name,
            "description": _collapse_whitespace(
                str(item.get("description") or "")
            ),
            "names": [name],
            "labels": _normalize_labels(item.get("tags")),
            "descriptions": [
                str(item.get("description") or ""),
                str(item.get("content") or "")[:4000],
            ],
            "interfaces": _flatten_resource_text({
                "server": item.get("serverUrl"),
                "config": item.get("configJson"),
                "registry": item.get("registryJson"),
            }),
            "installed": False,
            "quality": 1.0,
            "form_kind": option.form_kind,
            "config": option.config,
            "installation_options": [option],
            "default_option_id": option.option_id,
        })
    return catalog


async def search_uninstalled_resources_impl(
    *,
    requirements: list[ResourceRequirement],
    exclude_refs: list[str],
    tenant_id: str,
    user_id: str,
) -> ResourceSearchOutput:
    """Search and rank tenant-visible installable resources."""

    catalog = await _load_internal_uninstalled_resource_catalog(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    excluded = set(exclude_refs)
    return _rank_resource_catalog(
        requirements=requirements,
        catalog=[
            item for item in catalog if item["candidate_ref"] not in excluded
        ],
    )


def _verified_resource_candidate(
    actual: dict[str, Any],
    supplied: ResourceCandidate,
) -> ResourceCandidate:
    if (
        supplied.resource_type != actual["resource_type"]
        or supplied.source != actual["source"]
    ):
        raise Nl2AgentResourceError("invalid_candidates")
    return ResourceCandidate(
        candidate_ref=actual["candidate_ref"],
        resource_type=actual["resource_type"],
        source=actual["source"],
        name=actual["name"],
        description=actual["description"],
        requirement_ids=supplied.requirement_ids,
        score=supplied.score,
    )


def _recommended_resource(
    *,
    actual: dict[str, Any],
    supplied: ResourceCandidate,
    recommended_refs: set[str],
    is_bound: bool = False,
) -> RecommendedResource:
    return RecommendedResource(
        candidate=_verified_resource_candidate(actual, supplied),
        recommendation=(
            "recommended"
            if supplied.candidate_ref in recommended_refs
            else "optional"
        ),
        is_bound=is_bound,
        form_kind=actual.get("form_kind") or (
            "TOOL_CONFIG"
            if actual["resource_type"] == "tool"
            else "SKILL_CONFIG"
        ),
        config=actual["config"],
        installation_options=actual.get("installation_options") or [],
        default_option_id=actual.get("default_option_id"),
    )


async def recommend_uninstalled_resources_impl(
    *,
    candidates: list[ResourceCandidate],
    recommended_refs: list[str],
    tenant_id: str,
    user_id: str,
) -> RecommendResourcesOutput:
    """Resolve installable candidates against their current source records."""

    internal_catalog = await _load_internal_uninstalled_resource_catalog(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    by_ref = {item["candidate_ref"]: item for item in internal_catalog}
    recommended = set(recommended_refs)
    resources: list[RecommendedResource] = []
    for supplied in candidates:
        actual = by_ref.get(supplied.candidate_ref)
        if actual is None:
            raise Nl2AgentResourceError("resource_not_visible")
        resources.append(_recommended_resource(
            actual=actual,
            supplied=supplied,
            recommended_refs=recommended,
        ))
    return RecommendResourcesOutput(resources=resources)


async def recommend_installed_resources_impl(
    *,
    agent_id: int,
    candidates: list[ResourceCandidate],
    recommended_refs: list[str],
    tenant_id: str,
    user_id: str,
) -> RecommendResourcesOutput:
    """Resolve model-selected refs into current tenant-owned card data."""

    catalog = await _load_installed_resource_catalog(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    by_ref = {item["candidate_ref"]: item for item in catalog}
    bound_tool_refs = {
        f"tool:{instance['tool_id']}"
        for instance in query_all_enabled_tool_instances(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=0,
        )
        if isinstance(instance.get("tool_id"), int)
    }
    recommended = set(recommended_refs)
    resources: list[RecommendedResource] = []
    for supplied in candidates:
        actual = by_ref.get(supplied.candidate_ref)
        if actual is None:
            raise Nl2AgentResourceError("resource_not_visible")
        resources.append(_recommended_resource(
            actual=actual,
            supplied=supplied,
            recommended_refs=recommended,
            is_bound=supplied.candidate_ref in bound_tool_refs,
        ))
    return RecommendResourcesOutput(resources=resources)


async def recommend_resources_impl(
    *,
    agent_id: int,
    candidates: list[ResourceCandidate],
    recommended_refs: list[str],
    tenant_id: str,
    user_id: str,
) -> RecommendResourcesOutput:
    """Dispatch a homogeneous candidate set to its trusted source resolver."""

    sources = {candidate.source for candidate in candidates}
    if sources and sources.issubset(INSTALLED_RESOURCE_SOURCES):
        return await recommend_installed_resources_impl(
            agent_id=agent_id,
            candidates=candidates,
            recommended_refs=recommended_refs,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    if sources and sources.issubset(UNINSTALLED_RESOURCE_SOURCES):
        return await recommend_uninstalled_resources_impl(
            candidates=candidates,
            recommended_refs=recommended_refs,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    raise Nl2AgentResourceError("invalid_candidates")


def _parse_nl2agent_card_action_agent_id(query: str) -> int | None:
    """Return the required Agent ID from a structured NL2Agent action."""

    try:
        action = json.loads(query)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(action, dict) or action.get("type") != "nl2agent_card_action":
        return None
    agent_id = action.get("agent_id")
    if not isinstance(agent_id, int) or isinstance(agent_id, bool) or agent_id <= 0:
        raise Nl2AgentDraftSaveError("agent_context_mismatch")
    return agent_id


async def _load_verified_nl2agent_state(
    *,
    agent_id: int,
    tenant_id: str,
    user_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    draft = require_agent_draft_edit(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    catalog = await _load_installed_resource_catalog(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    by_ref = {item["candidate_ref"]: item for item in catalog}
    facts: list[dict[str, Any]] = []
    for instance in query_all_enabled_tool_instances(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=0,
    ):
        tool_id = instance.get("tool_id")
        resource = by_ref.get(f"tool:{tool_id}")
        if resource is None:
            continue
        params = instance.get("params")
        facts.append({
            "resource_type": "tool",
            "resource_id": tool_id,
            "name": resource["name"],
            "description": resource["description"],
            "input_fields": sorted(resource["inputs"]),
            "configured_fields": sorted(params) if isinstance(params, dict) else [],
        })
    for instance in query_enabled_skill_instances(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=0,
    ):
        skill_id = instance.get("skill_id")
        resource = by_ref.get(f"skill:{skill_id}")
        if resource is None:
            continue
        config_values = instance.get("config_values")
        facts.append({
            "resource_type": "skill",
            "resource_id": skill_id,
            "name": resource["name"],
            "description": resource["description"],
            "config_fields": sorted(
                item["name"]
                for item in resource["config"]
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ),
            "configured_fields": (
                sorted(config_values) if isinstance(config_values, dict) else []
            ),
        })
    facts.sort(key=lambda item: (item["resource_type"], item["resource_id"]))
    return draft, facts


async def _build_verified_bound_resources_context(
    *,
    agent_id: int,
    tenant_id: str,
    user_id: str,
) -> ContextItemInput:
    draft, facts = await _load_verified_nl2agent_state(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    state = {
        "type": "nl2agent_verified_state",
        "agent_id": agent_id,
        "draft_fields": (
            {
                field_name: draft.get(field_name)
                for field_name in AGENT_DRAFT_FIELD_ORDER
                if draft.get(field_name) is not None
            }
            if isinstance(draft, dict)
            else {}
        ),
        "bound_resources": facts,
    }
    return ContextItemInput(
        id="system:nl2agent_bound_resources",
        type=ContextItemType.SYSTEM,
        content={
            "text": "Verified database binding facts: "
            + json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        },
        source=("database:agent_bindings",),
        priority=85,
        metadata={"authority": "tenant"},
    )


async def validate_agent_generation_complete_impl(
    *,
    agent_id: int,
    tenant_id: str,
    user_id: str,
) -> None:
    """Verify the final NL2Agent fields directly from persisted database state."""

    draft, facts = await _load_verified_nl2agent_state(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    description = draft.get("description")
    if not isinstance(description, str) or not description.strip():
        raise Nl2AgentCompletionError("draft_fields_incomplete", ["description"])

    required_prompt_fields = ["duty_prompt", "greeting_message"]
    if facts:
        required_prompt_fields.extend(["constraint_prompt", "few_shots_prompt"])
    missing_prompts = [
        field_name
        for field_name in required_prompt_fields
        if not isinstance(draft.get(field_name), str)
        or not draft[field_name].strip()
    ]
    example_questions = draft.get("example_questions")
    if (
        not isinstance(example_questions, list)
        or not example_questions
        or any(not isinstance(item, str) or not item.strip() for item in example_questions)
    ):
        missing_prompts.append("example_questions")
    if missing_prompts:
        raise Nl2AgentCompletionError(
            "prompt_fields_incomplete",
            missing_prompts,
        )


def _convert_history(history: list[HistoryItem] | None) -> list[AgentHistory]:
    if not history:
        return []
    return [
        AgentHistory(role=item.role, content=item.content)
        for item in history
        if item.role in {"user", "assistant"}
    ]


async def build_nl2agent_run_info(
    request: NL2AgentRunRequest,
    tenant_id: str,
    language: str,
    authorization: str | None,
) -> AgentRunInfo:
    """Build all request-scoped NL2Agent runtime objects in memory."""

    action_agent_id = _parse_nl2agent_card_action_agent_id(request.query)
    if action_agent_id is not None and request.agent_id != action_agent_id:
        raise Nl2AgentDraftSaveError("agent_context_mismatch")
    user_id, authenticated_tenant_id = get_current_user_id(authorization)
    if authenticated_tenant_id != tenant_id:
        raise PermissionError("tenant mismatch")
    binding_context = await _build_verified_bound_resources_context(
        agent_id=request.agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    final_query = await join_minio_file_description_to_query(
        minio_files=request.minio_files,
        query=request.query,
        history=request.history,
    )
    model_config_list = await create_model_config_list(tenant_id)
    agent_config = create_nl2agent_agent_config(language)
    agent_config.context_items = [
        *(agent_config.context_items or []),
        binding_context,
    ]
    default_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id,
    )
    input_budget, capacity_snapshot, resolved_capacity_snapshot = (
        _resolve_input_budget(default_model)
    )
    safe_input_budget_snapshot = _resolve_safe_input_budget(
        capacity_snapshot=resolved_capacity_snapshot,
        tenant_id=tenant_id,
        agent_requested_output_tokens=None,
        request_requested_output_tokens=None,
    )
    if safe_input_budget_snapshot is not None:
        soft_input_budget_tokens = safe_input_budget_snapshot[
            "soft_input_budget_tokens"
        ]
        hard_input_budget_tokens = safe_input_budget_snapshot[
            "hard_input_budget_tokens"
        ]
        token_threshold = soft_input_budget_tokens
    else:
        soft_input_budget_tokens = 0
        hard_input_budget_tokens = 0
        token_threshold = input_budget

    context_window_tokens = (
        resolved_capacity_snapshot.context_window_tokens
        if resolved_capacity_snapshot is not None
        and resolved_capacity_snapshot.context_window_tokens is not None
        else input_budget
    )
    agent_config.context_manager_config = ContextManagerConfig(
        token_threshold=token_threshold,
        context_window_tokens=context_window_tokens,
        soft_input_budget_tokens=soft_input_budget_tokens,
        hard_input_budget_tokens=hard_input_budget_tokens,
    )
    agent_config.capacity_snapshot = capacity_snapshot
    agent_config.safe_input_budget_snapshot = safe_input_budget_snapshot
    mcp_config: dict[str, Any] = {
        "url": urljoin(LOCAL_MCP_SERVER, "sse"),
        "transport": "sse",
        "httpx_client_factory": create_httpx_client,
        "bypass_proxy": True,
    }
    mcp_headers: dict[str, str] = {}
    if authorization:
        mcp_headers["Authorization"] = authorization
    mcp_headers[NL2AGENT_AGENT_ID_HEADER] = str(request.agent_id)
    if mcp_headers:
        mcp_config["headers"] = mcp_headers

    stop_event = threading.Event()
    run_info = AgentRunInfo(
        query=final_query,
        model_config_list=model_config_list,
        observer=_Nl2AgentBoundaryObserver(
            lang=language,
            stop_event=stop_event,
        ),
        agent_config=agent_config,
        mcp_host=[mcp_config],
        history=_convert_history(request.history),
        stop_event=stop_event,
        capacity_snapshot=capacity_snapshot,
        safe_input_budget_snapshot=safe_input_budget_snapshot,
        enable_planning=False,
        sandbox_config=None,
        redis_client=None,
    )
    run_info.context_input = build_authorized_context_input(run_info)
    return run_info


async def create_nl2agent_stream(
    request: NL2AgentRunRequest,
    tenant_id: str,
    language: str,
    authorization: str | None,
) -> AsyncIterator[str]:
    """Create an SSE-compatible stream for one ephemeral NL2Agent run."""

    run_info = await build_nl2agent_run_info(
        request=request,
        tenant_id=tenant_id,
        language=language,
        authorization=authorization,
    )

    async def generate() -> AsyncIterator[str]:
        boundary_delivered = False
        try:
            async for chunk in agent_run(run_info):
                if boundary_delivered:
                    continue
                yield f"data: {chunk}\n\n"
                try:
                    boundary_delivered = (
                        json.loads(chunk).get("type") == ProcessType.NL2A.value
                    )
                except (AttributeError, TypeError, json.JSONDecodeError):
                    boundary_delivered = False
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("NL2Agent execution failed")
            error_payload = json.dumps(
                {
                    "type": "error",
                    "content": "NL2Agent execution failed.",
                },
                ensure_ascii=False,
            )
            yield f"data: {error_payload}\n\n"
        finally:
            run_info.stop_event.set()

    return generate()
