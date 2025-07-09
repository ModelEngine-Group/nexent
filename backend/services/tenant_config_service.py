import logging
from typing import List

from database.tenant_config_db import get_tenant_config_info, insert_config, delete_config_by_tenant_config_id
from database.knowledge_db import get_knowledge_info_by_knowledge_ids, get_knowledge_ids_by_index_names


logger = logging.getLogger("tenant_config_service")

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
