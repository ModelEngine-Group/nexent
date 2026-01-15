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
    _generate_unique_invitation_code,
    _normalize_invitation_data,
    get_invitation_by_code,
    check_invitation_available
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
def test_create_invitation_code_user_not_found(mock_get_user_info):
    """Test creating invitation code when user is not found"""
    # Setup mocks
    mock_get_user_info.return_value = None

    with pytest.raises(NotFoundException, match="User test_user not found"):
        create_invitation_code(
            tenant_id="test_tenant",
            code_type="ADMIN_INVITE",
            user_id="test_user"
        )


@patch('backend.services.invitation_service.get_tenant_default_group_id')
@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
@patch('backend.services.invitation_service._generate_unique_invitation_code')
@patch('backend.services.invitation_service.add_invitation')
@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.update_invitation_code_status')
def test_create_invitation_code_default_empty_group_ids(
    mock_update_status,
    mock_query_invitation,
    mock_add_invitation,
    mock_generate_code,
    mock_get_user_info,
    mock_get_tenant_default_group_id,
    mock_user_info
):
    """Test creating invitation code with default empty group_ids when no default group found"""
    # Setup mocks
    mock_user_info["user_role"] = "SU"
    mock_get_user_info.return_value = mock_user_info
    mock_get_tenant_default_group_id.return_value = None  # No default group found
    mock_generate_code.return_value = "ABC123"
    mock_add_invitation.return_value = 123
    mock_update_status.return_value = None
    mock_query_invitation.return_value = {"status": "IN_USE"}

    # Test ADMIN_INVITE with no default group - should result in empty group_ids
    result = create_invitation_code(
        tenant_id="test_tenant",
        code_type="ADMIN_INVITE",
        user_id="test_user"
    )

    assert result["invitation_id"] == 123
    assert result["code_type"] == "ADMIN_INVITE"
    assert result["group_ids"] == []  # Should be empty list when default group is None
    mock_add_invitation.assert_called_once()
    call_args = mock_add_invitation.call_args[1]
    assert call_args["group_ids"] == []


@patch('backend.services.invitation_service.get_tenant_default_group_id')
@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
@patch('backend.services.invitation_service.add_invitation')
@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.update_invitation_code_status')
def test_create_invitation_code_provided_code_uppercase_conversion(
    mock_update_status,
    mock_query_invitation,
    mock_add_invitation,
    mock_get_user_info,
    mock_get_tenant_default_group_id,
    mock_user_info
):
    """Test creating invitation code with provided code converted to uppercase (line 93)"""
    # Setup mocks
    mock_user_info["user_role"] = "SU"
    mock_get_user_info.return_value = mock_user_info
    mock_get_tenant_default_group_id.return_value = None
    mock_add_invitation.return_value = 123
    mock_update_status.return_value = None
    mock_query_invitation.return_value = {"status": "IN_USE"}

    result = create_invitation_code(
        tenant_id="test_tenant",
        code_type="ADMIN_INVITE",
        invitation_code="abc123",  # lowercase code
        user_id="test_user"
    )

    assert result["invitation_code"] == "ABC123"  # Should be converted to uppercase
    mock_add_invitation.assert_called_once_with(
        tenant_id="test_tenant",
        invitation_code="ABC123",  # Should be uppercase in the call
        code_type="ADMIN_INVITE",
        group_ids=[],
        capacity=1,
        expiry_date=None,
        status="IN_USE",
        created_by="test_user"
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


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
def test_update_invitation_code_user_not_found(mock_get_user_info):
    """Test updating invitation code when user is not found"""
    # Setup mocks
    mock_get_user_info.return_value = None

    with pytest.raises(UnauthorizedError, match="User test_user not found"):
        update_invitation_code(
            invitation_id=123,
            updates={"status": "DISABLE"},
            user_id="test_user"
        )


@patch('backend.services.invitation_service.get_user_tenant_by_user_id')
def test_update_invitation_code_unauthorized_user_role(mock_get_user_info, mock_user_info):
    """Test updating invitation code with unauthorized user role"""
    # Setup mocks
    mock_user_info["user_role"] = "USER"  # Not SU or ADMIN
    mock_get_user_info.return_value = mock_user_info

    with pytest.raises(UnauthorizedError, match="not authorized to update invitation codes"):
        update_invitation_code(
            invitation_id=123,
            updates={"status": "DISABLE"},
            user_id="test_user"
        )


def test_normalize_invitation_data_empty_input():
    """Test _normalize_invitation_data with empty input (lines 180-181)"""
    # Test with None input
    result = _normalize_invitation_data(None)
    assert result is None

    # Test with empty dict input
    result = _normalize_invitation_data({})
    assert result == {}


def test_normalize_invitation_data_datetime_conversion():
    """Test _normalize_invitation_data datetime to ISO conversion (lines 188-189)"""
    from datetime import datetime

    test_datetime = datetime(2024, 12, 31, 23, 59, 59)
    input_data = {
        "invitation_id": 123,
        "created_at": test_datetime,
        "updated_at": test_datetime,
        "capacity": 5,
        "group_ids": [1, 2, 3]
    }

    result = _normalize_invitation_data(input_data)

    # Check that datetime objects are converted to ISO strings
    assert result["created_at"] == "2024-12-31T23:59:59"
    assert result["updated_at"] == "2024-12-31T23:59:59"
    # Other fields should remain unchanged
    assert result["invitation_id"] == 123
    assert result["capacity"] == 5
    assert result["group_ids"] == [1, 2, 3]


def test_normalize_invitation_data_group_ids_conversion():
    """Test _normalize_invitation_data group_ids string/list conversion (lines 199-202)"""
    # Test string to list conversion (comma-separated format from database)
    input_data_string = {
        "invitation_id": 123,
        "group_ids": "1,2,3"
    }
    result = _normalize_invitation_data(input_data_string)
    assert result["group_ids"] == [1, 2, 3]

    # Test None to empty list conversion
    input_data_none = {
        "invitation_id": 123,
        "group_ids": None
    }
    result = _normalize_invitation_data(input_data_none)
    assert result["group_ids"] == []

    # Test list remains unchanged
    input_data_list = {
        "invitation_id": 123,
        "group_ids": [4, 5, 6]
    }
    result = _normalize_invitation_data(input_data_list)
    assert result["group_ids"] == [4, 5, 6]


@patch('backend.services.invitation_service.query_invitation_by_code')
def test_get_invitation_by_code_success(mock_query_invitation_by_code):
    """Test get_invitation_by_code function success case (lines 217-218)"""
    mock_data = {
        "invitation_id": 123,
        "invitation_code": "ABC123",
        "code_type": "ADMIN_INVITE",
        "group_ids": "1,2,3",  # Comma-separated string format from database
        "capacity": 5
    }
    mock_query_invitation_by_code.return_value = mock_data

    result = get_invitation_by_code("ABC123")

    assert result is not None
    assert result["invitation_id"] == 123
    assert result["invitation_code"] == "ABC123"
    assert result["group_ids"] == [1, 2, 3]  # Should be normalized
    mock_query_invitation_by_code.assert_called_once_with("ABC123")


@patch('backend.services.invitation_service.query_invitation_by_code')
def test_get_invitation_by_code_not_found(mock_query_invitation_by_code):
    """Test get_invitation_by_code function when invitation not found"""
    mock_query_invitation_by_code.return_value = None

    result = get_invitation_by_code("NONEXISTENT")

    assert result is None
    mock_query_invitation_by_code.assert_called_once_with("NONEXISTENT")


@patch('backend.services.invitation_service.query_invitation_by_code')
@patch('backend.services.invitation_service.count_invitation_usage')
def test_check_invitation_available_not_found(mock_count_usage, mock_query_invitation_by_code):
    """Test check_invitation_available when invitation not found (line 231-233)"""
    mock_query_invitation_by_code.return_value = None

    result = check_invitation_available("NONEXISTENT")

    assert result is False
    mock_query_invitation_by_code.assert_called_once_with("NONEXISTENT")
    mock_count_usage.assert_not_called()


@patch('backend.services.invitation_service.query_invitation_by_code')
@patch('backend.services.invitation_service.count_invitation_usage')
def test_check_invitation_available_not_in_use(mock_count_usage, mock_query_invitation_by_code):
    """Test check_invitation_available when status is not IN_USE (lines 235-237)"""
    mock_query_invitation_by_code.return_value = {
        "invitation_id": 123,
        "status": "EXPIRE",
        "capacity": 5
    }

    result = check_invitation_available("ABC123")

    assert result is False
    mock_query_invitation_by_code.assert_called_once_with("ABC123")
    mock_count_usage.assert_not_called()


@patch('backend.services.invitation_service.query_invitation_by_code')
@patch('backend.services.invitation_service.count_invitation_usage')
def test_check_invitation_available_capacity_exceeded(mock_count_usage, mock_query_invitation_by_code):
    """Test check_invitation_available when capacity exceeded (lines 239-241)"""
    mock_query_invitation_by_code.return_value = {
        "invitation_id": 123,
        "status": "IN_USE",
        "capacity": 5
    }
    mock_count_usage.return_value = 5  # At capacity

    result = check_invitation_available("ABC123")

    assert result is False
    mock_query_invitation_by_code.assert_called_once_with("ABC123")
    mock_count_usage.assert_called_once_with(123)


@patch('backend.services.invitation_service.query_invitation_by_code')
@patch('backend.services.invitation_service.count_invitation_usage')
def test_check_invitation_available_success(mock_count_usage, mock_query_invitation_by_code):
    """Test check_invitation_available success case"""
    mock_query_invitation_by_code.return_value = {
        "invitation_id": 123,
        "status": "IN_USE",
        "capacity": 5
    }
    mock_count_usage.return_value = 2  # Below capacity

    result = check_invitation_available("ABC123")

    assert result is True
    mock_query_invitation_by_code.assert_called_once_with("ABC123")
    mock_count_usage.assert_called_once_with(123)


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


@patch('backend.services.invitation_service.check_invitation_available')
@patch('backend.services.invitation_service.query_invitation_by_code')
def test_use_invitation_code_double_check_not_found(mock_query_invitation_by_code, mock_check_available):
    """Test use_invitation_code double check logic when invitation not found (lines 267-268)"""
    # First check passes
    mock_check_available.return_value = True
    # But second check fails (double-check logic)
    mock_query_invitation_by_code.return_value = None

    with pytest.raises(NotFoundException, match="not found"):
        use_invitation_code(
            invitation_code="ABC123",
            user_id="test_user"
        )

    # Verify both functions are called
    mock_check_available.assert_called_once_with("ABC123")
    mock_query_invitation_by_code.assert_called_once_with("ABC123")


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


@patch('backend.services.invitation_service.query_invitation_by_id')
def test_update_invitation_code_status_invitation_not_found(mock_query_invitation_by_id):
    """Test update_invitation_code_status when invitation not found (lines 304-305)"""
    mock_query_invitation_by_id.return_value = None

    result = update_invitation_code_status(999)

    assert result is False
    mock_query_invitation_by_id.assert_called_once_with(999)


@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.count_invitation_usage')
def test_update_invitation_code_status_invalid_expiry_date(mock_count_invitation_usage, mock_query_invitation_by_id):
    """Test update_invitation_code_status with invalid expiry date handling (lines 317-327)"""
    # Mock invitation with invalid expiry date
    mock_query_invitation_by_id.return_value = {
        "invitation_id": 123,
        "expiry_date": "invalid-date-format",
        "capacity": 5,
        "status": "IN_USE"
    }
    mock_count_invitation_usage.return_value = 2

    result = update_invitation_code_status(123)

    # Should return False because status didn't change and invalid date was logged but not crashed
    assert result is False
    mock_query_invitation_by_id.assert_called_once_with(123)
    mock_count_invitation_usage.assert_called_once_with(123)


@patch('backend.services.invitation_service.query_invitation_by_id')
@patch('backend.services.invitation_service.count_invitation_usage')
def test_update_invitation_code_status_no_change(mock_count_invitation_usage, mock_query_invitation_by_id):
    """Test update_invitation_code_status when status doesn't change (line 343)"""
    from datetime import datetime

    # Mock invitation that's not expired and not at capacity
    future_date = datetime.now().replace(year=datetime.now().year + 1).isoformat()
    mock_query_invitation_by_id.return_value = {
        "invitation_id": 123,
        "expiry_date": future_date,
        "capacity": 10,
        "status": "IN_USE"
    }
    mock_count_invitation_usage.return_value = 5  # Well below capacity

    result = update_invitation_code_status(123)

    # Should return False because status didn't change
    assert result is False
    mock_query_invitation_by_id.assert_called_once_with(123)
    mock_count_invitation_usage.assert_called_once_with(123)


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


@patch('backend.services.invitation_service.query_invitation_by_code')
def test_generate_unique_invitation_code_uniqueness_logic(mock_query_invitation_by_code):
    """Test _generate_unique_invitation_code uniqueness logic (line 359)"""
    # Mock that first two codes exist, third doesn't
    mock_query_invitation_by_code.side_effect = [True, True, None]

    with patch('random.choices') as mock_random:
        # First call returns existing code, second call also returns existing code, third call succeeds
        mock_random.side_effect = [
            ['A', 'B', 'C', '1', '2', '3'],  # First attempt - exists
            ['D', 'E', 'F', '4', '5', '6'],  # Second attempt - exists
            ['G', 'H', 'I', '7', '8', '9']   # Third attempt - doesn't exist
        ]

        result = _generate_unique_invitation_code()

        assert result == "GHI789"
        assert len(result) == 6
        # Should be called 3 times: twice for existing codes, once for success
        assert mock_query_invitation_by_code.call_count == 3


@patch('backend.services.invitation_service.query_invitation_by_code')
def test_generate_unique_invitation_code_max_attempts_exception(mock_query_invitation_by_code):
    """Test _generate_unique_invitation_code max attempts exception (line 369)"""
    # Mock that all codes exist (never find a unique one)
    mock_query_invitation_by_code.return_value = True

    with patch('random.choices') as mock_random:
        mock_random.return_value = ['A', 'B', 'C', '1', '2', '3']

        with pytest.raises(RuntimeError, match="Failed to generate unique invitation code after 100 attempts"):
            _generate_unique_invitation_code()

        # Should be called 100 times (max_attempts)
        assert mock_query_invitation_by_code.call_count == 100


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
