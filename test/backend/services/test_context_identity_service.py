import pytest

from backend.services.context_identity_service import (
    authorize_context_operation,
    require_context_identity,
    resolve_context_identity,
)


def test_authorize_context_operation_without_identity_logs_denial(caplog):
    decision = authorize_context_operation(
        identity=None,
        operation="conversation.read",
        resource="conversation",
        allowed=False,
        reason_code="identity_not_found",
        audit_metadata={"source": "test"},
    )

    assert decision.allowed is False
    assert decision.reason_code == "identity_not_found"
    assert decision.audit_metadata == {"source": "test"}
    assert "context_authorization_denied" in caplog.text


def test_authorize_context_operation_denied_identity_uses_default_reason(caplog):
    identity = resolve_context_identity(
        tenant_id="tenant-1",
        user_id="user-1",
        conversation_id=7,
    )

    decision = authorize_context_operation(
        identity=identity,
        operation="conversation.write",
        resource="conversation",
        allowed=False,
    )

    assert decision.allowed is False
    assert decision.reason_code == "user_not_authorized"
    assert decision.identity_hash == identity.scoped_hash
    assert "user_not_authorized" in caplog.text


def test_require_context_identity_records_denial_for_incomplete_identity(caplog):
    with pytest.raises(ValueError, match="tenant_id"):
        require_context_identity(
            tenant_id=None,
            user_id="user-1",
            conversation_id=7,
            operation="conversation.read",
        )

    assert "identity_not_found" in caplog.text
