import pytest

from services.agent_draft_permission_service import (
    AgentDraftEditError,
    require_agent_draft_edit,
)


def test_require_agent_draft_edit_returns_editable_draft(mocker):
    draft = {
        "agent_id": 42,
        "version_no": 0,
        "delete_flag": "N",
        "created_by": "user-a",
    }
    query = mocker.patch(
        "services.agent_draft_permission_service.query_agent_records_for_nl2agent",
        return_value=[draft],
    )
    mocker.patch(
        "services.agent_draft_permission_service.get_user_role_by_tenant",
        return_value="MEMBER",
    )

    assert require_agent_draft_edit(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    ) is draft
    query.assert_called_once_with(agent_id=42, tenant_id="tenant-a")


def test_require_agent_draft_edit_treats_missing_role_as_non_admin(mocker):
    draft = {
        "agent_id": 42,
        "version_no": 0,
        "delete_flag": "N",
        "created_by": "user-a",
    }
    mocker.patch(
        "services.agent_draft_permission_service.query_agent_records_for_nl2agent",
        return_value=[draft],
    )
    mocker.patch(
        "services.agent_draft_permission_service.get_user_role_by_tenant",
        return_value=None,
    )

    assert require_agent_draft_edit(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    ) is draft


@pytest.mark.parametrize(
    ("records", "permission", "expected_code"),
    [
        ([], "EDIT", "agent_not_found"),
        ([{"version_no": 1, "delete_flag": "N"}], "EDIT", "agent_not_draft"),
        ([{"version_no": 0, "delete_flag": "Y"}], "EDIT", "agent_deleted"),
        ([{"version_no": 0, "delete_flag": "N"}], "READ_ONLY", "agent_read_only"),
    ],
)
def test_require_agent_draft_edit_rejects_invalid_records(
    mocker,
    records,
    permission,
    expected_code,
):
    mocker.patch(
        "services.agent_draft_permission_service.query_agent_records_for_nl2agent",
        return_value=records,
    )
    mocker.patch(
        "services.agent_draft_permission_service.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "services.agent_draft_permission_service.resolve_agent_list_permission",
        return_value=permission,
    )

    with pytest.raises(AgentDraftEditError) as exc_info:
        require_agent_draft_edit(
            agent_id=42,
            tenant_id="tenant-a",
            user_id="user-a",
        )

    assert exc_info.value.code == expected_code
