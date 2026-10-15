"""Historical test-local scenarios with no production entry points."""

import json
import logging
import os
from collections import deque

from fastapi.responses import JSONResponse

from consts.model import ExportAndImportAgentInfo
from database.agent_db import (
    delete_related_agent,
    insert_related_agent,
    query_sub_agents_id_list,
    search_agent_id_by_agent_name,
)

logger = logging.getLogger(__name__)


def load_default_agents_json_file(default_agent_path):
    # load all json files in the folder
    all_json_files = []
    agent_file_list = os.listdir(default_agent_path)
    for agent_file in agent_file_list:
        if agent_file.endswith(".json"):
            with open(os.path.join(default_agent_path, agent_file), "r", encoding="utf-8") as f:
                agent_json = json.load(f)

            export_agent_info = ExportAndImportAgentInfo.model_validate(
                agent_json)
            all_json_files.append(export_agent_info)
    return all_json_files


def insert_related_agent_impl(parent_agent_id, child_agent_id, tenant_id):
    # search the agent by bfs, check if there is a circular call
    search_list = deque([child_agent_id])
    agent_id_set = set()

    while len(search_list):
        left_ele = search_list.popleft()
        if left_ele == parent_agent_id:
            return JSONResponse(
                status_code=500,
                content={
                    "message": "There is a circular call in the agent", "status": "error"}
            )
        if left_ele in agent_id_set:
            continue
        else:
            agent_id_set.add(left_ele)
        sub_ids = query_sub_agents_id_list(
            main_agent_id=left_ele, tenant_id=tenant_id)
        search_list.extend(sub_ids)

    result = insert_related_agent(parent_agent_id, child_agent_id, tenant_id)
    if result:
        return JSONResponse(
            status_code=200,
            content={"message": "Insert relation success", "status": "success"}
        )
    else:
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to insert relation", "status": "error"}
        )


async def get_agent_id_by_name(agent_name: str, tenant_id: str) -> int:
    """
    Resolve unique agent id by its unique name under the same tenant.
    """
    if not agent_name:
        raise Exception("agent_name required")
    try:
        return search_agent_id_by_agent_name(agent_name, tenant_id)
    except Exception as _:
        logger.error(
            f"Failed to find agent id with '{agent_name}' in tenant {tenant_id}")
        raise Exception("agent not found")


def delete_related_agent_impl(parent_agent_id: int, child_agent_id: int, tenant_id: str):
    """
    Delete the relationship between a parent agent and its child agent

    Args:
        parent_agent_id (int): The ID of the parent agent
        child_agent_id (int): The ID of the child agent to be removed from parent
        tenant_id (str): The tenant ID for data isolation

    Raises:
        ValueError: When deletion operation fails
    """
    try:
        return delete_related_agent(parent_agent_id, child_agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to delete related agent: {str(e)}")
        raise Exception(f"Failed to delete related agent: {str(e)}")
