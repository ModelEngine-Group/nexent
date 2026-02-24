import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Patch boto3 before importing backend modules (some services may rely on it)
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import target endpoints with all external dependencies patched
from backend.apps.conversation_management_app import (
    create_new_conversation_endpoint,
    list_conversations_endpoint,
    rename_conversation_endpoint,
    delete_conversation_endpoint,
    get_conversation_history_endpoint,
    get_sources_endpoint,
    generate_conversation_title_endpoint,
    update_opinion_endpoint,
    get_message_id_endpoint,
)


# -----------------------------
# Fixtures
# -----------------------------

@pytest.fixture
def conversation_mocks():
    """Provide fresh mocks for each conversation management test"""
    with patch('backend.apps.conversation_management_app.get_current_user_id') as mock_get_current_user_id, \
            patch('backend.apps.conversation_management_app.create_new_conversation') as mock_create_new_conv, \
            patch('backend.apps.conversation_management_app.get_conversation_list_service') as mock_get_conv_list, \
            patch('backend.apps.conversation_management_app.rename_conversation_service') as mock_rename_conv, \
            patch('backend.apps.conversation_management_app.logging') as mock_logging, \
            patch('backend.apps.conversation_management_app.delete_conversation_service') as mock_delete_conv, \
            patch('backend.apps.conversation_management_app.get_conversation_history_service') as mock_history_service, \
            patch('backend.apps.conversation_management_app.get_sources_service') as mock_sources_service, \
            patch('backend.apps.conversation_management_app.generate_conversation_title_service') as mock_generate_title_service, \
            patch('backend.apps.conversation_management_app.update_message_opinion_service') as mock_update_opinion_service, \
            patch('backend.apps.conversation_management_app.get_message_id_by_index_impl') as mock_get_msg_id_impl, \
            patch('backend.apps.conversation_management_app.get_current_user_info') as mock_get_user_info:

        yield {
            'get_current_user_id': mock_get_current_user_id,
            'create_new_convo': mock_create_new_conv,
            'get_conversation_list': mock_get_conv_list,
            'rename_conversation': mock_rename_conv,
            'logging': mock_logging,
            'delete_conversation': mock_delete_conv,
            'history_service': mock_history_service,
            'sources_service': mock_sources_service,
            'generate_title_service': mock_generate_title_service,
            'update_opinion_service': mock_update_opinion_service,
            'get_message_id_impl': mock_get_msg_id_impl,
            'get_user_info': mock_get_user_info,
        }


# -----------------------------
# Test Cases
# -----------------------------

@pytest.mark.asyncio
async def test_create_new_conversation_success(conversation_mocks):
    """Verify successful conversation creation"""
    # Arrange
    mock_auth_header = "Bearer test-token"
    conversation_title = "New Conversation"
    dummy_response = {
        "conversation_id": 1,
        "conversation_title": conversation_title,
        "create_time": 1234567890,
        "update_time": 1234567890,
    }

    # Setup mocks
    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['create_new_convo'].return_value = dummy_response

    # Use a simple object with a .title attribute to satisfy the endpoint signature
    request_obj = MagicMock()
    request_obj.title = conversation_title

    # Act
    result = await create_new_conversation_endpoint(request_obj, authorization=mock_auth_header)

    # Assert
    assert result.code == 0
    assert result.data == dummy_response
    conversation_mocks['get_current_user_id'].assert_called_once_with(
        mock_auth_header)
    conversation_mocks['create_new_convo'].assert_called_once_with(
        conversation_title, "user_id")


@pytest.mark.asyncio
async def test_create_new_conversation_failure(conversation_mocks):
    """Verify endpoint handles exception during conversation creation"""
    mock_auth_header = "Bearer test-token"
    conversation_title = "New Conversation"

    # Setup mocks
    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['create_new_convo'].side_effect = Exception(
        "creation error")

    request_obj = MagicMock()
    request_obj.title = conversation_title

    with pytest.raises(HTTPException) as exc_info:
        await create_new_conversation_endpoint(request_obj, authorization=mock_auth_header)

    assert exc_info.value.status_code == 500
    assert "creation error" in str(exc_info.value.detail)
    conversation_mocks['logging'].error.assert_called_once()


@pytest.mark.asyncio
async def test_list_conversations_success(conversation_mocks):
    """Verify successful retrieval of conversation list"""
    # Arrange
    mock_auth_header = "Bearer test-token"
    dummy_list = [
        {"conversation_id": 1, "conversation_title": "Chat 1"},
        {"conversation_id": 2, "conversation_title": "Chat 2"},
    ]

    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['get_conversation_list'].return_value = dummy_list

    # Act
    result = await list_conversations_endpoint(authorization=mock_auth_header)

    # Assert
    assert result.code == 0
    assert result.data == dummy_list
    conversation_mocks['get_current_user_id'].assert_called_once_with(
        mock_auth_header)
    conversation_mocks['get_conversation_list'].assert_called_once_with(
        "user_id")


@pytest.mark.asyncio
async def test_list_conversations_unauthorized(conversation_mocks):
    """Ensure unauthorized access raises HTTPException"""
    # Arrange
    mock_auth_header = "Bearer invalid-token"
    conversation_mocks['get_current_user_id'].return_value = (None, None)

    # Act / Assert
    with pytest.raises(HTTPException) as exc_info:
        await list_conversations_endpoint(authorization=mock_auth_header)

    assert exc_info.value.status_code == 500
    assert "Unauthorized access" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rename_conversation_success(conversation_mocks):
    """Verify successful conversation rename"""
    # Arrange
    mock_auth_header = "Bearer test-token"
    conversation_id = 1
    new_title = "Renamed Conversation"

    # Setup mocks
    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    # rename_conversation_service returns None, indicating success

    # Create a request-like object with required attributes
    request_obj = MagicMock()
    request_obj.conversation_id = conversation_id
    request_obj.name = new_title

    # Act
    result = await rename_conversation_endpoint(request_obj, authorization=mock_auth_header)

    # Assert
    assert result.code == 0
    assert result.data is True
    conversation_mocks['get_current_user_id'].assert_called_once_with(
        mock_auth_header)
    conversation_mocks['rename_conversation'].assert_called_once_with(
        conversation_id, new_title, "user_id")


# -----------------------------
# Error Case for Rename
# -----------------------------


@pytest.mark.asyncio
async def test_rename_conversation_failure(conversation_mocks):
    """Verify rename endpoint handles exceptions correctly"""
    # Arrange
    mock_auth_header = "Bearer test-token"
    conversation_id = 1
    new_title = "Broken Title"

    # Setup mocks
    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['rename_conversation'].side_effect = Exception(
        "DB error")

    request_obj = MagicMock()
    request_obj.conversation_id = conversation_id
    request_obj.name = new_title

    # Act / Assert
    with pytest.raises(HTTPException) as exc_info:
        await rename_conversation_endpoint(request_obj, authorization=mock_auth_header)

    assert exc_info.value.status_code == 500
    assert "DB error" in str(exc_info.value.detail)
    conversation_mocks['logging'].error.assert_called_once()


# -----------------------------
# Additional Endpoints Tests
# -----------------------------


# delete_conversation_endpoint


@pytest.mark.asyncio
async def test_delete_conversation_success(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    conversation_id = 1

    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")

    result = await delete_conversation_endpoint(conversation_id, authorization=mock_auth_header)

    assert result.code == 0 and result.data is True
    conversation_mocks['delete_conversation'].assert_called_once_with(
        conversation_id, "user_id")


@pytest.mark.asyncio
async def test_delete_conversation_failure(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    conversation_id = 1

    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['delete_conversation'].side_effect = Exception(
        "delete error")

    with pytest.raises(HTTPException) as exc_info:
        await delete_conversation_endpoint(conversation_id, authorization=mock_auth_header)

    assert exc_info.value.status_code == 500
    conversation_mocks['logging'].error.assert_called_once()


# get_conversation_history_endpoint


@pytest.mark.asyncio
async def test_get_history_success(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    conversation_id = 1
    dummy_history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['history_service'].return_value = dummy_history

    result = await get_conversation_history_endpoint(conversation_id, authorization=mock_auth_header)

    assert result.code == 0 and result.data == dummy_history
    conversation_mocks['history_service'].assert_called_once_with(
        conversation_id, "user_id")


@pytest.mark.asyncio
async def test_get_history_failure(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    conversation_id = 1
    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['history_service'].side_effect = Exception(
        "history error")

    with pytest.raises(HTTPException) as exc_info:
        await get_conversation_history_endpoint(conversation_id, authorization=mock_auth_header)

    assert exc_info.value.status_code == 500
    conversation_mocks['logging'].error.assert_called_once()


# get_sources_endpoint


@pytest.mark.asyncio
async def test_get_sources_success(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    req_body = {"conversation_id": 1, "message_id": 2, "type": "all"}
    dummy_sources = {"images": [], "search": []}

    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['sources_service'].return_value = dummy_sources

    result = await get_sources_endpoint(req_body, authorization=mock_auth_header)

    assert result == dummy_sources
    conversation_mocks['sources_service'].assert_called_once_with(
        1, 2, "all", "user_id")


@pytest.mark.asyncio
async def test_get_sources_failure(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    req_body = {"conversation_id": 1, "message_id": 2}

    conversation_mocks['get_current_user_id'].return_value = (
        "user_id", "tenant_id")
    conversation_mocks['sources_service'].side_effect = Exception("src error")

    with pytest.raises(HTTPException) as exc_info:
        await get_sources_endpoint(req_body, authorization=mock_auth_header)

    assert exc_info.value.status_code == 500
    conversation_mocks['logging'].error.assert_called_once()


# generate_conversation_title_endpoint


@pytest.mark.asyncio
async def test_generate_title_success(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    conversation_id = 1
    question = "How to use Python effectively?"
    dummy_title = "Python Tips"

    # get_current_user_info returns (user_id, tenant_id, language)
    conversation_mocks['get_user_info'].return_value = (
        "user_id", "tenant_id", "en")
    conversation_mocks['generate_title_service'].return_value = dummy_title

    request_obj = MagicMock()
    request_obj.conversation_id = conversation_id
    request_obj.question = question

    http_request = MagicMock()

    result = await generate_conversation_title_endpoint(request_obj, http_request, authorization=mock_auth_header)

    assert result.code == 0 and result.data == dummy_title
    conversation_mocks['generate_title_service'].assert_called_once_with(
        conversation_id, question, "user_id", tenant_id="tenant_id", language="en")


@pytest.mark.asyncio
async def test_generate_title_failure(conversation_mocks):
    mock_auth_header = "Bearer test-token"
    request_obj = MagicMock()
    request_obj.conversation_id = 1
    request_obj.question = "Test question"
    http_request = MagicMock()

    conversation_mocks['get_user_info'].side_effect = Exception("auth fail")

    with pytest.raises(HTTPException) as exc_info:
        await generate_conversation_title_endpoint(request_obj, http_request, authorization=mock_auth_header)

    assert exc_info.value.status_code == 500
    conversation_mocks['logging'].error.assert_called_once()


# update_opinion_endpoint


@pytest.mark.asyncio
async def test_update_opinion_success(conversation_mocks):
    request_obj = MagicMock()
    request_obj.message_id = 5
    request_obj.opinion = "like"

    result = await update_opinion_endpoint(request_obj)

    assert result.code == 0 and result.data is True
    conversation_mocks['update_opinion_service'].assert_called_once_with(
        5, "like")


@pytest.mark.asyncio
async def test_update_opinion_failure(conversation_mocks):
    request_obj = MagicMock()
    request_obj.message_id = 5
    request_obj.opinion = "like"

    conversation_mocks['update_opinion_service'].side_effect = Exception(
        "opinion error")

    with pytest.raises(HTTPException) as exc_info:
        await update_opinion_endpoint(request_obj)

    assert exc_info.value.status_code == 500
    conversation_mocks['logging'].error.assert_called_once()


# get_message_id_endpoint


@pytest.mark.asyncio
async def test_get_message_id_success(conversation_mocks):
    request_obj = MagicMock()
    request_obj.conversation_id = 1
    request_obj.message_index = 3

    conversation_mocks['get_message_id_impl'].return_value = 99

    result = await get_message_id_endpoint(request_obj)

    assert result.code == 0 and result.data == 99
    conversation_mocks['get_message_id_impl'].assert_called_once_with(
        request_obj.conversation_id, request_obj.message_index)


@pytest.mark.asyncio
async def test_get_message_id_failure(conversation_mocks):
    request_obj = MagicMock()
    request_obj.conversation_id = 1
    request_obj.message_index = 3

    conversation_mocks['get_message_id_impl'].side_effect = Exception(
        "msg id error")

    with pytest.raises(HTTPException) as exc_info:
        await get_message_id_endpoint(request_obj)

    assert exc_info.value.status_code == 500
    conversation_mocks['logging'].error.assert_called_once()
