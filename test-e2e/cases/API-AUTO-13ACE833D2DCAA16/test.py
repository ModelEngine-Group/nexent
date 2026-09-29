"""D2 API-IT for the marketplace agent-repository tag statistics endpoint.

Case: API-AUTO-13ACE833D2DCAA16
Contract: GET /repository/agent/tags
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio

from shared.asset_registry import register_asset
from shared.auth import TestIdentity
from shared.http import assert_status, client, redacted_response_body

CASE_ID = "API-AUTO-13ACE833D2DCAA16"


def _run_token() -> str:
    return uuid.uuid4().hex[:10]


def _find_int(payload: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload and payload[key] is not None:
                try:
                    return int(payload[key])
                except (TypeError, ValueError):
                    continue
        for value in payload.values():
            found = _find_int(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_int(value, keys)
            if found is not None:
                return found
    return None


def _register_agent(identity_id: str, agent_id: int) -> None:
    register_asset(
        "agent",
        f"{identity_id}:{agent_id}",
        agent_id,
        owner_case_id=CASE_ID,
        cleanup={
            "identity": identity_id,
            "service": "config",
            "method": "DELETE",
            "path": "/agent",
            "json": {"agent_id": agent_id},
            "allowed_statuses": [200, 404],
        },
    )


def _register_listing(identity_id: str, repository_id: int) -> None:
    register_asset(
        "agent_repository_listing",
        f"{identity_id}:{repository_id}",
        repository_id,
        owner_case_id=CASE_ID,
        cleanup={
            "identity": identity_id,
            "service": "config",
            "method": "PATCH",
            "path": f"/repository/agent/{repository_id}/status",
            "json": {"status": "not_shared"},
            "allowed_statuses": [200, 400, 404],
        },
    )


async def _create_agent(identity: TestIdentity, name: str) -> int:
    async with client("config", token=identity.access_token) as api:
        response = await api.post(
            "/agent/update",
            json={
                "name": name,
                "display_name": name,
                "description": "API-IT tag stats fixture",
                "business_description": "Repository tag statistics fixture",
                "max_steps": 5,
                "provide_run_summary": False,
                "version_no": 0,
            },
        )
    assert_status(response, 200)
    agent_id = _find_int(response.json(), ("agent_id", "id"))
    assert agent_id is not None, redacted_response_body(response)
    return agent_id


async def _publish_version(identity: TestIdentity, agent_id: int) -> int:
    async with client("config", token=identity.access_token) as api:
        response = await api.post(
            f"/agent/{agent_id}/publish",
            json={"version_name": "v1"},
        )
    assert_status(response, 200)
    version_no = _find_int(response.json(), ("version_no", "versionNo"))
    if version_no is None:
        async with client("config", token=identity.access_token) as api:
            current = await api.get(f"/agent/{agent_id}/current_version")
        assert_status(current, 200)
        version_no = _find_int(current.json(), ("version_no", "versionNo"))
    assert version_no is not None and version_no > 0, redacted_response_body(response)
    return version_no


async def _create_listing(identity: TestIdentity, agent_id: int, version_no: int, tags: list[str]) -> int:
    async with client("config", token=identity.access_token) as api:
        response = await api.post(
            f"/repository/agent/{agent_id}/versions/{version_no}",
            json={"icon": "robot", "tags": tags, "content": "API-IT tag stats fixture"},
        )
    assert_status(response, 200)
    repository_id = _find_int(response.json(), ("agent_repository_id", "id"))
    assert repository_id is not None, redacted_response_body(response)
    return repository_id


async def _set_listing_status(identity: TestIdentity, repository_id: int, status: str) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.patch(
            f"/repository/agent/{repository_id}/status",
            json={"status": status},
        )
    assert_status(response, 200)


async def _provision_listing(identity: TestIdentity, name: str, tags: list[str], target_status: str) -> int:
    agent_id = await _create_agent(identity, name)
    _register_agent(identity.id, agent_id)
    version_no = await _publish_version(identity, agent_id)
    repository_id = await _create_listing(identity, agent_id, version_no, tags)
    # Journal the owned listing before the status transition: a failure in the
    # transition must not leave an untracked repository entry behind.
    _register_listing(identity.id, repository_id)
    if target_status != "pending_review":
        await _set_listing_status(identity, repository_id, target_status)
    return repository_id


@pytest_asyncio.fixture(scope="session")
async def tag_stats_setup(tenant_a_admin: TestIdentity, tenant_b_admin: TestIdentity) -> dict[str, Any]:
    token = _run_token()

    await _provision_listing(tenant_a_admin, f"apiit-tag-{token}-a-shared-1", ["NLP", "nlp", "RAG"], "shared")
    await _provision_listing(tenant_a_admin, f"apiit-tag-{token}-a-shared-2", ["rag", "多模态"], "shared")
    await _provision_listing(tenant_a_admin, f"apiit-tag-{token}-a-shared-3", ["RAG"], "shared")
    await _provision_listing(tenant_a_admin, f"apiit-tag-{token}-a-pending", ["draft"], "pending_review")
    await _provision_listing(tenant_a_admin, f"apiit-tag-{token}-a-notshared", ["draft"], "not_shared")
    await _provision_listing(tenant_b_admin, f"apiit-tag-{token}-b-shared-1", ["tenantB-only"], "shared")

    return {
        "expected_a": {"NLP": 1, "nlp": 1, "RAG": 2, "rag": 1, "多模态": 1},
        "expected_b": {"tenantB-only": 1},
    }


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
async def test_agent_repository_tag_stats(tag_stats_setup, tenant_a_admin, tenant_b_admin):
    expected_a = tag_stats_setup["expected_a"]
    expected_b = tag_stats_setup["expected_b"]

    async with client("config", token=tenant_a_admin.access_token) as api:
        response = await api.get("/repository/agent/tags")
    assert_status(response, 200)
    body = response.json()
    assert isinstance(body, dict) and set(body.keys()) == {"items"}, body

    items = body["items"]
    assert isinstance(items, list), items

    for item in items:
        assert isinstance(item, dict) and set(item.keys()) == {"tag", "count"}, item
        assert isinstance(item["tag"], str) and item["tag"], item
        assert isinstance(item["count"], int) and item["count"] >= 1, item

    tags_order = [item["tag"] for item in items]
    counts = {item["tag"]: item["count"] for item in items}

    assert counts == expected_a, counts
    assert tags_order == sorted(tags_order, key=lambda tag: tag.lower()), tags_order
    assert "draft" not in counts, counts
    assert "tenantB-only" not in counts, counts

    async with client("config", token=tenant_b_admin.access_token) as api:
        tenant_b_response = await api.get("/repository/agent/tags")
    assert_status(tenant_b_response, 200)
    tenant_b_items = tenant_b_response.json().get("items") or []
    tenant_b_counts = {item["tag"]: item["count"] for item in tenant_b_items}
    assert tenant_b_counts == expected_b, tenant_b_counts
    assert not (set(tenant_b_counts) & set(expected_a)), tenant_b_counts
    assert "tenantB-only" in tenant_b_counts, tenant_b_counts

    async with client("config") as anon:
        missing_auth = await anon.get("/repository/agent/tags")
    assert missing_auth.status_code == 401, redacted_response_body(missing_auth)
    assert missing_auth.json().get("detail") or missing_auth.json().get("message"), missing_auth.text

    async with client("config", token="not-a-real-api-key") as invalid:
        invalid_auth = await invalid.get("/repository/agent/tags")
    assert invalid_auth.status_code == 401, redacted_response_body(invalid_auth)
    assert invalid_auth.json().get("detail") or invalid_auth.json().get("message"), invalid_auth.text
