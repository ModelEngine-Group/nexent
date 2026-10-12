from __future__ import annotations

from unittest.mock import Mock

import pytest

from services import repository_import_precheck as precheck
from services.repository_import_precheck import _check_model_available
from management.services.model.resolver import is_model_available
from consts.model import ModelConnectStatusEnum

CASE_ID = "UT-BE-AUTO-51975A59626F5BE8"
TENANT_ID = "tenant-with-run-id"
REASON_MODEL_UNAVAILABLE = "model_unavailable"


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D1")
def test_check_model_available_migration(monkeypatch):
    assert precheck.is_model_available is is_model_available

    id_mock = Mock()
    info_mock = Mock()
    monkeypatch.setattr(precheck, "get_model_id_by_display_name", id_mock)
    monkeypatch.setattr(precheck, "get_model_by_model_id", info_mock)
    for blank in (None, "", "   ", "\t\n"):
        assert _check_model_available(blank, TENANT_ID) == (True, None)
    id_mock.assert_not_called()
    info_mock.assert_not_called()

    for missing_id in (None, 0):
        id_mock = Mock(return_value=missing_id)
        info_mock = Mock()
        monkeypatch.setattr(precheck, "get_model_id_by_display_name", id_mock)
        monkeypatch.setattr(precheck, "get_model_by_model_id", info_mock)
        assert _check_model_available("  some-model  ", TENANT_ID) == (False, REASON_MODEL_UNAVAILABLE)
        id_mock.assert_called_once_with("some-model", TENANT_ID)
        info_mock.assert_not_called()

    available_info = {"model_id": 1, "connect_status": ModelConnectStatusEnum.AVAILABLE.value}
    monkeypatch.setattr(precheck, "get_model_id_by_display_name", Mock(return_value=1))
    monkeypatch.setattr(precheck, "get_model_by_model_id", Mock(return_value=available_info))
    assert _check_model_available("available-model", TENANT_ID) == (True, None)
    assert is_model_available(available_info) is True

    for status in (
        ModelConnectStatusEnum.UNAVAILABLE.value,
        ModelConnectStatusEnum.NOT_DETECTED.value,
        ModelConnectStatusEnum.DETECTING.value,
        "failed",
    ):
        unavailable_info = {"model_id": 2, "connect_status": status}
        monkeypatch.setattr(precheck, "get_model_id_by_display_name", Mock(return_value=2))
        monkeypatch.setattr(precheck, "get_model_by_model_id", Mock(return_value=unavailable_info))
        assert _check_model_available("unavailable-model", TENANT_ID) == (False, REASON_MODEL_UNAVAILABLE)
        assert is_model_available(unavailable_info) is False

    for info in (None, {}):
        monkeypatch.setattr(precheck, "get_model_id_by_display_name", Mock(return_value=3))
        monkeypatch.setattr(precheck, "get_model_by_model_id", Mock(return_value=info))
        assert _check_model_available("missing-record-model", TENANT_ID) == (False, REASON_MODEL_UNAVAILABLE)
        assert is_model_available(info) is False

    for info in (
        {"model_id": 4},
        {"model_id": 5, "connect_status": None},
        {"model_id": 6, "connect_status": ""},
    ):
        monkeypatch.setattr(precheck, "get_model_id_by_display_name", Mock(return_value=4))
        monkeypatch.setattr(precheck, "get_model_by_model_id", Mock(return_value=info))
        assert _check_model_available("no-status-model", TENANT_ID) == (False, REASON_MODEL_UNAVAILABLE)
        assert is_model_available(info) is False
