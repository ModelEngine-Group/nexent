import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock external dependencies before importing
sys.modules['psycopg2'] = MagicMock()
sys.modules['boto3'] = MagicMock()
sys.modules['supabase'] = MagicMock()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

from consts.exceptions import NotFoundException, UnauthorizedError
from backend.services.invitation_service import (
    create_invitation_code,
    update_invitation_code,
    use_invitation_code,
    update_invitation_code_status,
    get_invitations_list,
    _generate_unique_invitation_code
)


@pytest.fixture
def mock_user_info():
    """Mock user tenant information"""
    return {
        "user_tenant_id": 1,
        "user_id": "test_user",
        "tenant_id": "test_tenant",
        "user_role": "SU"
    }


@pytest.fixture
def mock_invitation_info():
    """Mock invitation code information"""
    return {
        "invitation_id": 123,
        "tenant_id": "test_tenant",
        "invitation_code": "ABC123",
        "code_type": "ADMIN_INVITE",
        "group_ids": [],
        "capacity": 5,
        "expiry_date": "2024-12-31T23:59:59",
        "status": "IN_USE"
    }


@patch('backend.services.invitation_service.get_tenant_default_group_id')
@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
@patch('backend.services.invitation_service._generate_unique_invitation_code')
@patch('backend.services.invitation_service.add_invitation')
@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.update_invitation_code_status')
def test_create_invitation_code_admin_invite(
    mock_update_status,
    mock_query_invitation,
    mock_add_invitation,
    mock_generate_code,
    mock_get_user_info,
    mock_get_tenant_default_group_id,
    mock_user_info
):
    """Test creating ADMIN_INVITE invitation code"""
    # Setup mocks
    mock_user_info["user_role"] = "SU"
    mock_get_user_info.return_value = mock_user_info
    mock_get_tenant_default_group_id.return_value = None
    mock_generate_code.return_value = "ABC123"
    mock_add_invitation.return_value = 123
    mock_update_status.return_value = None
    mock_query_invitation.return_value = {"status": "IN_USE"}

    result = create_invitation_code(
        tenant_id="test_tenant",
        code_type="ADMIN_INVITE",
        user_id="test_user"
    )

    assert result["invitation_id"] == 123
    assert result["code_type"] == "ADMIN_INVITE"
    assert result["group_ids"] == []
    mock_add_invitation.assert_called_once_with(
        tenant_id="test_tenant",
        invitation_code="ABC123",
        code_type="ADMIN_INVITE",
        group_ids=[],
        capacity=1,
        expiry_date=None,
        status="IN_USE",
        created_by="test_user"
    )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
@patch('backend.services.invitation_service.query_group_ids_by_user')
@patch('backend.services.invitation_service._generate_unique_invitation_code')
@patch('backend.services.invitation_service.add_invitation')
@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.update_invitation_code_status')
def test_create_invitation_code_dev_invite_admin_role(
    mock_update_status,
    mock_query_invitation,
    mock_add_invitation,
    mock_generate_code,
    mock_query_group_ids_by_user,
    mock_get_user_info,
    mock_user_info
):
    """Test creating DEV_INVITE invitation code with ADMIN role"""
    # Setup mocks
    mock_user_info["user_role"] = "ADMIN"
    mock_get_user_info.return_value = mock_user_info
    mock_query_group_ids_by_user.return_value = [1, 2, 3]
    mock_generate_code.return_value = "DEF456"
    mock_add_invitation.return_value = 123
    mock_update_status.return_value = None
    mock_query_invitation.return_value = {"status": "IN_USE"}

    result = create_invitation_code(
        tenant_id="test_tenant",
        code_type="DEV_INVITE",
        user_id="test_user"
    )

    assert result["invitation_id"] == 123
    assert result["code_type"] == "DEV_INVITE"
    assert result["group_ids"] == [1, 2, 3]
    mock_add_invitation.assert_called_once_with(
        tenant_id="test_tenant",
        invitation_code="DEF456",
        code_type="DEV_INVITE",
        group_ids=[1, 2, 3],
        capacity=1,
        expiry_date=None,
        status="IN_USE",
        created_by="test_user"
    )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
def test_create_invitation_code_invalid_code_type(mock_get_user_info, mock_user_info):
    """Test creating invitation code with invalid code_type"""
    # Setup mocks
    mock_user_info["user_role"] = "SU"
    mock_get_user_info.return_value = mock_user_info

    with pytest.raises(ValueError, match="Invalid code_type"):
            create_invitation_code(
                tenant_id="test_tenant",
                code_type="INVALID_TYPE",
                user_id="test_user"
            )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
def test_create_invitation_code_unauthorized_admin_invite(mock_get_user_info, mock_user_info):
    """Test creating ADMIN_INVITE code with insufficient permissions"""
    # Setup mocks
    mock_user_info["user_role"] = "ADMIN"
    mock_get_user_info.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to create ADMIN_INVITE codes"):
            create_invitation_code(
                tenant_id="test_tenant",
                code_type="ADMIN_INVITE",
                user_id="test_user"
            )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
def test_create_invitation_code_unauthorized_dev_invite(mock_get_user_info, mock_user_info):
    """Test creating DEV_INVITE code with insufficient permissions"""
    # Setup mocks
    mock_user_info["user_role"] = "USER"
    mock_get_user_info.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to create DEV_INVITE codes"):
            create_invitation_code(
                tenant_id="test_tenant",
                code_type="DEV_INVITE",
                user_id="test_user"
            )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
@patch('backend.services.invitation_service.modify_invitation')
@patch('backend.services.invitation_service.update_invitation_code_status')
def test_update_invitation_code_success(mock_update_status, mock_modify_invitation, mock_get_user_info, mock_user_info):
    """Test updating invitation code successfully"""
    mock_get_user_info.return_value = mock_user_info
    mock_modify_invitation.return_value = True
    mock_update_status.return_value = None

    result = update_invitation_code(
        invitation_id=123,
        updates={"status": "DISABLE"},
        user_id="test_user"
    )

    assert result is True
    mock_modify_invitation.assert_called_once_with(
        invitation_id=123,
        updates={"status": "DISABLE"},
        updated_by="test_user"
    )


@patch('backend.services.invitation_service.check_invitation_available')
@patch('backend.services.invitation_service.query_invitation_by_code')
@patch('backend.services.invitation_service.add_invitation_record')
@patch('backend.services.invitation_service.update_invitation_code_status')
def test_use_invitation_code_success(
    mock_update_status,
    mock_add_invitation_record,
    mock_query_invitation_by_code,
    mock_check_available,
    mock_invitation_info
):
    """Test using invitation code successfully"""
    mock_check_available.return_value = True
    mock_query_invitation_by_code.return_value = mock_invitation_info
    mock_add_invitation_record.return_value = 456

    result = use_invitation_code(
        invitation_code="ABC123",
        user_id="test_user"
    )

    assert result["invitation_record_id"] == 456
    assert result["invitation_code"] == "ABC123"
    assert result["code_type"] == "ADMIN_INVITE"
    assert result["group_ids"] == []
    mock_add_invitation_record.assert_called_once_with(
        invitation_id=123,
        user_id="test_user",
        created_by="test_user"
    )
    mock_update_status.assert_called_once_with(123)


@patch('backend.services.invitation_service.check_invitation_available')
def test_use_invitation_code_unavailable(mock_check_available):
    """Test using unavailable invitation code"""
    mock_check_available.return_value = False

    with pytest.raises(NotFoundException, match="is not available"):
        use_invitation_code(
            invitation_code="ABC123",
            user_id="test_user"
        )


@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.count_invitation_usage')
@patch('backend.services.invitation_service.modify_invitation')
def test_update_invitation_code_status_expired(
    mock_modify_invitation,
    mock_count_invitation_usage,
    mock_query_invitation_by_code,
    mock_invitation_info
):
    """Test updating invitation status to expired"""
    from datetime import datetime

    # Mock expired invitation
    mock_invitation_info["expiry_date"] = "2020-01-01T00:00:00"
    mock_query_invitation_by_code.return_value = mock_invitation_info
    mock_count_invitation_usage.return_value = 2

    result = update_invitation_code_status(123)

    assert result is True
    mock_modify_invitation.assert_called_once_with(
        invitation_id=123,
        updates={"status": "EXPIRE"},
        updated_by="system"
    )


@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.count_invitation_usage')
@patch('backend.services.invitation_service.modify_invitation')
def test_update_invitation_code_status_run_out(
    mock_modify_invitation,
    mock_count_invitation_usage,
    mock_query_invitation_by_code,
    mock_invitation_info
):
    """Test updating invitation status to run out"""
    # Mock invitation at capacity
    mock_invitation_info["capacity"] = 5
    mock_query_invitation_by_code.return_value = mock_invitation_info
    mock_count_invitation_usage.return_value = 5

    result = update_invitation_code_status(123)

    assert result is True
    mock_modify_invitation.assert_called_once_with(
        invitation_id=123,
        updates={"status": "RUN_OUT"},
        updated_by="system"
    )


@patch('backend.services.invitation_service.query_invitation_by_code')
def test_generate_unique_invitation_code(mock_query_invitation_by_code):
    """Test generating unique invitation code"""
    # Mock that first code exists, second doesn't
    mock_query_invitation_by_code.side_effect = [True, None]

    with patch('random.choices') as mock_random:
        mock_random.return_value = ['A', 'B', 'C', '1', '2', '3']

        result = _generate_unique_invitation_code()

        assert result == "ABC123"
        assert len(result) == 6


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
@patch('backend.services.invitation_service.query_invitations_with_pagination')
def test_get_invitations_list_success(mock_query_invitations, mock_get_user, mock_user_info):
    """Test getting invitations list successfully"""
    mock_get_user.return_value = mock_user_info

    mock_invitations_data = {
        "items": [
            {
                "invitation_id": 123,
                "invitation_code": "ABC123",
                "code_type": "ADMIN_INVITE",
                "group_ids": [],
                "capacity": 5,
                "expiry_date": "2024-12-31T23:59:59",
                "status": "IN_USE"
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 10
    }
    mock_query_invitations.return_value = mock_invitations_data

    result = get_invitations_list(
        tenant_id="test_tenant",
        page=1,
        page_size=10,
        user_id="test_user"
    )

    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["invitation_code"] == "ABC123"
    mock_query_invitations.assert_called_once_with(
        tenant_id="test_tenant",
        page=1,
        page_size=10
    )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
def test_get_invitations_list_user_not_found(mock_get_user):
    """Test getting invitations list when user doesn't exist"""
    mock_get_user.return_value = None

    with pytest.raises(UnauthorizedError, match="User test_user not found"):
        get_invitations_list(
            tenant_id="test_tenant",
            page=1,
            page_size=10,
            user_id="test_user"
        )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
@patch('backend.services.invitation_service.query_invitations_with_pagination')
def test_get_invitations_list_unauthorized_user_role(mock_query_invitations, mock_get_user, mock_user_info):
    """Test getting invitations list with unauthorized user role"""
    mock_user_info["user_role"] = "USER"
    mock_get_user.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to view invitation lists"):
        get_invitations_list(
            tenant_id="test_tenant",
            page=1,
            page_size=10,
            user_id="test_user"
        )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
def test_get_invitations_list_unauthorized_user_role_all_tenants(mock_get_user, mock_user_info):
    """Test getting invitations list for all tenants with insufficient permissions"""
    mock_user_info["user_role"] = "ADMIN"
    mock_get_user.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to view all tenant invitations"):
        get_invitations_list(
            tenant_id=None,  # Requesting all tenants
            page=1,
            page_size=10,
            user_id="test_user"
        )
