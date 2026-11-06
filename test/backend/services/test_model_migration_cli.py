# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The administrative migration CLI defaults to preview and reports failures."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize('arguments,dry_run,failed', [([], True, 0), (['--apply', '--batch-size', '3'], False, 1)])
def test_cli_requires_explicit_apply_and_propagates_failure_status(monkeypatch, capsys, arguments, dry_run, failed):
    service = ModuleType('management.services.model.outlet_migration')
    service.migrate_legacy_outlets = Mock(return_value={'migrated': 2, 'failed': failed})
    monkeypatch.setitem(__import__('sys').modules, service.__name__, service)
    monkeypatch.setattr('sys.argv', ['migrate_model_outlets', *arguments])
    path = Path(__file__).resolve().parents[3] / 'backend/scripts/migrate_model_outlets.py'
    spec = importlib.util.spec_from_file_location('_migration_cli_test', path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main() == int(bool(failed))
    service.migrate_legacy_outlets.assert_called_once_with(dry_run=dry_run, batch_size=3 if arguments else 100)
    assert json.loads(capsys.readouterr().out) == {'migrated': 2, 'failed': failed}
