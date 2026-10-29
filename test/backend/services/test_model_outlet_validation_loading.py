# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Connection checks load only an intact tenant-owned outlet snapshot."""

import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references
from management.services.model.profiles import _load_validation_outlet

from test.backend.services.test_model_outlet_update_service import saved_profile  # noqa: F401


@pytest.fixture
def record_lookup(monkeypatch):
    database = ModuleType('management.db.model.repository')
    database.get_model_by_model_id = Mock()
    monkeypatch.setitem(sys.modules, database.__name__, database)
    return database.get_model_by_model_id


def test_validation_load_retains_credential_for_sender_only(record_lookup, saved_profile):
    record = encode_resolved_model_profile(saved_profile, registered_references=model_service_references())
    record['api_key'] = 'controlled-key'
    record_lookup.return_value = record
    profile, key, headers = _load_validation_outlet(42, 'tenant')
    assert profile == saved_profile and key == 'controlled-key'
    assert headers == {}
    assert 'controlled-key' not in profile.model_dump_json()
    record_lookup.assert_called_once_with(42, tenant_id='tenant')


def test_missing_outlet_fails_before_decoding(record_lookup):
    record_lookup.return_value = None
    with pytest.raises(LookupError):
        _load_validation_outlet(42, 'tenant')


@pytest.mark.parametrize('outlet_id,tenant', [(43, 'tenant'), (42, 'foreign')])
def test_wrong_identity_is_rejected_even_if_storage_returns_a_row(record_lookup, saved_profile, outlet_id, tenant):
    record_lookup.return_value = encode_resolved_model_profile(saved_profile, registered_references=model_service_references())
    with pytest.raises(ModelOutletValidationError):
        _load_validation_outlet(outlet_id, tenant)


def test_corrupt_snapshot_reports_storage_error_without_credential(record_lookup):
    record_lookup.return_value = {'profile_schema_version': 1, 'api_key': 'controlled-key'}
    with pytest.raises(ModelOutletValidationError) as error:
        _load_validation_outlet(42, 'tenant')
    assert error.value.category == 'PROFILE_STORAGE_INVALID'
    assert 'controlled-key' not in str(error.value)
