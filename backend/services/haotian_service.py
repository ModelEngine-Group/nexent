"""
Haotian Service Layer

Implements proxy fetching and normalization for Haotian external knowledge base APIs.
"""

import logging
from typing import Any, Dict, List, Tuple

import httpx

logger = logging.getLogger("haotian_service")

_DEFAULT_KNOWLEDGE_BASE_ID = "a8d68fbf-bd6e-5461-a9d1-cf1bb3522e38"


def _normalize_list_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize Haotian list payload to:
    {
      "knowledge_sets": [
        {
          "name": str,
          "knowledge_bases": [{"dify_dataset_id": str, "name": str}]
        }
      ]
    }

    When dify_dataset_id is "null", it is replaced with the default ID.
    """
    knowledge_sets = raw.get("knowledge_sets", [])
    if not isinstance(knowledge_sets, list):
        knowledge_sets = []

    normalized_sets: List[Dict[str, Any]] = []
    for ks in knowledge_sets:
        if not isinstance(ks, dict):
            continue
        set_name = str(ks.get("name", "") or "").strip()
        if not set_name:
            continue

        bases = ks.get("knowledge_bases", [])
        if not isinstance(bases, list):
            bases = []

        normalized_bases: List[Dict[str, Any]] = []
        for kb in bases:
            if not isinstance(kb, dict):
                continue
            dataset_id = str(kb.get("dify_dataset_id", "") or "").strip()
            kb_name = str(kb.get("name", "") or "").strip()
            if not kb_name:
                continue
            if dataset_id == "null" or not dataset_id:
                dataset_id = _DEFAULT_KNOWLEDGE_BASE_ID
            normalized_bases.append(
                {"dify_dataset_id": dataset_id, "name": kb_name}
            )

        if normalized_bases:
            normalized_sets.append(
                {"name": set_name, "knowledge_bases": normalized_bases}
            )

    return {"knowledge_sets": normalized_sets}


async def fetch_haotian_knowledge_sets_impl(
    list_url: str,
    external_authorization: str,
    timeout_s: float = 20.0,
) -> Dict[str, Any]:
    """
    Fetch knowledge sets from the external Haotian list API.
    """
    if not list_url or not isinstance(list_url, str):
        raise ValueError("list_url is required and must be a non-empty string")
    if not external_authorization or not isinstance(external_authorization, str):
        raise ValueError(
            "authorization is required and must be a non-empty string"
        )

    headers = {"Authorization": external_authorization}
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
        resp = await client.get(list_url, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Haotian list API HTTP error: {resp.status_code}"
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Haotian list API returned non-object JSON")
        return _normalize_list_payload(data)


async def test_haotian_connection_impl(
    list_url: str,
    external_authorization: str,
    timeout_s: float = 10.0,
) -> Tuple[bool, str]:
    """
    Test Haotian connection by calling list_url once.
    """
    try:
        await fetch_haotian_knowledge_sets_impl(
            list_url=list_url,
            external_authorization=external_authorization,
            timeout_s=timeout_s,
        )
        return (True, "")
    except Exception as e:
        return (False, str(e))

