# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Runtime outlet restoration boundaries without database or provider I/O."""

from unittest.mock import Mock

import pytest
from management.services.model.runtime_snapshot import restore_runtime_model_snapshot


def test_unmigrated_record_remains_legacy():
    assert restore_runtime_model_snapshot({"model_id": 1}, "tenant") is None


def test_wrong_tenant_fails_before_decoding(mocker):
    decoder = mocker.patch("nexent.core.model_service.profiles.outlet_storage.decode_resolved_model_profile")
    with pytest.raises(ValueError, match="MODEL_OUTLET_TENANT_MISMATCH"):
        restore_runtime_model_snapshot({"profile_schema_version": 1, "tenant_id": "other"}, "tenant")
    decoder.assert_not_called()


def test_saved_record_uses_canonical_codec(mocker):
    profile = Mock()
    decoder = mocker.patch("nexent.core.model_service.profiles.outlet_storage.decode_resolved_model_profile",
                           return_value=profile)
    record = {"profile_schema_version": 1, "tenant_id": "tenant"}
    assert restore_runtime_model_snapshot(record, "tenant") is profile
    assert decoder.call_args.args == (record,)
    assert "registered_references" in decoder.call_args.kwargs


def test_corrupt_saved_record_does_not_fall_back(mocker):
    mocker.patch("nexent.core.model_service.profiles.outlet_storage.decode_resolved_model_profile",
                 side_effect=ValueError("PROFILE_STORAGE_INVALID"))
    with pytest.raises(ValueError, match="PROFILE_STORAGE_INVALID"):
        restore_runtime_model_snapshot({"profile_schema_version": 1, "tenant_id": "tenant"}, "tenant")


def test_canonical_columns_supersede_stale_transitional_snapshot(mocker):
    profile = Mock()
    decoder = mocker.patch("nexent.core.model_service.profiles.outlet_storage.decode_resolved_model_profile",
                           return_value=profile)
    record = {"profile_schema_version": 1, "tenant_id": "tenant", "model_id": 7,
              "runtime_outlet_snapshot": {"version": 1, "source_fingerprint": "stale", "row": {}}}
    assert restore_runtime_model_snapshot(record, "tenant") is profile
    assert decoder.call_args.args == (record,)


@pytest.mark.parametrize("strict", [True, False])
def test_invalid_canonical_columns_never_restore_a_transitional_profile(mocker, strict):
    decoder = mocker.patch("nexent.core.model_service.profiles.outlet_storage.decode_resolved_model_profile",
                           side_effect=ValueError("PROFILE_STORAGE_INVALID"))
    record = {"profile_schema_version": 1, "tenant_id": "tenant",
              "runtime_outlet_snapshot": {"version": 1, "row": {"model_id": 7}}}
    if strict:
        with pytest.raises(ValueError, match="PROFILE_STORAGE_INVALID"):
            restore_runtime_model_snapshot(record, "tenant", strict=strict)
    else:
        assert restore_runtime_model_snapshot(record, "tenant", strict=strict) is None
    assert decoder.call_count == 1 and decoder.call_args.args == (record,)
