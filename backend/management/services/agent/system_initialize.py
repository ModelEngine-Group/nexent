# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit installation command: python -m management.services.agent.system_initialize."""

import json
from pathlib import Path

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.db.agent.system import (
    create_workbench_draft, has_legacy_workbench_agents,
    load_system_agent, lock_system_agent_release, replace_workbench_draft_bindings,
)
from management.db.client import get_db_session
from management.services.agent.system import SystemAgentProvider


def prepare_shared_resources(provider):
    """Prepare shared catalogs and official files explicitly, outside data migration."""
    from management.db.tool.repository import update_tool_table_from_scan_tool_list
    from management.db.skill import repository as skill_db
    from management.services.skill.files import get_skill_manager
    from management.services.skill.transfer import install_skills_from_zip_for_tenant
    from management.services.tool.configuration import get_local_tools

    update_tool_table_from_scan_tool_list(ASSET_OWNER_TENANT_ID, "system", get_local_tools())
    # SQL can clone official Skill metadata but cannot populate its shared filesystem directory.
    manager = get_skill_manager()
    official = [skill for skill in skill_db.list_skills(ASSET_OWNER_TENANT_ID)
                if str(skill.get("source")).lower() == "official"]
    names = set(provider.release_manifest.official_skill_names) | {skill["name"] for skill in official}

    def has_files(name):
        directory = manager.resolve_skill_dir(name, tenant_id=ASSET_OWNER_TENANT_ID)
        return (Path(directory) / "SKILL.md").is_file()

    install_skills_from_zip_for_tenant(
        skill_names=sorted(name for name in names if not has_files(name)),
        tenant_id=ASSET_OWNER_TENANT_ID, user_id="system",
    )
    for skill in skill_db.list_skills(ASSET_OWNER_TENANT_ID):
        if str(skill.get("source")).lower() == "official" and not has_files(skill["name"]):
            raise ValueError(f"Shared official Skill files are unavailable: {skill['name']}")
    return (
        provider.get_workbench_default_tools(ASSET_OWNER_TENANT_ID),
        provider.get_workbench_default_skills(ASSET_OWNER_TENANT_ID),
    )


def initialize_system_agents(*, app_version=None):
    """Initialize only Workbench; creator identities belong exclusively to SQL migrations."""
    provider = SystemAgentProvider(app_version=app_version)
    with get_db_session() as session:
        lock_system_agent_release(session, "workbench_main")
        if has_legacy_workbench_agents(session):
            raise ValueError("Apply the shared system Agent SQL migration before initialization")
        tools, skills = prepare_shared_resources(provider)
        workbench = load_system_agent(session, "workbench_main")
        if workbench is None:
            agent_id = create_workbench_draft(session, provider._editable_fields())
            replace_workbench_draft_bindings(session, agent_id, tools, skills)
        else:
            agent_id = workbench["agent_id"]
    return {"workbench_main": agent_id}


def main():
    print(json.dumps(initialize_system_agents()))


if __name__ == "__main__":
    main()
