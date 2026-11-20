# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from management.maintenance import legacy_broker
from nexent.storage.errors import ScopeDenied, Unavailable


@pytest.fixture
def broker(monkeypatch):
    port = Mock()
    port.get.return_value = {
        "id": "queues", "queues": {"parse_q": 0}, "shared_default_queue": 0,
        "shared_unacked": 0, "shared_unacked_index": 0,
    }

    files = Mock()
    files.get.return_value = {"id": "files", "count": 0}

    @contextmanager
    def ports(actor, *, context):
        assert actor.user_id == "operator" and actor.tenant_id == "tenant"
        yield object(), port, files

    identity_roles = Mock(return_value={"SU"})
    monkeypatch.setattr(legacy_broker, "legacy_broker_ports", ports)
    monkeypatch.setattr(legacy_broker, "quota_identity_roles", identity_roles)
    return port, files, identity_roles


def args(output):
    return ["--tenant-id", "tenant", "--user-id", "operator", "--output", str(output), "--legacy-quiesced"]


@pytest.mark.parametrize("counts,pending", [({}, False), ({"queues": {"parse_q": 1}}, True), ({"shared_unacked_index": 1}, True)])
def test_only_completed_operator_attestation_writes_receipt(broker, tmp_path, counts, pending):
    port, files, roles = broker
    port.get.return_value.update(counts)
    output = tmp_path / "receipt.json"

    assert legacy_broker.main(args(output)) == (3 if pending else 0)

    result = json.loads(output.read_text())
    assert result["broker_empty"] is not pending
    assert result["migration_ready"] is False and result["legacy_quiesced_attested"] is True
    assert roles.call_count == 2
    port.get.assert_called_once()
    files.get.assert_called_once()


@pytest.mark.parametrize("revoked", [False, True])
def test_denial_or_revocation_has_no_receipt(broker, tmp_path, revoked):
    port, files, roles = broker
    roles.side_effect = [{"SU"}, ScopeDenied()] if revoked else [{"ADMIN"}]
    output = tmp_path / "receipt.json"
    assert legacy_broker.main(args(output)) == 1 and not output.exists()
    assert port.get.call_count == files.get.call_count == int(revoked)


def test_worker_confirmation_is_required(broker, tmp_path):
    port, files, _ = broker
    with pytest.raises(SystemExit):
        legacy_broker.main(args(tmp_path / "receipt.json")[:-1])
    port.get.assert_not_called()
    files.get.assert_not_called()


def test_empty_redis_with_legacy_file_work_is_blocked(broker, tmp_path):
    _, files, _ = broker
    files.get.return_value["count"] = 2
    output = tmp_path / "receipt.json"

    assert legacy_broker.main(args(output)) == 3
    result = json.loads(output.read_text())
    assert result["broker_empty"] is True
    assert result["legacy_inflight_files"] == 2
    assert result["migration_ready"] is False


@pytest.mark.parametrize("error", [None, Unavailable()])
def test_missing_pg_evidence_does_not_write_a_receipt(broker, tmp_path, error):
    _, files, _ = broker
    files.get.return_value = None
    files.get.side_effect = error
    output = tmp_path / "receipt.json"

    assert legacy_broker.main(args(output)) == 1
    assert not output.exists()


def test_optional_result_inventory_is_aggregate_and_keeps_queue_semantics(broker, tmp_path):
    port, _, roles = broker
    port.get.side_effect = [
        port.get.return_value,
        {"id": "result_metadata", "with_index_hint": 7, "without_index_hint": 2, "invalid_task_key": 1,
         "without_index_hint_pg_references": {"one_file": 1, "multiple_files": 0, "no_file": 1,
                                               "private_id": "must not appear"},
         "private_result": "must not appear"},
    ]
    output = tmp_path / "receipt.json"

    assert legacy_broker.main(args(output) + ["--include-result-inventory"]) == 0

    result = json.loads(output.read_text())
    assert result["broker_empty"] is True and result["migration_ready"] is False
    assert result["result_metadata"] == {"with_index_hint": 7, "without_index_hint": 2, "invalid_task_key": 1}
    assert result["result_pg_references"] == {"one_file": 1, "multiple_files": 0, "no_file": 1}
    assert [call.args[1] for call in port.get.call_args_list] == ["queues", "result_metadata"]
    assert roles.call_count == 2


@pytest.mark.parametrize("revoked", [False, True])
def test_result_inventory_failure_or_late_revocation_prevents_receipt(broker, tmp_path, revoked):
    port, _, roles = broker
    port.get.side_effect = [
        port.get.return_value,
        {"with_index_hint": 0, "without_index_hint": 0, "invalid_task_key": 0,
         "without_index_hint_pg_references": {"no_file": 0, "one_file": 0, "multiple_files": 0}}
        if revoked else Unavailable(),
    ]
    if revoked:
        roles.side_effect = [{"SU"}, {"ADMIN"}]
    output = tmp_path / "receipt.json"

    assert legacy_broker.main(args(output) + ["--include-result-inventory"]) == 1
    assert not output.exists()
