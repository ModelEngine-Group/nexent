import logging

from database.client import get_db_session, as_dict, filter_property
from database.db_models import AgentInfo, ToolInstance, AgentRelation

logger = logging.getLogger("agent_db")


def search_agent_info_by_agent_id(agent_id: int, tenant_id: str):
    """
    Search agent info by agent_id
    """
    with get_db_session() as session:
        agent = session.query(AgentInfo).filter(
            AgentInfo.agent_id == agent_id,
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.delete_flag != 'Y'
        ).first()

        if not agent:
            raise ValueError("agent not found")

        agent_dict = as_dict(agent)

        return agent_dict


def search_agent_id_by_agent_name(agent_name: str, tenant_id: str):
    """
    Search agent id by agent name
    """
    with get_db_session() as session:
        agent = session.query(AgentInfo).filter(
            AgentInfo.name == agent_name,
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.delete_flag != 'Y').first()
        if not agent:
            raise ValueError("agent not found")
        return agent.agent_id


def search_blank_sub_agent_by_main_agent_id(tenant_id: str):
    """
    Search blank sub agent by main agent id
    """
    with get_db_session() as session:
        sub_agent = session.query(AgentInfo).filter(
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.delete_flag != 'Y',
            AgentInfo.enabled == False
        ).first()
        if sub_agent:
            return sub_agent.agent_id
        else:
            return None


def query_sub_agents_id_list(main_agent_id: int, tenant_id: str):
    """
    Query the sub agent id list by main agent id
    """
    with get_db_session() as session:
        query = session.query(AgentRelation).filter(AgentRelation.parent_agent_id == main_agent_id,
                                                    AgentRelation.tenant_id == tenant_id,
                                                    AgentRelation.delete_flag != 'Y')
        relations = query.all()
        return [relation.selected_agent_id for relation in relations]


def create_agent(agent_info, tenant_id: str, user_id: str):
    """
    Create a new agent in the database.
    :param agent_info: Dictionary containing agent information
    :param tenant_id:
    :param user_id:
    :return: Created agent object
    """
    agent_info.update({
        "tenant_id": tenant_id,
        "created_by": user_id,
        "updated_by": user_id,
        "max_steps": 5
    })
    with get_db_session() as session:
        new_agent = AgentInfo(**filter_property(agent_info, AgentInfo))
        new_agent.delete_flag = 'N'
        session.add(new_agent)
        session.flush()

        return as_dict(new_agent)


def update_agent(agent_id, agent_info, tenant_id, user_id):
    """
    Update an existing agent in the database.
    :param agent_id: ID of the agent to update
    :param agent_info: Dictionary containing updated agent information
    :param tenant_id: tenant ID
    :param user_id: Optional user ID
    :return: Updated agent object
    """
    with (get_db_session() as session):
        # update ag_tenant_agent_t
        agent = session.query(AgentInfo).filter(AgentInfo.agent_id == agent_id,
                                                AgentInfo.tenant_id == tenant_id,
                                                AgentInfo.delete_flag != 'Y'
                                                ).first()
        if not agent:
            raise ValueError("ag_tenant_agent_t Agent not found")

        for key, value in filter_property(agent_info.__dict__, AgentInfo).items():
            if value is None:
                continue
            setattr(agent, key, value)
        agent.updated_by = user_id


def delete_agent_by_id(agent_id, tenant_id: str, user_id: str):
    """
    Delete an agent in the database.
    :param agent_id: ID of the agent to delete
    :param tenant_id: Tenant ID for filtering, mandatory
    :param user_id: Optional user ID for filtering
    :return: None
    """
    with get_db_session() as session:
        session.query(AgentInfo).filter(AgentInfo.agent_id == agent_id,
                                        AgentInfo.tenant_id == tenant_id).update(
            {AgentInfo.delete_flag: 'Y', 'updated_by': user_id})
        session.query(ToolInstance).filter(ToolInstance.agent_id == agent_id,
                                           ToolInstance.tenant_id == tenant_id).update(
            {ToolInstance.delete_flag: 'Y', 'updated_by': user_id})
        session.commit()


def query_all_agent_info_by_tenant_id(tenant_id: str):
    """
    Query all agent info by tenant id
    """
    with get_db_session() as session:
        agents = session.query(AgentInfo).filter(AgentInfo.tenant_id == tenant_id,
                                                 AgentInfo.delete_flag != 'Y').order_by(AgentInfo.create_time.desc()).all()
        return [as_dict(agent) for agent in agents]


def insert_related_agent(parent_agent_id: int, child_agent_id: int, tenant_id: str) -> bool:
    try:
        relation_info = {
            "parent_agent_id": parent_agent_id,
            "selected_agent_id": child_agent_id,
            "tenant_id": tenant_id,
            "created_by": tenant_id,
            "updated_by": tenant_id
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


def delete_related_agent(parent_agent_id: int, child_agent_id: int, tenant_id: str) -> bool:
    try:
        with get_db_session() as session:
            session.query(AgentRelation).filter(AgentRelation.parent_agent_id == parent_agent_id,
                                                AgentRelation.selected_agent_id == child_agent_id,
                                                AgentRelation.tenant_id == tenant_id).update(
                {ToolInstance.delete_flag: 'Y', 'updated_by': tenant_id})
            return True
    except Exception as e:
        logger.error(f"Failed to delete related agent: {str(e)}")
        return False


def delete_agent_relationship(agent_id: int, tenant_id: str, user_id: str):
    with get_db_session() as session:
        session.query(AgentRelation).filter(AgentRelation.parent_agent_id == agent_id,
                                            AgentRelation.tenant_id == tenant_id).update(
            {AgentRelation.delete_flag: 'Y', 'updated_by': user_id})
        session.query(AgentRelation).filter(AgentRelation.selected_agent_id == agent_id,
                                            AgentRelation.tenant_id == tenant_id).update(
            {AgentRelation.delete_flag: 'Y', 'updated_by': user_id})
        session.commit()
