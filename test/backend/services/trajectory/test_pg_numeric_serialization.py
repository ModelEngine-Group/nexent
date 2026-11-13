# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PG token aggregates keep integer JSON types in cached conversation records."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.db.trajectory.queries import ExecutionCatalog
from management.services.trajectory.access import Actor
from management.services.trajectory.cache import ByteCache
from management.services.trajectory.pg_collection import records
from management.services.trajectory.primitives import ReferenceStore


@pytest.mark.parametrize("view", ["conversation", "execution"])
@pytest.mark.parametrize(
    "tokens",
    [(3179, 1446, 4625), (None, 0, None), (9007199254740993, 0, 9007199254740993)],
)
def test_pg_token_numbers_survive_json_cache_response_and_frozen_paging(
    mocker, view, tokens
):
    run = "00000000-0000-0000-0000-000000000001"
    row = {
        "status": "success",
        "tenant_id": "t",
        "user_id": "owner",
        "user_name": "Owner",
        "conversation_id": 123,
        "conversation_title": "Trace",
        "trajectory_id": run,
        "agent_id": 7,
        "agent_version_no": 0,
        "models": ["model"],
        "started_at": datetime(2026, 11, 13, tzinfo=UTC),
        "finished_at": None,
        "duration_ms": 100.5,
        "runs": [{"id": run, "status": "success", "turn": 1, "matches": True}],
        "execution_count": 1,
        "matching_execution_count": 1,
    }
    for key, value in zip(("input", "output", "total"), tokens):
        row[key + "_tokens"] = value
        # PostgreSQL sum(bigint) returns numeric, decoded by psycopg2 as Decimal.
        row["cumulative_" + key + "_tokens"] = (
            Decimal(value) if value is not None else None
        )
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = [row]
    mocker.patch(
        "management.db.trajectory.queries._session",
        side_effect=lambda: nullcontext(session),
    )
    catalog = ExecutionCatalog()
    mocker.patch.object(catalog, "validate")
    mocker.patch.object(catalog, "statistics", return_value={"complete": False})
    authority = Mock()
    authority.actor_active.return_value = True
    authority.tenants.return_value = ["t"]
    authority.names.return_value = {}
    authority.agent_names.return_value = {}
    service = SimpleNamespace(
        execution_catalog=catalog,
        catalog=authority,
        max_candidates=100,
        queries=ByteCache(),
        references=ReferenceStore(),
    )
    actor = Actor("admin", "t", "ADMIN")
    first = records(service, actor, {}, view=view, sort_by="total_tokens", page_size=1)
    parsed = json.loads(json.dumps(first))
    usage = parsed["items"][0]["usage"]
    for key, expected in zip(("input", "output", "total"), tokens):
        assert usage[key] == expected
        assert usage[key] is None or type(usage[key]) is int
    assert usage["complete"] is all(value is not None for value in tokens)
    assert parsed["items"][0]["duration_ms"] == 100.5
    second = records(
        service,
        actor,
        {},
        view=view,
        query_id=first["query_id"],
        sort_by="total_tokens",
        page=2,
        page_size=1,
    )
    assert second["items"] == [] and second["total"] == 1
    assert session.execute.call_count == 1
