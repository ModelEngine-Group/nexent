# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Migration validation checks identity and expiry with isolated PG collaborators."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("fault", [None, "missing", "owner", "turn", "expiry"])
def test_backfill_verifies_identity_turn_and_expired_status(mocker, fault):
    from infrastructure.observability.trajectory_store import CaptureIdentity
    from ops.scripts import backfill_trajectory_summaries as script

    identity = CaptureIdentity("t", "u", "123", "7")
    store, repository, session = Mock(), Mock(), Mock()
    store.identities.return_value = iter([identity])
    store.manifest.return_value = {"runs": [{"trajectory_id": "id", "turn_no": 4}]}
    repository.placeholders.side_effect = [1000, 0]
    mocker.patch.object(script, "authorize_capture")
    projector = mocker.patch.object(script, "Projector").return_value
    projector.archive.available.return_value = "expired"
    row = SimpleNamespace(
        delete_flag="N",
        conversation_id=123,
        created_by="u",
        turn_no=4,
        status="expired",
    )
    if fault == "owner":
        row.created_by = "other"
    elif fault == "turn":
        row.turn_no = 2
    elif fault == "expiry":
        row.status = "success"
    session.get.return_value = None if fault == "missing" else row
    mocker.patch.object(script, "get_db_session", return_value=nullcontext(session))
    if fault:
        with pytest.raises(RuntimeError, match="verification failed"):
            script.backfill(store, repository)
    else:
        assert script.backfill(store, repository) == 1
    projector.sync.assert_called_once_with(identity)
    assert repository.placeholders.call_count == 2


def test_backfill_does_not_republish_a_former_tenant_archive(mocker):
    from ops.scripts import backfill_trajectory_summaries as script

    store, repository = Mock(), Mock()
    repository.placeholders.return_value = 0
    store.identities.return_value = iter(["orphan"])
    mocker.patch.object(script, "authorize_capture", side_effect=PermissionError)
    projector = mocker.patch.object(script, "Projector").return_value
    assert script.backfill(store, repository) == 0
    projector.sync.assert_not_called()
    store.manifest.assert_not_called()
