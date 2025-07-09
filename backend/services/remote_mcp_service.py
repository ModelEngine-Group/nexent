import logging
import httpx
from fastapi.responses import JSONResponse

from database.remote_mcp_db import create_mcp_record, delete_mcp_record_by_name_and_url, get_mcp_records_by_tenant, \
    check_mcp_name_exists
from utils.config_utils import config_manager

logger = logging.getLogger("remote_mcp_service")

async def add_remote_proxy(remote_mcp_server: str,
                           remote_mcp_server_name: str) -> JSONResponse:
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
                timeout=15.0
            )

            if response.status_code == 200:
                logger.info(f"Successfully added remote MCP proxy: {remote_mcp_server_name}")
                return JSONResponse(
                    status_code=200,
                    content={"message": "Successful", "status": "error"}
                )
            elif response.status_code == 409:
                logger.error(f"Failed to add remote proxy: Service name {remote_mcp_server_name} already exists")
                return JSONResponse(
                    status_code=409,
                    content={"message": "Service name already exists", "status": "error"}
                )
            elif response.status_code == 503:
                logger.error("Failed to add remote proxy: Cannot connect to remote MCP server")
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
    except httpx.TimeoutException:
        logger.error(f"Timeout when calling add-remote-proxies endpoint: {remote_mcp_server_name}")
        return JSONResponse(
            status_code=400,
            content={"message": "Timeout when calling add-remote-proxies endpoint", "status": "error"}
        )

    except Exception as e:
        logger.error(f"Error calling nexent_mcp_service add-remote-proxies: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to add remote MCP proxy", "status": "error"}
        )


async def add_remote_mcp_server_list(tenant_id: str,
                                     user_id: str,
                                     remote_mcp_server: str,
                                     remote_mcp_server_name: str):
    # first check if the name and url is already in use
    if check_mcp_name_exists(mcp_name=remote_mcp_server_name):
        return JSONResponse(
            status_code=409,
            content={"message": "Service name already exists", "status": "error"}
        )

    # call the add-remote-proxies endpoint of nexent_mcp_service
    response = await add_remote_proxy(remote_mcp_server=remote_mcp_server,
                                      remote_mcp_server_name=remote_mcp_server_name)

    if response.status_code != 200:
        if remote_mcp_server_name not in get_all_mount_mcp_service():
            # check out mount status
            return response

    # update the PG database record
    insert_mcp_data = {"mcp_name": remote_mcp_server_name,
                       "mcp_server": remote_mcp_server}
    result = create_mcp_record(mcp_data=insert_mcp_data, tenant_id=tenant_id, user_id=user_id)
    if not result:
        logger.error(
            f"add_remote_mcp_server_list failed, tenant_id: {tenant_id}, user_id: {user_id}, remote_mcp_server: {remote_mcp_server}, remote_mcp_server_name: {remote_mcp_server_name}")
        return False
    return JSONResponse(
        status_code=200,
        content={"message": "Successfully added remote MCP proxy", "status": "success"}
    )

async def delete_remote_mcp_server_list(tenant_id: str, user_id: str, remote_mcp_server: str, remote_mcp_server_name: str):
    # first check if the name and url is already in use
    if not check_mcp_name_exists(mcp_name=remote_mcp_server_name):
        return JSONResponse(
            status_code=409,
            content={"message": "Service name not exists", "status": "error"}
        )

    # second call the delete remote proxy endpoint of nexent_mcp_service, to avoid network problem causing delete failure
    try:
        async with httpx.AsyncClient() as client:
            nexent_mcp_server = config_manager.get_config("NEXENT_MCP_SERVER")
            url = f"{nexent_mcp_server}/remote-proxies?service_name={remote_mcp_server_name}"
            response = await client.delete(
                url,
                timeout=15.0
            )

            if response.status_code == 200:
                logger.info(f"Successfully removed remote MCP proxy: {remote_mcp_server_name}")
            elif response.status_code == 404:
                logger.warning(f"Remote MCP proxy '{remote_mcp_server_name}' not found, may already be removed")
            else:
                logger.error(f"Failed to call remote-proxies DELETE endpoint: {response.status_code} - {response.text}")
                return JSONResponse(
                    status_code=400,
                    content={"message": "Failed to delete remote MCP proxy", "status": "error"}
                )
    except httpx.TimeoutException:
        logger.error(f"Timeout when calling remove remote-proxies endpoint: {remote_mcp_server_name}")
        return JSONResponse(
            status_code=400,
            content={"message": "Timeout when calling remove remote-proxies endpoint", "status": "error"}
        )
    except Exception as e:
        logger.error(f"Error calling nexent_mcp_service remove remote-proxies: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to delete remote MCP proxy", "status": "error"}
        )

    # third delete the record in the PG database
    result = delete_mcp_record_by_name_and_url(mcp_name=remote_mcp_server_name,
                                               mcp_server=remote_mcp_server,
                                               tenant_id=tenant_id,
                                               user_id=user_id)
    if not result:
        logger.error(
            f"delete_remote_mcp_server_list failed, tenant_id: {tenant_id}, user_id: {user_id}, remote_mcp_server: {remote_mcp_server}, remote_mcp_server_name: {remote_mcp_server_name}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to delete remote MCP server, server not record", "status": "error"}
        )

    return JSONResponse(
        status_code=200,
        content={"message": "Successfully added remote MCP proxy", "status": "success"}
    )

async def get_all_mount_mcp_service():
    try:
        async with httpx.AsyncClient() as client:
            nexent_mcp_server = config_manager.get_config("NEXENT_MCP_SERVER")
            url = f"{nexent_mcp_server}/list-remote-proxies"
            response = await client.get(
                url,
                timeout=15.0
            )

            if response.status_code == 200:
                logger.info("Successfully get all mount MCP proxy")
                mount_info = response.json()
                return mount_info.get("proxies", {}).keys()
            else:
                logger.error(f"list-remote-proxies error: {response.status_code} - {response.text}")
                return []
    except httpx.TimeoutException:
        logger.error("Timeout when calling list-remote-proxies endpoint")
        return []
    except Exception as e:
        logger.info(f"Failed get all mount MCP proxy: {e}")
        return []

async def get_remote_mcp_server_list(tenant_id: str):
    mcp_records = get_mcp_records_by_tenant(tenant_id=tenant_id)
    mcp_records_list = []

    mount_mcp_server = await get_all_mount_mcp_service()
    for record in mcp_records:
        mcp_records_list.append({
            "remote_mcp_server_name": record["mcp_name"],
            "remote_mcp_server": record["mcp_server"],
            "status": True if record["mcp_name"] in mount_mcp_server else False
        })
    return mcp_records_list


async def recover_remote_mcp_server(tenant_id: str):
    record_mcp_server_info = await get_remote_mcp_server_list(tenant_id=tenant_id)

    result = JSONResponse(
        status_code=200,
        content={"message": "Successfully recovered remote MCP proxy", "status": "success"}
    )
    for record in record_mcp_server_info:
        mcp_name = record["remote_mcp_server_name"]
        if not record["status"]:
            response = await add_remote_proxy(remote_mcp_server=record["remote_mcp_server"],
                                              remote_mcp_server_name=mcp_name)
            if response.status_code == 200:
                logger.info(f"Successfully added remote MCP proxy: {mcp_name}")
            else:
                logger.error(f"Failed to recover remote MCP proxy: {mcp_name}")
                result = response

    return result
