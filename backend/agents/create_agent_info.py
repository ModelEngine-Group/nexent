import json
import threading
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import AgentRunInfo, ModelConfig, AgentConfig, ToolConfig, ExternalA2AAgentConfig, AgentHistory, AgentVerificationConfig
from nexent.core.agents.context import (
    ContextManagerConfig,
    PolicyLayers,
    resolve_policy,
)
from nexent.core.models.prompt_cache import resolve_prompt_cache_profile
from nexent.core.models.capacity_resolver import (
    ModelCapacitySnapshot,
    ProviderCapabilityUnknown,
    ResolverError,
    resolve_capacity,
)
from nexent.core.models.capacity_budget import (
    RequestBudgetOverrides,
    SafeInputBudgetCalculator,
    UncertaintyReserveBasisUnknown,
)
from nexent.core.tools.parallel_executor import ParallelExecutorTool
from nexent.core.agents.sandbox import SandboxConfig
from nexent.memory.memory_service import search_memory_in_levels

from consts.capability_profiles import CATALOG as CAPABILITY_CATALOG

from services.file_management_service import get_llm_model, validate_urls_access
from services.vectordatabase_service import (
    ElasticSearchService,
    get_vector_db_core,
    get_embedding_model_by_index_name,
    get_rerank_model,
)
from services.remote_mcp_service import get_remote_mcp_server_list

from database.a2a_agent_db import PROTOCOL_JSONRPC
from services.memory_config_service import build_memory_context
from services.image_service import get_video_understanding_model, get_vlm_model
from database.agent_db import (
    search_agent_info_by_agent_id,
    query_sub_agent_relations,
    resolve_sub_agent_version_no,
)
from database.agent_version_db import query_current_version_no
from database.tool_db import search_tools_for_sub_agent
from database.model_management_db import get_model_records, get_model_by_model_id
from database.knowledge_db import get_knowledge_name_map_by_index_names
from database.client import minio_client
from utils.model_name_utils import add_repo_to_name
from utils.prompt_template_utils import get_agent_prompt_template
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.context_utils import build_context_inputs
from utils.redis_utils import get_redis_client
from consts.const import (
    AIDP_API_KEY,
    AIDP_SERVER_URL,
    AIDP_TENANT_ID,
    DATA_PROCESS_SERVICE,
    LANGUAGE,
    LOCAL_MCP_SERVER,
    MINIO_DEFAULT_BUCKET,
    MODEL_CONFIG_MAPPING,
)
from consts.model import ToolParamsRequest
from consts.exceptions import ValidationError

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.DEBUG)


# Safe fallback for context-manager token_threshold when no capacity is known.
# Used only when the resolver fails (uncataloged model with no operator-supplied
# hard capacity). Sized to cover the typical 32K-context band shared by the
# majority of production LLMs (GPT-3.5 16K, GLM-4 32K, Qwen2 32K, Llama 3
# 32K, etc.). Larger windows benefit only by skipping a few extra
# compressions; smaller ones surface as a clear provider token-overflow
# error at request time rather than silent truncation. Will be removed
# once enforcement phase requires snapshots end to end.
_TOKEN_THRESHOLD_LEGACY_FALLBACK = 32768

_OPERATOR_OVERRIDE_FIELDS = (
    "context_window_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "default_output_reserve_tokens",
    "tokenizer_family",
)

# Per-process dedup for the "model has no capacity configured" warning.
# Without this, every agent run logs the same line, drowning real signal.
# Keyed by model_id; cleared only on process restart.
# Guarded by a lock because the check-then-add window is not atomic on its
# own: two threads can both pass the `in` check before either calls `add`,
# leading to duplicate WARNING lines defeating the per-process dedup.
_CAPACITY_WARNING_EMITTED: set = set()
_CAPACITY_WARNING_LOCK = threading.Lock()


# W11 spec line 710: emitted every time _resolve_input_budget resolves a row
# whose dispatch-time capability_profile_version is non-null (i.e. the W1
# exact catalog lookup succeeded). Combined with
# model_capacity_suggestion_accept_total at save time gives the SLO ratio
# "95% of accepted catalog suggestions produce the expected runtime profile".
# Guarded so a missing OpenTelemetry runtime never breaks agent startup.
try:
    from opentelemetry import metrics as _otel_metrics

    _capacity_dispatch_meter = _otel_metrics.get_meter(__name__)
    _capacity_dispatch_profile_hit_total = _capacity_dispatch_meter.create_counter(
        name="model_capacity_suggestion_dispatch_profile_hit_total",
        description=(
            "Count of agent dispatches where the resolved W1 capacity "
            "snapshot reports a non-null capability_profile_version "
            "(i.e. the runtime profile match succeeded). Labelled by "
            "provider."
        ),
        unit="dispatches",
    )
except Exception:  # pragma: no cover - OTel is optional at runtime
    _capacity_dispatch_profile_hit_total = None


def _record_dispatch_profile_hit(provider: Optional[str]) -> None:
    """Emit dispatch_profile_hit_total for one successful runtime profile match."""
    if _capacity_dispatch_profile_hit_total is None:
        return
    try:
        _capacity_dispatch_profile_hit_total.add(
            1,
            {"provider": (provider or "unknown").lower()},
        )
    except Exception:  # pragma: no cover - never break agent run for telemetry
        pass


def _operator_overrides_from_model_info(model_info: Optional[dict]) -> dict:
    """Extract the W1 operator-override fields from a model_record_t row."""
    if not isinstance(model_info, dict):
        return {}
    overrides = {}
    for field in _OPERATOR_OVERRIDE_FIELDS:
        value = model_info.get(field)
        if value is not None:
            overrides[field] = value
    return overrides


def _dominant_capacity_source(field_sources: dict) -> Optional[str]:
    values = [value for value in field_sources.values() if value]
    if not values:
        return None
    for preferred in ("operator", "profile", "provider_candidate", "legacy", "default", "unknown"):
        if preferred in values:
            return preferred
    return values[0]


def _capacity_snapshot_for_monitoring(snapshot: Any) -> dict:
    data = snapshot.model_dump() if hasattr(snapshot, "model_dump") else dict(snapshot)
    return {
        "provider": data.get("provider"),
        "model_name": data.get("model_name"),
        "context_window_tokens": data.get("context_window_tokens"),
        "default_output_reserve_tokens": data.get("default_output_reserve_tokens"),
        "capability_profile_version": data.get("capability_profile_version"),
        "capacity_source": _dominant_capacity_source(data.get("field_sources") or {}),
        "requested_output_tokens": data.get("requested_output_tokens"),
        "provider_input_limit_tokens": data.get("provider_input_limit_tokens"),
        "tokenizer_family": data.get("tokenizer_family"),
        "counting_mode": data.get("counting_mode"),
        "unknown_capabilities": data.get("unknown_capabilities") or [],
        "capacity_fingerprint": data.get("fingerprint"),
    }


def _safe_input_budget_for_monitoring(snapshot: Any) -> dict:
    return snapshot.model_dump() if hasattr(snapshot, "model_dump") else dict(snapshot)


def _resolve_safe_input_budget(
    *,
    capacity_snapshot: Optional[ModelCapacitySnapshot],
    tenant_id: str,
    agent_requested_output_tokens: Optional[int],
    request_requested_output_tokens: Optional[int],
) -> Optional[dict]:
    """Resolve the W2 budget snapshot before context assembly begins."""
    if capacity_snapshot is None:
        return None

    request_overrides = None
    if request_requested_output_tokens is not None:
        request_overrides = RequestBudgetOverrides(
            requested_output_tokens=request_requested_output_tokens,
        )

    output_reserve_source = (
        "agent" if agent_requested_output_tokens is not None else "model_default"
    )
    try:
        snapshot = SafeInputBudgetCalculator().calculate_safe_input_budget(
            capacity_snapshot=capacity_snapshot,
            reserve_policy=tenant_config_manager.get_capacity_reserve_policy(tenant_id),
            request_overrides=request_overrides,
            requested_output_tokens=agent_requested_output_tokens,
            output_reserve_source=output_reserve_source,
        )
    except UncertaintyReserveBasisUnknown as exc:
        # W2 uncertainty reserve needs context_window_tokens as the 10% basis.
        # Falls through here when a model row has max_input_tokens set but
        # context_window_tokens is NULL — possible for rows imported before
        # W11 V1 save-time defaults landed, or for rows written directly via
        # SQL/legacy import. Degrade to the same "no W2 snapshot" branch the
        # caller already handles (falls back to W1 input_budget).
        logger.warning(
            "W2 safe input budget unavailable (tenant_id=%s model=%s): %s - "
            "falling back to W1 input_budget. Fill context_window_tokens on the "
            "model record to enable W2 enforcement.",
            tenant_id,
            capacity_snapshot.model_name,
            exc,
        )
        return None
    logger.info(
        "W2 safe input budget resolved: tenant_id=%s model=%s requested_output_tokens=%s "
        "soft_input_budget_tokens=%s hard_input_budget_tokens=%s fingerprint=%s warnings=%s",
        tenant_id,
        snapshot.model_name,
        snapshot.requested_output_tokens,
        snapshot.soft_input_budget_tokens,
        snapshot.hard_input_budget_tokens,
        snapshot.fingerprint,
        list(snapshot.warnings),
    )
    return _safe_input_budget_for_monitoring(snapshot)


def _resolve_input_budget(
    model_info: Optional[dict],
) -> tuple[int, Optional[dict], Optional[ModelCapacitySnapshot]]:
    """Resolve the context-manager input budget for a model_record_t row.

    Calls ModelCapacityResolver with the catalog + operator overrides. Returns
    snapshot.provider_input_limit_tokens and monitoring fields on success.
    Falls back to _TOKEN_THRESHOLD_LEGACY_FALLBACK with no snapshot when
    capacity is unknown — this is the migration-window behavior before all
    model rows are backfilled.
    """
    if not isinstance(model_info, dict):
        return _TOKEN_THRESHOLD_LEGACY_FALLBACK, None, None
    provider_raw = model_info.get("model_factory")
    provider = provider_raw.lower().strip() if isinstance(provider_raw, str) else ""
    model_id = model_info.get("model_name") or ""
    provider_missing_detail = None
    if not provider:
        provider_missing_detail = (
            "model_factory/provider is missing; capacity catalog matching is disabled"
        )
    try:
        snapshot = resolve_capacity(
            model_id=model_id,
            provider=provider,
            operator_overrides=_operator_overrides_from_model_info(model_info),
            capability_profiles=CAPABILITY_CATALOG,
        )
        logger.debug(
            "Capacity resolved for (%s, %s): input_limit=%s source=%s profile=%s fingerprint=%s",
            provider, model_id,
            snapshot.provider_input_limit_tokens,
            dict(snapshot.field_sources),
            snapshot.capability_profile_version,
            snapshot.fingerprint,
        )
        if snapshot.capability_profile_version:
            _record_dispatch_profile_hit(provider)
        return (
            snapshot.provider_input_limit_tokens,
            _capacity_snapshot_for_monitoring(snapshot),
            snapshot,
        )
    except ProviderCapabilityUnknown:
        _warn_missing_capacity_once(
            model_info, provider, model_id, detail=provider_missing_detail,
        )
        return _TOKEN_THRESHOLD_LEGACY_FALLBACK, None, None
    except ResolverError as exc:
        _warn_missing_capacity_once(
            model_info, provider, model_id, detail=str(exc),
        )
        return _TOKEN_THRESHOLD_LEGACY_FALLBACK, None, None


def _warn_missing_capacity_once(
    model_info: Optional[dict],
    provider: str,
    model_id_str: str,
    detail: Optional[str] = None,
) -> None:
    """Log one WARNING per process per model when capacity is not configured.

    Plain-English message aimed at operators reading backend logs. Tells
    them what is disabled, which model is affected, and how to fix it
    through the existing UI.
    """
    db_model_id = (
        model_info.get("model_id") if isinstance(model_info, dict) else None
    )
    dedup_key = db_model_id if db_model_id is not None else f"{provider}/{model_id_str}"
    # Test-and-set inside the lock so concurrent first-time callers don't
    # both make it past the membership check. Logging happens outside the
    # lock to avoid serialising I/O across all warning paths.
    with _CAPACITY_WARNING_LOCK:
        if dedup_key in _CAPACITY_WARNING_EMITTED:
            return
        _CAPACITY_WARNING_EMITTED.add(dedup_key)

    reason = (
        f"resolver error: {detail}"
        if detail
        else "no context_window_tokens or max_output_tokens configured"
    )
    logger.warning(
        "Output token cap and budget consistency check are not enforced for "
        "model '%s' (model_id=%s, provider=%s) because %s. "
        "To enable enforcement, open the Nexent model management UI, edit "
        "this model, and fill in 'Context window tokens' and 'Max output "
        "tokens'. Falling back to a default context threshold of %s tokens.",
        model_id_str, db_model_id, provider, reason,
        _TOKEN_THRESHOLD_LEGACY_FALLBACK,
    )


def _normalize_tool_params_request(tool_params: Optional[ToolParamsRequest | Dict[str, Any]]) -> ToolParamsRequest:
    """Normalize request-scoped tool parameter overrides into a ToolParamsRequest."""
    if tool_params is None:
        return ToolParamsRequest()
    if isinstance(tool_params, ToolParamsRequest):
        return tool_params
    if not isinstance(tool_params, dict):
        raise ValidationError("tool_params must be an object.")
    try:
        return ToolParamsRequest.model_validate(tool_params)
    except Exception as exc:
        raise ValidationError(f"Invalid tool_params payload: {exc}") from exc


def _get_agent_tool_overrides(
    tool_params: Optional[ToolParamsRequest],
    agent_name: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Resolve tool overrides for a specific agent by its name."""
    if tool_params is None:
        return {}
    if not agent_name:
        return {}
    agent_override = tool_params.agents.get(agent_name)
    if agent_override is None:
        return {}
    return dict(agent_override.tools)


def _merge_tool_params(
    tool_record: Dict[str, Any],
    override_params: Optional[Dict[str, Any]],
    extra_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge request overrides on top of tool instance defaults from DB.

    Args:
        tool_record: Tool configuration from database
        override_params: Request-scoped overrides from tool_params
        extra_params: Additional internal params not in DB schema (e.g., document_paths)

    Returns:
        Merged params dict with DB defaults, overrides, and extra params
    """
    merged_params: Dict[str, Any] = {}
    for param in tool_record.get("params", []):
        merged_params[param["name"]] = param.get("default")

    if override_params:
        merged_params.update(override_params)

    # Extra params (e.g., internal access control params) always take precedence
    if extra_params:
        merged_params.update(extra_params)

    return merged_params


def _build_internal_s3_url(file: dict) -> str:
    """Build a valid S3 URL for internal tools from uploaded file metadata."""
    if not isinstance(file, dict):
        return ""

    object_name = str(file.get("object_name") or "").strip().lstrip("/")
    if object_name:
        bucket = MINIO_DEFAULT_BUCKET or "nexent"
        return f"s3://{bucket}/{object_name}"

    url = str(file.get("url") or "").strip()
    if not url or url.startswith("blob:") or url.startswith("s3:/blob:"):
        return ""

    if url.startswith("s3://"):
        return url

    if url.startswith("s3:/"):
        return "s3://" + url.replace("s3:/", "", 1).lstrip("/")

    return "s3:/" + url


def _get_skills_for_template(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0
) -> List[dict]:
    """Get skills list for prompt template injection.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number

    Returns:
        List of skill dicts with name and description
    """
    try:
        from services.skill_service import SkillService
        skill_service = SkillService()
        enabled_skills = skill_service.get_enabled_skills_for_agent(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )
        return [
            {"name": s.get("name", ""), "description": s.get("description", "")}
            for s in enabled_skills
        ]
    except Exception as e:
        logger.error(f"Failed to get skills for agent {agent_id} (tenant={tenant_id}, version={version_no}): {e}", exc_info=True)
        return []


def _extract_url_from_card(raw_card: Optional[dict]) -> str:
    """Extract http-json-rpc URL from Agent Card supportedInterfaces."""
    if not raw_card:
        return ""

    supported_interfaces = raw_card.get("supportedInterfaces", [])
    if not supported_interfaces:
        return raw_card.get("url", "")

    # Prefer http-json-rpc protocol
    for iface in supported_interfaces:
        protocol_binding = iface.get("protocolBinding", "").lower()
        if protocol_binding in ("http-json-rpc", "jsonrpc", "httpjsonrpc"):
            url = iface.get("url", "")
            if url:
                return url

    # Fallback to first interface with a URL
    for iface in supported_interfaces:
        url = iface.get("url", "")
        if url:
            return url

    return raw_card.get("url", "")


def _build_external_agent_config(agent: dict, agent_url: str) -> ExternalA2AAgentConfig:
    """Build an ExternalA2AAgentConfig from agent data."""
    return ExternalA2AAgentConfig(
        agent_id=str(agent.get("external_agent_id", "")),
        name=agent.get("name", "Unknown"),
        description=agent.get("description", "External A2A agent"),
        url=agent_url,
        api_key=None,
        transport_type=agent.get("transport_type", "http-streaming"),
        protocol_version=agent.get("protocol_version", "1.0"),
        protocol_type=agent.get("protocol_type", PROTOCOL_JSONRPC),
        timeout=300.0,
        raw_card=agent.get("raw_card"),
    )


def _get_external_a2a_agents(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0
) -> List[ExternalA2AAgentConfig]:
    """Get external A2A agent configurations for an agent.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number

    Returns:
        List of ExternalA2AAgentConfig for external A2A sub-agents
    """
    logger.info(f"[_get_external_a2a_agents] START - agent_id={agent_id}, tenant_id={tenant_id}")
    try:
        from database import a2a_agent_db

        external_agents = a2a_agent_db.query_external_sub_agents(
            local_agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        logger.info(f"[_get_external_a2a_agents] DB query returned {len(external_agents)} agents")
        logger.debug(f"[_get_external_a2a_agents] agent details: {external_agents}")

        result = []
        for agent in external_agents:
            agent_url = agent.get("agent_url", "") or _extract_url_from_card(agent.get("raw_card"))
            if not agent_url:
                logger.warning(
                    f"[_get_external_a2a_agents] Skipping agent '{agent.get('name')}' - no URL available"
                )
                continue

            result.append(_build_external_agent_config(agent, agent_url))

        logger.info(f"[_get_external_a2a_agents] returning {len(result)} ExternalA2AAgentConfig")
        for i, config in enumerate(result):
            logger.info(f"  [{i}] name={config.name}, description={config.description}")
        return result
    except Exception as e:
        logger.error(f"[_get_external_a2a_agents] FAILED: {e}", exc_info=True)
        return []


def _get_skill_script_tools(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0
) -> List[ToolConfig]:
    """Get tool config for skill script execution and skill reading.

    Args:
        agent_id: Agent ID for filtering available skills in error messages.
        tenant_id: Tenant ID for filtering available skills in error messages.
        version_no: Version number for filtering available skills.

    Returns:
        List of ToolConfig for skill execution and reading tools
    """
    from consts.const import CONTAINER_SKILLS_PATH

    skill_context = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "version_no": version_no,
    }

    try:
        return [
            ToolConfig(
                class_name="RunSkillScriptTool",
                name="run_skill_script",
                description="Execute a skill script with given parameters. Use this to run Python or shell scripts that are part of a skill.",
                inputs='{"skill_name": "str", "script_path": "str", "params": "dict"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            ),
            ToolConfig(
                class_name="ReadSkillMdTool",
                name="read_skill_md",
                description="Read skill execution guide and optional additional files. Always reads SKILL.md first, then optionally reads additional files.",
                inputs='{"skill_name": "str", "additional_files": "list[str]"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            ),
            ToolConfig(
                class_name="ReadSkillConfigTool",
                name="read_skill_config",
                description="Read the config.yaml file from a skill directory. Returns JSON containing configuration variables needed for skill workflows.",
                inputs='{"skill_name": "str"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            ),
            ToolConfig(
                class_name="WriteSkillFileTool",
                name="write_skill_file",
                description="Write content to a file within a skill directory. Creates parent directories if they do not exist.",
                inputs='{"skill_name": "str", "file_path": "str", "content": "str"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            )
        ]
    except Exception as e:
        logger.warning(f"Failed to load skill script tool: {e}")
        return []


async def create_model_config_list(tenant_id):
    records = get_model_records({"model_type": "llm"}, tenant_id)
    model_list = []
    for record in records:
        model_list.append(
            ModelConfig(cite_name=record["display_name"],
                        api_key=record.get("api_key", ""),
                        model_name=add_repo_to_name(
                                model_repo=record["model_repo"],
                                model_name=record["model_name"],
                            ),
                        url=record["base_url"],
                        ssl_verify=record.get("ssl_verify", True),
                        model_factory=record.get("model_factory"),
                        timeout_seconds=record.get("timeout_seconds"),
                        concurrency_limit=record.get("concurrency_limit"),
                        prompt_cache=resolve_prompt_cache_profile(
                            record.get("model_factory")),
                        # W1 step 6: pass capacity columns through so SDK can
                        # honor operator-configured values end to end.
                        max_output_tokens=record.get("max_output_tokens"),
                        max_tokens=record.get("max_tokens"),
                        context_window_tokens=record.get("context_window_tokens"),
                        max_input_tokens=record.get("max_input_tokens"),
                        default_output_reserve_tokens=record.get("default_output_reserve_tokens"),
                        tokenizer_family=record.get("tokenizer_family"),
                        capacity_source=record.get("capacity_source"),
                        capability_profile_version=record.get("capability_profile_version")))
    # fit for old version, main_model and sub_model use default model
    main_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
    main_prompt_cache = resolve_prompt_cache_profile(
        main_model_config.get("model_factory"))
    model_list.append(
        ModelConfig(cite_name="main_model",
                    api_key=main_model_config.get("api_key", ""),
                    model_name=get_model_name_from_config(main_model_config) if main_model_config.get(
                        "model_name") else "",
                    url=main_model_config.get("base_url", ""),
                    ssl_verify=main_model_config.get("ssl_verify", True),
                    model_factory=main_model_config.get("model_factory"),
                    timeout_seconds=main_model_config.get("timeout_seconds"),
                    concurrency_limit=main_model_config.get("concurrency_limit"),
                    prompt_cache=main_prompt_cache))
    model_list.append(
        ModelConfig(cite_name="sub_model",
                    api_key=main_model_config.get("api_key", ""),
                    model_name=get_model_name_from_config(main_model_config) if main_model_config.get(
                        "model_name") else "",
                    url=main_model_config.get("base_url", ""),
                    ssl_verify=main_model_config.get("ssl_verify", True),
                    model_factory=main_model_config.get("model_factory"),
                    timeout_seconds=main_model_config.get("timeout_seconds"),
                    concurrency_limit=main_model_config.get("concurrency_limit"),
                    prompt_cache=main_prompt_cache))

    return model_list


def _inject_plan_tools(tools: List[ToolConfig], enable_planning: bool) -> None:
    """Inject plan tool configs into the given tools list if enable_planning is True."""
    if not enable_planning:
        return

    plan_names = {"create_plan", "update_plan_step"}
    if any(t.name in plan_names for t in tools):
        return

    # description_zh/zh pairs match the bilingual descriptions in plan_tools.py
    tools.extend([
        ToolConfig(
            class_name="CreatePlanTool",
            name="create_plan",
            description="为当前任务创建执行计划。开始执行前调用一次，传入 3-8 个功能块步骤。"
            "每个步骤必须有稳定的 id（step-1、step-2、...）、简短标题和详细描述。"
            "返回创建的计划 id 和步骤数量。",
            inputs='{"plan_id": "string", "title": "string", "steps": "array"}',
            output_type="object",
            params={},
            source="builtin",
        ),
        ToolConfig(
            class_name="UpdatePlanStepTool",
            name="update_plan_step",
            description="更新单个计划步骤的状态。完成后调用 status='completed'，不再需要时调用"
            " status='skipped'，开始执行时调用 status='in_progress'。"
            "返回被更新的步骤 id 和状态。",
            inputs='{"step_id": "string", "status": "string"}',
            output_type="object",
            params={},
            source="builtin",
        ),
    ])


async def create_agent_config(
    agent_id,
    tenant_id,
    user_id,
    language: str = LANGUAGE["ZH"],
    last_user_query: str = None,
    allow_memory_search: bool = True,
    version_no: int = 0,
    override_model_id: int | None = None,
    request_requested_output_tokens: int | None = None,
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]] = None,
    request_context_policy: Optional[Dict[str, Any]] = None,
    enable_planning: bool = False,
):
    normalized_tool_params = _normalize_tool_params_request(tool_params)
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)

    # create sub agent
    sub_agent_relations = query_sub_agent_relations(
        main_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)
    managed_agents = []
    for rel in sub_agent_relations:
        sub_agent_id = rel['selected_agent_id']
        sub_agent_version_no = resolve_sub_agent_version_no(
            selected_agent_id=sub_agent_id,
            selected_agent_version_no=rel.get('selected_agent_version_no'),
            tenant_id=tenant_id,
        )
        sub_agent_config = await create_agent_config(
            agent_id=sub_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            language=language,
            last_user_query=last_user_query,
            allow_memory_search=allow_memory_search,
            version_no=sub_agent_version_no,
            override_model_id=None,
            tool_params=normalized_tool_params,
        )
        managed_agents.append(sub_agent_config)

    # create external A2A agents (synchronous function, no await needed)
    external_a2a_agents = _get_external_a2a_agents(agent_id, tenant_id, version_no)

    tool_list = await create_tool_config_list(
        agent_id,
        tenant_id,
        user_id,
        version_no=version_no,
        tool_params=normalized_tool_params,
    )

    # Append parallel_executor as a system-managed tool (always available,
    # like store_memory / search_memory).  Description and inputs are read
    # from the Tool class so they stay in sync with the SDK definition.
    tool_list.append(ToolConfig(
        class_name=ParallelExecutorTool.__name__,
        name=ParallelExecutorTool.name,
        description=ParallelExecutorTool.description,
        inputs=json.dumps(ParallelExecutorTool.inputs, ensure_ascii=False),
        output_type=ParallelExecutorTool.output_type,
        params={},
        source="local",
    ))

    # Build system prompt: prioritize segmented fields, fallback to original prompt field if not available
    duty_prompt = agent_info.get("duty_prompt", "")
    constraint_prompt = agent_info.get("constraint_prompt", "")
    few_shots_prompt = agent_info.get("few_shots_prompt", "")

    is_manager = len(managed_agents) > 0 or len(external_a2a_agents) > 0

    # Get app information
    default_app_description = 'Nexent 是一个开源智能体SDK和平台' if language == 'zh' else 'Nexent is an open-source agent SDK and platform'
    app_name = tenant_config_manager.get_app_config(
        'APP_NAME', tenant_id=tenant_id) or "Nexent"
    app_description = tenant_config_manager.get_app_config(
        'APP_DESCRIPTION', tenant_id=tenant_id) or default_app_description

    # Get memory list
    memory_context = build_memory_context(user_id, tenant_id, agent_id, skip_query=not allow_memory_search)
    memory_list = []
    if allow_memory_search and memory_context.user_config.memory_switch:
        logger.debug("Retrieving memory list...")
        memory_levels = ["tenant", "agent", "user", "user_agent"]
        if memory_context.user_config.agent_share_option == "never":
            memory_levels.remove("agent")
        if memory_context.agent_id in memory_context.user_config.disable_agent_ids:
            memory_levels.remove("agent")
        if memory_context.agent_id in memory_context.user_config.disable_user_agent_ids:
            memory_levels.remove("user_agent")

        try:
            search_res = await search_memory_in_levels(
                query_text=last_user_query,
                memory_config=memory_context.memory_config,
                tenant_id=memory_context.tenant_id,
                user_id=memory_context.user_id,
                agent_id=memory_context.agent_id,
                memory_levels=memory_levels,
            )
            memory_list = search_res.get("results", [])
            logger.debug(f"Retrieved memory list: {memory_list}")
        except Exception as e:
            # Bubble up to streaming layer so it can emit <MEM_FAILED> and fall back
            raise Exception(f"Failed to retrieve memory list: {e}")

    # Append active memory tools if memory is enabled
    if memory_context.user_config.memory_switch and memory_context.memory_config:
        try:
            memory_metadata = {
                "memory_config": memory_context.memory_config,
                "memory_user_config": memory_context.user_config,
                "tenant_id": memory_context.tenant_id,
                "user_id": memory_context.user_id,
                "agent_id": memory_context.agent_id,
            }

            memory_tool_names = {"store_memory", "search_memory"}
            tool_list = [t for t in tool_list if t.name not in memory_tool_names]

            store_tool_config = ToolConfig(
                class_name="StoreMemoryTool",
                name="store_memory",
                description=(
                    "Save important information to long-term memory for future recall. "
                    "Use this when the user shares personal preferences, facts about themselves, "
                    "project context, or instructions that should persist across conversations. "
                    "Do NOT store transient information like temporary calculations, information "
                    "already in the knowledge base, or data the user explicitly says to forget."
                ),
                inputs=json.dumps({
                    "content": {
                        "type": "string",
                        "description": "The information to remember",
                        "description_zh": "需要记住的信息"
                    }
                }, ensure_ascii=False),
                output_type="string",
                params={},
                source="local",
                usage=None,
                metadata=memory_metadata,
            )
            tool_list.append(store_tool_config)

            search_tool_config = ToolConfig(
                class_name="SearchMemoryTool",
                name="search_memory",
                description=(
                    "Search long-term memory for relevant information from previous interactions. "
                    "Use this when you need context about the user's preferences, past decisions, "
                    "or previously discussed topics that aren't in the current conversation. "
                    "The system already provides some memory context automatically -- use this tool "
                    "when you need to search for specific information not already available."
                ),
                inputs=json.dumps({
                    "query": {
                        "type": "string",
                        "description": "Natural language query describing what to search for",
                        "description_zh": "描述要搜索内容的自然语言查询"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "description_zh": "返回结果的最大数量",
                        "default": 5,
                        "nullable": True
                    }
                }, ensure_ascii=False),
                output_type="string",
                params={},
                source="local",
                usage=None,
                metadata=memory_metadata,
            )
            tool_list.append(search_tool_config)
            logger.debug("Active memory tools appended to agent tool list")
        except Exception as e:
            logger.warning(f"Failed to append active memory tools: {e}")

    # Build knowledge base summary
    knowledge_base_summary = ""
    kb_ids = []
    try:
        for tool in tool_list:
            if "KnowledgeBaseSearchTool" == tool.class_name:
                index_names = tool.params.get("index_names")
                if index_names:
                    # Reuse the index_name -> display_name mapping from tool.metadata
                    # (already computed in create_tool_config_list to avoid redundant DB query)
                    index_name_to_display_map = tool.metadata.get("index_name_to_display_map", {}) if tool.metadata else {}
                    for index_name in index_names:
                        try:
                            display_name = index_name_to_display_map.get(index_name, index_name)
                            message = ElasticSearchService().get_summary(index_name=index_name)
                            summary = message.get("summary", "")
                            knowledge_base_summary += f"**{display_name}**: {summary}\n\n"
                            kb_ids.append(index_name)
                        except Exception as e:
                            logger.warning(
                                f"Failed to get summary for knowledge base {index_name}: {e}")
                else:
                    # TODO: Prompt should be refactored to yaml file
                    knowledge_base_summary = "当前没有可用的知识库索引。\n" if language == 'zh' else "No knowledge base indexes are currently available.\n"
                break  # Only process the first KnowledgeBaseSearchTool found
    except Exception as e:
        logger.error(f"Failed to build knowledge base summary: {e}")

    # This compatibility flag controls compression only. ContextManager remains
    # the single context assembly path when compression is disabled.
    enable_context_manager = agent_info.get("enable_context_manager", False)

    # Get the skills included in ContextManager items.
    skills = _get_skills_for_template(agent_id, tenant_id, version_no)

    is_manager = len(managed_agents) > 0 or len(external_a2a_agents) > 0
    builtin_tools = _get_skill_script_tools(agent_id, tenant_id, version_no)
    available_tools = tool_list + builtin_tools

    _inject_plan_tools(available_tools, enable_planning)

    render_kwargs = {
        "duty": duty_prompt,
        "constraint": constraint_prompt,
        "few_shots": few_shots_prompt,
        "tools": {tool.name: tool for tool in available_tools},
        "skills": skills,
        "managed_agents": {agent.name: agent for agent in managed_agents},
        "external_a2a_agents": {agent.agent_id: agent for agent in external_a2a_agents},
        "APP_NAME": app_name,
        "APP_DESCRIPTION": app_description,
        "memory_list": memory_list,
        "knowledge_base_summary": knowledge_base_summary,
        "user_id": user_id,
    }
    model_id_to_use = override_model_id if override_model_id else agent_info.get("model_id")
    model_info = None
    if model_id_to_use is not None:
        model_info = get_model_by_model_id(model_id_to_use, tenant_id=tenant_id)
        model_name = model_info["display_name"] if model_info is not None else "main_model"
        # W1 step 6: derive input budget via ModelCapacityResolver instead of
        # treating model_info["max_tokens"] (a deprecated output cap) as a
        # context threshold. Falls back to a safe constant when capacity is
        # unknown during the migration window.
        input_budget, capacity_snapshot, resolved_capacity_snapshot = (
            _resolve_input_budget(model_info)
        )
    else:
        model_name = "main_model"
        input_budget = _TOKEN_THRESHOLD_LEGACY_FALLBACK
        capacity_snapshot = None
        resolved_capacity_snapshot = None

    requested_output_tokens = agent_info.get("requested_output_tokens")
    safe_input_budget_snapshot = _resolve_safe_input_budget(
        capacity_snapshot=resolved_capacity_snapshot,
        tenant_id=tenant_id,
        agent_requested_output_tokens=requested_output_tokens,
        request_requested_output_tokens=request_requested_output_tokens,
    )
    if safe_input_budget_snapshot is not None:
        soft_input_budget_tokens = safe_input_budget_snapshot["soft_input_budget_tokens"]
        hard_input_budget_tokens = safe_input_budget_snapshot["hard_input_budget_tokens"]
        context_token_threshold = soft_input_budget_tokens
    else:
        soft_input_budget_tokens = 0
        hard_input_budget_tokens = 0
        context_token_threshold = input_budget

    context_window_tokens = (
        resolved_capacity_snapshot.context_window_tokens
        if resolved_capacity_snapshot is not None
        and resolved_capacity_snapshot.context_window_tokens is not None
        else input_budget
    )

    logger.info(
        "Agent main LLM: agent_id=%s, model_id=%s, display_name=%s, model_name=%s",
        agent_id,
        model_id_to_use,
        model_info.get("display_name") if model_info else model_name,
        model_info.get("model_name") if model_info else model_name,
    )

    context_items = build_context_inputs(
        duty=duty_prompt,
        constraint=constraint_prompt,
        few_shots=few_shots_prompt,
        app_name=app_name,
        app_description=app_description,
        user_id=user_id,
        language=language,
        is_manager=is_manager,
        enable_planning=enable_planning,
        tools=render_kwargs["tools"],
        skills=skills,
        managed_agents=render_kwargs["managed_agents"],
        external_a2a_agents=render_kwargs["external_a2a_agents"],
        memory_list=memory_list,
        memory_search_query=last_user_query,
        knowledge_base_summary=knowledge_base_summary,
        kb_ids=kb_ids,
    )

    logger.info(
        f"Agent {agent_id} context assembly: "
        f"skills_count={len(skills)}, "
        f"items={[f'{item.id}(type={item.type.value},priority={item.priority})' for item in context_items]}"
    )
    policy_layers = PolicyLayers.model_validate({
        "platform": {
            "processing_mode": "adaptive_compact" if enable_context_manager else "passthrough"
        },
        "tenant": tenant_config_manager.get_context_policy(tenant_id),
        "agent": agent_info.get("context_policy"),
        "request": request_context_policy,
    })
    effective_context_policy = resolve_policy(policy_layers)
    effective_processing_mode = getattr(
        effective_context_policy.processing_mode,
        "value",
        effective_context_policy.processing_mode,
    )
    policy_layers_payload = (
        policy_layers.model_dump(mode="json")
        if hasattr(policy_layers, "model_dump")
        else policy_layers
    )
    logger.info(
        "Agent %s effective context policy: processing_mode=%s layers=%s",
        agent_id,
        effective_processing_mode,
        policy_layers_payload,
    )
    cm_config = ContextManagerConfig(
        token_threshold=context_token_threshold,
        context_window_tokens=context_window_tokens,
        soft_input_budget_tokens=soft_input_budget_tokens,
        hard_input_budget_tokens=hard_input_budget_tokens,
        policy_layers=policy_layers,
    )


    agent_config = AgentConfig(
        name="undefined" if agent_info["name"] is None else agent_info["name"],
        description="undefined" if agent_info["description"] is None else agent_info["description"],
        prompt_templates=await prepare_prompt_templates(
            is_manager=len(managed_agents) > 0 or len(external_a2a_agents) > 0,
            language=language,
            agent_id=agent_id
        ),
        tools=available_tools,
        max_steps=agent_info.get("max_steps", 15),
        requested_output_tokens=requested_output_tokens,
        model_name=model_name,
        provide_run_summary=agent_info.get("provide_run_summary", False),
        managed_agents=managed_agents,
        external_a2a_agents=external_a2a_agents,
        context_manager_config=cm_config,
        context_items=context_items,
        capacity_snapshot=capacity_snapshot,
        safe_input_budget_snapshot=safe_input_budget_snapshot,
        verification_config=AgentVerificationConfig.model_validate(agent_info.get("verification_config") or {}),
        enable_planning=enable_planning,
    )
    logger.info(
        "Agent metadata | name=%s | tool_list=%s | managed_agents=%s | model_name=%s | max_steps=%s | enable_planning=%s | has_plan_tools=%s",
        agent_config.name,
        [t.name for t in agent_config.tools],
        [a.name for a in agent_config.managed_agents],
        agent_config.model_name,
        agent_config.max_steps,
        agent_config.enable_planning,
        any(t.name in {"create_plan", "update_plan_step"} for t in agent_config.tools),
    )
    return agent_config


async def create_tool_config_list(
    agent_id,
    tenant_id,
    user_id,
    version_no: int = 0,
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]] = None,
):
    tool_config_list = []
    langchain_tools = await discover_langchain_tools()
    normalized_tool_params = _normalize_tool_params_request(tool_params)

    # now only admin can modify the agent, user_id is not used
    tools_list = search_tools_for_sub_agent(agent_id, tenant_id, version_no=version_no)

    # Look up agent name for use in error messages.
    # Agent name is optional for tool_params matching (matching uses tool identifiers only),
    # but we include it in error messages so callers can identify which agent/tool caused a failure.
    agent_info = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)
    agent_name = agent_info.get("name") if agent_info else None
    agent_tool_overrides = _get_agent_tool_overrides(normalized_tool_params, agent_name)

    tool_keys_seen = set()
    for tool in tools_list:
        tool_identifier = tool.get("name") or tool.get("class_name")
        if tool_identifier in tool_keys_seen:
            raise ValidationError(
                f"Duplicate tool identifier '{tool_identifier}' found in agent '{agent_name or agent_id}'."
            )
        tool_keys_seen.add(tool_identifier)

        override_params = None
        if tool.get("name") in agent_tool_overrides:
            override_params = agent_tool_overrides[tool.get("name")]
        elif tool.get("class_name") in agent_tool_overrides:
            override_params = agent_tool_overrides[tool.get("class_name")]

        param_dict = _merge_tool_params(tool, override_params)
        if tool.get("class_name") == "AidpSearchTool":
            # Credentials are backend-owned since the v7.1 permission
            # redesign; populate them from the central constants (the
            # database row may carry a stale value).
            param_dict.pop("server_url", None)
            param_dict.pop("api_key", None)
            param_dict.pop("tenant_id", None)
            param_dict.update({
                "server_url": AIDP_SERVER_URL,
                "api_key": AIDP_API_KEY,
                "tenant_id": AIDP_TENANT_ID,
            })

        # v7.1: inject the runtime whitelist for AidpSearchTool. The
        # permission service recomputes it on every agent call so per-KB
        # permission changes take effect immediately without re-publishing
        # the agent. Falls back to the configured ``kds_list`` when the
        # whitelist lookup fails (defensive path).
        _allowed_kds_set: set[str] = set()
        if tool.get("class_name") == "AidpSearchTool":
            try:
                from ext_components.aidp.services import (
                    aidp_permission_service as _aidp_perms,
                )
                _allowed_kds_set = set(
                    _aidp_perms.get_allowed_kds_list(
                        user_id=user_id, tenant_id=tenant_id,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Aidp permission whitelist lookup failed; "
                    "falling back to configured kds_list: %s", exc,
                )

        tool_config = ToolConfig(
            class_name=tool.get("class_name"),
            name=tool.get("name"),
            description=tool.get("description"),
            inputs=tool.get("inputs"),
            output_type=tool.get("output_type"),
            params=param_dict,
            source=tool.get("source"),
            usage=tool.get("usage")
        )

        if tool.get("class_name") == "AidpSearchTool":
            # Carry over the runtime whitelist first; langchain metadata, if
            # any, takes precedence for non-whitelist keys via the merge.
            tool_config.metadata = {
                **tool_config.metadata,
                "allowed_kds_set": _allowed_kds_set,
            }
            tool_class_name = tool.get("class_name")
            for langchain_tool in langchain_tools:
                if langchain_tool.name == tool_class_name:
                    tool_config.metadata = {
                        **tool_config.metadata,
                        "langchain_tool": langchain_tool,
                    }
                    break

        if tool.get("source") == "langchain" and tool.get("class_name") != "AidpSearchTool":
            tool_class_name = tool.get("class_name")
            for langchain_tool in langchain_tools:
                if langchain_tool.name == tool_class_name:
                    tool_config.metadata = langchain_tool
                    break

        # Extract document_paths for KnowledgeBaseSearchTool (internal access control, not in DB schema)
        document_paths = None
        if override_params and "document_paths" in override_params:
            document_paths = override_params.get("document_paths")
        # Also check using the tool name as key
        if not document_paths:
            kb_overrides = agent_tool_overrides.get("knowledge_base_search")
            if kb_overrides and "document_paths" in kb_overrides:
                document_paths = kb_overrides.get("document_paths")

        # special logic for search tools that may use reranking models
        if tool_config.class_name == "KnowledgeBaseSearchTool":
            rerank = tool_config.params.get("rerank", False)
            rerank_model_name = tool_config.params.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            # Build display_name to index_name mapping for LLM parameter conversion
            # Also build reverse mapping (index_name -> display_name) for knowledge_base_summary
            index_names = tool_config.params.get("index_names", [])

            # Enforce knowledge-base-level read permission for the chatting user.
            # Agent-level permission controls "who can use this agent", but each knowledge
            # base has its own "who can read" permission (group_ids + ingroup_permission).
            # Filter out any index the current user does NOT have at least read access to,
            # so the tool, its display-name mapping, and the injected KB summary all honour
            # the per-KB ACL.
            if index_names:
                original_count = len(index_names)
                index_names = ElasticSearchService.filter_accessible_indices(
                    index_names, user_id=user_id, tenant_id=tenant_id,
                )
                filtered_count = original_count - len(index_names)
                if filtered_count > 0:
                    logger.info(
                        "Filtered %d inaccessible knowledge base(s) for user '%s' in agent '%s'",
                        filtered_count, user_id, agent_name or agent_id,
                    )
                # Persist the filtered list back into params so downstream consumers
                # (knowledge_base_summary builder, metadata) see only accessible indices.
                tool_config.params["index_names"] = index_names

            display_name_to_index_map = {}
            index_name_to_display_map = {}
            if index_names:
                knowledge_name_map = get_knowledge_name_map_by_index_names(
                    index_names,
                    tenant_id=tenant_id,
                )
                # Reverse the mapping: display_name (knowledge_name) -> index_name
                for idx_name, kb_name in knowledge_name_map.items():
                    display_name_to_index_map[kb_name] = idx_name
                    index_name_to_display_map[idx_name] = kb_name

            tool_config.metadata = {
                "vdb_core": get_vector_db_core(),
                "embedding_model": None,
                "rerank_model": rerank_model,
                "display_name_to_index_map": display_name_to_index_map,
                "index_name_to_display_map": index_name_to_display_map,
                # Internal access control: restrict results to specific document paths (path_or_urls)
                "document_paths": document_paths,
                # Defense-in-depth whitelist: forward() will reject any index not in this list,
                # even if the LLM fabricates an unauthorized index name.
                "allowed_index_names": list(index_names),
            }

            if not index_names:
                # Empty after permission filtering means the current user has no read access
                # to any of the agent's configured knowledge bases. Instead of skipping the tool
                # (which would cause the LLM to hallucinate tool calls against a non-existent tool),
                # we keep the tool in the list with empty index_names. The SDK forward() will return
                # a clear "no accessible knowledge base" message, allowing the LLM to explain
                # the situation to the user instead of entering a retry loop.
                logger.warning(
                    "Keeping knowledge_base_search tool for agent '%s' with no accessible "
                    "knowledge bases for user '%s' after permission filtering. "
                    "Tool will return a permission-denial message at search time.",
                    agent_name or agent_id, user_id,
                )
                # Append the tool and skip embedding model lookup (no index to lookup from)
                tool_config_list.append(tool_config)
                continue

            embedding_model, _, _ = get_embedding_model_by_index_name(tenant_id, index_names[0])
            if not embedding_model:
                raise ValidationError(
                    f"No embedding model found for index '{index_names[0]}'. "
                    f"Please configure an embedding model for this knowledge base.")
            tool_config.metadata["embedding_model"] = embedding_model
        elif tool_config.class_name in ["DifySearchTool", "DataMateSearchTool", "RAGFlowSearchTool"]:
            rerank = tool_config.params.get("rerank", False)
            rerank_model_name = tool_config.params.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            tool_config.metadata = {
                "rerank_model": rerank_model,
            }
        elif tool_config.class_name == "AnalyzeTextFileTool":
            selected_model_id = param_dict.get("selected_model_id")
            tool_config.metadata = {
                "llm_model": get_llm_model(tenant_id=tenant_id, model_id=selected_model_id),
                "storage_client": minio_client,
                "data_process_service_url": DATA_PROCESS_SERVICE,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id)
            }
        elif tool_config.class_name == "AnalyzeImageTool":
            selected_model_id = param_dict.get("selected_model_id")
            tool_config.metadata = {
                # get_vlm_model reads the first multimodal slot, now shown as image understanding.
                "vlm_model": get_vlm_model(tenant_id=tenant_id, model_id=selected_model_id),
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id)
            }
        elif tool_config.class_name in ["AnalyzeAudioTool", "AnalyzeVideoTool"]:
            selected_model_id = param_dict.get("selected_model_id")
            tool_config.metadata = {
                "vlm_model": get_video_understanding_model(tenant_id=tenant_id, model_id=selected_model_id),
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id)
            }

        tool_config_list.append(tool_config)

    return tool_config_list


async def discover_langchain_tools():
    """
    Discover LangChain tools implemented with the `@tool` decorator.

    Returns:
        list: List of discovered LangChain tool instances
    """
    from utils.langchain_utils import discover_langchain_modules

    langchain_tools = []

    # ----------------------------------------------
    # Discover LangChain tools implemented with the
    # `@tool` decorator and convert them to ToolConfig
    # ----------------------------------------------
    try:
        # Use the utility function to discover all BaseTool objects
        discovered_tools = discover_langchain_modules()

        for obj, filename in discovered_tools:
            try:
                # Log successful tool discovery
                logger.info(
                    f"Loaded LangChain tool '{obj.name}' from {filename}")
                langchain_tools.append(obj)
            except Exception as e:
                logger.error(
                    f"Error processing LangChain tool from {filename}: {e}")

    except Exception as e:
        logger.error(
            f"Unexpected error scanning LangChain tools directory: {e}")

    return langchain_tools


async def prepare_prompt_templates(
    is_manager: bool,
    language: str = 'zh',
    agent_id: int = None,
):
    """
    Prepare prompt templates, support multiple languages

    Args:
        is_manager: Whether it is a manager mode
        language: Language code ('zh' or 'en')
        agent_id: Agent ID for fetching skill instances

    Returns:
        dict: Prompt template configuration
    """
    prompt_templates = get_agent_prompt_template(is_manager, language)
    # Stable context is assembled exclusively by ContextManager. Keep the key
    # for smolagents prompt-template compatibility, but never source it from a
    # second rendering path.
    prompt_templates["system_prompt"] = ""

    return prompt_templates


async def join_minio_file_description_to_query(
    minio_files,
    query,
    history=None,
    max_files: int = 50,
    max_chars: int = 10000,
):
    """
    Join MinIO file descriptions to the user query.

    This function formats uploaded file information into a structured description
    that includes both S3 URL (for internal tools) and presigned_url (for external MCP tools).
    It processes files from both the current message and historical messages.

    De-duplication is performed using the file URL as the unique key. A maximum
    file count and total character limit are enforced to prevent prompt bloat.

    Args:
        minio_files: List of file info dicts from current message upload
        query: Original user query
        history: Optional list of historical message dicts, each may contain minio_files
        max_files: Maximum number of files to include (default 50)
        max_chars: Maximum total characters for file descriptions (default 10000)

    Returns:
        Modified query with file descriptions appended
    """
    final_query = query
    seen_urls: set[str] = set()
    all_files: list[dict] = []

    # Collect files from current message first (higher priority)
    if minio_files and isinstance(minio_files, list):
        for file in minio_files:
            if isinstance(file, dict) and file.get("name") and (file.get("url") or file.get("object_name")):
                s3_url = _build_internal_s3_url(file)
                if not s3_url:
                    continue
                if s3_url not in seen_urls:
                    seen_urls.add(s3_url)
                    all_files.append(file)

    # Collect files from historical messages (lower priority, already-deduped)
    if history and isinstance(history, list):
        for msg in history:
            if isinstance(msg, dict) and msg.get("minio_files"):
                for file in msg["minio_files"]:
                    if isinstance(file, dict) and file.get("name") and (file.get("url") or file.get("object_name")):
                        s3_url = _build_internal_s3_url(file)
                        if not s3_url:
                            continue
                        if s3_url not in seen_urls:
                            seen_urls.add(s3_url)
                            all_files.append(file)

    # Enforce file count limit (keep most recent files by truncating from the end)
    if len(all_files) > max_files:
        all_files = all_files[:max_files]
        logger.debug(f"File list truncated from {len(all_files)} to {max_files} files")

    if all_files:
        file_descriptions: list[str] = []
        # Calculate fixed overhead that is added only once
        prefix = "User uploaded files. The file information is as follows:\n"
        suffix = f"\n\nUser wants to answer questions based on the information in the above files: {query}"
        fixed_overhead = len(prefix) + len(suffix)

        for i, file in enumerate(all_files):
            s3_url = _build_internal_s3_url(file)
            presigned_url = file.get("presigned_url", "")

            # Build description with both URLs
            if presigned_url:
                desc = (
                    f"File name: {file['name']}\n"
                    f"- S3 URL: {s3_url}  [for tools WITHOUT [MCP] prefix, like analyze_text_file]\n"
                    f"- presigned_url: {presigned_url}  [for tools WITH [MCP] prefix]"
                )
            else:
                desc = f"File name: {file['name']}, S3 URL: {s3_url}  [permanent]"

            # Calculate total length if we include this description
            # Each description after the first adds 2 chars for \n\n separator
            separator_chars = 2 if i > 0 else 0
            total_len = sum(len(d) for d in file_descriptions) + len(desc) + separator_chars + fixed_overhead

            # Check if adding this description would exceed the character limit
            if total_len > max_chars:
                logger.debug(
                    f"File descriptions truncated at {len(file_descriptions)} files "
                    f"to stay within {max_chars} character limit"
                )
                break

            file_descriptions.append(desc)

        if file_descriptions:
            final_query = prefix + "\n\n".join(file_descriptions) + suffix

    return final_query


def _format_minio_files_for_content(minio_files: Optional[List[dict]], max_files: int = 20) -> str:
    """Format minio_files into a string for embedding in history content.

    Args:
        minio_files: List of file info dicts
        max_files: Maximum number of files to include per message

    Returns:
        Formatted string describing the files, or empty string if no files
    """
    if not minio_files or not isinstance(minio_files, list):
        return ""

    file_lines = []
    for i, file in enumerate(minio_files):
        if i >= max_files:
            file_lines.append(f"  - ... (and {len(minio_files) - max_files} more files)")
            break
        if isinstance(file, dict) and file.get("name") and (file.get("url") or file.get("object_name")):
            s3_url = _build_internal_s3_url(file)
            if not s3_url:
                continue
            presigned_url = file.get("presigned_url", "")
            if presigned_url:
                file_lines.append(
                    f"  - {file['name']}: {s3_url} (for non-MCP tools), presigned_url: {presigned_url} (for [MCP] tools)"
                )
            else:
                file_lines.append(f"  - {file['name']}: {s3_url}")

    if not file_lines:
        return ""

    return "\n[Attached files]:\n" + "\n".join(file_lines)


def _convert_history_with_minio_files(history: List) -> Optional[List[AgentHistory]]:
    """Convert HistoryItem list to AgentHistory list, embedding minio_files into content.

    Args:
        history: List of HistoryItem from API

    Returns:
        List of AgentHistory with file info embedded in content, or None if history is None
    """
    if history is None:
        return None

    result = []
    for item in history:
        content = item.content
        if item.minio_files:
            file_info = _format_minio_files_for_content(item.minio_files)
            if file_info:
                content = content + file_info if content else file_info
        result.append(AgentHistory(role=item.role, content=content))
    return result


def filter_mcp_servers_and_tools(input_agent_config: AgentConfig, mcp_info_dict) -> list:
    """
    Filter mcp servers and tools, only keep the actual used mcp servers
    Support multi-level agent, recursively check all sub-agent tools
    """
    used_mcp_urls = set()

    # Recursively check all agent tools
    def check_agent_tools(agent_config: AgentConfig):
        # Check current agent tools
        for tool in agent_config.tools:
            if tool.source == "mcp" and tool.usage in mcp_info_dict:
                used_mcp_urls.add(
                    mcp_info_dict[tool.usage]["remote_mcp_server"])

        # Recursively check sub-agents (only internal AgentConfig, not external A2A)
        for sub_agent_config in agent_config.managed_agents:
            check_agent_tools(sub_agent_config)

    # Check all agent tools
    check_agent_tools(input_agent_config)

    return list(used_mcp_urls)


async def create_agent_run_info(
    agent_id,
    minio_files,
    query,
    history,
    tenant_id: str,
    user_id: str,
    language: str = "zh",
    allow_memory_search: bool = True,
    is_debug: bool = False,
    override_version_no: int | None = None,
    override_model_id: int | None = None,
    requested_output_tokens: int | None = None,
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]] = None,
    context_policy: Optional[Dict[str, Any]] = None,
    enable_planning: bool = False,
):
    # Determine which version_no to use based on is_debug flag
    # If is_debug=false, use the current published version (current_version_no)
    # If is_debug=true, use version 0 (draft/editing state)
    if override_version_no is not None:
        version_no = override_version_no
    elif is_debug:
        version_no = 0
    else:
        version_no = query_current_version_no(agent_id=agent_id, tenant_id=tenant_id)
        if version_no is None:
            version_no = 0
            logger.info(f"Agent {agent_id} has no published version, using draft version 0")

    final_query = await join_minio_file_description_to_query(
        minio_files=minio_files,
        query=query,
        history=history
    )
    model_list = await create_model_config_list(tenant_id)
    create_config_kwargs = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "language": language,
        "last_user_query": final_query,
        "allow_memory_search": allow_memory_search,
        "version_no": version_no,
        "enable_planning": enable_planning,
    }
    if override_model_id is not None:
        create_config_kwargs["override_model_id"] = override_model_id
    if requested_output_tokens is not None:
        create_config_kwargs["request_requested_output_tokens"] = requested_output_tokens
    if context_policy is not None:
        create_config_kwargs["request_context_policy"] = context_policy

    agent_config = await create_agent_config(**create_config_kwargs, tool_params=tool_params)

    remote_mcp_list = await get_remote_mcp_server_list(tenant_id=tenant_id, is_need_auth=True)
    default_mcp_url = urljoin(LOCAL_MCP_SERVER, "sse")
    remote_mcp_list.append({
        "remote_mcp_server_name": "outer-apis",
        "remote_mcp_server": default_mcp_url,
        "status": True,
        "authorization_token": None
    })
    remote_mcp_dict = {record["remote_mcp_server_name"]: record for record in remote_mcp_list if record["status"]}

    # Filter MCP servers and tools, and build mcp_host with authorization
    used_mcp_urls = filter_mcp_servers_and_tools(agent_config, remote_mcp_dict)

    # Build mcp_host list with authorization tokens and custom headers
    mcp_host = []
    for url in used_mcp_urls:
        # Find the MCP record for this URL
        mcp_record = None
        for record in remote_mcp_list:
            if record.get("remote_mcp_server") == url and record.get("status"):
                mcp_record = record
                break

        if mcp_record:
            mcp_config = {
                "url": url,
                "transport": "sse" if url.endswith("/sse") else "streamable-http"
            }
            headers = {}
            auth_token = mcp_record.get("authorization_token")
            if auth_token:
                headers["Authorization"] = auth_token
            custom_headers = mcp_record.get("custom_headers")
            if custom_headers and isinstance(custom_headers, dict):
                headers.update(custom_headers)
            if headers:
                mcp_config["headers"] = headers
            mcp_host.append(mcp_config)
        else:
            # Fallback to string format if record not found
            mcp_host.append(url)

    # Convert HistoryItem (from API) to AgentHistory (expected by SDK)
    converted_history = _convert_history_with_minio_files(history)

    # Resolve sandbox config: DB policy overrides env-var defaults.
    # build_sandbox_policy returns None when level=local (backward-compatible).
    # Import inside function body to avoid circular dependency.
    from services.agent_service import build_sandbox_policy, get_sandbox_minio_client
    sandbox_policy = build_sandbox_policy(tenant_id=tenant_id, agent_type="")
    agent_db_policy = getattr(agent_config, "sandbox_policy", None)
    merged_policy = sandbox_policy if sandbox_policy else agent_db_policy
    sandbox_config = SandboxConfig.from_dict(merged_policy) if merged_policy else None
    minio_client = get_sandbox_minio_client() if sandbox_config and sandbox_config.auto_sync_outputs else None

    agent_run_info = AgentRunInfo(
        query=final_query,
        model_config_list=model_list,
        observer=MessageObserver(lang=language),
        agent_config=agent_config,
        mcp_host=mcp_host,
        history=converted_history,
        stop_event=threading.Event(),
        capacity_snapshot=getattr(agent_config, "capacity_snapshot", None),
        safe_input_budget_snapshot=getattr(
            agent_config,
            "safe_input_budget_snapshot",
            None,
        ),
        sandbox_config=sandbox_config,
        minio_client=minio_client,
        redis_client=get_redis_client(),
    )
    return agent_run_info
