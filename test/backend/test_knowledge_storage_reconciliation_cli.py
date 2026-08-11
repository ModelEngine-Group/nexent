"""Tests for the thin knowledge storage reconciliation CLI."""

import json
import sys
import types
from unittest.mock import MagicMock

import pytest

client_module = types.ModuleType("database.client")
client_module.as_dict = MagicMock(name="as_dict")
client_module.get_db_session = MagicMock(name="get_db_session")
client_module.minio_client = MagicMock(name="minio_client")
previous_client_module = sys.modules.get("database.client")
sys.modules["database.client"] = client_module

import knowledge_storage_reconciliation as cli

if previous_client_module is None:
    sys.modules.pop("database.client", None)
else:
    sys.modules["database.client"] = previous_client_module


@pytest.mark.parametrize(
    ("operation", "apply", "errors", "expected_exit"),
    [
        ("backfill", True, 0, 0),
        ("reconcile", False, 1, 1),
    ],
)
def test_main_runs_requested_operation_and_prints_report(
    operation, apply, errors, expected_exit, monkeypatch, capsys
):
    get_core = MagicMock(return_value=MagicMock(name="vdb_core"))
    vectordatabase_module = types.ModuleType("services.vectordatabase_service")
    vectordatabase_module.get_vector_db_core = get_core
    monkeypatch.setitem(
        sys.modules, "services.vectordatabase_service", vectordatabase_module
    )

    report = {"operation": operation, "summary": {"errors": errors}}
    service = MagicMock()
    getattr(service, operation).return_value = report
    service_factory = MagicMock(return_value=service)
    monkeypatch.setattr(cli, "KnowledgeStorageReconciliationService", service_factory)

    argv = [operation, "--tenant-id", "tenant-1"]
    if apply:
        argv.append("--apply")
    exit_code = cli.main(argv)

    assert exit_code == expected_exit
    getattr(service, operation).assert_called_once_with(apply=apply)
    service_factory.assert_called_once_with(
        tenant_id="tenant-1",
        vdb_core=get_core.return_value,
        updated_by="storage-reconciliation-cli",
    )
    assert json.loads(capsys.readouterr().out) == report


def test_parser_rejects_missing_tenant():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["backfill"])
