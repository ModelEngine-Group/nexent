"""Tests for tenant isolation in API key management."""

from unittest.mock import MagicMock, patch

import pytest

from backend.services import api_key_service
from consts.exceptions import ForbiddenError, NotFoundException, ValidationError


@pytest.mark.parametrize(
    "operation",
    [api_key_service.refresh_user_api_key, api_key_service.revoke_user_api_keys],
)
@patch("backend.services.api_key_service.create_token")
@patch("backend.services.api_key_service.soft_delete_tokens_by_user")
@patch("backend.services.api_key_service.get_user_tenant_in_tenant")
def test_user_id_outside_admin_tenant_is_rejected_before_key_mutation(
    mock_get_target,
    mock_soft_delete,
    mock_create_token,
    operation,
):
    mock_get_target.return_value = None

    with pytest.raises(
        ForbiddenError,
        match="Cannot manage API keys for a user outside the caller tenant",
    ):
        operation(
            actor_user_id="admin-a",
            actor_tenant_id="tenant-a",
            actor_role="ADMIN",
            user_id="user-in-tenant-b",
        )

    mock_get_target.assert_called_once_with("user-in-tenant-b", "tenant-a")
    mock_soft_delete.assert_not_called()
    mock_create_token.assert_not_called()


@pytest.mark.parametrize(
    "operation",
    [api_key_service.refresh_user_api_key, api_key_service.revoke_user_api_keys],
)
@patch("backend.services.api_key_service.create_token")
@patch("backend.services.api_key_service.soft_delete_tokens_by_user")
@patch("backend.services.api_key_service.get_user_tenant_in_tenant")
def test_mismatched_tenant_record_is_rejected_before_key_mutation(
    mock_get_target,
    mock_soft_delete,
    mock_create_token,
    operation,
):
    mock_get_target.return_value = {
        "user_id": "user-in-tenant-b",
        "tenant_id": "tenant-b",
    }

    with pytest.raises(ForbiddenError):
        operation(
            actor_user_id="admin-a",
            actor_tenant_id="tenant-a",
            actor_role="ADMIN",
            user_id="user-in-tenant-b",
        )

    mock_soft_delete.assert_not_called()
    mock_create_token.assert_not_called()


@pytest.mark.parametrize("role", ["ADMIN", "SU", "su"])
def test_require_tenant_admin_accepts_administrator_roles(role):
    api_key_service._require_tenant_admin("tenant-a", role)


@pytest.mark.parametrize("role", ["", "DEV", "USER"])
def test_require_tenant_admin_rejects_non_administrators(role):
    with pytest.raises(ForbiddenError, match="Only administrators"):
        api_key_service._require_tenant_admin("tenant-a", role)


def test_require_tenant_admin_requires_tenant_context():
    with pytest.raises(ForbiddenError, match="Tenant context"):
        api_key_service._require_tenant_admin("", "SU")


@patch("backend.services.api_key_service.get_user_tenant_by_email")
def test_resolve_target_by_email_returns_tenant_user(mock_by_email):
    target = {"user_id": "user-1", "tenant_id": "tenant-a", "user_email": "api@example.com"}
    mock_by_email.return_value = target

    assert api_key_service._resolve_target("tenant-a", None, "api@example.com") == target
    mock_by_email.assert_called_once_with("api@example.com", "tenant-a")


@pytest.mark.parametrize("user_id,email", [(None, None), ("", "")])
def test_resolve_target_requires_target(user_id, email):
    with pytest.raises(ValidationError, match="Exactly one"):
        api_key_service._resolve_target("tenant-a", user_id, email)


@patch("backend.services.api_key_service.query_groups")
@patch("backend.services.api_key_service.get_tenant_default_group_id")
def test_create_api_users_batch_allows_superuser_and_uses_default_group(mock_default_group, mock_groups):
    session = MagicMock()
    mock_default_group.return_value = 7
    mock_groups.return_value = {"group_id": 7, "tenant_id": "tenant-a", "group_name": "Default"}
    with patch("backend.services.api_key_service.get_db_session") as mock_session, \
            patch("backend.services.api_key_service.uuid.uuid4", side_effect=["user-1", "user-2"]), \
            patch("backend.services.api_key_service.insert_user_tenant") as mock_insert, \
            patch("backend.services.api_key_service.add_user_to_group") as mock_add_group, \
            patch("backend.services.api_key_service.generate_access_key", side_effect=["key-1", "key-2"]), \
            patch("backend.services.api_key_service.create_token", side_effect=[
                {"access_key": "key-1"}, {"access_key": "key-2"},
            ]):
        mock_session.return_value.__enter__.return_value = session
        result = api_key_service.create_api_users_batch(
            actor_user_id="su-1",
            actor_tenant_id="tenant-a",
            actor_role="SU",
            role="dev",
            count=2,
        )

    assert [item["user_id"] for item in result] == ["user-1", "user-2"]
    assert all(item["role"] == "DEV" for item in result)
    assert mock_insert.call_count == 2
    assert mock_add_group.call_count == 2


@patch("backend.services.api_key_service.get_user_tenant_in_tenant")
def test_refresh_user_api_key_revokes_then_creates_in_shared_session(mock_target):
    session = MagicMock()
    mock_target.return_value = {"user_id": "user-1", "tenant_id": "tenant-a", "user_email": "api@example.com"}
    with patch("backend.services.api_key_service.get_db_session") as mock_session, \
            patch("backend.services.api_key_service.soft_delete_tokens_by_user", return_value=3) as mock_revoke, \
            patch("backend.services.api_key_service.generate_access_key", return_value="new-key"), \
            patch("backend.services.api_key_service.create_token", return_value={"access_key": "new-key"}) as mock_create:
        mock_session.return_value.__enter__.return_value = session
        result = api_key_service.refresh_user_api_key(
            actor_user_id="admin-1",
            actor_tenant_id="tenant-a",
            actor_role="ADMIN",
            user_id="user-1",
        )

    assert result == {
        "user_id": "user-1", "email": "api@example.com", "api_key": "new-key", "revoked_count": 3,
    }
    mock_revoke.assert_called_once_with("user-1", "admin-1", session)
    mock_create.assert_called_once_with("new-key", "user-1", created_by="admin-1", db_session=session)


@patch("backend.services.api_key_service.get_user_tenant_in_tenant")
def test_revoke_user_api_keys_reports_missing_active_key(mock_target):
    mock_target.return_value = {"user_id": "user-1", "tenant_id": "tenant-a"}
    with patch("backend.services.api_key_service.soft_delete_tokens_by_user", return_value=0):
        with pytest.raises(NotFoundException, match="no active API key"):
            api_key_service.revoke_user_api_keys(
                actor_user_id="admin-1",
                actor_tenant_id="tenant-a",
                actor_role="ADMIN",
                user_id="user-1",
            )


@patch("backend.services.api_key_service.list_active_tokens_by_tenant")
def test_list_tenant_api_keys_allows_superuser_and_forwards_pagination(mock_list):
    mock_list.return_value = {"items": [], "total": 0}

    result = api_key_service.list_tenant_api_keys(
        actor_tenant_id="tenant-a", actor_role="SU", tenant_id="tenant-a", page=2, page_size=10, sort_order="asc"
    )

    assert result == {"items": [], "total": 0}
    mock_list.assert_called_once_with("tenant-a", 2, 10, "asc")


def test_list_tenant_api_keys_rejects_other_tenant():
    with pytest.raises(NotFoundException, match="Tenant not found"):
        api_key_service.list_tenant_api_keys(
            actor_tenant_id="tenant-a", actor_role="ADMIN", tenant_id="tenant-b"
        )
