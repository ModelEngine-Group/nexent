"""
Unit tests for the auth audit service.

Tests backend/services/audit_service.py: single-line entry formatting,
client IP resolution priority, and the best-effort (never-raise) contract
of record_auth_event.
"""
import logging
import re
from types import SimpleNamespace

from backend.services.audit_service import (
    AUDIT_LOG_PREFIX,
    AUDIT_RESULT_FAILURE,
    AUDIT_RESULT_SUCCESS,
    format_audit_entry,
    get_client_ip,
    record_auth_event,
)


class _FakeRequest:
    def __init__(self, headers=None, client_host="127.0.0.1"):
        self.headers = headers or {}
        self.client = SimpleNamespace(host=client_host) if client_host else None


class _BrokenRequest:
    @property
    def headers(self):
        raise RuntimeError("boom")


class TestGetClientIp:
    def test_none_request_returns_empty(self):
        assert get_client_ip(None) == ""

    def test_forwarded_for_first_hop_wins(self):
        request = _FakeRequest(headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"})
        assert get_client_ip(request) == "203.0.113.7"

    def test_forwarded_for_trims_whitespace(self):
        request = _FakeRequest(headers={"x-forwarded-for": "  198.51.100.2 , 10.0.0.1"})
        assert get_client_ip(request) == "198.51.100.2"

    def test_real_ip_fallback(self):
        request = _FakeRequest(headers={"x-real-ip": "192.0.2.9"})
        assert get_client_ip(request) == "192.0.2.9"

    def test_socket_peer_fallback(self):
        request = _FakeRequest()
        assert get_client_ip(request) == "127.0.0.1"

    def test_empty_headers_and_no_client(self):
        request = _FakeRequest(client_host=None)
        assert get_client_ip(request) == ""


class TestFormatAuditEntry:
    def test_full_entry_field_order(self):
        entry = format_audit_entry(
            event_type="user_signin",
            result=AUDIT_RESULT_SUCCESS,
            reason="",
            user_id="u-1",
            tenant_id="t-1",
            user_email="a@b.com",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            session_id="s-1",
            details={"provider": "github"},
        )
        assert entry == (
            'event=user_signin result=success reason=- user_id=u-1 tenant_id=t-1 '
            'email=a@b.com ip=1.2.3.4 ua="Mozilla/5.0" session_id=s-1 '
            'details={"provider":"github"}'
        )

    def test_empty_fields_rendered_as_dash(self):
        entry = format_audit_entry(event_type="user_logout", result=AUDIT_RESULT_SUCCESS)
        assert 'reason=-' in entry
        assert 'user_id=-' in entry
        assert 'ua=-' in entry
        assert 'details=-' in entry

    def test_newlines_and_spaces_flattened(self):
        entry = format_audit_entry(
            event_type="user_signin",
            result=AUDIT_RESULT_FAILURE,
            reason="invalid\ncredentials",
            user_email="evil\nemail@x.com\r\nmore words",
        )
        assert "\n" not in entry
        assert "\r" not in entry
        assert "email=evilemail@x.commorewords" in entry

    def test_user_agent_quotes_replaced_and_truncated(self):
        entry = format_audit_entry(
            event_type="user_signin",
            result=AUDIT_RESULT_SUCCESS,
            user_agent='Mozilla "quoted" ' + "x" * 300,
        )
        match = re.search(r'ua="([^"]*)"', entry)
        assert match is not None
        assert '"' not in match.group(1)
        assert len(match.group(1)) <= 200

    def test_details_is_last_field_and_single_line(self):
        entry = format_audit_entry(
            event_type="token_create",
            result=AUDIT_RESULT_SUCCESS,
            details={"token_id": 3, "note": "has spaces inside"},
        )
        assert entry.endswith('details={"token_id":3,"note":"has spaces inside"}')

    def test_unserializable_details_kept_as_marker(self):
        circular = {}
        circular["self"] = circular
        entry = format_audit_entry(
            event_type="token_create",
            result=AUDIT_RESULT_SUCCESS,
            details=circular,
        )
        assert entry.endswith("details=unserializable")


class TestRecordAuthEvent:
    def test_emits_prefixed_line(self, caplog):
        with caplog.at_level(logging.INFO, logger="audit.auth"):
            record_auth_event("user_signin", AUDIT_RESULT_SUCCESS,
                              request=_FakeRequest(headers={"user-agent": "pytest/1"}),
                              user_id="u-1", user_email="a@b.com")
        message = caplog.records[-1].getMessage()
        assert message.startswith(AUDIT_LOG_PREFIX)
        assert "event=user_signin" in message
        assert "result=success" in message
        assert "email=a@b.com" in message
        assert 'ua="pytest/1"' in message

    def test_none_request_still_records(self, caplog):
        with caplog.at_level(logging.INFO, logger="audit.auth"):
            record_auth_event("user_logout", AUDIT_RESULT_SUCCESS, request=None)
        message = caplog.records[-1].getMessage()
        assert "ip=-" in message
        assert "ua=-" in message

    def test_never_raises_on_broken_request(self, caplog):
        with caplog.at_level(logging.INFO, logger="audit.auth"):
            record_auth_event("user_signin", AUDIT_RESULT_FAILURE,
                              request=_BrokenRequest(), reason="invalid_credentials")
        assert caplog.records[-1].levelno == logging.ERROR
        assert "Failed to record auth audit entry" in caplog.records[-1].getMessage()

    def test_failure_result_recorded(self, caplog):
        with caplog.at_level(logging.INFO, logger="audit.auth"):
            record_auth_event("password_update", AUDIT_RESULT_FAILURE, request=None,
                              user_id="u-2", reason="invalid_old_password")
        message = caplog.records[-1].getMessage()
        assert "result=failure" in message
        assert "reason=invalid_old_password" in message


class TestReasonFromException:
    def test_maps_domain_exceptions(self):
        # Runtime code imports domain exceptions via the bare `consts` path
        # (backend/ is the import root in the serving process); use the same
        # path here so isinstance checks inside reason_from_exception match.
        from consts.exceptions import (
            DuplicateError,
            ForbiddenError,
            NotFoundException,
            UnauthorizedError,
            ValidationError,
        )
        from backend.services.audit_service import reason_from_exception

        assert reason_from_exception(UnauthorizedError("x")) == "unauthorized"
        assert reason_from_exception(ForbiddenError("x")) == "forbidden"
        assert reason_from_exception(NotFoundException("x")) == "not_found"
        assert reason_from_exception(DuplicateError("x")) == "duplicate"
        assert reason_from_exception(ValidationError("x")) == "validation_error"
        assert reason_from_exception(ValueError("x")) == "validation_error"
        assert reason_from_exception(RuntimeError("x")) == "internal_error"
