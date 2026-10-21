# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any, Dict, List, Optional

from contracts.agent_repository import STATUS_SHARED
from consts.const import SYSTEM_TENANT_ID
from contracts.models import AgentRepositorySnapshot, KnowledgeBaseResolution, SkillResolution
from management.db.agent.repository import delete_agent_by_id
from management.db.agent.catalog import get_agent_repository_by_id, increment_agent_repository_downloads, list_agent_repository_summaries, soft_delete_agent_repository_record
from management.services.agent.service import (
    import_agent_impl,
    import_agent_with_skills_impl,
)
from management.services.repository.agent.common import (
    logger,
)
from management.services.repository.precheck import build_repository_import_precheck


def check_repository_import_precheck_impl(
    agent_repository_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Check whether the current tenant can import a shared repository listing."""
    record = get_agent_repository_by_id(
        agent_repository_id,
        tenant_id,
    )
    if not record:
        record = get_agent_repository_by_id(
            agent_repository_id,
            SYSTEM_TENANT_ID,
        )
    if not record:
        raise ValueError("Repository listing not found")
    if record.get("status") != STATUS_SHARED:
        raise ValueError("Repository listing is not available for import")

    if record.get("publisher_tenant_id") == SYSTEM_TENANT_ID:
        # Re-read the mounted bundle so the precheck sees the same Skill,
        # MCP, model and logical KB declarations that the official installer
        # will use. The repository snapshot is intentionally not treated as
        # the source of official seed documents.
        from management.services.repository.agent.official import _load_bundle

        bundle_name = str(record.get("name") or "")
        bundle = _load_bundle(bundle_name)
        if bundle is None:
            raise ValueError(f"Official agent bundle not found: {bundle_name}")
        display_name = (
            str(record.get("display_name") or "").strip()
            or str(record.get("name") or "").strip()
            or "Agent"
        )
        result = build_repository_import_precheck(
            agent_repository_id=agent_repository_id,
            display_name=display_name,
            snapshot=bundle,
            tenant_id=tenant_id,
            require_kb_embedding_model=True,
        )
        return result.model_dump()

    agent_info_json = record.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("Repository listing has no agent snapshot")

    snapshot = AgentRepositorySnapshot.model_validate(agent_info_json)
    display_name = (
        str(record.get("display_name") or "").strip()
        or str(record.get("name") or "").strip()
        or "Agent"
    )
    result = build_repository_import_precheck(
        agent_repository_id=agent_repository_id,
        display_name=display_name,
        snapshot=snapshot,
        tenant_id=tenant_id,
    )
    return result.model_dump()


async def import_agent_from_repository_impl(
    agent_repository_id: int,
    tenant_id: str,
    authorization: str,
    skill_resolutions: Optional[List[SkillResolution]] = None,
    model_ids: Optional[Dict[str, int]] = None,
    embedding_model_ids: Optional[Dict[str, int]] = None,
    knowledge_base_resolutions: Optional[List[KnowledgeBaseResolution]] = None,
    user_id: Optional[str] = None,
    return_root_id: bool = False,
) -> Dict[int, int] | Dict[str, int]:
    """Import an agent tree from a marketplace repository listing into the current tenant."""
    record = get_agent_repository_by_id(
        agent_repository_id,
        tenant_id,
    )
    if not record:
        record = get_agent_repository_by_id(
            agent_repository_id,
            SYSTEM_TENANT_ID,
        )
    if not record:
        raise ValueError("Repository listing not found")

    # Official listings are templates backed by a mounted bundle. Their
    # knowledge bases, skills and MCP servers must be prepared in the target
    # tenant before the normal agent snapshot is imported. Ordinary listings
    # continue through the existing import path below.
    if record.get("publisher_tenant_id") == SYSTEM_TENANT_ID:
        from management.services.repository.agent.official import (
            install_official_agents,
        )

        # The official bundle directory name is the root Agent name, which is
        # already stored in the repository record's ``name`` field.
        bundle_name = str(record.get("name") or "")
        logger.info(
            "Repository import resolved official listing id=%s name=%r "
            "publisher_tenant_id=%r target_tenant_id=%r",
            agent_repository_id,
            bundle_name,
            record.get("publisher_tenant_id"),
            tenant_id,
        )
        results = await install_official_agents(
            [bundle_name],
            tenant_id=tenant_id,
            user_id=user_id or "repository-import",
            authorization=authorization,
            model_ids=model_ids,
            embedding_model_ids=embedding_model_ids,
            skill_resolutions=skill_resolutions,
            knowledge_base_resolutions=knowledge_base_resolutions,
        )
        item = results[0] if results else None
        if item is None:
            raise ValueError("Official agent installation returned no result")
        if item.status == "needs_model":
            raise ValueError(
                item.message or "Official agent requires model configuration"
            )
        if item.status == "failed":
            raise ValueError(item.message or "Official agent installation failed")
        if item.status == "not_found":
            raise ValueError(item.message or "Official agent bundle not found")

        affected = increment_agent_repository_downloads(agent_repository_id)
        if affected == 0:
            logger.warning(
                "Failed to increment repository downloads after official import "
                "(agent_repository_id=%s)",
                agent_repository_id,
            )
        if return_root_id:
            return {"agent_id": item.agent_id} if item.agent_id else {}
        return {record.get("agent_id"): item.agent_id} if item.agent_id else {}

    agent_info_json = record.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("Repository listing has no agent snapshot")

    snapshot = AgentRepositorySnapshot.model_validate(agent_info_json)
    if snapshot.skills:
        result = await import_agent_with_skills_impl(
            snapshot,
            snapshot.skills,
            authorization,
            skill_resolutions=skill_resolutions,
            resolve_name_conflicts=True,
        )
    else:
        result = await import_agent_impl(
            snapshot,
            authorization,
            resolve_name_conflicts=True,
        )

    affected = increment_agent_repository_downloads(agent_repository_id)
    if affected == 0:
        logger.warning(
            "Failed to increment repository downloads after import "
            "(agent_repository_id=%s)",
            agent_repository_id,
        )
    if return_root_id:
        return {"agent_id": result[snapshot.agent_id]}
    return result


def list_official_agent_management_impl() -> List[Dict[str, Any]]:
    """Return active official listings for super-admin management."""
    records = list_agent_repository_summaries(
        publisher_tenant_id=SYSTEM_TENANT_ID,
        status=STATUS_SHARED,
    )
    return [
        {
            **record,
            "publisher_tenant_id": SYSTEM_TENANT_ID,
        }
        for record in records
    ]


def delete_official_agent_impl(
    agent_repository_id: int, user_id: str
) -> Dict[str, Any]:
    """Delete an official template and source bundle, preserving tenant copies."""
    import os
    import shutil

    from consts.const import OFFICIAL_AGENTS_PATH

    record = get_agent_repository_by_id(agent_repository_id, SYSTEM_TENANT_ID)
    if not record:
        raise ValueError("Official agent repository listing not found")
    bundle_name = str(record.get("name") or "").strip()
    if (
        not bundle_name
        or bundle_name in {".", ".."}
        or "/" in bundle_name
        or "\\" in bundle_name
    ):
        raise ValueError("Official agent bundle name is invalid")
    root = os.path.realpath(OFFICIAL_AGENTS_PATH)
    candidates: list[str] = []
    direct_dir = os.path.join(root, bundle_name)
    if os.path.isdir(direct_dir):
        candidates.append(direct_dir)
    for current_root, directories, files in os.walk(root):
        directories[:] = [item for item in directories if not item.startswith(".")]
        if os.path.basename(current_root) == bundle_name and "agent.json" in files:
            candidates.append(current_root)
        for filename in files:
            if filename in {f"{bundle_name}.json", f"{bundle_name}.zip"}:
                candidates.append(os.path.join(current_root, filename))
    deleted_paths: list[str] = []
    for candidate in dict.fromkeys(candidates):
        resolved = os.path.realpath(candidate)
        if resolved == root or not resolved.startswith(root + os.sep):
            raise ValueError("Official agent bundle path escapes configured root")
        if os.path.isdir(resolved):
            shutil.rmtree(resolved)
        elif os.path.isfile(resolved):
            os.remove(resolved)
        deleted_paths.append(candidate)
    snapshot = record.get("agent_info_json") or {}
    for source_id in (snapshot.get("agent_info") or {}).keys():
        if str(source_id).isdigit():
            delete_agent_by_id(int(source_id), SYSTEM_TENANT_ID, user_id)
    affected = soft_delete_agent_repository_record(
        agent_repository_id,
        publisher_tenant_id=SYSTEM_TENANT_ID,
        user_id=user_id,
    )
    if affected == 0:
        raise ValueError("Official agent repository listing was already deleted")
    return {
        "agent_repository_id": agent_repository_id,
        "name": bundle_name,
        "deleted_bundle_paths": deleted_paths,
        "preserved_tenant_copies": True,
    }
