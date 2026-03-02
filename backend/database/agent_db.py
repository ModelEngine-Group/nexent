import logging
from typing import List
from sqlalchemy import update

from database.client import get_db_session, as_dict, filter_property
from database.db_models import AgentInfo, ToolInstance, AgentRelation
from utils.str_utils import convert_list_to_string

logger = logging.getLogger("agent_db")


def search_agent_info_by_agent_id(agent_id: int, tenant_id: str, version_no: int = 0):
    """
    Search agent info by agent_id.
    Default version_no=0 queries the draft version.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        agent = session.query(AgentInfo).filter(
            AgentInfo.agent_id == agent_id,
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.version_no == version_no,
            AgentInfo.delete_flag != 'Y'
        ).first()

        if not agent:
            raise ValueError("agent not found")

        agent_dict = as_dict(agent)

        return agent_dict


def search_agent_id_by_agent_name(agent_name: str, tenant_id: str, version_no: int = 0):
    """
    Search agent id by agent name.
    Default version_no=0 queries the draft version.

    Args:
        agent_name: Agent name
        tenant_id: Tenant ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        agent = session.query(AgentInfo).filter(
            AgentInfo.name == agent_name,
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.version_no == version_no,
            AgentInfo.delete_flag != 'Y').first()
        if not agent:
            raise ValueError("agent not found")
        return agent.agent_id


def search_blank_sub_agent_by_main_agent_id(tenant_id: str, version_no: int = 0):
    """
    Search blank sub agent by main agent id.
    Default version_no=0 queries the draft version.

    Args:
        tenant_id: Tenant ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        sub_agent = session.query(AgentInfo).filter(
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.version_no == version_no,
            AgentInfo.delete_flag != 'Y',
            AgentInfo.enabled == False
        ).first()
        if sub_agent:
            return sub_agent.agent_id
        else:
            return None


def query_sub_agents_id_list(main_agent_id: int, tenant_id: str, version_no: int = 0):
    """
    Query the sub agent id list by main agent id.
    Default version_no=0 queries the draft version.

    Args:
        main_agent_id: Parent agent ID
        tenant_id: Tenant ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        query = session.query(AgentRelation).filter(
            AgentRelation.parent_agent_id == main_agent_id,
            AgentRelation.tenant_id == tenant_id,
            AgentRelation.version_no == version_no,
            AgentRelation.delete_flag != 'Y')
        relations = query.all()
        return [relation.selected_agent_id for relation in relations]


def clear_agent_new_mark(agent_id: int, tenant_id: str, user_id: str, version_no: int = 0):
    """
    Clear the NEW mark for an agent.
    This clears the NEW mark for ALL versions of the agent, regardless of version_no parameter.

    Args:
        agent_id (int): Agent ID
        tenant_id (str): Tenant ID
        user_id (str): User ID (for audit purposes)
        version_no: Version number (kept for API compatibility, but always clears all versions)
    """
    with get_db_session() as session:
        # Clear NEW mark for ALL versions of this agent
        result = session.execute(
            update(AgentInfo)
            .where(
                AgentInfo.agent_id == agent_id,
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.delete_flag == 'N'
            )
            .values(is_new=False, updated_by=user_id)
        )
        # return number of rows affected
        return result.rowcount


def mark_agents_as_new(agent_ids: list[int], tenant_id: str, user_id: str, version_no: int = 0):
    """
    Mark a list of agents as new.
    This marks ALL versions of the specified agents as new, regardless of version_no parameter.

    Args:
        agent_ids: List of Agent IDs
        tenant_id: Tenant ID
        user_id: User ID
        version_no: Version number (kept for API compatibility, but always marks all versions)
    """
    if not agent_ids:
        return
    with get_db_session() as session:
        session.execute(
            update(AgentInfo)
            .where(
                AgentInfo.agent_id.in_(agent_ids),
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.delete_flag == 'N'
            )
            .values(is_new=True, updated_by=user_id)
        )


def create_agent(agent_info, tenant_id: str, user_id: str):
    """
    Create a new agent in the database (draft version, version_no=0).
    :param agent_info: Dictionary containing agent information
    :param tenant_id:
    :param user_id:
    :return: Created agent object
    """
    info_with_metadata = dict(agent_info)
    info_with_metadata.setdefault("max_steps", 5)
    info_with_metadata.update({
        "tenant_id": tenant_id,
        "version_no": 0,  # Default to draft version
        "created_by": user_id,
        "updated_by": user_id,
        "is_new": True,  # Mark new agents as new
    })
    with get_db_session() as session:
        new_agent = AgentInfo(**filter_property(info_with_metadata, AgentInfo))
        new_agent.delete_flag = 'N'
        session.add(new_agent)
        session.flush()

        # Directly extract agent_id and return as dict
        result = {
            "agent_id": new_agent.agent_id,
            "tenant_id": new_agent.tenant_id,
            "name": new_agent.name,
            "display_name": new_agent.display_name,
            "description": new_agent.description,
            "author": new_agent.author,
            "model_id": new_agent.model_id,
            "model_name": new_agent.model_name,
            "max_steps": new_agent.max_steps,
            "duty_prompt": new_agent.duty_prompt,
            "constraint_prompt": new_agent.constraint_prompt,
            "few_shots_prompt": new_agent.few_shots_prompt,
            "parent_agent_id": new_agent.parent_agent_id,
            "enabled": new_agent.enabled,
            "provide_run_summary": new_agent.provide_run_summary,
            "business_description": new_agent.business_description,
            "business_logic_model_id": new_agent.business_logic_model_id,
            "business_logic_model_name": new_agent.business_logic_model_name,
            "group_ids": new_agent.group_ids,
            "is_new": new_agent.is_new,
            "current_version_no": new_agent.current_version_no,
            "version_no": new_agent.version_no,
            "created_by": new_agent.created_by,
            "updated_by": new_agent.updated_by,
            "delete_flag": new_agent.delete_flag,
        }
        return result


def update_agent(agent_id, agent_info, user_id, version_no: int = 0):
    """
    Update an existing agent in the database.
    Default version_no=0 updates the draft version.

    Args:
        agent_id: ID of the agent to update
        agent_info: Dictionary containing updated agent information
        tenant_id: Tenant ID
        user_id: Optional user ID
        version_no: Version number to filter. Default 0 = draft/editing state
    Returns:
        Updated agent object
    """
    with (get_db_session() as session):
        # update ag_tenant_agent_t
        agent = session.query(AgentInfo).filter(
            AgentInfo.agent_id == agent_id,
            AgentInfo.version_no == version_no,
            AgentInfo.delete_flag != 'Y'
        ).first()
        if not agent:
            raise ValueError("ag_tenant_agent_t Agent not found")

        for key, value in filter_property(agent_info.__dict__, AgentInfo).items():
            if value is None:
                continue
            if key == "group_ids":
                value = convert_list_to_string(value)
            setattr(agent, key, value)
        agent.updated_by = user_id


def delete_agent_by_id(agent_id, tenant_id: str, user_id: str):
    """
    Delete an agent in the database (all versions).
    :param agent_id: ID of the agent to delete
    :param tenant_id: Tenant ID for filtering, mandatory
    :param user_id: Optional user ID for filtering
    :return: None
    """
    from sqlalchemy import update as sqlalchemy_update

    with get_db_session() as session:
        # Soft delete all agent versions (version_no >= 0)
        session.execute(
            sqlalchemy_update(AgentInfo)
            .where(
                AgentInfo.agent_id == agent_id,
                AgentInfo.tenant_id == tenant_id
            )
            .values(delete_flag='Y', updated_by=user_id)
        )
        # Soft delete all tool instances (all versions)
        session.execute(
            sqlalchemy_update(ToolInstance)
            .where(
                ToolInstance.agent_id == agent_id,
                ToolInstance.tenant_id == tenant_id
            )
            .values(delete_flag='Y', updated_by=user_id)
        )


def query_all_agent_info_by_tenant_id(tenant_id: str, version_no: int = 0):
    """
    Query all agent info by tenant id.
    Default version_no=0 queries all draft versions.

    Args:
        tenant_id: Tenant ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        agents = session.query(AgentInfo).filter(
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.version_no == version_no,
            AgentInfo.delete_flag != 'Y'
        ).order_by(AgentInfo.create_time.desc()).all()
        return [as_dict(agent) for agent in agents]


def insert_related_agent(parent_agent_id: int, child_agent_id: int, tenant_id: str, user_id: str, version_no: int = 0) -> bool:
    """
    Insert a related agent.
    Default version_no=0 creates the draft version.

    Args:
        parent_agent_id: Parent agent ID
        child_agent_id: Child agent ID
        tenant_id: Tenant ID
        user_id: User ID
        version_no: Version number. Default 0 = draft/editing state
    """
    try:
        relation_info = {
            "parent_agent_id": parent_agent_id,
            "selected_agent_id": child_agent_id,
            "tenant_id": tenant_id,
            "version_no": version_no,
            "created_by": user_id,
            "updated_by": user_id
        }
        with get_db_session() as session:
            new_relation = AgentRelation(
                **filter_property(relation_info, AgentRelation))
            session.add(new_relation)
            session.flush()
            return True
    except Exception as e:
        logger.error(f"Failed to insert related agent: {str(e)}")
        return False


def delete_related_agent(parent_agent_id: int, child_agent_id: int, tenant_id: str, user_id: str, version_no: int = 0) -> bool:
    """
    Delete a related agent.
    Default version_no=0 deletes the draft version.

    Args:
        parent_agent_id: Parent agent ID
        child_agent_id: Child agent ID
        tenant_id: Tenant ID
        user_id: User ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    try:
        with get_db_session() as session:
            session.query(AgentRelation).filter(
                AgentRelation.parent_agent_id == parent_agent_id,
                AgentRelation.selected_agent_id == child_agent_id,
                AgentRelation.tenant_id == tenant_id,
                AgentRelation.version_no == version_no
            ).update(
                {AgentRelation.delete_flag: 'Y', 'updated_by': user_id})
            return True
    except Exception as e:
        logger.error(f"Failed to delete related agent: {str(e)}")
        return False


def update_related_agents(parent_agent_id: int, related_agent_ids: List[int], tenant_id: str, user_id: str, version_no: int = 0):
    """
    Update related agents for a parent agent by replacing all existing relations.
    Default version_no=0 updates the draft version.

    This function handles both creation and deletion of relations in a single transaction.

    Args:
        parent_agent_id: ID of the parent agent
        related_agent_ids: List of child agent IDs to be related
        tenant_id: Tenant ID
        user_id: User ID for audit trail
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        # Get current relations
        current_relations = session.query(AgentRelation).filter(
            AgentRelation.parent_agent_id == parent_agent_id,
            AgentRelation.tenant_id == tenant_id,
            AgentRelation.version_no == version_no,
            AgentRelation.delete_flag != 'Y'
        ).all()

        current_related_ids = {
            rel.selected_agent_id for rel in current_relations}
        new_related_ids = set(
            related_agent_ids) if related_agent_ids else set()

        # Find IDs to delete (in current but not in new)
        ids_to_delete = current_related_ids - new_related_ids
        # Find IDs to add (in new but not in current)
        ids_to_add = new_related_ids - current_related_ids

        # Soft delete removed relations
        if ids_to_delete:
            session.query(AgentRelation).filter(
                AgentRelation.parent_agent_id == parent_agent_id,
                AgentRelation.selected_agent_id.in_(ids_to_delete),
                AgentRelation.tenant_id == tenant_id,
                AgentRelation.version_no == version_no
            ).update(
                {AgentRelation.delete_flag: 'Y', 'updated_by': user_id},
                synchronize_session=False
            )

        # Add new relations
        for child_agent_id in ids_to_add:
            relation_info = {
                "parent_agent_id": parent_agent_id,
                "selected_agent_id": child_agent_id,
                "tenant_id": tenant_id,
                "version_no": version_no,
                "created_by": user_id,
                "updated_by": user_id
            }
            new_relation = AgentRelation(
                **filter_property(relation_info, AgentRelation))
            session.add(new_relation)


def delete_agent_relationship(agent_id: int, tenant_id: str, user_id: str, version_no: int = 0):
    """
    Delete all relationships for an agent.
    Default version_no=0 deletes the draft version.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        user_id: User ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        session.query(AgentRelation).filter(
            AgentRelation.parent_agent_id == agent_id,
            AgentRelation.tenant_id == tenant_id,
            AgentRelation.version_no == version_no
        ).update(
            {AgentRelation.delete_flag: 'Y', 'updated_by': user_id})
        session.query(AgentRelation).filter(
            AgentRelation.selected_agent_id == agent_id,
            AgentRelation.tenant_id == tenant_id,
            AgentRelation.version_no == version_no
        ).update(
            {AgentRelation.delete_flag: 'Y', 'updated_by': user_id})
