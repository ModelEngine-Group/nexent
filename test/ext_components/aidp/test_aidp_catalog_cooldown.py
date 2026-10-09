"""Regression coverage for transient catalog failures and recovery."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from ext_components.aidp.services import aidp_access_service as service
from ext_components.aidp.services import aidp_service


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch, mocker):
    service.invalidate_aidp_catalog_cache()
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(service, "time", SimpleNamespace(
        monotonic=lambda: clock.now, perf_counter=lambda: clock.now,
    ))
    permissions = mocker.patch.object(
        service.aidp_permission_service, "intersect_accessible_kbs_with_name_map",
        return_value=([], {}),
    )
    yield clock, permissions
    service.invalidate_aidp_catalog_cache()


def resolve(**kwargs):
    return service.resolve_current_aidp_access(
        "https://aidp.example", "key", "user", "tenant", **kwargs,
    )


@pytest.mark.parametrize("code", [
    ErrorCode.AIDP_CONNECTION_ERROR, ErrorCode.AIDP_RATE_LIMIT, ErrorCode.AIDP_SERVICE_ERROR,
])
def test_transient_failure_is_reused_without_sharing_mutable_error_details(code, mocker, isolated_catalog):
    _, permissions = isolated_catalog
    original = AppException(code, "Unavailable", {"attempts": [503]})
    fetch = mocker.patch.object(service, "fetch_all_aidp_knowledge_bases_impl", side_effect=original)
    with pytest.raises(AppException) as first:
        resolve()
    first.value.details["attempts"].append(500)
    errors = []
    for _ in range(2):
        with pytest.raises(AppException) as caught:
            resolve()
        errors.append(caught.value)
        assert caught.value.error_code == code
        assert caught.value.message == "Unavailable"
        assert caught.value.details == {"attempts": [503]}
    assert errors[0] is not errors[1]
    assert next(iter(service._catalog_failures.values()))[1].__traceback__ is None
    fetch.assert_called_once()
    permissions.assert_not_called()


def test_cooldown_expires_at_five_seconds_and_recomputes_permissions(mocker, isolated_catalog):
    clock, permissions = isolated_catalog
    fetch = mocker.patch.object(service, "fetch_all_aidp_knowledge_bases_impl", side_effect=[
        AppException(ErrorCode.AIDP_SERVICE_ERROR, "Unavailable"), {"value": [{"kds_id": "1"}]},
    ])
    with pytest.raises(AppException):
        resolve()
    clock.now += 4.999
    with pytest.raises(AppException):
        resolve()
    assert fetch.call_count == 1
    clock.now = 105.0
    assert resolve().remote_ids == {"1"}
    service.resolve_current_aidp_access("https://aidp.example", "key", "another-user", "tenant")
    assert fetch.call_count == 2
    assert [call.kwargs["user_id"] for call in permissions.call_args_list] == ["user", "another-user"]
    assert not service._catalog_failures


@pytest.mark.parametrize("keyword", [None, "alpha"])
@pytest.mark.parametrize("refresh", ["force", "scoped", "global"])
def test_explicit_refresh_bypasses_failure_for_full_and_search_catalogs(keyword, refresh, mocker):
    fetch = mocker.patch.object(service, "fetch_all_aidp_knowledge_bases_impl", side_effect=[
        AppException(ErrorCode.AIDP_SERVICE_ERROR, "Unavailable"), {"value": [{"kds_id": "1"}]},
    ])
    with pytest.raises(AppException):
        resolve(keyword=keyword)
    if refresh == "scoped":
        service.invalidate_aidp_catalog_cache("https://aidp.example", "key")
    elif refresh == "global":
        service.invalidate_aidp_catalog_cache()
    assert resolve(keyword=keyword, force_refresh=refresh == "force").remote_ids == {"1"}
    assert fetch.call_count == 2


@pytest.mark.parametrize("error", [
    AppException(ErrorCode.AIDP_AUTH_ERROR, "Denied"),
    AppException(ErrorCode.AIDP_RESPONSE_ERROR, "Invalid response"),
    ValueError("Invalid configuration"),
])
def test_nontransient_errors_are_not_suppressed(error, mocker):
    fetch = mocker.patch.object(service, "fetch_all_aidp_knowledge_bases_impl", side_effect=error)
    for _ in range(2):
        with pytest.raises(type(error)):
            resolve()
    assert fetch.call_count == 2
    assert not service._catalog_failures


def test_failed_forced_refresh_never_authorizes_with_stale_catalog(mocker, isolated_catalog):
    _, permissions = isolated_catalog
    fetch = mocker.patch.object(service, "fetch_all_aidp_knowledge_bases_impl", side_effect=[
        {"value": [{"kds_id": "1"}]}, AppException(ErrorCode.AIDP_SERVICE_ERROR, "Unavailable"),
    ])
    assert resolve().remote_ids == {"1"}
    for force in (True, False):
        with pytest.raises(AppException):
            resolve(force_refresh=force)
    assert fetch.call_count == 2
    permissions.assert_called_once()
    assert not service._catalog_cache


def test_failure_is_scoped_to_remote_tenant_url_and_keyword(mocker):
    fetch = mocker.patch.object(service, "fetch_all_aidp_knowledge_bases_impl", side_effect=[
        AppException(ErrorCode.AIDP_SERVICE_ERROR, "Unavailable"),
        {"value": []}, {"value": []}, {"value": []},
    ])
    with pytest.raises(AppException):
        resolve()
    resolve(aidp_tenant_id="other-remote-tenant")
    resolve(keyword="alpha")
    service.resolve_current_aidp_access("https://other.example", "key", "user", "tenant")
    with pytest.raises(AppException):
        resolve()
    assert fetch.call_count == 4


def test_real_count_retry_sequence_runs_once_during_cooldown(mocker, monkeypatch, isolated_catalog):
    clock, permissions = isolated_catalog
    request = httpx.Request("POST", "https://aidp.example/KnowledgeBases/0/Count")
    client = MagicMock()
    client.post.side_effect = [
        httpx.Response(503, request=request), httpx.Response(503, request=request),
        httpx.Response(503, request=request), httpx.Response(200, json={"count": 0}, request=request),
    ]
    mocker.patch.object(aidp_service.http_client_manager, "get_sync_client", return_value=client)
    sleep = MagicMock()
    monkeypatch.setattr(aidp_service, "time", SimpleNamespace(perf_counter=lambda: clock.now, sleep=sleep))
    for _ in range(3):
        with pytest.raises(AppException) as caught:
            resolve()
        assert caught.value.error_code == ErrorCode.AIDP_SERVICE_ERROR
    assert client.post.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [0.5, 1.0]
    assert all(call.args[0].endswith("/0/Count") for call in client.post.call_args_list)
    permissions.assert_not_called()
    clock.now += 5.0
    assert resolve().remote_ids == set()
    assert resolve().remote_ids == set()
    assert client.post.call_count == 4
    assert permissions.call_count == 2
    client.get.assert_not_called()
