# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Batch installation projections based only on user-visible Skill copies."""

from sqlalchemy import and_, or_, select

from management.db.client import get_db_session
from management.db.identity.group import query_group_ids_by_user
from management.db.skill.models import SkillInfo, SkillInstance
from contracts.errors.exceptions import ForbiddenError
from management.services.skill.permission import _can_edit_skill
from management.services.skill.permission import can_view_skill, resolve_skill_permission
from management.utils.serialization import convert_string_to_list


def installation_states(repository_ids: list[int], visible: list[dict]) -> dict:
    copies = {str(repository_id): [] for repository_id in repository_ids}
    unknown = False
    for skill in visible:
        source_id = skill.get("source_repository_id")
        if skill.get("source") == "repository" and source_id is None:
            unknown = True
        if source_id is not None and str(source_id) in copies:
            copies[str(source_id)].append({"skill_id": skill["skill_id"], "name": skill["name"],
                                          "can_uninstall": skill.get("permission") == "EDIT"})
    return {key: {"installed_copies": value,
                  "installation_state": "installed" if value else "unknown" if unknown else "not_installed"}
            for key, value in copies.items()}


def get_installation_states(repository_ids: list[int], tenant_id: str, user_id: str, role: str) -> dict:
    if not repository_ids:
        return {}
    groups = set(query_group_ids_by_user(user_id) or [])
    with get_db_session() as session:
        rows = session.execute(select(SkillInfo.skill_id, SkillInfo.skill_name, SkillInfo.source,
            SkillInfo.source_repository_id, SkillInfo.created_by, SkillInfo.group_ids,
            SkillInfo.ingroup_permission).where(
                SkillInfo.tenant_id == tenant_id, SkillInfo.delete_flag != "Y",
                or_(SkillInfo.source_repository_id.in_(repository_ids),
                    and_(SkillInfo.source == "repository", SkillInfo.source_repository_id.is_(None))))).mappings().all()
    visible = []
    for row in rows:
        skill = {**dict(row), "name": row["skill_name"], "group_ids": convert_string_to_list(row["group_ids"])}
        if can_view_skill(skill=skill, user_id=user_id, user_role=role, user_group_ids=groups):
            skill["permission"] = resolve_skill_permission(skill=skill, user_id=user_id, user_role=role, user_group_ids=groups)
            visible.append(skill)
    return installation_states(repository_ids, visible)


def uninstall_repository_copy(repository_id: int | None, skill_id: int, tenant_id: str, user_id: str) -> None:
    from management.db.repository_transactions import repository_unit_of_work
    from management.services.skill.service import SkillService

    with repository_unit_of_work() as session:
        skill = session.scalar(select(SkillInfo).where(
            SkillInfo.skill_id == skill_id, SkillInfo.tenant_id == tenant_id,
            *([SkillInfo.source_repository_id == repository_id] if repository_id is not None else []), SkillInfo.delete_flag != "Y",
        ).with_for_update())
        if skill is None:
            raise LookupError("Installed copy not found")
        policy = {"created_by": skill.created_by, "group_ids": convert_string_to_list(skill.group_ids),
                  "ingroup_permission": skill.ingroup_permission}
        if not _can_edit_skill(policy, user_id):
            raise ForbiddenError("Installed copy is read-only")
        if session.scalar(select(SkillInstance.skill_instance_id).where(
            SkillInstance.skill_id == skill_id, SkillInstance.tenant_id == tenant_id,
            SkillInstance.delete_flag != "Y").limit(1)) is not None:
            raise ValueError("Skill is referenced by an agent")
        SkillService(tenant_id=tenant_id).delete_skill(skill.skill_name, tenant_id=tenant_id, user_id=user_id)
