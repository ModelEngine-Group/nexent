"""Creator metadata remains local, batched and scoped to the current tenant."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def creator_module(monkeypatch):
    database = ModuleType("database.user_tenant_db")
    database.get_user_email_map = MagicMock(return_value={"u-1": "admin@example.test"})
    monkeypatch.setitem(sys.modules, "database.user_tenant_db", database)
    source = Path(__file__).parents[3] / "backend/ext_components/aidp/services/aidp_creator_service.py"
    spec = importlib.util.spec_from_file_location("isolated_creator_service", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_creator_lookup_is_batched_and_tenant_scoped(creator_module):
    result = creator_module.get_nexent_creator_names(["u-1", None, "u-1", "u-2"], "tenant-a")
    creator_module.get_user_email_map.assert_called_once_with(["u-1", "u-2"], tenant_id="tenant-a")
    assert result == {"u-1": "admin@example.test"}


def test_missing_owners_skip_database_query(creator_module):
    assert creator_module.get_nexent_creator_names([None, ""], "tenant-a") == {}
    creator_module.get_user_email_map.assert_not_called()


def test_lookup_failure_does_not_replace_owner_with_remote_or_current_user(creator_module):
    creator_module.get_user_email_map.side_effect = RuntimeError("database unavailable")
    assert creator_module.get_nexent_creator_names(["deleted-owner"], "tenant-a") == {}
