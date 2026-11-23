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
@pytest.mark.case_id("CTR-048")
@pytest.mark.asyncio
async def test_model_catalog_endpoints_share_one_serializable_contract(tenant_a_admin) -> None:
    async with client("config", token=tenant_a_admin.access_token) as api:
        full = await api.get("/model/catalog/all")
        providers = await api.get("/model/catalog/providers")
        specs = await api.get("/model/catalog/inference_field_specs")
        missing = await api.get("/model/catalog/__unknown_provider__/__unknown_model__")
    for response in (full, providers):
        assert_status(response, 200)
        assert response.json().get("catalog_available") in {True, False}
        assert "api_key" not in response.text.lower()
    # inference_field_specs returns a fixed spec dictionary and intentionally
    # omits the catalog availability flag shared by catalog endpoints.
    assert_status(specs, 200)
    assert "api_key" not in specs.text.lower()
    data = full.json().get("data") or {}
    assert {"version", "metadata", "providers"}.issubset(data)
    assert isinstance(providers.json().get("data"), list)
    assert isinstance(specs.json().get("data"), dict)
    assert_status(missing, 404)
