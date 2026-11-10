# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bounded outlet provisioning retains dry-run isolation and tenant selection."""

from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from management.db.model import runtime_profile
from management.db.models import ModelRecord


@pytest.mark.parametrize("size", [0, -1, 1001, True, 1.5, "10"])
def test_invalid_batch_size_is_rejected_before_opening_a_transaction(mocker, size):
    session = mocker.patch.object(runtime_profile, "get_db_session")
    with pytest.raises(ValueError, match="MODEL_OUTLET_BATCH_SIZE_INVALID"):
        runtime_profile.provision_runtime_outlet_batch(Mock(), batch_size=size)
    session.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("kind", ["ready", "migrated", "failed"])
def test_batch_status_and_updates_preserve_snapshot_ownership(mocker, dry_run, kind):
    previous = {"revision": 1}
    snapshot = previous if kind == "ready" else ({"revision": 2} if kind == "migrated" else {"error": "SAFE_CODE"})
    record = ModelRecord(model_id=7, tenant_id="tenant", model_type="llm", runtime_outlet_snapshot=previous)
    session = Mock()
    session.scalars.return_value.all.return_value = [record]
    mocker.patch.object(runtime_profile, "get_db_session", return_value=nullcontext(session))
    builder = Mock(return_value=snapshot)
    result = runtime_profile.provision_runtime_outlet_batch(builder, after_model_id=3, batch_size=10,
        tenant_id="tenant", dry_run=dry_run)
    assert result == [{"model_id": 7, "status": kind}]
    submitted = builder.call_args.args[0]
    assert submitted["model_id"] == 7 and submitted["tenant_id"] == "tenant"
    assert submitted["runtime_outlet_snapshot"] == previous and record.runtime_outlet_snapshot == previous
    statement = session.scalars.call_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "FOR UPDATE" in sql and "LIMIT 10" in sql and "model_id > 3" in sql
    assert "tenant_id = 'tenant'" in sql and "delete_flag = 'N'" in sql
    assert "model_type IN ('llm', 'chat')" in sql and "ORDER BY" in sql
    if dry_run or kind == "ready":
        session.execute.assert_not_called()
    else:
        params = session.execute.call_args.args[0].compile().params
        assert params["runtime_outlet_snapshot"] == snapshot
        assert params["updated_by"] == "runtime-outlet-migration"
    session.commit.assert_not_called()


def test_empty_batch_without_tenant_does_not_invoke_builder(mocker):
    session, builder = Mock(), Mock()
    session.scalars.return_value.all.return_value = []
    mocker.patch.object(runtime_profile, "get_db_session", return_value=nullcontext(session))
    assert runtime_profile.provision_runtime_outlet_batch(builder, batch_size=1000) == []
    builder.assert_not_called()
    session.execute.assert_not_called()
