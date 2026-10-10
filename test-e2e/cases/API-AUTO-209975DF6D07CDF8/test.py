from __future__ import annotations

import pytest

from shared.http import assert_status, client
from shared.resource_ids import absent_numeric_id


_BASE = "/tag-libraries"


@pytest.mark.asyncio
@pytest.mark.stage("D2")
@pytest.mark.case_id("API-AUTO-209975DF6D07CDF8")
async def test_api_auto_209975df6d07cdf8(tenant_a_user):
    token = tenant_a_user.access_token

    async with client("config", token=token) as api:
        # filter: document resource_type must use batch-status endpoint
        response = await api.post(
            f"{_BASE}/assignments/knowledge_document/filter",
            json={"resource_ids": ["doc-1"]},
        )
        assert_status(response, 400)

        # filter: unknown resource_type is rejected
        response = await api.post(
            f"{_BASE}/assignments/not_a_resource_type/filter",
            json={"resource_ids": ["r1"]},
        )
        assert_status(response, 400)

        # filter: empty resource_ids violates request schema
        response = await api.post(
            f"{_BASE}/assignments/agent/filter",
            json={"resource_ids": []},
        )
        assert_status(response, 422)

        # filter: predicate definition_id must be positive
        response = await api.post(
            f"{_BASE}/assignments/agent/filter",
            json={
                "resource_ids": ["r1"],
                "predicates": [{"definition_id": 0, "value_ids": [1]}],
            },
        )
        assert_status(response, 422)

        # filter: empty predicates echo the authorized id set unchanged (dedup)
        response = await api.post(
            f"{_BASE}/assignments/agent/filter",
            json={"resource_ids": ["id-b", "id-a", "id-b"]},
        )
        assert_status(response, 200)
        body = response.json()
        assert body["resource_type"] == "agent"
        assert body["matched_resource_ids"] == ["id-b", "id-a"]

        # filter: predicates only narrow the authorized set (never widen)
        response = await api.post(
            f"{_BASE}/assignments/agent/filter",
            json={
                "resource_ids": ["id-a", "id-b"],
                "predicates": [{"definition_id": 2**30, "value_ids": [1]}],
            },
        )
        assert_status(response, 200)
        body = response.json()
        assert set(body["matched_resource_ids"]) <= {"id-a", "id-b"}
        assert body["matched_resource_ids"] == []

        # batch-status: provider is required
        response = await api.post(
            f"{_BASE}/documents/batch-status",
            json={"document_ids": ["d1"]},
        )
        assert_status(response, 400)

        # batch-status: knowledge_base_id is required
        response = await api.post(
            f"{_BASE}/documents/batch-status",
            params={"provider": "local"},
            json={"document_ids": ["d1"]},
        )
        assert_status(response, 400)

        # batch-status: empty document_ids violates request schema
        response = await api.post(
            f"{_BASE}/documents/batch-status",
            params={"provider": "local", "knowledge_base_id": "kb-1"},
            json={"document_ids": []},
        )
        assert_status(response, 422)

        # batch-status: more than 200 document ids violates request schema
        response = await api.post(
            f"{_BASE}/documents/batch-status",
            params={"provider": "local", "knowledge_base_id": "kb-1"},
            json={"document_ids": [f"doc-{i}" for i in range(201)]},
        )
        assert_status(response, 422)

        # batch-status: unknown knowledge base is fail-closed 404
        response = await api.post(
            f"{_BASE}/documents/batch-status",
            params={"provider": "local", "knowledge_base_id": "no-such-kb-run-id"},
            json={"document_ids": ["d1"]},
        )
        assert_status(response, 404)

        # flat-tags: unknown resource is fail-closed 404 (no cross-tenant leak)
        response = await api.get(
            f"{_BASE}/assignments/agent/{absent_numeric_id(__name__)}/compatibility/flat-tags",
        )
        assert_status(response, 404)
