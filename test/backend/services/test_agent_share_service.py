"""Unit tests for authenticated Agent share-link management."""

from uuid import uuid4

import pytest


def _share_record(*, generation: int = 1, status: str = "active") -> dict:
    return {
        "agent_share_id": 7,
        "public_share_id": str(uuid4()),
        "token_generation": generation,
        "token_nonce": "nonce",
        "status": status,
    }


def test_enable_share_requires_edit_permission_and_published_agent(mocker):
    from services import agent_share_service

    mocker.patch.object(agent_share_service, "SUPABASE_JWT_SECRET", "auth-secret")
    require_edit = mocker.patch.object(agent_share_service, "require_agent_draft_edit", return_value={"agent_id": 9})
    mocker.patch.object(agent_share_service, "query_current_version_no", return_value=2)
    mocker.patch.object(agent_share_service, "get_active_agent_share", return_value=None)
    created = mocker.patch.object(agent_share_service, "create_agent_share", return_value=_share_record())

    result = agent_share_service.enable_agent_share(agent_id=9, tenant_id="tenant-a", user_id="owner-a")

    require_edit.assert_called_once_with(agent_id=9, tenant_id="tenant-a", user_id="owner-a")
    created.assert_called_once()
    assert result["share_token"]
    assert result["agent_id"] == 9


def test_enable_share_reuses_active_token_and_rejects_unpublished_agent(mocker):
    from services import agent_share_service

    mocker.patch.object(agent_share_service, "SUPABASE_JWT_SECRET", "auth-secret")
    mocker.patch.object(agent_share_service, "require_agent_draft_edit", return_value={"agent_id": 9})
    mocker.patch.object(agent_share_service, "query_current_version_no", return_value=2)
    mocker.patch.object(agent_share_service, "get_active_agent_share", return_value=_share_record())
    created = mocker.patch.object(agent_share_service, "create_agent_share")

    result = agent_share_service.enable_agent_share(agent_id=9, tenant_id="tenant-a", user_id="owner-a")

    assert result["share_token"]
    created.assert_not_called()

    mocker.patch.object(agent_share_service, "query_current_version_no", return_value=None)
    with pytest.raises(agent_share_service.AgentShareError, match="agent_not_published"):
        agent_share_service.enable_agent_share(agent_id=9, tenant_id="tenant-a", user_id="owner-a")


def test_rotate_and_revoke_share_are_scoped_to_share_owner(mocker):
    from services import agent_share_service

    mocker.patch.object(agent_share_service, "SUPABASE_JWT_SECRET", "auth-secret")
    mocker.patch.object(agent_share_service, "require_agent_draft_edit", return_value={"agent_id": 9})
    mocker.patch.object(agent_share_service, "query_current_version_no", return_value=2)
    mocker.patch.object(agent_share_service, "get_active_agent_share", return_value=_share_record(generation=3))
    rotated = mocker.patch.object(agent_share_service, "rotate_agent_share_record", return_value=True)
    revoked = mocker.patch.object(agent_share_service, "revoke_agent_share", return_value=True)

    result = agent_share_service.rotate_agent_share_link(agent_id=9, tenant_id="tenant-a", user_id="owner-a")
    assert result["generation"] == 4
    rotated.assert_called_once()

    agent_share_service.revoke_agent_share_link(agent_id=9, tenant_id="tenant-a", user_id="owner-a")
    revoked.assert_called_once_with(7, manager_user_id="owner-a")


def test_resolve_share_session_uses_the_logged_in_user_as_the_session_owner(mocker):
    from services import agent_share_service

    record = _share_record(generation=2)
    record.update({"tenant_id": "tenant-a", "agent_id": 9, "owner_user_id": "owner-a"})
    mocker.patch.object(agent_share_service, "SUPABASE_JWT_SECRET", "auth-secret")
    mocker.patch.object(agent_share_service, "get_agent_share_by_public_id", return_value=record)
    mocker.patch.object(
        agent_share_service,
        "parse_agent_share_token",
        return_value=agent_share_service.AgentShareTokenPayload(record["public_share_id"], 2),
    )
    mocker.patch.object(agent_share_service, "require_agent_draft_edit", return_value={"agent_id": 9})
    mocker.patch.object(agent_share_service, "query_current_version_no", return_value=4)
    get_or_create = mocker.patch.object(
        agent_share_service,
        "get_or_create_agent_share_session",
        return_value={"conversation_id": 88, "agent_version_no": 4},
    )

    result = agent_share_service.resolve_agent_share_session("opaque-token", visitor_user_id="visitor-a")

    assert result == {"agent_id": 9, "conversation_id": 88, "agent_version_no": 4}
    get_or_create.assert_called_once_with(
        agent_share_id=7,
        visitor_user_id="visitor-a",
        agent_id=9,
        agent_version_no=4,
    )


def test_resolve_share_context_validates_the_token_without_creating_a_session(mocker):
    from services import agent_share_service

    record = _share_record(generation=2)
    record.update({"tenant_id": "tenant-a", "agent_id": 9, "owner_user_id": "owner-a"})
    mocker.patch.object(agent_share_service, "SUPABASE_JWT_SECRET", "auth-secret")
    mocker.patch.object(agent_share_service, "get_agent_share_by_public_id", return_value=record)
    mocker.patch.object(
        agent_share_service,
        "parse_agent_share_token",
        return_value=agent_share_service.AgentShareTokenPayload(record["public_share_id"], 2),
    )
    mocker.patch.object(agent_share_service, "require_agent_draft_edit", return_value={"agent_id": 9})
    mocker.patch.object(agent_share_service, "query_current_version_no", return_value=4)
    create_session = mocker.patch.object(agent_share_service, "get_or_create_agent_share_session")

    result = agent_share_service.resolve_agent_share_context("opaque-token")

    assert result == {
        "agent_share_id": 7,
        "agent_id": 9,
        "agent_version_no": 4,
        "owner_user_id": "owner-a",
        "tenant_id": "tenant-a",
    }
    create_session.assert_not_called()


def test_share_metadata_whitelists_agent_display_fields(mocker):
    from services import agent_share_service

    mocker.patch.object(
        agent_share_service,
        "resolve_agent_share_context",
        return_value={
            "agent_share_id": 7,
            "agent_id": 9,
            "agent_version_no": 4,
            "owner_user_id": "owner-a",
            "tenant_id": "tenant-a",
        },
    )
    mocker.patch.object(
        agent_share_service,
        "search_agent_info_by_agent_id",
        return_value={
            "name": "internal-name",
            "display_name": "Shared Agent",
            "description": "Public description",
            "icon_url": "icons/shared.png",
            "greeting_message": "Welcome",
            "duty_prompt": "must not escape",
            "model_ids": [1, 2],
        },
    )
    mocker.patch.object(agent_share_service, "get_agent_share_session", return_value=None)

    result = agent_share_service.get_agent_share_metadata("opaque-token", visitor_user_id="visitor-a")

    assert result == {
        "display_name": "Shared Agent",
        "description": "Public description",
        "icon_url": "icons/shared.png",
        "greeting_message": "Welcome",
        "session_recoverable": False,
    }


def test_existing_share_session_never_creates_a_conversation(mocker):
    from services import agent_share_service

    mocker.patch.object(
        agent_share_service,
        "resolve_agent_share_context",
        return_value={"agent_share_id": 7},
    )
    mocker.patch.object(
        agent_share_service,
        "get_agent_share_session",
        return_value={"conversation_id": 88, "agent_version_no": 4},
    )
    create_session = mocker.patch.object(agent_share_service, "get_or_create_agent_share_session")

    result = agent_share_service.resolve_existing_agent_share_session(
        "opaque-token", visitor_user_id="visitor-a"
    )

    assert result == {"conversation_id": 88, "agent_version_no": 4}
    create_session.assert_not_called()


def test_share_is_unavailable_only_when_the_existing_auth_secret_is_missing(mocker):
    from services import agent_share_service

    mocker.patch.object(agent_share_service, "SUPABASE_JWT_SECRET", "")

    with pytest.raises(agent_share_service.AgentShareError, match="agent_share_unavailable"):
        agent_share_service.enable_agent_share(agent_id=9, tenant_id="tenant-a", user_id="owner-a")
