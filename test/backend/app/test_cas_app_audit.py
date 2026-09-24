"""Audit entries recorded on successful CAS login and single logout operations.

Feature-scoped companion to ``test_cas_app.py``. The import-time stub is
restored and the app module is evicted afterwards, so collecting both files in
the same process keeps each file's own collaborators.
"""

import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))


class _CasAuthenticationError(Exception):
    """Stand-in for the service exception raised by the CAS client."""


CAS_LOGIN_RESULT = {
    "user": {"id": "user-1", "email": "u@example.com", "role": "USER"},
    "session": {"access_token": "jwt", "expires_at": 1779780000, "expires_in_seconds": 3600},
    "redirect_url": "/chat",
}
CAS_LOGOUT_RESULT = {"revoked": 1, "cas_user_id": "cas-user-1", "session_index": "ST-1"}

LOGOUT_REQUEST_XML = """
<samlp:LogoutRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
  xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
  <saml:NameID>cas-user-1</saml:NameID>
  <samlp:SessionIndex>ST-1</samlp:SessionIndex>
</samlp:LogoutRequest>
"""

# Import-time isolation: the CAS client talks to an external CAS server.
_STUBBED_MODULES = ["services.cas_service", "apps.cas_app"]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _STUBBED_MODULES}

cas_service_stub = MagicMock()
cas_service_stub.CAS_SERVER_URL = "https://cas.example.com"
cas_service_stub.CasAuthenticationError = _CasAuthenticationError
cas_service_stub.login_with_ticket = AsyncMock(return_value=CAS_LOGIN_RESULT)
cas_service_stub.revoke_from_logout_request = MagicMock(return_value=CAS_LOGOUT_RESULT)
sys.modules["services.cas_service"] = cas_service_stub
# Rebuild the app module against the stub above instead of reusing one a legacy
# file already imported against its own stubs.
sys.modules.pop("apps.cas_app", None)

from http import HTTPStatus  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.cas_app import router  # noqa: E402

for _name, _module in _ORIGINAL_MODULES.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module

app = FastAPI()
app.include_router(router)
client = TestClient(app)

AUDIT_LOGGER = "audit.security"


@pytest.fixture(autouse=True)
def _reset_cas_service_stub():
    """Give every test a fresh CAS service stub with the success results."""
    cas_service_stub.reset_mock()
    cas_service_stub.login_with_ticket.return_value = CAS_LOGIN_RESULT
    cas_service_stub.revoke_from_logout_request.return_value = CAS_LOGOUT_RESULT


def _audit_messages(caplog):
    """Return the audit lines captured for the current test."""
    return [record.getMessage() for record in caplog.records if record.name == AUDIT_LOGGER]


def test_cas_login_success_records_audit_entry(caplog):
    """A successful CAS login records the signed-in user and source info."""
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.get("/user/cas/callback?ticket=ST-1&redirect=/chat")

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "[SEC_AUDIT]" in messages[0]
    assert "event=cas_login" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=user-1" in messages[0]
    assert "email=u@example.com" in messages[0]


def test_cas_logout_records_revoked_session(caplog):
    """A CAS single logout records the endpoint and the revoked session subject."""
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        response = client.post(
            "/user/cas/logout_callback",
            data={"logoutRequest": LOGOUT_REQUEST_XML},
        )

    assert response.status_code == HTTPStatus.OK
    messages = _audit_messages(caplog)
    assert len(messages) == 1
    assert "event=cas_logout" in messages[0]
    assert "result=success" in messages[0]
    assert '"endpoint":"logout_callback"' in messages[0]
    assert '"revoked":1' in messages[0]
    assert '"cas_user_id":"cas-user-1"' in messages[0]
