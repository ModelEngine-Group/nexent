# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual database-to-HTTP credential regression with UUID-owned inert models."""

import json
import os
from uuid import uuid4

import pytest

from shared.asset_registry import mark_asset_state, register_asset
from shared.auth import sign_in_credentials
from shared.case_evidence import write_case_evidence
from shared.http import client
from shared.postgres import postgres_scalar, postgres_sql

CASE_ID = "SEC-MODEL-HEADERS-D2-001"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D2")]


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.asyncio
async def test_persisted_model_lists_omit_header_credentials():
    suffix = uuid4().hex
    name = "pr4082-header-" + suffix
    headers = {"Authorization": "Bearer synthetic-auth-" + suffix,
               "X-API-Key": "synthetic-x-key-" + suffix}
    api_key = "synthetic-api-" + suffix
    identity = await sign_in_credentials(CASE_ID, {"username": os.environ["NEXENT_TEST_EMAIL"]},
                                         os.environ["NEXENT_TEST_PASSWORD"])
    token, tenant = identity.access_token, identity.tenant_id
    model_id = None
    receipts = []
    register_asset("owned_models", name, name, owner_case_id=CASE_ID,
                   cleanup={"service": "config", "method": "POST", "path": "/model/delete",
                            "params": {"display_name": name}, "allowed_statuses": [200, 404]})
    async with client("config", token=token, trust_env=False) as api:
        defaults = await api.get("/config/load_config")
        assert defaults.status_code == 200
        original_defaults = defaults.json()["config"].get("models")
        try:
            created = await api.post("/model/create", json={
                "model_name": name, "display_name": name, "model_type": "llm",
                "model_factory": "OpenAI-API-Compatible", "base_url": "https://fixture.invalid/v1",
                "api_key": api_key, "skip_default_backfill": True})
            assert created.status_code == 200, "Owned inert model creation failed"
            model_id = int(postgres_scalar("SELECT model_id FROM nexent.model_record_t WHERE display_name="
                           + literal(name) + " AND tenant_id=" + literal(tenant) + " AND delete_flag='N';"))
            guard = f"model_id={model_id} AND display_name={literal(name)} AND tenant_id={literal(tenant)}"
            postgres_sql("UPDATE nexent.model_record_t SET http_headers=" + literal(json.dumps(headers))
                         + "::jsonb WHERE " + guard + ";")
            stored = postgres_scalar("SELECT http_headers::text FROM nexent.model_record_t WHERE " + guard + ";")
            assert json.loads(stored) == headers
            paths = [
                ("GET", "/model/list", None), ("GET", "/model/llm_list", None),
                ("POST", "/model/provider/list", {"provider": "OpenAI-API-Compatible", "model_type": "llm"}),
                ("POST", "/model/manage/list", {"tenant_id": tenant, "page_size": 100}),
                ("POST", "/model/manage/provider/list", {"tenant_id": tenant,
                 "provider": "OpenAI-API-Compatible", "model_type": "llm"}),
            ]
            for method, path, body in paths:
                response = await api.request(method, path, **({"json": body} if body else {}))
                assert response.status_code == 200, f"List endpoint failed: {path}"
                data = response.json()["data"]
                rows = data["models"] if isinstance(data, dict) else data
                row = next(row for row in rows if row.get("display_name") == name)
                assert "http_headers" not in row and "api_key" not in row, f"Credential field exposed: {path}"
                assert all(secret not in response.text for secret in [api_key, *headers.values()]), path
                assert row["model_id"] == model_id and row["model_type"] == "llm"
                receipts.append({"path": path, "http_status": 200, "credential_fields_absent": True})
            assert postgres_scalar("SELECT http_headers::text FROM nexent.model_record_t WHERE " + guard + ";") == stored
        finally:
            removed = await api.post("/model/delete", params={"display_name": name})
            assert removed.status_code in {200, 404}, "Owned test model cleanup failed"
            if model_id is not None:
                assert postgres_scalar(f"SELECT delete_flag FROM nexent.model_record_t WHERE model_id={model_id};") == "Y"
            mark_asset_state("owned_models", name, "DELETED")
            defaults = await api.get("/config/load_config")
            assert defaults.status_code == 200
            assert defaults.json()["config"].get("models") == original_defaults
    write_case_evidence(CASE_ID, {"responses": receipts, "internal_headers_preserved": True,
                                 "cleanup": "owned model soft-deleted", "provider_calls": 0})
