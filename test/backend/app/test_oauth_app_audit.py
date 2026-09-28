"""Audit entries recorded on successful OAuth login, signup and unlink operations.

Feature-scoped companion to ``test_oauth_app.py``. The real audit service is
loaded from its file and the app module is rebuilt against local stubs, so these
assertions observe real audit lines no matter which test file ran first; the
previous ``sys.modules`` entries are restored afterwards.
"""

import importlib.util
import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.path.insert(0, backend_dir)

_STUBBED_MODULES = ["services.audit_service", "services.oauth_service",
                    "database.oauth_account_db", "apps.oauth_app"]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _STUBBED_MODULES}

# A previously collected legacy file may replace the `services` package with a
# MagicMock, which would shadow the audit service; loading it from its file keeps
# the audit lines real.
_audit_spec = importlib.util.spec_from_file_location(
    "services.audit_service", os.path.join(backend_dir, "services", "audit_service.py")
)
_audit_service = importlib.util.module_from_spec(_audit_spec)
_audit_spec.loader.exec_module(_audit_service)
sys.modules["services.audit_service"] = _audit_service

# Import-time isolation: the provider client and the account store reach
# external services that these audit assertions do not exercise.
sys.modules["services.oauth_service"] = MagicMock()
sys.modules["database.oauth_account_db"] = MagicMock()
# Rebuild the app module against the collaborators above instead of reusing one
# a legacy file already imported against its own stubs.
sys.modules.pop("apps.oauth_app", None)

from http import HTTPStatus  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import apps.oauth_app as oauth_app_module  # noqa: E402

for _name, _module in _ORIGINAL_MODULES.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module

app = FastAPI()
app.include_router(oauth_app_module.router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


@pytest.fixture
def oauth_callback_stub(mocker):
    """Stub the provider exchange and account plumbing for a successful callback."""
    mocker.patch.object(oauth_app_module, "get_all_provider_definitions",
                        return_value={"github": MagicMock()})
    mocker.patch.object(oauth_app_module, "parse_state",
                        return_value={"provider": "github", "link_user_id": ""})
    mocker.patch.object(oauth_app_module, "exchange_code_for_provider_token",
                        return_value={"access_token": "ghu_token"})
    mocker.patch.object(oauth_app_module, "get_provider_user_info",
                        return_value={"id": "12345", "email": "octocat@github.com",
                                      "username": "octocat"})
    mocker.patch.object(oauth_app_module, "ensure_user_tenant_exists")
    mocker.patch.object(oauth_app_module, "create_or_update_oauth_account")
    mocker.patch.object(oauth_app_module, "generate_session_jwt", return_value="eyJ.mock.token")
    mocker.patch.object(oauth_app_module, "calculate_expires_at", return_value=1735689600)


def test_oauth_login_success_records_audit_entry(caplog, mocker, oauth_callback_stub):
    """A completed OAuth login records the signed-in user and provider details."""
    mocker.patch.object(oauth_app_module, "get_oauth_account_by_provider",
                        return_value={"provider": "github", "provider_user_id": "12345",
                                      "user_id": "user-uuid-123"})

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.get("/user/oauth/callback?provider=github&code=valid_code")

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "[SEC_AUDIT]" in messages[0]
    assert "event=oauth_login" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=user-uuid-123" in messages[0]
    assert "email=octocat@github.com" in messages[0]
    assert '"provider":"github"' in messages[0]
    assert '"linked":false' in messages[0]
    assert "ghu_token" not in messages[0]


def test_oauth_signup_success_records_audit_entry(caplog, mocker):
    """Completing a pending OAuth signup records the created user, never the password."""
    mocker.patch.object(
        oauth_app_module,
        "complete_pending_oauth_account",
        new_callable=AsyncMock,
        return_value={
            "user": {"id": "new-user", "email": "new@example.com", "role": "USER"},
            "session": {"access_token": "jwt", "refresh_token": "",
                        "expires_at": 1735689600, "expires_in_seconds": 3600},
        },
    )

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/user/oauth/complete",
            headers={"X-OAuth-Pending-Token": "pending.jwt"},
            json={"email": "new@example.com", "password": "secret1", "invite_code": "ABC123"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=oauth_signup" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=new-user" in messages[0]
    assert "email=new@example.com" in messages[0]
    assert "secret1" not in messages[0]


def test_oauth_unlink_success_records_audit_entry(caplog, mocker):
    """Unlinking an OAuth account records the operator and the provider."""
    mocker.patch.object(oauth_app_module, "get_current_user_id",
                        return_value=("user-1", "t-1"))
    mocker.patch.object(oauth_app_module, "unlink_account", return_value=True)

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.delete(
            "/user/oauth/accounts/github",
            headers={"Authorization": "Bearer valid_token"},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=oauth_unlink" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=user-1" in messages[0]
    assert "tenant_id=t-1" in messages[0]
    assert '"provider":"github"' in messages[0]
