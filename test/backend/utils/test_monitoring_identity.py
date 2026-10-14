"""UT-BE-TRACE-013: email enrichment uses trusted tenant-scoped identity."""

import pytest

from utils import monitoring_identity


@pytest.mark.parametrize("stored,expected", [
    (" person@example.com ", "person@example.com"),
    (None, None), ("", None), ("  ", None), (123, None),
])
def test_ut_be_trace_013_resolves_email_in_the_correct_tenant(monkeypatch, stored, expected):
    calls = []

    def lookup(user_id, tenant_id):
        calls.append((user_id, tenant_id))
        return {"user_email": stored}

    monkeypatch.setattr(monitoring_identity, "get_user_tenant_in_tenant", lookup)
    assert monitoring_identity.resolve_monitoring_user_email("uuid", "tenant") == expected
    assert calls == [("uuid", "tenant")]


def test_ut_be_trace_013_missing_membership_has_no_email(monkeypatch):
    monkeypatch.setattr(monitoring_identity, "get_user_tenant_in_tenant", lambda *_args: None)
    assert monitoring_identity.resolve_monitoring_user_email("uuid", "other-tenant") is None


def test_ut_be_trace_013_lookup_failure_does_not_block_execution(monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(monitoring_identity, "get_user_tenant_in_tenant", unavailable)
    assert monitoring_identity.resolve_monitoring_user_email("uuid", "tenant") is None


@pytest.mark.parametrize("user,tenant", [("", "tenant"), ("uuid", "")])
def test_ut_be_trace_013_incomplete_identity_skips_query(monkeypatch, user, tenant):
    def forbidden(*_args):
        pytest.fail("Incomplete identity queried the database")
    monkeypatch.setattr(monitoring_identity, "get_user_tenant_in_tenant", forbidden)
    assert monitoring_identity.resolve_monitoring_user_email(user, tenant) is None
