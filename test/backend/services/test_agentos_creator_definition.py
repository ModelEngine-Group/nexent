# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed creators use a platform-scoped definition while Runtime stays independent."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from contracts.agentos import AgentVersionReference
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.rdb import system_agent_records
from runtime.agentos import creator_definition


@pytest.mark.parametrize("mode", ["nl2agent", "nl2skill"])
def test_runtime_loads_the_signed_creator_reference(monkeypatch, mode):
    row = {"agent_id": 21, "version_no": 0, "max_steps": 8}
    load = Mock(return_value=row)
    monkeypatch.setattr(creator_definition, "read_system_creator", load)
    payload = SimpleNamespace(mode=mode, system_agent=AgentVersionReference(agent_id=21, version_no=0))
    assert creator_definition.load_creator_definition(payload) == row
    load.assert_called_once_with(21, 0, mode + "_main")
    load.return_value = None
    with pytest.raises(HTTPException) as error:
        creator_definition.load_creator_definition(payload)
    assert error.value.status_code == 409


def test_old_signed_creator_without_definition_keeps_ephemeral_configuration(monkeypatch):
    load = Mock()
    monkeypatch.setattr(creator_definition, "read_system_creator", load)
    assert creator_definition.load_creator_definition(SimpleNamespace(system_agent=None)) is None
    load.assert_not_called()


def test_system_creator_query_cannot_read_a_tenant_or_deleted_definition(monkeypatch):
    session = Mock()
    row = {"agent_id": 21, "version_no": 0}
    session.execute.return_value.mappings.return_value.first.return_value = row
    monkeypatch.setattr(system_agent_records, "get_db_session", lambda: nullcontext(session))
    assert system_agent_records.read_system_creator(21, 0, "nl2agent_main") == row
    statement, values = session.execute.call_args.args
    assert values == {"agent_id": 21, "version_no": 0, "tenant_id": ASSET_OWNER_TENANT_ID,
                      "system_key": "nl2agent_main"}
    sql = str(statement)
    assert "agent_origin = 'SYSTEM'" in sql and "delete_flag = 'N'" in sql
    assert "enabled IS NOT FALSE" in sql
