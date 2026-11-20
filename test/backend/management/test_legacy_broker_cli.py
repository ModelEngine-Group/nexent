# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from management.maintenance import legacy_broker
from nexent.storage.errors import ScopeDenied


@pytest.fixture
def broker(monkeypatch):
    port = Mock()
    port.get.return_value = {
        "id": "queues", "queues": {"parse_q": 0}, "shared_default_queue": 0,
        "shared_unacked": 0, "shared_unacked_index": 0,
    }

    @contextmanager
    def ports(actor, *, context):
        assert actor.user_id == "operator" and actor.tenant_id == "tenant"
        yield object(), port

    identity_roles = Mock(return_value={"SU"})
    monkeypatch.setattr(legacy_broker, "legacy_broker_ports", ports)
    monkeypatch.setattr(legacy_broker, "quota_identity_roles", identity_roles)
    return port, identity_roles


def args(output):
    return ["--tenant-id", "tenant", "--user-id", "operator", "--output", str(output), "--legacy-quiesced"]


@pytest.mark.parametrize("counts,pending", [({}, False), ({"queues": {"parse_q": 1}}, True), ({"shared_unacked_index": 1}, True)])
def test_only_completed_operator_attestation_writes_receipt(broker, tmp_path, counts, pending):
    port, roles = broker
    port.get.return_value.update(counts)
    output = tmp_path / "receipt.json"

    assert legacy_broker.main(args(output)) == (3 if pending else 0)

    result = json.loads(output.read_text())
    assert result["broker_empty"] is not pending
    assert result["migration_ready"] is False and result["legacy_quiesced_attested"] is True
    assert roles.call_count == 2
    port.get.assert_called_once()


@pytest.mark.parametrize("revoked", [False, True])
def test_denial_or_revocation_has_no_receipt(broker, tmp_path, revoked):
    port, roles = broker
    roles.side_effect = [{"SU"}, ScopeDenied()] if revoked else [{"ADMIN"}]
    output = tmp_path / "receipt.json"
    assert legacy_broker.main(args(output)) == 1 and not output.exists()
    assert port.get.call_count == int(revoked)


def test_worker_confirmation_is_required(broker, tmp_path):
    port, _ = broker
    with pytest.raises(SystemExit):
        legacy_broker.main(args(tmp_path / "receipt.json")[:-1])
    port.get.assert_not_called()
