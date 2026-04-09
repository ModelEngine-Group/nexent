"""
Unit tests for iData Service Layer.

Tests the iData service functions which handle API calls to iData
for knowledge space and knowledge base operations.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
import httpx

from backend.consts.error_code import ErrorCode
from backend.consts.exceptions import AppException


def _create_mock_client(mock_response):
    """
    Create a properly configured mock client that works with the HttpClientManager.

    The http_client_manager.get_sync_client() returns a client instance directly.
    """
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    return mock_client


class TestValidateIdataBaseParams:
    """Test class for _validate_idata_base_params function."""

    def test_validate_idata_base_params_success(self):
        """Test validation with valid parameters."""
        from backend.services.idata_service import _validate_idata_base_params

        # Should not raise any exception
        _validate_idata_base_params(
            idata_api_base="https://idata.example.com",
            api_key="test-api-key",
            user_id="test-user-id"
        )

    def test_validate_idata_base_params_empty_api_base(self):
        """Test validation fails when API base is empty."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="",
                api_key="test-api-key",
                user_id="test-user-id"
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value
        assert "iData API URL is required" in str(exc_info.value)

    def test_validate_idata_base_params_none_api_base(self):
        """Test validation fails when API base is None."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base=None,
                api_key="test-api-key",
                user_id="test-user-id"
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_validate_idata_base_params_non_string_api_base(self):
        """Test validation fails when API base is not a string."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base=123,
                api_key="test-api-key",
                user_id="test-user-id"
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_validate_idata_base_params_invalid_scheme(self):
        """Test validation fails when API base doesn't start with http:// or https://."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="ftp://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id"
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value
        assert "must start with http:// or https://" in str(exc_info.value)

    def test_validate_idata_base_params_http_scheme(self):
        """Test validation succeeds with http:// scheme."""
        from backend.services.idata_service import _validate_idata_base_params

        # Should not raise any exception
        _validate_idata_base_params(
            idata_api_base="http://idata.example.com",
            api_key="test-api-key",
            user_id="test-user-id"
        )

    def test_validate_idata_base_params_https_scheme(self):
        """Test validation succeeds with https:// scheme."""
        from backend.services.idata_service import _validate_idata_base_params

        # Should not raise any exception
        _validate_idata_base_params(
            idata_api_base="https://idata.example.com",
            api_key="test-api-key",
            user_id="test-user-id"
        )

    def test_validate_idata_base_params_empty_api_key(self):
        """Test validation fails when API key is empty."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="https://idata.example.com",
                api_key="",
                user_id="test-user-id"
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value
        assert "iData API key is required" in str(exc_info.value)

    def test_validate_idata_base_params_none_api_key(self):
        """Test validation fails when API key is None."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="https://idata.example.com",
                api_key=None,
                user_id="test-user-id"
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_validate_idata_base_params_non_string_api_key(self):
        """Test validation fails when API key is not a string."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="https://idata.example.com",
                api_key=12345,
                user_id="test-user-id"
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_validate_idata_base_params_empty_user_id(self):
        """Test validation fails when user ID is empty."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id=""
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value
        assert "iData user ID is required" in str(exc_info.value)

    def test_validate_idata_base_params_none_user_id(self):
        """Test validation fails when user ID is None."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id=None
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_validate_idata_base_params_non_string_user_id(self):
        """Test validation fails when user ID is not a string."""
        from backend.services.idata_service import _validate_idata_base_params

        with pytest.raises(Exception) as exc_info:
            _validate_idata_base_params(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id=12345
            )
        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value


class TestNormalizeApiBase:
    """Test class for _normalize_api_base function."""

    def test_normalize_api_base_with_trailing_slash(self):
        """Test normalization removes trailing slash."""
        from backend.services.idata_service import _normalize_api_base

        result = _normalize_api_base("https://idata.example.com/")
        assert result == "https://idata.example.com"

    def test_normalize_api_base_without_trailing_slash(self):
        """Test normalization doesn't change URL without trailing slash."""
        from backend.services.idata_service import _normalize_api_base

        result = _normalize_api_base("https://idata.example.com")
        assert result == "https://idata.example.com"

    def test_normalize_api_base_multiple_trailing_slashes(self):
        """Test normalization removes multiple trailing slashes."""
        from backend.services.idata_service import _normalize_api_base

        result = _normalize_api_base("https://idata.example.com///")
        assert result == "https://idata.example.com"


class TestMakeIdataRequest:
    """Test class for _make_idata_request function."""

    def test_make_idata_request_success(self):
        """Test successful API request."""
        from backend.services.idata_service import _make_idata_request

        mock_response = MagicMock()
        mock_response.json.return_value = {"code": "1", "data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = _make_idata_request(
                api_base="https://idata.example.com",
                url="https://idata.example.com/api/test",
                headers={"Authorization": "Bearer token"},
                request_body={"userId": "user-1"}
            )

        assert result == {"code": "1", "data": []}
        mock_client.post.assert_called_once()
        mock_response.raise_for_status.assert_called_once()

    def test_make_idata_request_connection_error(self):
        """Test request error handling."""
        from backend.services.idata_service import _make_idata_request

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.RequestError("Connection failed")

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                _make_idata_request(
                    api_base="https://idata.example.com",
                    url="https://idata.example.com/api/test",
                    headers={},
                    request_body={}
                )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONNECTION_ERROR.value
        assert "iData API request failed" in str(exc_info.value)

    def test_make_idata_request_http_401_error(self):
        """Test HTTP 401 error handling."""
        from backend.services.idata_service import _make_idata_request

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_http_error = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=mock_response
        )

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_response.raise_for_status.side_effect = mock_http_error

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                _make_idata_request(
                    api_base="https://idata.example.com",
                    url="https://idata.example.com/api/test",
                    headers={},
                    request_body={}
                )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_AUTH_ERROR.value
        assert "iData authentication failed" in str(exc_info.value)

    def test_make_idata_request_http_403_error(self):
        """Test HTTP 403 error handling."""
        from backend.services.idata_service import _make_idata_request

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_http_error = httpx.HTTPStatusError(
            "Forbidden",
            request=MagicMock(),
            response=mock_response
        )

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_response.raise_for_status.side_effect = mock_http_error

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                _make_idata_request(
                    api_base="https://idata.example.com",
                    url="https://idata.example.com/api/test",
                    headers={},
                    request_body={}
                )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_AUTH_ERROR.value
        assert "iData access forbidden" in str(exc_info.value)

    def test_make_idata_request_http_429_error(self):
        """Test HTTP 429 error handling."""
        from backend.services.idata_service import _make_idata_request

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_http_error = httpx.HTTPStatusError(
            "Too Many Requests",
            request=MagicMock(),
            response=mock_response
        )

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_response.raise_for_status.side_effect = mock_http_error

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                _make_idata_request(
                    api_base="https://idata.example.com",
                    url="https://idata.example.com/api/test",
                    headers={},
                    request_body={}
                )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_RATE_LIMIT.value
        assert "iData API rate limit exceeded" in str(exc_info.value)

    def test_make_idata_request_http_500_error(self):
        """Test HTTP 500 error handling."""
        from backend.services.idata_service import _make_idata_request

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_error = httpx.HTTPStatusError(
            "Internal Server Error",
            request=MagicMock(),
            response=mock_response
        )

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_response.raise_for_status.side_effect = mock_http_error

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                _make_idata_request(
                    api_base="https://idata.example.com",
                    url="https://idata.example.com/api/test",
                    headers={},
                    request_body={}
                )

        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_SERVICE_ERROR.value
        assert "iData API HTTP error 500" in str(exc_info.value)

    def test_make_idata_request_json_decode_error(self):
        """Test JSON decode error handling."""
        from backend.services.idata_service import _make_idata_request

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                _make_idata_request(
                    api_base="https://idata.example.com",
                    url="https://idata.example.com/api/test",
                    headers={},
                    request_body={}
                )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_RESPONSE_ERROR.value
        assert "Failed to parse iData API response" in str(exc_info.value)


class TestParseIdataResponse:
    """Test class for _parse_idata_response function."""

    def test_parse_idata_response_success(self):
        """Test successful response parsing."""
        from backend.services.idata_service import _parse_idata_response

        result = {
            "code": "1",
            "msg": "Success",
            "data": [{"id": "1", "name": "Test"}],
            "msgParams": None
        }

        data = _parse_idata_response(result)
        assert data == [{"id": "1", "name": "Test"}]

    def test_parse_idata_response_error_code(self):
        """Test response parsing with error code."""
        from backend.services.idata_service import _parse_idata_response

        result = {
            "code": "0",
            "msg": "Error occurred",
            "data": []
        }

        with pytest.raises(Exception) as exc_info:
            _parse_idata_response(result)

        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_SERVICE_ERROR.value
        assert "iData API error: Error occurred" in str(exc_info.value)

    def test_parse_idata_response_error_code_no_msg(self):
        """Test response parsing with error code but no message."""
        from backend.services.idata_service import _parse_idata_response

        result = {
            "code": "0",
            "data": []
        }

        with pytest.raises(Exception) as exc_info:
            _parse_idata_response(result)

        assert hasattr(exc_info.value, 'error_code')
        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_SERVICE_ERROR.value
        assert "iData API error: Unknown error" in str(exc_info.value)

    def test_parse_idata_response_data_not_list(self):
        """Test response parsing when data is not a list."""
        from backend.services.idata_service import _parse_idata_response

        result = {
            "code": "1",
            "msg": "Success",
            "data": {"id": "1"}
        }

        with pytest.raises(Exception) as exc_info:
            _parse_idata_response(result)

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_RESPONSE_ERROR.value
        assert "data is not a list" in str(exc_info.value)

    def test_parse_idata_response_empty_data(self):
        """Test response parsing with empty data list."""
        from backend.services.idata_service import _parse_idata_response

        result = {
            "code": "1",
            "msg": "Success",
            "data": []
        }

        data = _parse_idata_response(result)
        assert data == []


class TestFetchIdataKnowledgeSpacesImpl:
    """Test class for fetch_idata_knowledge_spaces_impl function."""

    def test_fetch_idata_knowledge_spaces_impl_success(self):
        """Test successful fetching of knowledge spaces."""
        from backend.services.idata_service import fetch_idata_knowledge_spaces_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [
                {
                    "id": "6cbf949946bf4b769c073259406b04f8",
                    "name": "test1"
                },
                {
                    "id": "7dbf949946bf4b769c073259406b04f9",
                    "name": "test2"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_knowledge_spaces_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id"
            )

        assert len(result) == 2
        assert result[0]["id"] == "6cbf949946bf4b769c073259406b04f8"
        assert result[0]["name"] == "test1"
        assert result[1]["id"] == "7dbf949946bf4b769c073259406b04f9"
        assert result[1]["name"] == "test2"

        # Verify request was made correctly
        call_args = mock_client.post.call_args
        assert "/knowledgeSpaces/query" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-api-key"
        assert call_args[1]["json"]["userId"] == "test-user-id"

    def test_fetch_idata_knowledge_spaces_impl_with_trailing_slash(self):
        """Test fetching with API base URL that has trailing slash."""
        from backend.services.idata_service import fetch_idata_knowledge_spaces_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [{"id": "1", "name": "test"}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_knowledge_spaces_impl(
                idata_api_base="https://idata.example.com/",
                api_key="test-api-key",
                user_id="test-user-id"
            )

        assert len(result) == 1
        # Verify URL normalization worked (no double slash)
        call_args = mock_client.post.call_args
        assert "//apiaccess" not in call_args[0][0]

    def test_fetch_idata_knowledge_spaces_impl_empty_response(self):
        """Test fetching when API returns empty list."""
        from backend.services.idata_service import fetch_idata_knowledge_spaces_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": []
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_knowledge_spaces_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id"
            )

        assert result == []

    def test_fetch_idata_knowledge_spaces_impl_skips_invalid_items(self):
        """Test fetching skips items that are not dicts or missing required fields."""
        from backend.services.idata_service import fetch_idata_knowledge_spaces_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [
                {"id": "1", "name": "valid1"},
                "invalid_string",
                {"id": "2"},  # missing name
                {"name": "test"},  # missing id
                {"id": "3", "name": "valid2"},
                None,  # None item
                {"id": "", "name": "empty_id"},  # empty id
                {"id": "4", "name": ""}  # empty name
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_knowledge_spaces_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id"
            )

        # Only valid items should be included
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[0]["name"] == "valid1"
        assert result[1]["id"] == "3"
        assert result[1]["name"] == "valid2"

    def test_fetch_idata_knowledge_spaces_impl_validation_error(self):
        """Test fetching with invalid parameters raises validation error."""
        from backend.services.idata_service import fetch_idata_knowledge_spaces_impl

        with pytest.raises(Exception) as exc_info:
            fetch_idata_knowledge_spaces_impl(
                idata_api_base="",
                api_key="test-api-key",
                user_id="test-user-id"
            )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_fetch_idata_knowledge_spaces_impl_api_error(self):
        """Test fetching when API returns error code."""
        from backend.services.idata_service import fetch_idata_knowledge_spaces_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "0",
            "msg": "API Error",
            "data": []
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                fetch_idata_knowledge_spaces_impl(
                    idata_api_base="https://idata.example.com",
                    api_key="test-api-key",
                    user_id="test-user-id"
                )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_SERVICE_ERROR.value


class TestFetchIdataDatasetsImpl:
    """Test class for fetch_idata_datasets_impl function."""

    def test_fetch_idata_datasets_impl_success(self):
        """Test successful fetching of datasets."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [
                {
                    "id": "kb-1",
                    "name": "Knowledge Base 1",
                    "fileCount": 10
                },
                {
                    "id": "kb-2",
                    "name": "Knowledge Base 2",
                    "fileCount": 20
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1"
            )

        assert result["count"] == 2
        assert result["indices"] == ["kb-1", "kb-2"]
        assert len(result["indices_info"]) == 2

        # Verify first knowledge base
        assert result["indices_info"][0]["name"] == "kb-1"
        assert result["indices_info"][0]["display_name"] == "Knowledge Base 1"
        assert result["indices_info"][0]["stats"]["base_info"]["doc_count"] == 10
        assert result["indices_info"][0]["stats"]["base_info"]["process_source"] == "iData"

        # Verify second knowledge base
        assert result["indices_info"][1]["name"] == "kb-2"
        assert result["indices_info"][1]["display_name"] == "Knowledge Base 2"
        assert result["indices_info"][1]["stats"]["base_info"]["doc_count"] == 20
        assert result["indices_info"][1]["stats"]["base_info"]["process_source"] == "iData"

        # Verify request was made correctly
        call_args = mock_client.post.call_args
        assert "/knowledgeBases/query" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-api-key"
        assert call_args[1]["json"]["userId"] == "test-user-id"
        assert call_args[1]["json"]["knowledgeSpaceId"] == "space-1"

    def test_fetch_idata_datasets_impl_empty_response(self):
        """Test fetching when API returns empty list."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": []
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1"
            )

        assert result["count"] == 0
        assert result["indices"] == []
        assert result["indices_info"] == []

    def test_fetch_idata_datasets_impl_skips_invalid_items(self):
        """Test fetching skips items that are not dicts or missing id."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [
                {"id": "kb-1", "name": "KB 1", "fileCount": 5},
                "invalid_string",
                {"name": "KB 2", "fileCount": 10},  # missing id
                {"id": "", "name": "KB 3", "fileCount": 15},  # empty id
                {"id": "kb-4", "name": "KB 4", "fileCount": 20},
                None  # None item
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1"
            )

        # Only valid items should be included
        assert result["count"] == 2
        assert result["indices"] == ["kb-1", "kb-4"]
        assert len(result["indices_info"]) == 2

    def test_fetch_idata_datasets_impl_missing_file_count(self):
        """Test fetching handles missing fileCount field."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [
                {
                    "id": "kb-1",
                    "name": "Knowledge Base 1"
                    # fileCount missing
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1"
            )

        assert result["count"] == 1
        assert result["indices_info"][0]["stats"]["base_info"]["doc_count"] == 0

    def test_fetch_idata_datasets_impl_missing_name(self):
        """Test fetching handles missing name field."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [
                {
                    "id": "kb-1",
                    "fileCount": 10
                    # name missing
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1"
            )

        assert result["count"] == 1
        assert result["indices_info"][0]["display_name"] == ""

    def test_fetch_idata_datasets_impl_validation_error_api_base(self):
        """Test fetching with invalid API base raises validation error."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        with pytest.raises(Exception) as exc_info:
            fetch_idata_datasets_impl(
                idata_api_base="",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1"
            )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_fetch_idata_datasets_impl_validation_error_knowledge_space_id_empty(self):
        """Test fetching with empty knowledge space ID raises validation error."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        with pytest.raises(Exception) as exc_info:
            fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id=""
            )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value
        assert "Knowledge space ID is required" in str(exc_info.value)

    def test_fetch_idata_datasets_impl_validation_error_knowledge_space_id_none(self):
        """Test fetching with None knowledge space ID raises validation error."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        with pytest.raises(Exception) as exc_info:
            fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id=None
            )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_fetch_idata_datasets_impl_validation_error_knowledge_space_id_non_string(self):
        """Test fetching with non-string knowledge space ID raises validation error."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        with pytest.raises(Exception) as exc_info:
            fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id=12345
            )

        assert hasattr(exc_info.value, 'error_code')
        assert exc_info.value.error_code.value == ErrorCode.IDATA_CONFIG_INVALID.value

    def test_fetch_idata_datasets_impl_with_trailing_slash(self):
        """Test fetching with API base URL that has trailing slash."""
        from backend.services.idata_service import fetch_idata_datasets_impl

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "msg": "Success",
            "data": [{"id": "kb-1", "name": "KB 1", "fileCount": 5}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.idata_service.http_client_manager') as mock_manager:
            mock_manager.get_sync_client.return_value = mock_client

            result = fetch_idata_datasets_impl(
                idata_api_base="https://idata.example.com/",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1"
            )

        assert result["count"] == 1
        # Verify URL normalization worked (no double slash)
        call_args = mock_client.post.call_args
        assert "//apiaccess" not in call_args[0][0]
