"""D1 unit tests for ``get_provider_username`` in user_management_service.

The function under test is a pure helper that resolves the non-empty username
stored on a linked OAuth account (e.g. CAS). The database callback
``list_oauth_accounts_by_user_id`` is injected as a test double, so no
database or external OAuth/CAS service is required.
"""

import logging

import pytest

from services.user_management_service import get_provider_username

_CASE_ID = "UT-BE-AUTO-4CB026964D950965"

_LIST_ACCOUNTS_PATH = "services.user_management_service.list_oauth_accounts_by_user_id"


def _patch_accounts(monkeypatch, accounts):
    monkeypatch.setattr(_LIST_ACCOUNTS_PATH, lambda user_id: accounts)


@pytest.mark.stage("D1")
@pytest.mark.case_id(_CASE_ID)
def _check_returns_stripped_nonempty_username_for_matching_provider(monkeypatch):
    _patch_accounts(
        monkeypatch,
        [{"provider": "cas", "provider_username": "  Alice  "}],
    )
    result = get_provider_username("user-1", "cas")
    assert result == "Alice"


@pytest.mark.stage("D1")
def _check_skips_account_with_mismatched_provider(monkeypatch):
    _patch_accounts(
        monkeypatch,
        [{"provider": "google", "provider_username": "Alice"}],
    )
    result = get_provider_username("user-1", "cas")
    assert result is None


@pytest.mark.stage("D1")
@pytest.mark.parametrize("blank_username", [None, "", "   "])
def _check_returns_none_for_empty_or_blank_username(monkeypatch, blank_username):
    _patch_accounts(
        monkeypatch,
        [{"provider": "cas", "provider_username": blank_username}],
    )
    result = get_provider_username("user-1", "cas")
    assert result is None


@pytest.mark.stage("D1")
def _check_returns_none_and_logs_warning_on_db_error(monkeypatch, caplog):
    def _raise(user_id):
        raise RuntimeError("oauth account table unavailable")

    monkeypatch.setattr(_LIST_ACCOUNTS_PATH, _raise)

    with caplog.at_level(logging.WARNING):
        result = get_provider_username("user-1", "cas")

    assert result is None
    assert any(
        "Failed to load cas username for user user-1" in record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    )


@pytest.mark.stage("D1")
def _check_does_not_leak_non_username_account_fields(monkeypatch):
    account = {
        "provider": "cas",
        "provider_username": "Alice",
        "provider_user_id": "cas-subject-123",
        "provider_email": "alice@example.com",
        "access_token": "sk-secret-token",
    }
    _patch_accounts(monkeypatch, [account])
    result = get_provider_username("user-1", "cas")
    assert result == "Alice"
    assert result not in ("sk-secret-token", "cas-subject-123", "alice@example.com")


@pytest.mark.stage("D1")
@pytest.mark.case_id(_CASE_ID)
def test_get_provider_username_contract(monkeypatch, caplog):
    _check_returns_stripped_nonempty_username_for_matching_provider(monkeypatch)
    _check_skips_account_with_mismatched_provider(monkeypatch)
    for blank_username in (None, "", "   "):
        _check_returns_none_for_empty_or_blank_username(monkeypatch, blank_username)
    _check_returns_none_and_logs_warning_on_db_error(monkeypatch, caplog)
    _check_does_not_leak_non_username_account_fields(monkeypatch)
