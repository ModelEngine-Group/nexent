"""
Service layer for DataMate knowledge base integration.
Handles API calls to DataMate to fetch knowledge bases and their files.

This service layer uses the DataMate SDK client to interact with DataMate APIs.
"""
import logging
from typing import Dict, List, Optional, Any
import asyncio

from consts.const import DATAMATE_BASE_URL
from nexent.datamate import DataMateClient

logger = logging.getLogger("datamate_service")


def _get_datamate_client() -> DataMateClient:
    """Get DataMate client instance."""
    return DataMateClient(base_url=DATAMATE_BASE_URL)


async def fetch_datamate_knowledge_bases() -> List[Dict[str, Any]]:
    """
    Fetch list of knowledge bases from DataMate API.
    
    Returns:
        List of knowledge base dictionaries with their IDs and metadata.
    """
    try:
        client = _get_datamate_client()
        # Run synchronous SDK call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        knowledge_bases = await loop.run_in_executor(
            None,
            client.list_knowledge_bases
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
        client = _get_datamate_client()
        # Run synchronous SDK call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None,
            client.get_knowledge_base_files,
            knowledge_base_id
        )
        return files
    except Exception as e:
        logger.error(f"Error fetching files for knowledge base {knowledge_base_id}: {str(e)}")
        raise RuntimeError(f"Failed to fetch files for knowledge base {knowledge_base_id}: {str(e)}")


async def sync_datamate_knowledge_bases() -> Dict[str, Any]:
    """
    Sync all DataMate knowledge bases and their files.
    
    Returns:
        Dictionary containing knowledge bases with their file lists.
    """
    try:
        client = _get_datamate_client()
        # Run synchronous SDK call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            client.sync_all_knowledge_bases
        )
        return result
    except Exception as e:
        logger.error(f"Error syncing DataMate knowledge bases: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "knowledge_bases": [],
            "total_count": 0,
        }

