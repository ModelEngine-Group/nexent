"""
Service layer for DataMate knowledge base integration.
Handles API calls to DataMate to fetch knowledge bases and their files.

This service layer uses the DataMate SDK client to interact with DataMate APIs.
"""
import logging
from typing import Dict, List, Any, Optional
import asyncio

from consts.const import DATAMATE_URL
from utils.config_utils import tenant_config_manager
from database.knowledge_db import upsert_knowledge_record, get_knowledge_info_by_tenant_and_source, delete_knowledge_record
from nexent.vector_database.datamate_core import DataMateCore
from consts.const import MODEL_ENGINE_ENABLED


logger = logging.getLogger("datamate_service")


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
                # Use datamate as embedding model name
                "embedding_model_name": embedding_model_names[i]
            }

            # Run synchronous database operation in executor to avoid blocking
            loop = asyncio.get_event_loop()
            created_record = await loop.run_in_executor(
                None,
                upsert_knowledge_record,
                record_data
            )

            created_records.append(created_record)
            logger.info(
                f"Created knowledge record for DataMate KB '{knowledge_name}': {created_record}")

        except Exception as e:
            logger.error(
                f"Failed to create knowledge record for DataMate KB '{kb_id}': {str(e)}")
            # Continue with other knowledge bases even if one fails
            continue

    return created_records


def _get_datamate_core(tenant_id: str, datamate_url: Optional[str] = None) -> DataMateCore:
    """
    Get DataMate core instance.

    Args:
        tenant_id: Tenant ID for configuration lookup
        datamate_url: Optional DataMate server URL (for dynamic configuration)

    Returns:
        DataMateCore instance
    """
    datamate_server_url = datamate_url if datamate_url else tenant_config_manager.get_app_config(
        DATAMATE_URL, tenant_id=tenant_id)
    if not datamate_server_url:
        raise ValueError(f"DataMate URL not configured for tenant {tenant_id}")

    # For HTTPS URLs with self-signed certificates, disable SSL verification
    verify_ssl = not datamate_server_url.startswith("https://")

    return DataMateCore(base_url=datamate_server_url, verify_ssl=verify_ssl)


async def fetch_datamate_knowledge_base_file_list(knowledge_base_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Fetch file list for a specific DataMate knowledge base.

    Args:
        knowledge_base_id: The ID of the knowledge base.
        tenant_id: Tenant ID for configuration lookup.

    Returns:
        Dictionary containing file list with status, files array, etc.
    """
    try:
        core = _get_datamate_core(tenant_id)
        # Run synchronous SDK call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None,
            core.get_documents_detail,
            knowledge_base_id
        )

        # Transform to match vectordatabase files endpoint format
        return {
            "status": "success",
            "files": files
        }
    except Exception as e:
        logger.error(
            f"Error fetching file list for knowledge base {knowledge_base_id}: {str(e)}")
        raise RuntimeError(
            f"Failed to fetch file list for knowledge base {knowledge_base_id}: {str(e)}")


async def sync_datamate_knowledge_bases_and_create_records(
    tenant_id: str,
    user_id: str,
    datamate_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Sync all DataMate knowledge bases and create knowledge records in local database.

    Args:
        tenant_id: Tenant ID for creating knowledge records
        user_id: User ID for creating knowledge records
        datamate_url: Optional DataMate server URL from request (for dynamic configuration)

    Returns:
        Dictionary containing knowledge bases list and created records.
    """
    # Use provided datamate_url from request, fallback to tenant config
    effective_datamate_url = datamate_url if datamate_url else tenant_config_manager.get_app_config(
        DATAMATE_URL, tenant_id=tenant_id)

    if not effective_datamate_url:
        logger.warning(
            f"DataMate URL not configured for tenant {tenant_id}, skipping sync")
        return {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "created_records": []
        }

    logger.info(
        f"Starting DataMate sync for tenant {tenant_id} using URL: {effective_datamate_url}")

    try:
        core = _get_datamate_core(tenant_id, effective_datamate_url)

        # Run synchronous SDK calls in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()

        # Step 1: Get knowledge base ids
        knowledge_base_ids = await loop.run_in_executor(
            None,
            core.get_user_indices
        )

        if not knowledge_base_ids:
            return {
                "indices": [],
                "count": 0,
            }

        # Step 2: Get detailed information for all knowledge bases
        details, knowledge_base_names = await loop.run_in_executor(
            None,
            lambda: core.get_indices_detail(knowledge_base_ids)
        )

        response = {
            "indices": knowledge_base_names,
            "count": len(knowledge_base_names),
        }

        embedding_model_names = [
            detail['base_info']['embedding_model'] for detail in details.values()]

        # Add indices_info for consistency with list_indices method
        indices_info = []
        for i, kb_id in enumerate(knowledge_base_ids):
            if kb_id in details:
                kb_detail = details[kb_id]
                knowledge_base_name = knowledge_base_names[i] if i < len(
                    knowledge_base_names) else kb_id
                indices_info.append({
                    "name": kb_id,  # Internal index name (used as ID)
                    "display_name": knowledge_base_name,  # User-facing knowledge base name
                    "stats": kb_detail,
                })
        response["indices_info"] = indices_info

        # Create knowledge records in local database
        await _create_datamate_knowledge_records(
            knowledge_base_ids, knowledge_base_names, embedding_model_names, tenant_id, user_id
        )

        # Step 3: Handle deleted knowledge bases (soft delete)
        # Get all existing DataMate records for this tenant
        loop = asyncio.get_event_loop()
        existing_records = await loop.run_in_executor(
            None,
            get_knowledge_info_by_tenant_and_source,
            tenant_id,
            "datamate"
        )

        # Find records that exist in DB but not in API response
        existing_index_names = {record['index_name']
                                for record in existing_records}
        api_index_names = set(knowledge_base_ids)

        # Records to delete (exist in DB but not in API)
        records_to_delete = existing_index_names - api_index_names

        # Soft delete records that are no longer in DataMate
        for index_name in records_to_delete:
            try:
                delete_result = await loop.run_in_executor(
                    None,
                    delete_knowledge_record,
                    {"index_name": index_name, "user_id": user_id}
                )
                if delete_result:
                    logger.info(
                        f"Soft deleted DataMate knowledge base record: {index_name}")
                else:
                    logger.warning(
                        f"Failed to soft delete DataMate knowledge base record: {index_name}")
            except Exception as e:
                logger.error(
                    f"Error soft deleting DataMate knowledge base record {index_name}: {str(e)}")
                # Continue with other records even if one fails

        return response
    except Exception as e:
        logger.error(
            f"Error syncing DataMate knowledge bases and creating records: {str(e)}")
        return {
            "indices": [],
            "count": 0,
        }


async def check_datamate_connection(
    tenant_id: str,
    datamate_url: Optional[str] = None
) -> tuple:
    """
    Test connection to DataMate server.

    Args:
        tenant_id: Tenant ID for configuration lookup.
        datamate_url: Optional DataMate server URL from request (for dynamic configuration).

    Returns:
        Tuple of (is_connected: bool, error_message: str).
        is_connected is True if connection successful, False otherwise.
        error_message contains error details if connection failed, empty string if successful.
    """
    # Check if ModelEngine is enabled
    if str(MODEL_ENGINE_ENABLED).lower() != "true":
        logger.info(
            f"ModelEngine is disabled (MODEL_ENGINE_ENABLED={MODEL_ENGINE_ENABLED}), skipping DataMate connection test")
        return (False, "ModelEngine is disabled")

    # Use provided datamate_url from request, fallback to tenant config
    effective_datamate_url = datamate_url if datamate_url else tenant_config_manager.get_app_config(
        DATAMATE_URL, tenant_id=tenant_id)

    if not effective_datamate_url:
        logger.warning(
            f"DataMate URL not configured for tenant {tenant_id}")
        return (False, "DataMate URL not configured")

    logger.info(
        f"Testing DataMate connection for tenant {tenant_id} using URL: {effective_datamate_url}")

    try:
        core = _get_datamate_core(tenant_id, effective_datamate_url)

        # Run synchronous SDK call in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()

        # Test connection by fetching user indices
        await loop.run_in_executor(
            None,
            core.get_user_indices
        )

        logger.info(
            f"DataMate connection test successful for tenant {tenant_id}")
        return (True, "")

    except ValueError as e:
        # Configuration error (e.g., missing DataMate URL)
        error_msg = str(e)
        logger.error(
            f"DataMate connection test failed (configuration error) for tenant {tenant_id}: {error_msg}")
        return (False, error_msg)

    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"DataMate connection test failed for tenant {tenant_id}: {error_msg}")
        return (False, error_msg)
