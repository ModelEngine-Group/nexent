"""D2 skill and skill-marketplace API contracts."""

from __future__ import annotations
from shared.factories.skill import _skill_payload, _create_skill, _delete_skill
from shared.resource_ids import absent_numeric_id

import uuid

import pytest

from shared.asset_registry import register_asset
from shared.factories.ownership import register_owned_http
from shared.http import assert_status, client


STAGE = pytest.mark.stage("D2")










@STAGE
@pytest.mark.case_id("API-077")
@pytest.mark.asyncio
async def test_official_zip_install_json_create_and_upload_lifecycle(tenant_a_admin, tenant_a_user) -> None:
    skill = await _create_skill(tenant_a_admin)
    name = skill["name"]
    try:
        async with client("config", token=tenant_a_admin.access_token) as api:
            fetched = await api.get(f"/skills/{name}")
            assert_status(fetched, 200)
            updated = await api.put(f"/skills/{name}", json={"description": "updated by D2"})
            assert_status(updated, 200)
            assert updated.json()["description"] == "updated by D2"
    finally:
        await _delete_skill(tenant_a_admin, name)

    # Candidate V5 assertion 5: repeated installs refresh same-name OFFICIAL
    # skills from the bundled ZIP while same-name CUSTOM skills are preserved.
    async with client("config", token=tenant_a_user.access_token) as api:
        official = await api.get("/skills/official")
        assert_status(official, 200)
    installable = sorted(
        str(item["name"]) for item in official.json()["skills"]
        if item.get("status") == "installable" and item.get("name")
    )
    if len(installable) < 2:
        raise AssertionError(
            "official ZIP assets require at least two installable skills; "
            f"official list exposed {installable}"
        )
    refresh_name, shadow_name = installable[0], installable[1]

    async with client("config", token=tenant_a_user.access_token) as api:
        installed = await api.post("/skills/install", json={"skill_names": [refresh_name]})
        assert_status(installed, 200)
        register_owned_http(tenant_a_user, 'owned_skills', refresh_name, f'/skills/{refresh_name}')
        assert refresh_name in installed.json()["installed"]
        fetched = await api.get(f"/skills/{refresh_name}")
        assert_status(fetched, 200)
        assert fetched.json().get("source") == "official"
        original_description = fetched.json().get("description")
        tampered = await api.put(
            f"/skills/{refresh_name}", json={"description": "tampered by API-077"}
        )
        assert_status(tampered, 200)
        reinstalled = await api.post("/skills/install", json={"skill_names": [refresh_name]})
        assert_status(reinstalled, 200)
        refreshed = await api.get(f"/skills/{refresh_name}")
        assert_status(refreshed, 200)
        assert refreshed.json().get("source") == "official"
        assert refreshed.json().get("description") == original_description, (
            "reinstalling the official ZIP must refresh the bundled content"
        )
        assert refreshed.json().get("description") != "tampered by API-077"
    await _delete_skill(tenant_a_user, refresh_name)

    shadow = await _create_skill(tenant_a_user, exact_name=shadow_name)
    assert shadow["name"] == shadow_name
    try:
        async with client("config", token=tenant_a_user.access_token) as api:
            installed = await api.post("/skills/install", json={"skill_names": [shadow_name]})
            assert_status(installed, 200)
            preserved = await api.get(f"/skills/{shadow_name}")
            assert_status(preserved, 200)
            assert preserved.json().get("source") == "custom"
            assert preserved.json().get("description") == "automated contract skill", (
                "a same-name custom skill must keep its own content after install"
            )
    finally:
        await _delete_skill(tenant_a_user, shadow_name)

    # SKILL.md upload path with a unique name, read back through the API.
    upload_name = f"upload-{uuid.uuid4().hex[:10]}"
    markdown = (
        f"---\nname: {upload_name}\ndescription: uploaded via SKILL.md\n---\n"
        f"# {upload_name}\n"
    )
    async with client("config", token=tenant_a_user.access_token) as api:
        uploaded = await api.post(
            "/skills/upload",
            files={"file": ("SKILL.md", markdown.encode("utf-8"), "text/markdown")},
        )
        assert_status(uploaded, 201)
        uploaded_name = str(uploaded.json().get('name') or '')
        if uploaded_name:
            register_owned_http(tenant_a_user, 'owned_skills', uploaded_name, f'/skills/{uploaded_name}')
        assert uploaded.json()["name"] == upload_name
        read_back = await api.get(f"/skills/{upload_name}")
        assert_status(read_back, 200)
        assert read_back.json()["description"] == "uploaded via SKILL.md"
    await _delete_skill(tenant_a_user, upload_name)

    # Create a separate batch-scoped Skill after the delete assertion. Later
    # D3 binding/runtime cases reuse it; the daily cleanup removes it.
    shared = await _create_skill(tenant_a_user, "daily-shared")
    shared_name = str(shared["name"])
    shared_id = int(shared["skill_id"])
    cleanup = {
        "service": "config", "identity": "tenant_a_user", "method": "DELETE",
        "path": f"/skills/{shared_name}", "allowed_statuses": [200, 400, 404],
    }
    register_asset(
        "skills", "configurable_id", shared_id,
        owner_case_id="API-077", cleanup=cleanup,
    )
    register_asset("skills", "configurable_name", shared_name, owner_case_id="API-077")












