# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify list body selection against the running Skill HTTP API."""

import os
import re

import pytest

from shared.factories.skill import _create_skill, _delete_skill
from shared.http import assert_status, client


@pytest.mark.stage("D2")
@pytest.mark.case_id("SKILL-LIST-CONTENT-D2-001")
@pytest.mark.asyncio
async def test_skill_list_content_selection_and_cleanup(tenant_a_user):
    batch_source = (
        os.environ.get("TEST_BATCH")
        or os.path.basename(os.environ.get("RESULT_DIR", ""))
        or "manual"
    )
    batch = re.sub(r"[^a-z0-9-]", "-", batch_source.lower())[:36]
    created = await _create_skill(tenant_a_user, prefix=f"list-content-{batch}")
    skill_id, name = int(created["skill_id"]), str(created["name"])
    try:
        async with client("config", token=tenant_a_user.access_token) as api:
            before = await api.get(f"/skills/{skill_id}")
            assert_status(before, 200)
            body = before.json()["content"]
            assert isinstance(body, str) and body.strip()
            responses = []
            for params in [{}, {"include_content": "false"}, {"include_content": "true"}]:
                response = await api.get("/skills", params=params)
                assert_status(response, 200)
                rows = response.json()["skills"]
                assert isinstance(rows, list)
                matches = [row for row in rows if int(row["skill_id"]) == skill_id]
                assert len(matches) == 1
                responses.append(matches[0])
            default, omitted, full = responses
            assert "content" not in default
            assert "content" not in omitted
            assert default == omitted == {key: value for key, value in full.items() if key != "content"}
            assert full["content"] == body
            invalid = await api.get("/skills", params={"include_content": "invalid"})
            assert_status(invalid, 422)
            after = await api.get(f"/skills/{skill_id}")
            assert_status(after, 200)
            assert after.json() == before.json()
    finally:
        await _delete_skill(tenant_a_user, name)
        async with client("config", token=tenant_a_user.access_token) as api:
            absent = await api.get(f"/skills/{skill_id}")
            assert_status(absent, 404)
