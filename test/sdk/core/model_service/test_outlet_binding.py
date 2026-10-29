# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""ModelID selects one tenant-scoped snapshot without network or shared run state."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.model_service.service import ModelService


@pytest.fixture
def saved_profile(openai_profile):
    data = openai_profile.model_dump()
    data["outlet_id"] = 42
    data["connection"]["credential_ref"]["model_id"] = 42
    return openai_profile.__class__.model_validate(data)


def test_selection_reads_once_detaches_snapshot_and_does_not_resolve_credentials(saved_profile):
    reader = Mock(return_value=saved_profile)
    sender = Mock(side_effect=AssertionError("Selection must not send HTTP or resolve credentials"))
    service = ModelService(sender, outlet_reader=reader)
    context = SimpleNamespace(tenant_id=saved_profile.identity.tenant_id)
    selected = service.bind_outlet(42, context)
    reader.assert_called_once_with(42, context)
    sender.assert_not_called()
    assert selected == saved_profile and selected is not saved_profile
    saved_profile.provenance.provider_metadata["later"] = "updated"
    assert "later" not in selected.provenance.provider_metadata


@pytest.mark.parametrize("model_id", [True, None, 0, -1, 2**31, "42"])
def test_invalid_ids_fail_before_reader_or_sender(model_id):
    reader, sender = Mock(), Mock()
    service = ModelService(sender, outlet_reader=reader)
    with pytest.raises(ValueError, match="MODEL_OUTLET_SELECTION_INVALID"):
        service.bind_outlet(model_id, SimpleNamespace(tenant_id="tenant"))
    reader.assert_not_called()
    sender.assert_not_called()


@pytest.mark.parametrize("tenant", [None, "", " "])
def test_missing_tenant_does_not_use_global_default(tenant):
    reader = Mock()
    with pytest.raises(ValueError, match="SELECTION_INVALID"):
        ModelService(Mock(), outlet_reader=reader).bind_outlet(42, SimpleNamespace(tenant_id=tenant))
    reader.assert_not_called()


@pytest.mark.parametrize("wrong", ["tenant", "id"])
def test_other_tenant_or_outlet_cannot_be_bound(saved_profile, wrong):
    context = SimpleNamespace(tenant_id="other" if wrong == "tenant" else saved_profile.identity.tenant_id)
    sender = Mock()
    with pytest.raises(ValueError, match="SNAPSHOT_MISMATCH"):
        ModelService(sender, outlet_reader=lambda *_: saved_profile).bind_outlet(43 if wrong == "id" else 42, context)
    sender.assert_not_called()


def test_missing_reader_missing_row_and_reader_error_are_explicit_and_safe():
    context = SimpleNamespace(tenant_id="tenant")
    with pytest.raises(ValueError, match="READER_UNCONFIGURED"):
        ModelService(Mock()).bind_outlet(42, context)
    with pytest.raises(ValueError, match="NOT_FOUND"):
        ModelService(Mock(), outlet_reader=lambda *_: None).bind_outlet(42, context)
    reader = Mock(side_effect=RuntimeError("sensitive database detail"))
    with pytest.raises(ValueError, match="RESOLUTION_FAILED") as caught:
        ModelService(Mock(), outlet_reader=reader).bind_outlet(42, context)
    assert "sensitive" not in str(caught.value) and caught.value.__suppress_context__
    with pytest.raises(ValueError, match="SNAPSHOT_INVALID"):
        ModelService(Mock(), outlet_reader=lambda *_: {}).bind_outlet(42, context)


def test_async_reader_requires_backend_preparation():
    async def reader(*_):
        return None
    with pytest.raises(TypeError, match="synchronous"):
        ModelService(Mock(), outlet_reader=reader)


def test_one_service_does_not_overwrite_another_runs_selection(saved_profile):
    data = saved_profile.model_dump()
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 43
    data["identity"]["tenant_id"] = "other"
    other = saved_profile.__class__.model_validate(data)
    rows = {42: saved_profile, 43: other}
    service = ModelService(Mock(), outlet_reader=lambda model_id, _ctx: rows[model_id])
    first = service.bind_outlet(42, SimpleNamespace(tenant_id="tenant"))
    second = service.bind_outlet(43, SimpleNamespace(tenant_id="other"))
    assert first.outlet_id == 42 and first.identity.tenant_id == "tenant"
    assert second.outlet_id == 43 and second.identity.tenant_id == "other"
