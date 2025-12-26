import backend.services.me_model_management_service as svc
from consts.exceptions import MEConnectionException, TimeoutException
import sys
import os
import asyncio

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

# Add the project root directory to sys.path
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../../..')))


@pytest.mark.asyncio
async def test_check_me_variable_set_truthy_when_both_present():
    # Patch service module constants to have non-empty values
    with patch.object(svc, 'MODEL_ENGINE_API_KEY', 'k'), \
            patch.object(svc, 'MODEL_ENGINE_HOST', 'http://mock-model-engine-host'):
        assert await svc.check_me_variable_set()

@pytest.mark.asyncio
async def test_check_me_variable_set_falsy_when_host_missing():
    with patch.object(svc, 'MODEL_ENGINE_API_KEY', 'k'), \
            patch.object(svc, 'MODEL_ENGINE_HOST', ''):
        assert not await svc.check_me_variable_set()


@pytest.mark.asyncio
async def test_check_me_connectivity_success():
    """Test successful ME connectivity check"""
    with patch.object(svc, 'MODEL_ENGINE_API_KEY', 'mock-api-key'), \
            patch.object(svc, 'MODEL_ENGINE_HOST', 'https://me-host.com'), \
            patch('backend.services.me_model_management_service.aiohttp.ClientSession') as mock_session_class:

        # Create mock response
        mock_response = AsyncMock()
        mock_response.status = 200

        # Create mock session
        mock_session = AsyncMock()
        mock_get = AsyncMock()
        mock_get.__aenter__.return_value = mock_response
        mock_session.get = MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Execute
        result = await svc.check_me_connectivity(timeout=30)

        # Assert
        assert result is True


@pytest.mark.asyncio
async def test_check_me_connectivity_http_error():
    """Test ME connectivity check with HTTP error response"""
    with patch.object(svc, 'MODEL_ENGINE_API_KEY', 'mock-api-key'), \
            patch.object(svc, 'MODEL_ENGINE_HOST', 'https://me-host.com'), \
            patch('backend.services.me_model_management_service.aiohttp.ClientSession') as mock_session_class:

        # Create mock response with error status
        mock_response = AsyncMock()
        mock_response.status = 500

        # Create mock session
        mock_session = AsyncMock()
        mock_get = AsyncMock()
        mock_get.__aenter__.return_value = mock_response
        mock_session.get = MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Execute and expect an exception
        with pytest.raises(MEConnectionException) as exc_info:
            await svc.check_me_connectivity(timeout=30)

        # Assert the exception message
        assert "Connection failed, error code: 500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_check_me_connectivity_timeout():
    """Test ME connectivity check with timeout error"""
    with patch.object(svc, 'MODEL_ENGINE_API_KEY', 'mock-api-key'), \
            patch.object(svc, 'MODEL_ENGINE_HOST', 'https://me-host.com'), \
            patch('backend.services.me_model_management_service.aiohttp.ClientSession') as mock_session_class:

        # Create mock session that raises TimeoutError
        mock_session = AsyncMock()
        mock_get = AsyncMock()
        mock_get.__aenter__.side_effect = asyncio.TimeoutError()
        mock_session.get = MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Execute and expect a TimeoutException
        with pytest.raises(TimeoutException) as exc_info:
            await svc.check_me_connectivity(timeout=30)

        # Assert the exception message
        assert "Connection timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_check_me_connectivity_variables_not_set():
    """Test ME connectivity check when environment variables not set"""
    with patch.object(svc, 'MODEL_ENGINE_API_KEY', ''), \
            patch.object(svc, 'MODEL_ENGINE_HOST', ''):

        # Execute - should return False when env vars not set
        result = await svc.check_me_connectivity(timeout=30)

        # Assert
        assert result is False


@pytest.mark.asyncio
async def test_check_me_connectivity_general_exception():
    """Test ME connectivity check with general exception (covers lines 54-55)"""
    with patch.object(svc, 'MODEL_ENGINE_API_KEY', 'mock-api-key'), \
            patch.object(svc, 'MODEL_ENGINE_HOST', 'https://me-host.com'), \
            patch('backend.services.me_model_management_service.aiohttp.ClientSession') as mock_session_class:

        # Create mock session that raises a general exception
        mock_session = AsyncMock()
        mock_get = AsyncMock()
        mock_get.__aenter__.side_effect = ValueError("Unexpected error")
        mock_session.get = MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Execute and expect a generic Exception
        with pytest.raises(Exception) as exc_info:
            await svc.check_me_connectivity(timeout=30)

        # Assert the exception message contains "Unknown error occurred"
        assert "Unknown error occurred" in str(exc_info.value)
        assert "Unexpected error" in str(exc_info.value)
