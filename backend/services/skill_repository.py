"""Skill repository for database operations."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import update as sa_update

from database.client import get_db_session, as_dict
from database.db_models import SkillInfo, SkillToolRelation, SkillInstance, ToolInfo
from utils.skill_params_utils import strip_params_comments_for_db

logger = logging.getLogger(__name__)


def _params_value_for_db(raw: Any) -> Any:
    """Strip UI/YAML comment metadata, then JSON round-trip for the DB JSON column."""
    if raw is None:
        return None
    stripped = strip_params_comments_for_db(raw)
    return json.loads(json.dumps(stripped, default=str))


class SkillRepository:
    """Repository for skill database operations."""

    @staticmethod
    def list_skills() -> List[Dict[str, Any]]:
        """List all skills from database."""
        with get_db_session() as session:
            skills = session.query(SkillInfo).filter(
                SkillInfo.delete_flag != 'Y'
            ).all()
            results = []
            for s in skills:
                result = SkillRepository._to_dict(s)
                result["tool_ids"] = SkillRepository._get_tool_ids(session, s.skill_id)
                results.append(result)
            return results

    @staticmethod
    def get_skill_by_name(skill_name: str) -> Optional[Dict[str, Any]]:
        """Get skill by name."""
        with get_db_session() as session:
            skill = session.query(SkillInfo).filter(
                SkillInfo.skill_name == skill_name,
                SkillInfo.delete_flag != 'Y'
            ).first()
            if skill:
                result = SkillRepository._to_dict(skill)
                result["tool_ids"] = SkillRepository._get_tool_ids(session, skill.skill_id)
                return result
            return None

    @staticmethod
    def get_skill_by_id(skill_id: int) -> Optional[Dict[str, Any]]:
        """Get skill by ID."""
        with get_db_session() as session:
            skill = session.query(SkillInfo).filter(
                SkillInfo.skill_id == skill_id,
                SkillInfo.delete_flag != 'Y'
            ).first()
            if skill:
                result = SkillRepository._to_dict(skill)
                result["tool_ids"] = SkillRepository._get_tool_ids(session, skill.skill_id)
                return result
            return None

    @staticmethod
    def create_skill(skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new skill."""
        with get_db_session() as session:
            skill = SkillInfo(
                skill_name=skill_data["name"],
                skill_description=skill_data.get("description", ""),
                skill_tags=skill_data.get("tags", []),
                skill_content=skill_data.get("content", ""),
                params=_params_value_for_db(skill_data.get("params")),
                source=skill_data.get("source", "custom"),
                created_by=skill_data.get("created_by"),
                create_time=datetime.now(),
                updated_by=skill_data.get("updated_by"),
                update_time=datetime.now(),
            )
            session.add(skill)
            session.flush()

            skill_id = skill.skill_id

            tool_ids = skill_data.get("tool_ids", [])
            if tool_ids:
                for tool_id in tool_ids:
                    rel = SkillToolRelation(
                        skill_id=skill_id,
                        tool_id=tool_id,
                        create_time=datetime.now()
                    )
                    session.add(rel)

            session.commit()

            result = SkillRepository._to_dict(skill)
            result["tool_ids"] = tool_ids
            return result

    @staticmethod
    def update_skill(
        skill_name: str,
        skill_data: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing skill.

        Args:
            skill_name: Skill name (unique key).
            skill_data: Business fields to update (description, content, tags, source, params, tool_ids).
            updated_by: Actor user id from server-side auth; never taken from the HTTP request body.

        Notes:
            Uses a single Core UPDATE for ag_skill_info_t columns. Mixing ORM attribute assignment
            with session.execute(update()) can let autoflush emit an UPDATE that overwrites JSON
            params with stale in-memory values, so we avoid ORM writes for this row.
        """
        with get_db_session() as session:
            skill = session.query(SkillInfo).filter(
                SkillInfo.skill_name == skill_name,
                SkillInfo.delete_flag != "Y",
            ).first()

            if not skill:
                raise ValueError(f"Skill not found: {skill_name}")

            skill_id = skill.skill_id
            now = datetime.now()
            row_values: Dict[str, Any] = {"update_time": now}
            if updated_by:
                row_values["updated_by"] = updated_by

            if "description" in skill_data:
                row_values["skill_description"] = skill_data["description"]
            if "content" in skill_data:
                row_values["skill_content"] = skill_data["content"]
            if "tags" in skill_data:
                row_values["skill_tags"] = skill_data["tags"]
            if "source" in skill_data:
                row_values["source"] = skill_data["source"]
            if "params" in skill_data:
                row_values["params"] = _params_value_for_db(skill_data["params"])

            session.execute(
                sa_update(SkillInfo)
                .where(
                    SkillInfo.skill_id == skill_id,
                    SkillInfo.delete_flag != "Y",
                )
                .values(**row_values)
            )

            if "tool_ids" in skill_data:
                session.query(SkillToolRelation).filter(
                    SkillToolRelation.skill_id == skill_id
                ).delete()

                for tool_id in skill_data["tool_ids"]:
                    rel = SkillToolRelation(
                        skill_id=skill_id,
                        tool_id=tool_id,
                        create_time=datetime.now()
                    )
                    session.add(rel)

            session.commit()

            refreshed = session.query(SkillInfo).filter(
                SkillInfo.skill_id == skill_id,
                SkillInfo.delete_flag != "Y",
            ).first()
            if not refreshed:
                raise ValueError(f"Skill not found after update: {skill_name}")

            result = SkillRepository._to_dict(refreshed)
            result["tool_ids"] = skill_data.get(
                "tool_ids",
                SkillRepository._get_tool_ids(session, skill_id),
            )
            return result

    @staticmethod
    def delete_skill(skill_name: str, updated_by: Optional[str] = None) -> bool:
        """Soft delete a skill (mark as deleted).

        Args:
            skill_name: Name of the skill to delete
            updated_by: User ID of the user performing the delete

        Returns:
            True if deleted successfully
        """
        with get_db_session() as session:
            skill = session.query(SkillInfo).filter(
                SkillInfo.skill_name == skill_name
            ).first()

            if not skill:
                return False

            skill_id = skill.skill_id
            skill.delete_flag = 'Y'
            skill.update_time = datetime.now()
            if updated_by:
                skill.updated_by = updated_by

            # Soft delete all skill instances associated with this skill in the same transaction
            session.query(SkillInstance).filter(
                SkillInstance.skill_id == skill_id,
                SkillInstance.delete_flag != 'Y'
            ).update({
                SkillInstance.delete_flag: 'Y',
                'updated_by': updated_by
            })

            session.commit()
            return True

    @staticmethod
    def _get_tool_ids(session, skill_id: int) -> List[int]:
        """Get tool IDs for a skill."""
        relations = session.query(SkillToolRelation).filter(
            SkillToolRelation.skill_id == skill_id
        ).all()
        return [r.tool_id for r in relations]

    @staticmethod
    def _to_dict(skill: SkillInfo) -> Dict[str, Any]:
        """Convert SkillInfo to dict."""
        return {
            "skill_id": skill.skill_id,
            "name": skill.skill_name,
            "description": skill.skill_description,
            "tags": skill.skill_tags or [],
            "content": skill.skill_content or "",
            "params": skill.params if skill.params is not None else {},
            "source": skill.source,
            "created_by": skill.created_by,
            "create_time": skill.create_time.isoformat() if skill.create_time else None,
            "updated_by": skill.updated_by,
            "update_time": skill.update_time.isoformat() if skill.update_time else None,
        }

    @staticmethod
    def get_tool_names_by_ids(session, tool_ids: List[int]) -> List[str]:
        """Get tool names from tool IDs."""
        if not tool_ids:
            return []
        tools = session.query(ToolInfo.name).filter(
            ToolInfo.tool_id.in_(tool_ids)
        ).all()
        return [t.name for t in tools]

    @staticmethod
    def get_tool_ids_by_names(tool_names: List[str], tenant_id: str) -> List[int]:
        """Get tool IDs from tool names.

        Args:
            tool_names: List of tool names
            tenant_id: Tenant ID

        Returns:
            List of tool IDs
        """
        if not tool_names:
            return []
        with get_db_session() as session:
            tools = session.query(ToolInfo.tool_id).filter(
                ToolInfo.name.in_(tool_names),
                ToolInfo.delete_flag != 'Y',
                ToolInfo.author == tenant_id
            ).all()
            return [t.tool_id for t in tools]

    @staticmethod
    def get_tool_names_by_skill_name(skill_name: str) -> List[str]:
        """Get tool names for a skill by skill name.

        Args:
            skill_name: Name of the skill

        Returns:
            List of tool names
        """
        with get_db_session() as session:
            skill = session.query(SkillInfo).filter(
                SkillInfo.skill_name == skill_name,
                SkillInfo.delete_flag != 'Y'
            ).first()
            if not skill:
                return []
            tool_ids = SkillRepository._get_tool_ids(session, skill.skill_id)
            return SkillRepository.get_tool_names_by_ids(session, tool_ids)

    @staticmethod
    def get_skill_with_tool_names(skill_name: str) -> Optional[Dict[str, Any]]:
        """Get skill with tool names included."""
        with get_db_session() as session:
            skill = session.query(SkillInfo).filter(
                SkillInfo.skill_name == skill_name,
                SkillInfo.delete_flag != 'Y'
            ).first()
            if skill:
                result = SkillRepository._to_dict(skill)
                tool_ids = SkillRepository._get_tool_ids(session, skill.skill_id)
                result["tool_ids"] = tool_ids
                result["allowed_tools"] = SkillRepository.get_tool_names_by_ids(session, tool_ids)
                return result
            return None
