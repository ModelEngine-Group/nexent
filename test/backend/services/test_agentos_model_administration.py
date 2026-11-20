# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from contracts.model_administration import ModelProbe, ModelUpdate
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import model_records
from runtime.agentos import model_administration


@pytest.mark.parametrize("field", ["tenant_id", "delete_flag", "created_by", "update_time"])
def test_model_patch_rejects_ownership_fields(field):
    with pytest.raises(ValidationError):
        ModelUpdate(display_name="model", patch={field: "forged"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "model_type", "expected_key"),
    [
        ("https://provider.example/v1", "llm", "stored-key"),
        ("https://different.example/v1", "llm", ""),
        ("https://provider.example/v1", "embedding", ""),
    ],
)
async def test_probe_keeps_stored_key_on_the_tenant_model_endpoint(monkeypatch, url, model_type, expected_key):
    lookup = Mock(return_value={
        "api_key": "stored-key",
        "base_url": "https://provider.example/v1/",
        "model_type": "llm",
        "model_factory": "openai",
    })
    probe = AsyncMock(return_value={"connectivity": True})
    monkeypatch.setattr(model_administration, "get_model_by_model_id", lookup)
    monkeypatch.setattr(model_administration.health, "verify_model_config_connectivity", probe)

    payload = ModelProbe(model_name="model", model_type=model_type, base_url=url, probe_model_id=17)
    assert await model_administration._probe(payload, ServicePrincipal("actor", "tenant")) == {"connectivity": True}
    lookup.assert_called_once_with(17, tenant_id="tenant")
    assert probe.await_args.args[0]["api_key"] == expected_key
    assert "probe_model_id" not in probe.await_args.args[0]


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_model_mutations_scope_sql_to_active_tenant(monkeypatch, operation):
    session = Mock()
    session.execute.return_value.rowcount = 0
    monkeypatch.setattr(model_records, "get_db_session", lambda: nullcontext(session))
    monkeypatch.setattr(model_records.db_client, "clean_string_values", lambda data: data.copy())

    if operation == "update":
        changed = model_records.update_model_record(17, {"display_name": "renamed"}, "actor", "tenant")
    else:
        changed = model_records.delete_model_record(17, "actor", "tenant")
    assert changed is False
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    update, where = str(statement).split(" WHERE ", maxsplit=1)
    assert "tenant_id" not in update
    assert "tenant_id" in where and "delete_flag" in where and "model_id" in where
    assert statement.params["tenant_id_1"] == "tenant"


def test_tenant_model_cleanup_uses_one_scoped_update(monkeypatch):
    session = Mock()
    session.execute.return_value.rowcount = 2
    monkeypatch.setattr(model_records, "get_db_session", lambda: nullcontext(session))

    assert model_records.deactivate_tenant_models("actor", "tenant") == 2
    session.execute.assert_called_once()
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    values, where = str(statement).split(" WHERE ", maxsplit=1)
    assert "tenant_id" not in values
    assert "tenant_id" in where and "delete_flag" in where
    assert statement.params["tenant_id_1"] == "tenant"
    assert statement.params["updated_by"] == "actor"
