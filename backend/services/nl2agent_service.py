"""NL2AGENT conversational agent generator service.

Provides the business logic for the NL2AGENT default agent: a conversational agent
that helps users build custom agents via multi-turn chat.

This module is a compatibility facade while workflow domains are moved into
focused services. Publication is delegated to ``nl2agent_publication_service``;
the three SDK search tools consume backend-injected immutable catalogs.
"""

import logging
import re
import unicodedata
import uuid
from functools import partial
from typing import Any, Dict, List, Optional

from nexent.core.tools.nl2agent.search_web_mcps_tool import normalize_mcp_candidate

from agents.nl2agent_session_catalog import (
    acquire_mcp_installation_lock,
    apply_requirements_revision_text,
    assert_trusted_local_search_batch,
    assert_workflow_action_allowed,
    assert_requirements_confirmed,
    assert_identity_confirmed,
    assert_mcp_workflows_resolved,
    assert_online_configuration_complete,
    assert_resource_review_complete,
    complete_recommendation_batch_apply,
    complete_online_configuration as complete_online_configuration_state,
    complete_mcp_binding_operation,
    complete_online_installation,
    confirm_requirements_summary,
    confirm_agent_identity,
    delete_nl2agent_session_catalogs,
    get_nl2agent_session_catalogs,
    get_nl2agent_session_state,
    initialize_nl2agent_session_state,
    register_recommendation_batch,
    register_online_recommendation_batch,
    register_requirements_summary,
    record_card_delivery,
    release_mcp_installation_lock,
    release_mcp_binding_operation,
    release_online_installation,
    release_recommendation_batch_apply,
    renew_mcp_installation_lock,
    resolve_recommendation_batch,
    reserve_recommendation_batch_apply,
    reserve_mcp_binding_operation,
    reserve_online_installation,
    set_nl2agent_session_catalogs,
    set_model_selection_confirmed,
    summarize_workflow_state,
    update_mcp_workflow,
)
from consts.const import LANGUAGE
from consts.const import DEFAULT_TENANT_ID, DEFAULT_USER_ID
from consts.exceptions import (
    AgentRunException,
    AppException,
    Nl2AgentCatalogUnavailableError as Nl2AgentCatalogUnavailableError,
    Nl2AgentDraftNotFoundError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
)
from consts.model import (
    AgentInfoRequest,
)
from database.agent_db import (
    create_agent,
    find_agent_id_by_agent_name,
    find_agent_info_by_agent_id,
    query_all_agent_info_by_tenant_id,
    search_agent_id_by_agent_name,
    search_agent_info_by_agent_id,
    update_agent,
)
from database.conversation_db import (
    create_conversation,
    get_conversation,
    get_latest_assistant_message_id,
    get_message,
    get_message_units,
)
from database.client import get_db_session
from database.model_management_db import get_model_records
from database.nl2agent_session_db import (
    NL2AGENT_SESSION_ACTIVE,
    create_nl2agent_session,
    get_nl2agent_session_by_conversation,
    update_nl2agent_session_status,
)
from database.skill_db import (
    create_or_update_skill_by_skill_info,
    get_skill_by_name as get_tenant_skill_by_name,
    list_skills_for_catalog as list_tenant_skills,
    query_enabled_skill_instances,
    query_skills_by_ids,
)
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    delete_tool_instances_by_ids,
    query_all_enabled_tool_instances,
    query_tools_by_ids_for_tenant,
    seed_nl2agent_builtin_tools,
    upsert_discovered_mcp_tools,
)
from database.remote_mcp_db import (
    get_mcp_record_by_id_and_tenant,
    get_mcp_records_by_tenant,
)
from services.mcp_management_service import (
    list_community_mcp_services,
    list_registry_mcp_services,
)
from services.nl2agent_catalog_service import (
    CatalogDependencies,
    SkillInstallationDependencies,
    install_web_skill as install_web_skill_service,
    load_session_catalogs,
    recommendation_id as _recommendation_id,
)
from services.nl2agent_mcp_service import (
    McpBindingDependencies,
    McpDiscoveryDependencies,
    McpInstallationDependencies,
    McpLockDependencies,
    McpProviderDependencies,
    McpSessionDependencies,
    bind_mcp_tools as bind_mcp_tools_service,
    install_recommended_mcp as install_recommended_mcp_service,
    skip_mcp_tool_binding as skip_mcp_tool_binding_service,
)
from services.nl2agent_mcp_url_security import (
    build_pinned_httpx_client_factory,
    validate_remote_mcp_url as validate_nl2agent_remote_mcp_url,
)
from services.nl2agent_publication_service import (
    PublicationDraftDependencies,
    PublicationDependencies,
    PublicationModelDependencies,
    PublicationPersistenceDependencies,
    PublicationProposal,
    PublicationResourceDependencies,
    PublicationWorkflowDependencies,
    publish_agent,
)
from services.nl2agent_resource_service import (
    LocalResourceDependencies,
    apply_local_resources,
    register_local_recommendations,
    skip_local_recommendations,
)
from services.nl2agent_session_service import (
    SessionInitializationDependencies,
    start_session as initialize_session,
)
from services.nl2agent_seed_service import (
    SeedDependencies,
    ensure_builder_ready,
    normalize_model_ids,
    seed_default_agent,
)
from services.nl2agent_summary_service import (
    raise_for_invalid_resource_references,
    resolve_model_summaries,
    resolve_resource_summaries,
    validate_available_llm_ids,
)
from services.nl2agent_workflow_service import (
    WorkflowDependencies,
    confirm_online_resource_configuration as confirm_online_configuration_workflow,
    confirm_requirements_review as confirm_requirements_review_workflow,
    get_session_state as get_workflow_session_state,
    process_requirements_revision_text as process_requirements_revision_workflow,
    register_online_resource_recommendations as register_online_recommendations_workflow,
    register_requirements_review as register_requirements_review_workflow,
    report_card_delivery as report_card_delivery_workflow,
    save_agent_identity as save_agent_identity_workflow,
)
from utils.nl2agent_card_validation import message_contains_valid_card
from services.remote_mcp_service import (
    add_container_mcp_service,
    add_mcp_service,
    reconfigure_container_mcp_service,
    update_mcp_service,
)
from services.tool_configuration_service import get_tool_from_remote_mcp_server
from services.skill_service import (
    get_official_skills_with_status,
    install_skills_for_tenant,
    install_skills_from_zip_for_tenant,
)
from services.tool_configuration_service import list_all_tools
from utils.prompt_template_utils import get_nl2agent_seed_config

logger = logging.getLogger(__name__)

# Reserved name of the NL2AGENT default agent shipped with the product.
NL2AGENT_AGENT_NAME = "nl2agent"

# Prefix for draft agent names created during NL2AGENT sessions.
DRAFT_AGENT_NAME_PREFIX = "draft_"

NL2AGENT_CHAT_INJECTION_TEXT = (
    "[[NL2AGENT_AUTO_CONTINUE]]\n"
    "The previous card action completed successfully. Re-read the authoritative "
    "Current Session state and continue naturally from the next incomplete stage. "
    "Do not ask the user to type continue."
)
NL2AGENT_CARD_RETRY_INJECTION_TEXT = (
    "[[NL2AGENT_CARD_RETRY]]\n"
    "The previous card output could not be rendered. Re-read the authoritative "
    "Current Session state and generate only the card required by the first "
    "incomplete stage. Do not claim the previous card is still valid."
)


def _is_draft_agent_name(name: Optional[str]) -> bool:
    return bool(name) and name.startswith(DRAFT_AGENT_NAME_PREFIX)


def _generate_internal_agent_name(
    display_name: str, agent_id: int, tenant_id: str
) -> str:
    """Generate a valid, tenant-unique internal identifier from a display title."""
    ascii_name = (
        unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode()
    )
    candidate = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_").lower()
    if not candidate or not re.match(r"^[A-Za-z_]", candidate):
        candidate = f"agent_{agent_id}"
    candidate = candidate[:50].rstrip("_") or f"agent_{agent_id}"
    existing_id = find_agent_id_by_agent_name(candidate, tenant_id)
    if existing_id not in (None, agent_id):
        suffix = f"_{agent_id}"
        candidate = f"{candidate[: 50 - len(suffix)].rstrip('_')}{suffix}"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,49}", candidate):
        candidate = f"agent_{agent_id}"[:50]
    return candidate


def _seed_dependencies() -> SeedDependencies:
    """Bind startup seed policy to the facade's infrastructure operations."""
    return SeedDependencies(
        get_seed_config=get_nl2agent_seed_config,
        get_model_records=get_model_records,
        update_agent=update_agent,
        seed_builtin_tools=seed_nl2agent_builtin_tools,
        query_all_agents=query_all_agent_info_by_tenant_id,
        create_agent=create_agent,
        bind_tool=create_or_update_tool_by_tool_info,
        agent_name=NL2AGENT_AGENT_NAME,
        language=LANGUAGE["EN"],
    )


def _ensure_nl2agent_builder_ready(
    agent: Dict[str, Any], user_id: str, tenant_id: str
) -> None:
    ensure_builder_ready(_seed_dependencies(), agent, user_id, tenant_id)


async def _load_session_catalogs(
    tenant_id: str,
) -> tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    """Load catalogs through the focused catalog service."""
    return await load_session_catalogs(
        tenant_id,
        CatalogDependencies(
            list_all_tools=list_all_tools,
            list_tenant_skills=list_tenant_skills,
            list_registry_mcp_services=list_registry_mcp_services,
            list_community_mcp_services=list_community_mcp_services,
            get_official_skills_with_status=get_official_skills_with_status,
        ),
    )


def _session_initialization_dependencies() -> SessionInitializationDependencies:
    """Build session initialization dependencies from facade operations."""
    return SessionInitializationDependencies(
        search_agent_id_by_name=search_agent_id_by_agent_name,
        provision_builder=seed_nl2agent_default_agent,
        search_agent_info_by_id=search_agent_info_by_agent_id,
        ensure_builder_ready=_ensure_nl2agent_builder_ready,
        load_session_catalogs=_load_session_catalogs,
        get_db_session=get_db_session,
        create_agent=create_agent,
        create_conversation=create_conversation,
        create_session_snapshot=create_nl2agent_session,
        initialize_session_state=initialize_nl2agent_session_state,
        set_session_catalogs=set_nl2agent_session_catalogs,
        delete_session_catalogs=delete_nl2agent_session_catalogs,
        new_uuid=uuid.uuid4,
        builder_agent_name=NL2AGENT_AGENT_NAME,
        draft_name_prefix=DRAFT_AGENT_NAME_PREFIX,
    )


async def start_session(user_id: str, tenant_id: str, language: str) -> Dict[str, Any]:
    """Delegate transactional draft initialization to the session service."""
    return await initialize_session(
        _session_initialization_dependencies(),
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
    )


def _validate_draft_agent_id(agent_id: int) -> None:
    if not isinstance(agent_id, int) or agent_id <= 0:
        raise Nl2AgentValidationError("Invalid NL2AGENT draft agent_id.")


def _get_owned_draft(
    agent_id: int,
    tenant_id: str,
    *,
    user_id: str,
) -> Dict[str, Any]:
    """Resolve one user-owned NL2AGENT draft."""
    _validate_draft_agent_id(agent_id)
    try:
        agent = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id)
    except ValueError as exc:
        if str(exc) != "agent not found":
            raise
        raise Nl2AgentDraftNotFoundError() from exc
    if (
        not agent
        or not _is_draft_agent_name(agent.get("name") or "")
        or str(agent.get("created_by") or "") != str(user_id)
    ):
        raise Nl2AgentDraftNotFoundError()
    return agent


def _require_active_run_session(
    *,
    draft_agent_id: int,
    conversation_id: Optional[int],
    tenant_id: str,
    user_id: str,
) -> None:
    """Require one active owner-scoped session and its live Conversation."""
    if not isinstance(conversation_id, int) or conversation_id <= 0:
        raise Nl2AgentValidationError(
            "A positive conversation_id is required for an NL2AGENT run."
        )
    session = get_nl2agent_session_by_conversation(
        tenant_id,
        user_id,
        conversation_id,
        status=NL2AGENT_SESSION_ACTIVE,
    )
    if (
        session is None
        or session.get("status") != NL2AGENT_SESSION_ACTIVE
        or int(session.get("draft_agent_id") or 0) != draft_agent_id
        or int(session.get("conversation_id") or 0) != conversation_id
        or not get_conversation(conversation_id, user_id=user_id)
    ):
        raise Nl2AgentDraftNotFoundError()


def _owned_draft_reader(user_id: str):
    """Bind request-scoped user authority into focused service dependencies."""
    return partial(_get_owned_draft, user_id=user_id)


def _require_workflow_action(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    action: str,
) -> None:
    """Map workflow state errors to the service-layer exception contract."""
    _get_owned_draft(agent_id, tenant_id, user_id=user_id)
    try:
        assert_workflow_action_allowed(tenant_id, agent_id, action)
    except AppException:
        raise
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc


async def select_models(
    agent_id: int,
    primary_model_id: int,
    fallback_model_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Validate and persist an ordered model selection on a draft agent."""
    _require_workflow_action(agent_id, tenant_id, user_id, "select_models")
    try:
        workflow_state = assert_requirements_confirmed(tenant_id, agent_id)
    except AppException:
        raise
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc
    ordered_ids = [int(primary_model_id), *[int(x) for x in fallback_model_ids]]
    if len(ordered_ids) > 5 or len(set(ordered_ids)) != len(ordered_ids):
        raise Nl2AgentValidationError(
            "Select one primary model and up to four distinct fallbacks."
        )

    validated_models = _validate_available_llm_ids(tenant_id, ordered_ids)

    previous_confirmation = bool(workflow_state.get("model_selection_confirmed"))
    redis_write_attempted = False
    try:
        with get_db_session() as db_session:
            update_agent(
                agent_id=agent_id,
                agent_info=AgentInfoRequest(
                    business_logic_model_id=ordered_ids[0],
                    model_ids=ordered_ids,
                ),
                user_id=user_id,
                version_no=0,
                db_session=db_session,
            )
            redis_write_attempted = True
            set_model_selection_confirmed(tenant_id, agent_id, True)
    except Exception as exc:
        if redis_write_attempted:
            try:
                set_model_selection_confirmed(
                    tenant_id,
                    agent_id,
                    previous_confirmation,
                )
            except Exception:
                logger.exception(
                    "Failed to compensate NL2AGENT model selection state: "
                    "tenant_id=%s draft_agent_id=%s",
                    tenant_id,
                    agent_id,
                )
        raise Nl2AgentOperationError("Failed to save the model selection.") from exc
    return {
        "agent_id": agent_id,
        "primary_model_id": ordered_ids[0],
        "fallback_model_ids": ordered_ids[1:],
        "models": [
            {
                "model_id": model_id,
                "display_name": validated_models[model_id]["display_name"],
            }
            for model_id in ordered_ids
        ],
        "chat_injection_text": NL2AGENT_CHAT_INJECTION_TEXT,
    }


def _validate_available_llm_ids(
    tenant_id: str,
    model_ids: List[int],
    *,
    finalizing: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """Validate IDs against the tenant's platform LLM inventory."""
    return validate_available_llm_ids(
        get_model_records(None, tenant_id) or [],
        model_ids,
        finalizing=finalizing,
    )


def _resolve_model_summaries(
    draft: Dict[str, Any], tenant_id: str
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve persisted model IDs into display-ready summaries without raising."""
    return resolve_model_summaries(draft, get_model_records(None, tenant_id) or [])


def _resolve_resource_summaries(
    tool_instances: List[Dict[str, Any]],
    skill_instances: List[Dict[str, Any]],
    tenant_id: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Enrich persisted resource instances and report dangling references."""
    tool_ids = [int(row["tool_id"]) for row in tool_instances]
    skill_ids = [int(row["skill_id"]) for row in skill_instances]
    return resolve_resource_summaries(
        tool_instances,
        skill_instances,
        query_tools_by_ids_for_tenant(tool_ids, tenant_id) if tool_ids else [],
        query_skills_by_ids(skill_ids, tenant_id) if skill_ids else [],
    )


def _raise_for_invalid_resource_references(
    invalid_references: List[Dict[str, Any]],
) -> None:
    """Block publication when a persisted resource no longer resolves."""
    raise_for_invalid_resource_references(invalid_references)


def _mcp_installation_dependencies(user_id: str) -> McpInstallationDependencies:
    """Build MCP installation dependencies from facade-level operations."""
    return McpInstallationDependencies(
        session=McpSessionDependencies(
            get_owned_draft=_owned_draft_reader(user_id),
            get_session_catalogs=get_nl2agent_session_catalogs,
            normalize_candidate=normalize_mcp_candidate,
            update_mcp_workflow=update_mcp_workflow,
            recommendation_id=_recommendation_id,
        ),
        lock=McpLockDependencies(
            acquire_installation_lock=acquire_mcp_installation_lock,
            renew_installation_lock=renew_mcp_installation_lock,
            release_installation_lock=release_mcp_installation_lock,
        ),
        provider=McpProviderDependencies(
            get_mcp_records=get_mcp_records_by_tenant,
            add_remote_mcp=add_mcp_service,
            add_container_mcp=add_container_mcp_service,
            update_remote_mcp=update_mcp_service,
            reconfigure_container_mcp=reconfigure_container_mcp_service,
            get_mcp_record=get_mcp_record_by_id_and_tenant,
        ),
        discovery=McpDiscoveryDependencies(
            discover_tools=get_tool_from_remote_mcp_server,
            upsert_discovered_tools=upsert_discovered_mcp_tools,
            validate_remote_url=validate_nl2agent_remote_mcp_url,
            build_httpx_client_factory=build_pinned_httpx_client_factory,
        ),
    )


async def install_recommended_mcp(
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    config_values: Dict[str, Any],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate recoverable installation to the MCP service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "configure_online_resources")
    return await install_recommended_mcp_service(
        _mcp_installation_dependencies(user_id),
        agent_id=agent_id,
        recommendation_id=recommendation_id,
        option_id=option_id,
        config_values=config_values,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _mcp_binding_dependencies(user_id: str) -> McpBindingDependencies:
    """Build MCP binding dependencies from facade-level operations."""
    return McpBindingDependencies(
        get_owned_draft=_owned_draft_reader(user_id),
        get_mcp_record=get_mcp_record_by_id_and_tenant,
        query_tools_by_ids=query_tools_by_ids_for_tenant,
        bind_tool=create_or_update_tool_by_tool_info,
        delete_tool_instances=delete_tool_instances_by_ids,
        get_db_session=get_db_session,
        reserve_binding=reserve_mcp_binding_operation,
        complete_binding=complete_mcp_binding_operation,
        release_binding=release_mcp_binding_operation,
    )


async def bind_mcp_tools(
    agent_id: int,
    mcp_id: int,
    tool_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate MCP tool binding to the MCP service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "configure_online_resources")
    return await bind_mcp_tools_service(
        _mcp_binding_dependencies(user_id),
        agent_id=agent_id,
        mcp_id=mcp_id,
        tool_ids=tool_ids,
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def skip_mcp_tool_binding(
    agent_id: int,
    mcp_id: int,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate explicit MCP binding skip to the MCP service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "configure_online_resources")
    return await skip_mcp_tool_binding_service(
        _mcp_binding_dependencies(user_id),
        agent_id=agent_id,
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _local_resource_dependencies(user_id: str) -> LocalResourceDependencies:
    """Build local-resource dependencies from facade-level operations."""
    return LocalResourceDependencies(
        get_owned_draft=_owned_draft_reader(user_id),
        get_session_state=get_nl2agent_session_state,
        get_session_catalogs=get_nl2agent_session_catalogs,
        query_tools_by_ids=query_tools_by_ids_for_tenant,
        query_skills_by_ids=query_skills_by_ids,
        get_db_session=get_db_session,
        bind_tool=create_or_update_tool_by_tool_info,
        bind_skill=create_or_update_skill_by_skill_info,
        assert_trusted_batch=assert_trusted_local_search_batch,
        register_batch=register_recommendation_batch,
        resolve_batch=resolve_recommendation_batch,
        reserve_batch_apply=reserve_recommendation_batch_apply,
        complete_batch_apply=complete_recommendation_batch_apply,
        release_batch_apply=release_recommendation_batch_apply,
        continuation_text=NL2AGENT_CHAT_INJECTION_TEXT,
    )


async def apply_local_resources_batch(
    agent_id: int,
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
    tenant_id: str,
    user_id: str,
    tool_config_values: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Delegate atomic local-resource binding to the resource service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "apply_local_resources")
    return await apply_local_resources(
        _local_resource_dependencies(user_id),
        agent_id=agent_id,
        recommendation_batch_id=recommendation_batch_id,
        tool_ids=tool_ids,
        skill_ids=skill_ids,
        tool_config_values=tool_config_values,
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def register_local_resource_recommendations(
    agent_id: int,
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate local recommendation registration to the resource service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "search_local_resources")
    return await register_local_recommendations(
        _local_resource_dependencies(user_id),
        agent_id=agent_id,
        recommendation_batch_id=recommendation_batch_id,
        tool_ids=tool_ids,
        skill_ids=skill_ids,
        tenant_id=tenant_id,
    )


async def skip_local_resource_recommendations(
    agent_id: int,
    recommendation_batch_id: str,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate local recommendation skipping to the resource service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "skip_local_resources")
    return await skip_local_recommendations(
        _local_resource_dependencies(user_id),
        agent_id=agent_id,
        recommendation_batch_id=recommendation_batch_id,
        tenant_id=tenant_id,
    )


def _get_completed_final_answer(message_id: int) -> str:
    """Rebuild the persisted final answer without exposing unit rows to the workflow."""
    return "".join(
        str(unit.get("unit_content") or "")
        for unit in get_message_units(message_id)
        if unit.get("unit_type") == "final_answer"
        and unit.get("unit_status") == "completed"
    )


def _workflow_dependencies(user_id: str) -> WorkflowDependencies:
    """Build workflow dependencies from facade-level operations."""
    return WorkflowDependencies(
        get_owned_draft=_owned_draft_reader(user_id),
        register_online_batch=register_online_recommendation_batch,
        get_session_state=get_nl2agent_session_state,
        summarize_workflow_state=summarize_workflow_state,
        get_message=get_message,
        get_completed_final_answer=_get_completed_final_answer,
        get_latest_assistant_message_id=get_latest_assistant_message_id,
        message_contains_valid_card=message_contains_valid_card,
        record_card_delivery=record_card_delivery,
        complete_online_configuration=complete_online_configuration_state,
        register_requirements_summary=register_requirements_summary,
        confirm_requirements_summary=confirm_requirements_summary,
        apply_requirements_revision_text=apply_requirements_revision_text,
        find_agent_info_by_agent_id=find_agent_info_by_agent_id,
        query_enabled_tool_instances=query_all_enabled_tool_instances,
        query_enabled_skill_instances=query_enabled_skill_instances,
        resolve_model_summaries=_resolve_model_summaries,
        resolve_resource_summaries=_resolve_resource_summaries,
        query_tools_by_ids=query_tools_by_ids_for_tenant,
        normalize_model_ids=normalize_model_ids,
        generate_internal_agent_name=_generate_internal_agent_name,
        get_db_session=get_db_session,
        update_agent=update_agent,
        confirm_agent_identity=confirm_agent_identity,
        runner_agent_name=NL2AGENT_AGENT_NAME,
        continuation_text=NL2AGENT_CHAT_INJECTION_TEXT,
        card_retry_text=NL2AGENT_CARD_RETRY_INJECTION_TEXT,
    )


async def register_online_resource_recommendations(
    agent_id: int,
    recommendation_batch_id: str,
    resource_type: str,
    item_keys: List[str],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate online recommendation registration to the workflow service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "search_online_resources")
    return await register_online_recommendations_workflow(
        _workflow_dependencies(user_id),
        agent_id=agent_id,
        recommendation_batch_id=recommendation_batch_id,
        resource_type=resource_type,
        item_keys=item_keys,
        tenant_id=tenant_id,
    )


async def report_card_delivery(
    agent_id: int,
    message_id: int,
    card_type: str,
    status: str,
    card_key: Optional[str],
    reason: Optional[str],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate card-delivery validation to the workflow service."""
    return await report_card_delivery_workflow(
        _workflow_dependencies(user_id),
        agent_id=agent_id,
        message_id=message_id,
        card_type=card_type,
        status=status,
        card_key=card_key,
        reason=reason,
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def confirm_online_resource_configuration(
    agent_id: int, tenant_id: str, user_id: str
) -> Dict[str, Any]:
    """Delegate online configuration completion to the workflow service."""
    _require_workflow_action(
        agent_id, tenant_id, user_id, "complete_online_configuration"
    )
    return await confirm_online_configuration_workflow(
        _workflow_dependencies(user_id),
        agent_id=agent_id,
        tenant_id=tenant_id,
    )


async def register_requirements_review(
    agent_id: int, summary: Dict[str, Any], tenant_id: str, user_id: str
) -> Dict[str, Any]:
    """Delegate requirements registration to the workflow service."""
    _require_workflow_action(
        agent_id, tenant_id, user_id, "render_requirements_summary"
    )
    return await register_requirements_review_workflow(
        _workflow_dependencies(user_id),
        agent_id=agent_id,
        summary=summary,
        tenant_id=tenant_id,
    )


def process_requirements_revision_text(
    runner_agent_id: Optional[int],
    draft_agent_id: int,
    tenant_id: str,
    user_id: str,
    text: str,
) -> Dict[str, Any]:
    """Delegate textual revision handling to the workflow service."""
    return process_requirements_revision_workflow(
        _workflow_dependencies(user_id),
        runner_agent_id=runner_agent_id,
        draft_agent_id=draft_agent_id,
        tenant_id=tenant_id,
        text=text,
    )


def validate_nl2agent_run_context(
    *,
    runner_agent_id: Optional[int],
    draft_agent_id: int,
    conversation_id: Optional[int],
    tenant_id: str,
    user_id: str,
) -> None:
    """Authorize the runner, draft owner, and Conversation before any run effect."""
    try:
        runner = search_agent_info_by_agent_id(
            agent_id=runner_agent_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        if str(exc) != "agent not found":
            raise
        runner = None
    if not runner or runner.get("name") != NL2AGENT_AGENT_NAME:
        raise Nl2AgentValidationError(
            "draft_agent_id is only valid when running the NL2AGENT builder."
        )
    _get_owned_draft(
        draft_agent_id,
        tenant_id,
        user_id=user_id,
    )
    _require_active_run_session(
        draft_agent_id=draft_agent_id,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def confirm_requirements_review(
    agent_id: int, fingerprint: str, tenant_id: str, user_id: str
) -> Dict[str, Any]:
    """Delegate requirements confirmation to the workflow service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "confirm_requirements")
    return await confirm_requirements_review_workflow(
        _workflow_dependencies(user_id),
        agent_id=agent_id,
        fingerprint=fingerprint,
        tenant_id=tenant_id,
    )


async def get_session_state(
    agent_id: int, tenant_id: str, user_id: str
) -> Dict[str, Any]:
    """Delegate authoritative session-state projection to the workflow service."""
    return await get_workflow_session_state(
        _workflow_dependencies(user_id),
        agent_id=agent_id,
        tenant_id=tenant_id,
    )


async def save_agent_identity(
    agent_id: int,
    display_name: str,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Delegate identity persistence to the workflow service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "save_identity")
    return await save_agent_identity_workflow(
        _workflow_dependencies(user_id),
        agent_id=agent_id,
        display_name=display_name,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _skill_installation_dependencies(user_id: str) -> SkillInstallationDependencies:
    """Build trusted Skill installation dependencies from facade operations."""
    return SkillInstallationDependencies(
        get_owned_draft=_owned_draft_reader(user_id),
        get_session_catalogs=get_nl2agent_session_catalogs,
        install_by_name=install_skills_from_zip_for_tenant,
        install_by_id=install_skills_for_tenant,
        get_installed_by_name=get_tenant_skill_by_name,
        bind_skill=create_or_update_skill_by_skill_info,
        acquire_installation_lock=acquire_mcp_installation_lock,
        renew_installation_lock=renew_mcp_installation_lock,
        release_installation_lock=release_mcp_installation_lock,
        reserve_installation=reserve_online_installation,
        complete_installation=complete_online_installation,
        release_installation=release_online_installation,
    )


async def install_web_skill(
    agent_id: int,
    skill_id: Optional[int],
    tenant_id: str,
    user_id: str,
    skill_name: Optional[str] = None,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """Delegate trusted official Skill installation to the catalog service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "configure_online_resources")
    return await install_web_skill_service(
        _skill_installation_dependencies(user_id),
        agent_id=agent_id,
        skill_id=skill_id,
        tenant_id=tenant_id,
        user_id=user_id,
        skill_name=skill_name,
        locale=locale,
    )


async def finalize_agent(
    agent_id: int,
    user_id: str,
    tenant_id: str,
    description: Optional[str] = None,
    business_description: Optional[str] = None,
    duty_prompt: Optional[str] = None,
    constraint_prompt: Optional[str] = None,
    few_shots_prompt: Optional[str] = None,
    greeting_message: Optional[str] = None,
    example_questions: Optional[List[str]] = None,
    max_steps: Optional[int] = None,
    requested_output_tokens: Optional[int] = None,
    provide_run_summary: bool = False,
    verification_config: Optional[Dict[str, Any]] = None,
    enable_context_manager: bool = True,
) -> Dict[str, Any]:
    """Delegate draft publication to the dedicated publication service."""
    _require_workflow_action(agent_id, tenant_id, user_id, "publish_agent")
    dependencies = PublicationDependencies(
        draft=PublicationDraftDependencies(
            validate_draft_agent_id=_validate_draft_agent_id,
            get_owned_draft=_owned_draft_reader(user_id),
            generate_internal_name=_generate_internal_agent_name,
        ),
        workflow=PublicationWorkflowDependencies(
            assert_requirements_confirmed=assert_requirements_confirmed,
            assert_resource_review_complete=assert_resource_review_complete,
            assert_mcp_workflows_resolved=assert_mcp_workflows_resolved,
            assert_online_configuration_complete=assert_online_configuration_complete,
            assert_identity_confirmed=assert_identity_confirmed,
        ),
        models=PublicationModelDependencies(
            normalize_model_ids=normalize_model_ids,
            validate_available_llm_ids=_validate_available_llm_ids,
        ),
        resources=PublicationResourceDependencies(
            query_enabled_tools=query_all_enabled_tool_instances,
            query_enabled_skills=query_enabled_skill_instances,
            resolve_resource_summaries=_resolve_resource_summaries,
            raise_for_invalid_references=_raise_for_invalid_resource_references,
        ),
        persistence=PublicationPersistenceDependencies(
            get_db_session=get_db_session,
            update_agent=update_agent,
            complete_session=update_nl2agent_session_status,
        ),
    )
    return await publish_agent(
        dependencies,
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        proposal=PublicationProposal(
            description=description,
            business_description=business_description,
            duty_prompt=duty_prompt,
            constraint_prompt=constraint_prompt,
            few_shots_prompt=few_shots_prompt,
            greeting_message=greeting_message,
            example_questions=example_questions,
            max_steps=max_steps,
            requested_output_tokens=requested_output_tokens,
            provide_run_summary=provide_run_summary,
            verification_config=verification_config,
            enable_context_manager=enable_context_manager,
        ),
    )


# ---------------------------------------------------------------------------
# Startup seeding
# ---------------------------------------------------------------------------


def seed_nl2agent_default_agent(
    tenant_id: str = DEFAULT_TENANT_ID,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[int]:
    """Seed or repair the built-in builder through the focused seed service."""
    return seed_default_agent(_seed_dependencies(), tenant_id, user_id)
