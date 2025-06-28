import logging
from typing import List
import httpx
from fastapi.responses import JSONResponse

from database.tenant_config_db import get_tenant_config_info, insert_config, delete_config_by_tenant_config_id, \
    delete_config
from database.knowledge_db import get_knowledge_info_by_knowledge_ids, get_knowledge_ids_by_index_names
from utils.config_utils import config_manager

logger = logging.getLogger("tenant config service")

def get_selected_knowledge_list(tenant_id: str, user_id: str):
    record_list = get_tenant_config_info(tenant_id=tenant_id, user_id=user_id, select_key="selected_knowledge_id")
    if len(record_list) == 0:
        return []
    knowledge_id_list = [record["config_value"] for record in record_list]
    knowledge_info = get_knowledge_info_by_knowledge_ids(knowledge_id_list)
    return knowledge_info

def update_selected_knowledge(tenant_id: str, user_id: str, index_name_list: List[str]):
    knowledge_ids = get_knowledge_ids_by_index_names(index_name_list)
    record_list = get_tenant_config_info(tenant_id=tenant_id, user_id=user_id, select_key="selected_knowledge_id")
    record_ids = [record["tenant_config_id"] for record in record_list]

    # if knowledge_ids is not in record_list, insert the record of knowledge_ids
    for knowledge_id in knowledge_ids:
        if knowledge_id not in record_ids:
            result = insert_config({
                "user_id": user_id,
                "tenant_id": tenant_id,
                "config_key": "selected_knowledge_id",
                "config_value": knowledge_id,
                "value_type": "multi"
            })
            if not result:
                logger.error(f"insert_config failed, tenant_id: {tenant_id}, user_id: {user_id}, knowledge_id: {knowledge_id}")
                return False

    # if record_list is not in knowledge_ids, delete the record of record_list
    for record in record_list:
        if record["config_value"] not in knowledge_ids:
            result = delete_config_by_tenant_config_id(record["tenant_config_id"])
            if not result:
                logger.error(f"delete_config_by_tenant_config_id failed, tenant_id: {tenant_id}, user_id: {user_id}, knowledge_id: {record['config_value']}")
                return False

    return True

def delete_selected_knowledge_by_index_name(tenant_id: str, user_id: str, index_name: str):
    knowledge_ids = get_knowledge_ids_by_index_names([index_name])
    record_list = get_tenant_config_info(tenant_id=tenant_id, user_id=user_id, select_key="selected_knowledge_id")

    for record in record_list:
        if record["config_value"] == str(knowledge_ids[0]):
            result = delete_config_by_tenant_config_id(record["tenant_config_id"])
            if not result:
                logger.error(f"delete_config_by_tenant_config_id failed, tenant_id: {tenant_id}, user_id: {user_id}, knowledge_id: {record['config_value']}")
                return False

    return True

async def add_remote_mcp_server_list(tenant_id: str,
                                     user_id: str,
                                     remote_mcp_server: str,
                                     remote_mcp_server_name: str,
                                     record_to_pg: bool = True):
    # 调用 nexent_mcp_service 的 add-remote-proxies 端点
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "mcp_url": remote_mcp_server,
                "service_name": remote_mcp_server_name,
                "transport": "sse"
            }

            nexent_mcp_server = config_manager.get_config("NEXENT_MCP_SERVER")
            response = await client.post(
                f"{nexent_mcp_server}/add-remote-proxies",
                json=payload,
                timeout=10.0
            )

            if response.status_code == 200:
                logger.info(f"Successfully added remote MCP proxy: {remote_mcp_server_name}")
            elif response.status_code == 409:
                logger.error(f"Failed to add remote proxy: Service name {remote_mcp_server_name} already exists")
                return JSONResponse(
                    status_code=409,
                    content={"message": "Service name already exists", "status": "error"}
                )
            elif response.status_code == 503:
                logger.error(f"Failed to add remote proxy: Cannot connect to remote MCP server")
                return JSONResponse(
                    status_code=503,
                    content={"message": "Cannot connect to remote MCP server", "status": "error"}
                )
            else:
                logger.error(f"Failed to call add-remote-proxies endpoint: {response.status_code} - {response.text}")
                return JSONResponse(
                    status_code=400,
                    content={"message": "Failed to add remote MCP proxy", "status": "error"}
                )

    except Exception as e:
        logger.error(f"Error calling nexent_mcp_service add-remote-proxies: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to add remote MCP proxy", "status": "error"}
        )
    if record_to_pg:
        # 更新PG库记录
        result = insert_config({
            "user_id": user_id,
            "tenant_id": tenant_id,
            "config_key": "remote_mcp_server",
            "config_value": f"{remote_mcp_server_name}|{remote_mcp_server}",
            "value_type": "multi"
        })
        if not result:
            logger.error(
                f"add_remote_mcp_server_list failed, tenant_id: {tenant_id}, user_id: {user_id}, remote_mcp_server: {remote_mcp_server}, remote_mcp_server_name: {remote_mcp_server_name}")
            return False
    return JSONResponse(
                status_code=200,
                content={"message": "Successfully added remote MCP proxy", "status": "success"}
            )

async def delete_remote_mcp_server_list(tenant_id: str, user_id: str, remote_mcp_server: str, remote_mcp_server_name: str):
    # 先删除PG库中的记录
    result = delete_config(tenant_id=tenant_id,
                           user_id=user_id,
                           select_key="remote_mcp_server",
                           config_value=f"{remote_mcp_server_name}|{remote_mcp_server}")
    if not result:
        logger.error(f"delete_remote_mcp_server_list failed, tenant_id: {tenant_id}, user_id: {user_id}, remote_mcp_server: {remote_mcp_server}, remote_mcp_server_name: {remote_mcp_server_name}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to delete remote MCP server, server not record", "status": "error"}
        )
        
    # 调用 nexent_mcp_service 的删除远程代理端点
    try:
        async with httpx.AsyncClient() as client:
            nexent_mcp_server = config_manager.get_config("NEXENT_MCP_SERVER")
            url = f"{nexent_mcp_server}/remote-proxies?service_name={remote_mcp_server_name}"
            response = await client.delete(
                url,
                timeout=10.0
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully removed remote MCP proxy: {remote_mcp_server_name}")
            elif response.status_code == 404:
                logger.warning(f"Remote MCP proxy '{remote_mcp_server_name}' not found, may already be removed")
                return JSONResponse(
                    status_code=400,
                    content={"message": "Failed to delete remote MCP proxy, may already be removed", "status": "error"}
                )
            else:
                logger.error(f"Failed to call remote-proxies DELETE endpoint: {response.status_code} - {response.text}")
                return JSONResponse(
                    status_code=400,
                    content={"message": "Failed to delete remote MCP proxy", "status": "error"}
                )
    except Exception as e:
        logger.error(f"Error calling nexent_mcp_service remove remote-proxies: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to delete remote MCP proxy", "status": "error"}
        )
    return JSONResponse(
                status_code=200,
                content={"message": "Successfully added remote MCP proxy", "status": "success"}
            )

async def get_remote_mcp_server_list(tenant_id: str, user_id: str):
    record_list = get_tenant_config_info(tenant_id=tenant_id, user_id=user_id, select_key="remote_mcp_server")
    remote_mcp_server_list = []
    for record in record_list:
        remote_mcp_server_list.append({
            "remote_mcp_server_name": record["config_value"].split("|")[0],
            "remote_mcp_server": record["config_value"].split("|")[1]
        })
    return remote_mcp_server_list

async def recover_remote_mcp_server(tenant_id: str, user_id: str):
    record_mcp_server_info = await get_remote_mcp_server_list(tenant_id=tenant_id, user_id=user_id)
    record_mcp_server_set = set([(record["remote_mcp_server_name"], record["remote_mcp_server"]) for record in record_mcp_server_info])
    
    async with httpx.AsyncClient() as client:
            nexent_mcp_server = config_manager.get_config("NEXENT_MCP_SERVER")
            url = f"{nexent_mcp_server}/list-remote-proxies"
            response = await client.get(
                url,
                timeout=10.0
            )
    if response.status_code == 200:
        remote_mcp_server_info = response.json()
        remote_mcp_server_set = set([(mcp_name, info["mcp_url"]) for mcp_name, info in remote_mcp_server_info["proxies"].items()])
        
        for mcp_name, mcp_url in list(record_mcp_server_set - remote_mcp_server_set):
            response = await add_remote_mcp_server_list(tenant_id=tenant_id,
                                             user_id=user_id,
                                             remote_mcp_server=mcp_url,
                                             remote_mcp_server_name=mcp_name,
                                             record_to_pg=False)
            if response.status_code == 200:
                logger.info(f"Successfully added remote MCP proxy: {mcp_name}")
            else:
                logger.error(f"Failed to recover remote MCP proxy: {mcp_name}")
                return response
    else:
        logger.error(f"Failed to load remote MCP proxy list: {response.status_code} - {response.text}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to load remote MCP proxy list", "status": "error"}
        )
        
    return JSONResponse(
                status_code=200,
                content={"message": "Successfully recovered remote MCP proxy", "status": "success"}
            )
