import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

test_dir = os.path.dirname(__file__)
backend_dir = os.path.abspath(os.path.join(test_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

_MODULES_TO_RESTORE = [
    "consts",
    "consts.const",
    "database.cas_session_db",
    "database.oauth_account_db",
    "database.user_tenant_db",
    "services.oauth_service",
    "services.skill_service",
    "services.tool_configuration_service",
    "utils.auth_utils",
]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _MODULES_TO_RESTORE}

consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.CAS_CA_BUNDLE = ""
consts_mock.const.CAS_CALLBACK_BASE_URL = "http://localhost:3000"
consts_mock.const.CAS_EMAIL_ATTRIBUTE = "mail"
consts_mock.const.CAS_ENABLED = True
consts_mock.const.CAS_LOGIN_MODE = "button"
consts_mock.const.CAS_LOGOUT_URL = ""
consts_mock.const.CAS_RENEW_BEFORE_SECONDS = 300
consts_mock.const.CAS_RENEW_TIMEOUT_SECONDS = 10
consts_mock.const.CAS_ROLE_ATTRIBUTE = "memberOf"
consts_mock.const.CAS_ROLE_MAP_JSON = '{"cn=admins":"ADMIN"}'
consts_mock.const.CAS_SERVER_URL = "https://cas.example.com/cas"
consts_mock.const.CAS_SESSION_MAX_AGE_SECONDS = 3600
consts_mock.const.CAS_SSL_VERIFY = True
consts_mock.const.CAS_SYNTHETIC_EMAIL_DOMAIN = "cas.local"
consts_mock.const.CAS_TENANT_ATTRIBUTE = "tenant"
consts_mock.const.CAS_USER_ATTRIBUTE = "uid"
consts_mock.const.CAS_VALIDATE_PATH = "/p3/serviceValidate"
consts_mock.const.DEFAULT_TENANT_ID = "tenant_id"
consts_mock.const.LOCAL_SESSION_MAX_AGE_SECONDS = 3600
sys.modules["consts"] = consts_mock
sys.modules["consts.const"] = consts_mock.const

sys.modules["database.cas_session_db"] = MagicMock()
sys.modules["database.oauth_account_db"] = MagicMock()
sys.modules["database.user_tenant_db"] = MagicMock()
sys.modules["services.oauth_service"] = MagicMock()
sys.modules["services.skill_service"] = MagicMock()
sys.modules["services.tool_configuration_service"] = MagicMock()
sys.modules["utils.auth_utils"] = MagicMock()

from services.cas_service import (  # noqa: E402
    CasAuthenticationError,
    build_login_url,
    build_logout_url,
    parse_logout_request,
    parse_service_validate_response,
)

for _name, _module in _ORIGINAL_MODULES.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module
sys.modules.pop("services.cas_service", None)


class TestCasServiceParsing(unittest.TestCase):
    def test_parse_success_response_with_attributes(self):
        xml = """
        <cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
          <cas:authenticationSuccess>
            <cas:user>fallback-user</cas:user>
            <cas:attributes>
              <cas:uid>cas-user-1</cas:uid>
              <cas:mail>User@Example.com</cas:mail>
              <cas:memberOf>cn=admins</cas:memberOf>
              <cas:tenant>tenant-a</cas:tenant>
              <cas:SessionIndex>ST-123</cas:SessionIndex>
              <cas:expiresAt>2026-05-26T10:00:00Z</cas:expiresAt>
            </cas:attributes>
          </cas:authenticationSuccess>
        </cas:serviceResponse>
        """

        principal = parse_service_validate_response(xml, fallback_session_index="ST-fallback")

        self.assertEqual(principal.cas_user_id, "cas-user-1")
        self.assertEqual(principal.email, "user@example.com")
        self.assertEqual(principal.role, "ADMIN")
        self.assertEqual(principal.tenant_id, "tenant-a")
        self.assertEqual(principal.session_index, "ST-123")
        self.assertIsInstance(principal.expires_at, datetime)

    def test_parse_failure_response_raises(self):
        xml = """
        <cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
          <cas:authenticationFailure code="INVALID_TICKET">bad ticket</cas:authenticationFailure>
        </cas:serviceResponse>
        """

        with self.assertRaises(CasAuthenticationError):
            parse_service_validate_response(xml)

    def test_parse_logout_request_supports_user_and_session_index(self):
        xml = """
        <samlp:LogoutRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
          xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
          <saml:NameID>cas-user-1</saml:NameID>
          <samlp:SessionIndex>ST-123</samlp:SessionIndex>
        </samlp:LogoutRequest>
        """

        result = parse_logout_request(xml)

        self.assertEqual(result["cas_user_id"], "cas-user-1")
        self.assertEqual(result["session_index"], "ST-123")

    def test_build_login_url_includes_service_redirect(self):
        url = build_login_url("/space")

        self.assertIn("https://cas.example.com/cas/login?", url)
        self.assertIn("service=http://localhost:3000/api/user/cas/callback?redirect=/space", url)

    def test_build_logout_url_returns_empty_when_logout_url_is_not_configured(self):
        url = build_logout_url()

        self.assertEqual(url, "")

    def test_build_logout_url_adds_login_service_to_configured_bare_logout_url(self):
        original = build_logout_url.__globals__["CAS_LOGOUT_URL"]
        build_logout_url.__globals__["CAS_LOGOUT_URL"] = "https://sso.example.com/cas/logout"
        try:
            url = build_logout_url()
        finally:
            build_logout_url.__globals__["CAS_LOGOUT_URL"] = original

        self.assertEqual(
            url,
            "https://sso.example.com/cas/logout?service=https://cas.example.com/cas/login",
        )

    def test_build_logout_url_resolves_absolute_path_against_cas_server_url(self):
        original = build_logout_url.__globals__["CAS_LOGOUT_URL"]
        build_logout_url.__globals__["CAS_LOGOUT_URL"] = "/logout"
        try:
            url = build_logout_url()
        finally:
            build_logout_url.__globals__["CAS_LOGOUT_URL"] = original

        self.assertEqual(
            url,
            "https://cas.example.com/cas/logout?service=https://cas.example.com/cas/login",
        )

    def test_build_logout_url_resolves_relative_path_against_cas_server_url(self):
        original = build_logout_url.__globals__["CAS_LOGOUT_URL"]
        build_logout_url.__globals__["CAS_LOGOUT_URL"] = "logout"
        try:
            url = build_logout_url()
        finally:
            build_logout_url.__globals__["CAS_LOGOUT_URL"] = original

        self.assertEqual(
            url,
            "https://cas.example.com/cas/logout?service=https://cas.example.com/cas/login",
        )

    def test_build_logout_url_preserves_configured_logout_url_with_query(self):
        original = build_logout_url.__globals__["CAS_LOGOUT_URL"]
        configured = "https://sso.example.com/cas/logout?redirect=https%3A%2F%2Fidp.example.com%2Flogin"
        build_logout_url.__globals__["CAS_LOGOUT_URL"] = configured
        try:
            url = build_logout_url()
        finally:
            build_logout_url.__globals__["CAS_LOGOUT_URL"] = original

        self.assertEqual(url, configured)


if __name__ == "__main__":
    unittest.main()
