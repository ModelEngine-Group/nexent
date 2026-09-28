"""Tests for the security audit logging service."""

import logging
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from services.audit_service import (
    AUDIT_LOG_PREFIX,
    USER_AGENT_MAX_LENGTH,
    format_audit_entry,
    get_client_ip,
    record_security_event,
)


def _fake_request(host="1.2.3.4", headers=None):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


def _audit_messages(caplog):
    return [record.getMessage() for record in caplog.records if record.name == "audit.security"]


class TestGetClientIp:
    @pytest.mark.parametrize(
        "headers,expected",
        [
            ({"x-forwarded-for": " 9.9.9.9 , 10.0.0.1"}, "9.9.9.9"),
            ({"x-real-ip": "8.8.8.8"}, "8.8.8.8"),
            ({"x-forwarded-for": " , "}, "1.2.3.4"),
            ({}, "1.2.3.4"),
        ],
    )
    def test_resolves_source_address_in_priority_order(self, headers, expected):
        """Forwarded-for wins, then real-ip, then the peer address."""
        assert get_client_ip(_fake_request(headers=headers)) == expected

    def test_none_request_returns_empty(self):
        assert get_client_ip(None) == ""

    def test_missing_client_returns_empty(self):
        request = SimpleNamespace(headers={}, client=None)

        assert get_client_ip(request) == ""


class TestFormatAuditEntry:
    def test_renders_fields_in_fixed_order(self):
        entry = format_audit_entry(
            event_type="user_signin",
            user_id="u-1",
            tenant_id="t-1",
            user_email="a@b.com",
            client_ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            session_id="s-1",
            details={"provider": "github"},
        )

        assert entry == (
            'event=user_signin result=success user_id=u-1 tenant_id=t-1 email=a@b.com '
            'ip=1.2.3.4 ua="Mozilla/5.0" session_id=s-1 details={"provider":"github"}'
        )

    def test_uses_dash_for_empty_values(self):
        entry = format_audit_entry(event_type="cas_logout")

        assert entry == (
            "event=cas_logout result=success user_id=- tenant_id=- email=- "
            "ip=- ua=- session_id=- details=-"
        )

    def test_compacts_atomic_fields_to_single_line(self):
        entry = format_audit_entry(event_type="user signin", user_email="a\nb@c.com")

        assert "event=usersignin" in entry
        assert "email=ab@c.com" in entry
        assert "\n" not in entry

    def test_replaces_quotes_and_truncates_user_agent(self):
        entry = format_audit_entry(
            event_type="user_signin", user_agent='Mozilla "5.0" ' * 50
        )
        ua_value = entry.split('ua="', 1)[1].split('"', 1)[0]

        assert '"' not in ua_value
        assert len(ua_value) == USER_AGENT_MAX_LENGTH

    def test_details_is_last_and_compacted(self):
        entry = format_audit_entry(
            event_type="user_signup", details={"note": "a\nb", "provider": "github"}
        )

        assert entry.endswith('details={"note":"a\\nb","provider":"github"}')
        assert "\n" not in entry

    def test_unserializable_details_degrade_gracefully(self):
        circular = {"name": "loop"}
        circular["self"] = circular

        entry = format_audit_entry(event_type="user_signup", details=circular)

        assert entry.endswith("details=unserializable")


class TestRecordSecurityEvent:
    def test_emits_single_prefixed_line(self, caplog):
        request = _fake_request(headers={"user-agent": "curl/8.0", "x-forwarded-for": "9.9.9.9"})

        with caplog.at_level(logging.INFO, logger="audit.security"):
            record_security_event(
                "user_signin",
                request=request,
                user_id="u-1",
                tenant_id="t-1",
                user_email="a@b.com",
            )

        messages = _audit_messages(caplog)
        assert len(messages) == 1
        assert messages[0].startswith(f"{AUDIT_LOG_PREFIX} ")
        assert "event=user_signin" in messages[0]
        assert "result=success" in messages[0]
        assert "user_id=u-1" in messages[0]
        assert "tenant_id=t-1" in messages[0]
        assert "ip=9.9.9.9" in messages[0]
        assert 'ua="curl/8.0"' in messages[0]

    def test_records_without_request(self, caplog):
        with caplog.at_level(logging.INFO, logger="audit.security"):
            record_security_event("cas_logout")

        messages = _audit_messages(caplog)
        assert len(messages) == 1
        assert "ip=-" in messages[0]
        assert "ua=-" in messages[0]

    def test_never_raises_on_broken_request(self, caplog):
        class _BrokenRequest:
            @property
            def headers(self):
                raise RuntimeError("broken headers")

        with caplog.at_level(logging.INFO, logger="audit.security"):
            record_security_event("user_signin", request=_BrokenRequest())

        audit_records = [r for r in caplog.records if r.name == "audit.security"]
        assert [r.levelno for r in audit_records] == [logging.ERROR]
        assert "Failed to record security audit entry" in audit_records[0].getMessage()

    def test_secret_fields_are_not_invented(self, caplog):
        with caplog.at_level(logging.INFO, logger="audit.security"):
            record_security_event("token_create", user_id="u-1", details={"token_id": 7})

        message = _audit_messages(caplog)[0]
        assert 'details={"token_id":7}' in message
        assert message.count("=") == 9
