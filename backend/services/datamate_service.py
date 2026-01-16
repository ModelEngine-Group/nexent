"""
Service layer for DataMate knowledge base integration.
Handles API calls to DataMate to fetch knowledge bases and their files.

This service layer uses the DataMate SDK client to interact with DataMate APIs.
"""
import json
import logging
from typing import Dict, List, Optional, Any
import asyncio

from consts.const import DATAMATE_URL
from utils.config_utils import tenant_config_manager
from database.knowledge_db import upsert_knowledge_record, get_knowledge_info_by_tenant_and_source, delete_knowledge_record
from nexent.vector_database.datamate_core import DataMateCore

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
            # Get knowledge base name, fallback to ID if not available
            knowledge_name = knowledge_base_names[i] if i < len(
                knowledge_base_names) else kb_id

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


def _get_datamate_core(tenant_id: str) -> DataMateCore:
    """Get DataMate core instance."""
    datamate_url = tenant_config_manager.get_app_config(
        DATAMATE_URL, tenant_id=tenant_id)
    if not datamate_url:
        raise ValueError(f"DataMate URL not configured for tenant {tenant_id}")
    return DataMateCore(base_url=datamate_url)


async def fetch_datamate_knowledge_base_files(knowledge_base_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """
    Fetch file list for a specific DataMate knowledge base.

    Args:
        knowledge_base_id: The ID of the knowledge base.
        tenant_id: Tenant ID for configuration lookup.

    Returns:
        List of file dictionaries with name, status, size, upload_date, etc.
    """
    try:
        core = _get_datamate_core(tenant_id)
        # Run synchronous SDK call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            core.get_index_chunks,
            knowledge_base_id
        )
        return result["chunks"]
    except Exception as e:
        logger.error(
            f"Error fetching files for knowledge base {knowledge_base_id}: {str(e)}")
        raise RuntimeError(
            f"Failed to fetch files for knowledge base {knowledge_base_id}: {str(e)}")


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


async def sync_datamate_knowledge_bases_and_create_records(tenant_id: str, user_id: str) -> Dict[str, Any]:
    """
    Sync all DataMate knowledge bases and create knowledge records in local database.

    Args:
        tenant_id: Tenant ID for creating knowledge records
        user_id: User ID for creating knowledge records

    Returns:
        Dictionary containing knowledge bases list and created records.
    """
    try:
        core = _get_datamate_core(tenant_id)

        # Step 1: Get knowledge base id
        knowledge_base_ids = core.get_user_indices()
        if not knowledge_base_ids:
            return {
                "indices": [],
                "count": 0,
            }

        # Step 2: Get detailed information for all knowledge bases
        details, knowledge_base_names = core.get_indices_detail(
            knowledge_base_ids)

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
        created_records = await _create_datamate_knowledge_records(
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
