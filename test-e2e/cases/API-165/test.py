"""D2 HTTP contracts for tags, external memory, legacy controls and model catalog."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest

from shared.http import assert_status, client


STAGE = pytest.mark.stage("D2")


def _is_masked_secret(value: object) -> bool:
    """Accept the current provider contract without requiring the plaintext secret."""
    if value is None or value == "***":
        return True
    return isinstance(value, str) and re.fullmatch(r".{3}\*{3}.{4}", value) is not None


@STAGE
@pytest.mark.case_id("API-165")
@pytest.mark.asyncio
async def test_tag_library_list_filter_and_tenant_scope(tenant_a_admin, tenant_b_admin) -> None:
    async with client("config", token=tenant_a_admin.access_token) as api:
        libraries = await api.get("/tag-libraries")
    assert_status(libraries, 200)
    rows = libraries.json()
    assert isinstance(rows, list) and rows
    bucket_id = int(rows[0]["bucket_id"])

    async with client("config", token=tenant_a_admin.access_token) as api:
        definitions = await api.get(f"/tag-libraries/{bucket_id}/definitions")
        echo = await api.post(
            "/tag-libraries/assignments/agent/filter",
            json={"resource_ids": ["1", "2"], "predicates": []},
        )
    assert_status(definitions, 200)
    assert_status(echo, 200)
    body = echo.json()
    # The filter endpoint returns matched resources as ``matched_resource_ids``
    # (the field was renamed from the early ``resource_ids`` echo contract).
    # With empty predicates every requested resource matches, in order.
    matched = body.get("matched_resource_ids", body.get("resource_ids"))
    assert matched == ["1", "2"]

    async with client("config", token=tenant_b_admin.access_token) as api:
        other = await api.get("/tag-libraries")
    assert_status(other, 200)
    # The library listing is tenant-scoped and does not echo tenant_id; prove
    # isolation by comparing bucket identity across the two tenants.
    tenant_a_bucket_ids = {row["bucket_id"] for row in rows}
    tenant_b_bucket_ids = {row["bucket_id"] for row in other.json()}
    if tenant_a_admin.tenant_id != tenant_b_admin.tenant_id:
        assert not (tenant_a_bucket_ids & tenant_b_bucket_ids), (
            "tenant B must not observe tenant A tag buckets"
        )






