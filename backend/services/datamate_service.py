"""
Service layer for DataMate knowledge base integration.
Handles API calls to DataMate to fetch knowledge bases and their files.
This service layer uses the DataMate SDK client to interact with DataMate APIs.
"""
import logging
from typing import Dict, List, Any

from consts.const import DATAMATE_BASE_URL
from database.knowledge_db import upsert_knowledge_record, get_knowledge_info_by_tenant_and_source, delete_knowledge_record
from nexent.vector_database.datamate_core import DataMateCore

logger = logging.getLogger("datamate_service")


def _get_datamate_core() -> DataMateCore:
    """Get DataMate core instance."""
    return DataMateCore(base_url=DATAMATE_BASE_URL)


def _soft_delete_datamate_records(knowledge_base_ids: List[str], tenant_id: str, user_id: str) -> None:
    """
    Soft delete DataMate knowledge base records that no longer exist in the API response.

    Args:
        knowledge_base_ids: List of current knowledge base IDs from API response
        tenant_id: Tenant ID for filtering records
        user_id: User ID for the delete operation
    """
    # Get all existing DataMate records for this tenant
    existing_records = get_knowledge_info_by_tenant_and_source(tenant_id, "datamate")

    # Find records that exist in DB but not in API response
    existing_index_names = {record['index_name'] for record in existing_records}
    api_index_names = set(knowledge_base_ids)

    # Records to delete (exist in DB but not in API)
    records_to_delete = existing_index_names - api_index_names

    # Soft delete records that are no longer in DataMate
    for index_name in records_to_delete:
        try:
            delete_result = delete_knowledge_record({"index_name": index_name, "user_id": user_id})
            if delete_result:
                logger.info(f"Soft deleted DataMate knowledge base record: {index_name}")
            else:
                logger.warning(f"Failed to soft delete DataMate knowledge base record: {index_name}")
        except Exception as e:
            logger.error(f"Error soft deleting DataMate knowledge base record {index_name}: {str(e)}")


async def _create_datamate_knowledge_records(knowledge_base_ids: List[str],
                                           knowledge_base_names: List[str],
                                           embedding_model_names: List[str],
                                           tenant_id: str,
                                           user_id: str) -> List[Dict[str, Any]]:
    """
    Create knowledge records in local database for DataMate knowledge bases.
    Args:
        knowledge_base_ids: List of DataMate knowledge base IDs
        knowledge_base_names: List of DataMate knowledge base names
        embedding_model_names: List of DataMate embedding model names
        tenant_id: Tenant ID for the knowledge records
        user_id: User ID for the knowledge records
    Returns:
        List of created knowledge record dictionaries
    """
    created_records = []

    for i, kb_id in enumerate(knowledge_base_ids):
        try:
            knowledge_name = knowledge_base_names[i]

            # Create or update knowledge record in local database
            record_data = {
                "index_name": kb_id,
                "knowledge_name": knowledge_name,
                "knowledge_describe": f"DataMate knowledge base: {knowledge_name}",
                "knowledge_sources": "datamate",  # Mark source as datamate
                "tenant_id": tenant_id,
                "user_id": user_id,
                "embedding_model_name": embedding_model_names[i]
            }

            # Create or update knowledge record in local database
            created_record = upsert_knowledge_record(record_data)

            created_records.append(created_record)
            logger.info(f"Created knowledge record for DataMate KB '{knowledge_name}': {created_record}")

        except Exception as e:
            logger.error(f"Failed to create knowledge record for DataMate KB '{kb_id}': {str(e)}")
            raise Exception(f"Failed to create knowledge record for DataMate KB '{kb_id}': {str(e)}")

    return created_records


async def fetch_datamate_knowledge_base_file_list(knowledge_base_id: str) -> Dict[str, Any]:
    """
    Fetch file list for a specific DataMate knowledge base.
    Args:
        knowledge_base_id: The ID of the knowledge base.
    Returns:
        Dictionary containing file list with status, files array, etc.
    """
    try:
        core = _get_datamate_core()
        # Get documents detail from DataMate
        files = core.get_documents_detail(knowledge_base_id)

        return {
            "status": "success",
            "files": files
        }
    except Exception as e:
        logger.error(f"Error fetching file list for datamate knowledge base {knowledge_base_id}: {str(e)}")
        raise RuntimeError(f"Failed to fetch file list for datamate knowledge base {knowledge_base_id}: {str(e)}")


async def sync_datamate_knowledge_bases_records(tenant_id: str, user_id: str) -> Dict[str, Any]:
    """
    Sync all DataMate knowledge bases and create knowledge records in local database.
    Args:
        tenant_id: Tenant ID for creating knowledge records
        user_id: User ID for creating knowledge records
    Returns:
        Dictionary containing knowledge bases list and created records.
    """
    try:
        core = _get_datamate_core()

        # Step 1: Get knowledge base id
        knowledge_base_ids = core.get_user_indices()
        if not knowledge_base_ids:
            return {
                "indices": [],
                "count": 0,
            }

        # Step 2: Get detailed information for all knowledge bases
        details, knowledge_base_names = core.get_indices_detail(knowledge_base_ids)

        response = {
            "indices": knowledge_base_names,
            "count": len(knowledge_base_names),
        }

        embedding_model_names = [detail['base_info']['embedding_model'] for detail in details.values()]

        # Add indices_info for consistency with list_indices method
        indices_info = []
        for i, kb_id in enumerate(knowledge_base_ids):
            if kb_id in details:
                indices_info.append({
                    "name": kb_id,
                    "display_name": knowledge_base_names[i],
                    "stats": details[kb_id],
                })
        response["indices_info"] = indices_info

        # Create knowledge records in local database
        await _create_datamate_knowledge_records(
            knowledge_base_ids, knowledge_base_names, embedding_model_names, tenant_id, user_id
        )

        # Step 3: Handle deleted knowledge bases (soft delete)
        _soft_delete_datamate_records(knowledge_base_ids, tenant_id, user_id)

        return response
    except Exception as e:
        logger.error(f"Error syncing DataMate knowledge bases and creating records: {str(e)}")
        return {
            "indices": [],
            "count": 0,
        }
