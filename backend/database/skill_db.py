"""Skill instance database operations."""

import logging
from typing import List, Optional

from database.client import get_db_session, filter_property, as_dict
from database.db_models import SkillInstance

logger = logging.getLogger(__name__)


def create_or_update_skill_by_skill_info(skill_info, tenant_id: str, user_id: str, version_no: int = 0):
    """
    Create or update a SkillInstance in the database.
    Default version_no=0 operates on the draft version.

    Args:
        skill_info: Dictionary or object containing skill instance information
        tenant_id: Tenant ID for filtering, mandatory
        user_id: User ID for updating (will be set as the last updater)
        version_no: Version number to filter. Default 0 = draft/editing state

    Returns:
        Created or updated SkillInstance object
    """
    skill_info_dict = skill_info.__dict__ if hasattr(skill_info, '__dict__') else skill_info
    skill_info_dict = skill_info_dict.copy()
    skill_info_dict.setdefault("tenant_id", tenant_id)
    skill_info_dict.setdefault("user_id", user_id)
    skill_info_dict.setdefault("version_no", version_no)
    skill_info_dict.setdefault("created_by", user_id)
    skill_info_dict.setdefault("updated_by", user_id)

    with get_db_session() as session:
        query = session.query(SkillInstance).filter(
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.agent_id == skill_info_dict.get('agent_id'),
            SkillInstance.delete_flag != 'Y',
            SkillInstance.skill_id == skill_info_dict.get('skill_id'),
            SkillInstance.version_no == version_no
        )
        skill_instance = query.first()

        if skill_instance:
            for key, value in skill_info_dict.items():
                if hasattr(skill_instance, key):
                    setattr(skill_instance, key, value)
        else:
            new_skill_instance = SkillInstance(
                **filter_property(skill_info_dict, SkillInstance))
            session.add(new_skill_instance)
            session.flush()
            skill_instance = new_skill_instance

        return as_dict(skill_instance)


def query_skill_instances_by_agent_id(agent_id: int, tenant_id: str, version_no: int = 0):
    """Query all SkillInstance for an agent (regardless of enabled status)."""
    with get_db_session() as session:
        query = session.query(SkillInstance).filter(
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.agent_id == agent_id,
            SkillInstance.version_no == version_no,
            SkillInstance.delete_flag != 'Y')
        skill_instances = query.all()
        return [as_dict(skill_instance) for skill_instance in skill_instances]


def query_enabled_skill_instances(agent_id: int, tenant_id: str, version_no: int = 0):
    """Query enabled SkillInstance in the database."""
    with get_db_session() as session:
        query = session.query(SkillInstance).filter(
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.version_no == version_no,
            SkillInstance.delete_flag != 'Y',
            SkillInstance.enabled,
            SkillInstance.agent_id == agent_id)
        skill_instances = query.all()
        return [as_dict(skill_instance) for skill_instance in skill_instances]


def query_skill_instance_by_id(agent_id: int, skill_id: int, tenant_id: str, version_no: int = 0):
    """Query SkillInstance in the database by agent_id and skill_id."""
    with get_db_session() as session:
        query = session.query(SkillInstance).filter(
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.agent_id == agent_id,
            SkillInstance.skill_id == skill_id,
            SkillInstance.version_no == version_no,
            SkillInstance.delete_flag != 'Y')
        skill_instance = query.first()
        if skill_instance:
            return as_dict(skill_instance)
        else:
            return None


def search_skills_for_agent(agent_id: int, tenant_id: str, version_no: int = 0):
    """Query enabled skills for an agent with skill content from SkillInstance."""
    with get_db_session() as session:
        query = session.query(SkillInstance).filter(
            SkillInstance.agent_id == agent_id,
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.version_no == version_no,
            SkillInstance.delete_flag != 'Y',
            SkillInstance.enabled
        )

        skill_instances = query.all()
        return [as_dict(skill_instance) for skill_instance in skill_instances]


def delete_skills_by_agent_id(agent_id: int, tenant_id: str, user_id: str, version_no: int = 0):
    """Delete all skill instances for an agent."""
    with get_db_session() as session:
        session.query(SkillInstance).filter(
            SkillInstance.agent_id == agent_id,
            SkillInstance.tenant_id == tenant_id,
            SkillInstance.version_no == version_no
        ).update({
            SkillInstance.delete_flag: 'Y', 'updated_by': user_id
        })


def delete_skill_instances_by_skill_id(skill_id: int, user_id: str):
    """Soft delete all skill instances for a specific skill.

    This is called when a skill is deleted to clean up associated skill instances.

    Args:
        skill_id: ID of the skill to delete instances for
        user_id: User ID for the updated_by field
    """
    with get_db_session() as session:
        session.query(SkillInstance).filter(
            SkillInstance.skill_id == skill_id,
            SkillInstance.delete_flag != 'Y'
        ).update({
            SkillInstance.delete_flag: 'Y',
            'updated_by': user_id
        })
