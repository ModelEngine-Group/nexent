"""Synchronize external official agent bundles into the platform repository."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from consts.agent_repository import STATUS_SHARED
from consts.const import (
    OFFICIAL_AGENT_TENANT_ID,
    OFFICIAL_AGENT_USER_ID,
    OFFICIAL_AGENTS_PATH,
    OFFICIAL_AGENT_PROFILES,
)
from database.agent_db import create_agent, search_agent_id_by_agent_name
from database.agent_repository_db import upsert_agent_repository_record
from services.official_agent_bundle_service import (
    OfficialAgentBundle,
    load_official_bundles,
    parse_official_agent_profiles,
)

logger = logging.getLogger("official_agent_sync_service")
_sync_lock = asyncio.Lock()


def _source_agent_payload(agent: Any) -> dict[str, Any]:
    return {
        "name": agent.name,
        "display_name": agent.display_name,
        "description": agent.description,
        "author": agent.author,
        "max_steps": agent.max_steps,
        "provide_run_summary": agent.provide_run_summary,
        "allow_chat_metadata": agent.allow_chat_metadata,
        "verification_config": agent.verification_config,
        "context_policy": agent.context_policy,
        "duty_prompt": agent.duty_prompt,
        "constraint_prompt": agent.constraint_prompt,
        "few_shots_prompt": agent.few_shots_prompt,
        "enabled": agent.enabled,
        "model_ids": agent.model_ids,
        "business_logic_model_id": agent.business_logic_model_id,
        "business_logic_model_name": agent.business_logic_model_name,
        "prompt_template_id": agent.prompt_template_id,
        "prompt_template_name": agent.prompt_template_name,
        "greeting_message": agent.greeting_message,
        "example_questions": agent.example_questions,
    }


def _find_or_create_source_agent(agent: Any) -> int:
    try:
        return int(search_agent_id_by_agent_name(
            agent.name, OFFICIAL_AGENT_TENANT_ID
        ))
    except ValueError:
        return int(create_agent(
            _source_agent_payload(agent),
            tenant_id=OFFICIAL_AGENT_TENANT_ID,
            user_id=OFFICIAL_AGENT_USER_ID,
        )["agent_id"])


def _materialize_snapshot(bundle: OfficialAgentBundle):
    mapping: dict[int, int] = {}
    for source_id, agent in bundle.snapshot.agent_info.items():
        mapping[int(source_id)] = _find_or_create_source_agent(agent)

    agent_info = {}
    for source_id, agent in bundle.snapshot.agent_info.items():
        remapped = agent.model_copy(update={
            "agent_id": mapping[int(source_id)],
            "tenant_id": OFFICIAL_AGENT_TENANT_ID,
            "managed_agents": [mapping[item] for item in agent.managed_agents],
        })
        agent_info[str(mapping[int(source_id)])] = remapped

    return bundle.snapshot.model_copy(
        update={
            "agent_id": mapping[bundle.snapshot.agent_id],
            "agent_info": agent_info,
        }
    )


def _sync_bundle(bundle: OfficialAgentBundle) -> dict[str, Any]:
    snapshot = _materialize_snapshot(bundle)
    root = snapshot.agent_info[str(snapshot.agent_id)]
    repository_data = {
        "agent_id": snapshot.agent_id,
        "version_no": getattr(root, "version_no", 1) or 1,
        "name": root.name,
        "display_name": bundle.display_name or root.display_name,
        "description": bundle.description or root.description,
        "author": root.author or "Nexent",
        "submitted_by": OFFICIAL_AGENT_USER_ID,
        "version_name": "Official",
        "agent_info_json": snapshot.model_dump(mode="json"),
        "status": STATUS_SHARED,
        "tags": bundle.tags or [],
        "icon": bundle.icon,
        "tool_count": sum(len(agent.tools) for agent in snapshot.agent_info.values()),
        "content": "Official Nexent agent",
    }
    repository_id, updated = upsert_agent_repository_record(
        repository_data,
        publisher_tenant_id=OFFICIAL_AGENT_TENANT_ID,
        publisher_user_id=OFFICIAL_AGENT_USER_ID,
    )
    return {"name": bundle.name, "agent_repository_id": repository_id, "updated": updated}


async def sync_official_agents(
    *,
    base_dir: str = OFFICIAL_AGENTS_PATH,
    profiles: str | list[str] = OFFICIAL_AGENT_PROFILES,
) -> list[dict[str, Any]]:
    """Synchronize selected bundles; one broken bundle does not abort others."""
    async with _sync_lock:
        selected = parse_official_agent_profiles(profiles)
        bundles = load_official_bundles(base_dir, selected)
        results: list[dict[str, Any]] = []
        for bundle in bundles:
            try:
                result = _sync_bundle(bundle)
                results.append(result)
                logger.info("Synchronized official agent bundle: %s", bundle.name)
            except Exception:
                logger.exception("Failed to synchronize official agent bundle: %s", bundle.name)
        return results
