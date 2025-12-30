"""
Service layer for DataMate knowledge base integration.
Handles API calls to DataMate to fetch knowledge bases and their files.

This service layer uses the DataMate SDK client to interact with DataMate APIs.
"""
import json
import logging
from typing import Dict, List, Optional, Any
import asyncio

from consts.const import DATAMATE_BASE_URL
from nexent.vector_database.datamate_core import DataMateCore

logger = logging.getLogger("datamate_service")


def _get_datamate_core() -> DataMateCore:
    """Get DataMate core instance."""
    return DataMateCore(base_url=DATAMATE_BASE_URL)


async def fetch_datamate_knowledge_bases() -> List[Dict[str, Any]]:
    """
    Fetch list of knowledge bases from DataMate API.

    Returns:
        List of knowledge base dictionaries with their IDs and metadata.
    """
    try:
        core = _get_datamate_core()
        # Run synchronous SDK call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        knowledge_bases = await loop.run_in_executor(
            None,
            core.get_knowledge_bases
        )
        return knowledge_bases
    except Exception as e:
        logger.error(f"Error fetching DataMate knowledge bases: {str(e)}")
        raise RuntimeError(f"Failed to fetch DataMate knowledge bases: {str(e)}")


async def fetch_datamate_knowledge_base_files(knowledge_base_id: str) -> List[Dict[str, Any]]:
    """
    Fetch file list for a specific DataMate knowledge base.

    Args:
        knowledge_base_id: The ID of the knowledge base.

    Returns:
        List of file dictionaries with name, status, size, upload_date, etc.
    """
    try:
        core = _get_datamate_core()
        # Run synchronous SDK call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            core.get_index_chunks,
            knowledge_base_id
        )
        return result["chunks"]
    except Exception as e:
        logger.error(f"Error fetching files for knowledge base {knowledge_base_id}: {str(e)}")
        raise RuntimeError(f"Failed to fetch files for knowledge base {knowledge_base_id}: {str(e)}")


async def sync_datamate_knowledge_bases() -> Dict[str, Any]:
    """
    Sync all DataMate knowledge bases and their files.

    Returns:
        Dictionary containing knowledge bases list in the same format as list_indices.
    """
    try:
        core = _get_datamate_core()

        # Step 1: Get knowledge base list using SDK
        knowledge_bases = core.client.list_knowledge_bases()

        # Extract knowledge base IDs
        knowledge_base_ids = []
        for kb in knowledge_bases:
            kb_id = kb.get("id")
            chunk_count = kb.get("chunkCount")
            if kb_id and chunk_count:
                knowledge_base_ids.append(str(kb_id))

        if not knowledge_base_ids:
            return {
                "indices": [],
                "count": 0,
            }

        # Step 2: Get detailed information for all knowledge bases
        # Run synchronous SDK call in executor to avoid blocking
        # loop = asyncio.get_event_loop()
        # details, knowledge_base_names = await loop.run_in_executor(
        #     None,
        #     core.get_indices_detail,
        #     knowledge_base_ids
        # )
        details, knowledge_base_names = core.get_indices_detail(knowledge_base_ids)

        response = {
            "indices": knowledge_base_names,
            "count": len(knowledge_base_names),
        }

        # Add indices_info for consistency with list_indices method
        indices_info = []
        for i, kb_id in enumerate(knowledge_base_ids):
            if kb_id in details:
                kb_detail = details[kb_id]
                knowledge_base_name = knowledge_base_names[i] if i < len(knowledge_base_names) else kb_id
                indices_info.append({
                    "name": kb_id,  # Internal index name (used as ID)
                    "display_name": knowledge_base_name,  # User-facing knowledge base name
                    "stats": kb_detail,
                })
        response["indices_info"] = indices_info

        return response
    except Exception as e:
        logger.error(f"Error syncing DataMate knowledge bases: {str(e)}")
        return {
            "indices": [],
            "count": 0,
        }

