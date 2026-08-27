import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from sdk.nexent.core.tools.serply_search_tool import SerplySearchTool
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.fixture
def mock_observer():
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def serply_search_tool(mock_observer):
    return SerplySearchTool(
        serply_api_key="test_api_key",
        observer=mock_observer,
        max_results=3,
    )


def create_mock_serply_response(count=3):
    """Helper method to create a mock Serply API response"""
    results = [
        {
            "title": f"Test Title {i}",
            "link": f"https://example.com/{i}",
            "description": f"This is test content {i}",
        }
        for i in range(count)
    ]
    return {"results": results}


def test_forward_with_results(serply_search_tool, mock_observer):
    """Test forward method with search results"""
    mock_response = MagicMock()
    mock_response.json.return_value = create_mock_serply_response(3)
    mock_response.raise_for_status.return_value = None

    with patch("sdk.nexent.core.tools.serply_search_tool.httpx.get", return_value=mock_response) as mock_get:
        result = serply_search_tool.forward("test query")

    search_results = json.loads(result)

    called_headers = mock_get.call_args.kwargs["headers"]
    assert called_headers["X-Api-Key"] == "test_api_key"
    assert "User-Agent" in called_headers

    called_params = mock_get.call_args.kwargs["params"]
    assert called_params == {"q": "test query", "num": 3}

    mock_observer.add_message.assert_any_call(
        "", ProcessType.CARD,
        json.dumps([{"icon": "search", "text": "test query"}], ensure_ascii=False)
    )

    assert len(search_results) == 3
    first_result = search_results[0]
    assert first_result["title"] == "Test Title 0"
    assert first_result["text"].startswith("This is test content")
    assert isinstance(first_result["index"], str)


def test_forward_no_results(serply_search_tool):
    """Test forward method with no search results"""
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.raise_for_status.return_value = None

    with patch("sdk.nexent.core.tools.serply_search_tool.httpx.get", return_value=mock_response), \
            pytest.raises(Exception) as excinfo:
        serply_search_tool.forward("test query")

    assert "No results found" in str(excinfo.value)


def test_forward_without_observer():
    """Test forward method without an observer"""
    tool = SerplySearchTool(serply_api_key="test_api_key", observer=None, max_results=2)

    mock_response = MagicMock()
    mock_response.json.return_value = create_mock_serply_response(2)
    mock_response.raise_for_status.return_value = None

    with patch("sdk.nexent.core.tools.serply_search_tool.httpx.get", return_value=mock_response):
        result = tool.forward("test query")

    search_results = json.loads(result)
    assert len(search_results) == 2


def test_forward_http_error(serply_search_tool):
    """Test forward method when the Serply API returns an HTTP error"""
    with patch("sdk.nexent.core.tools.serply_search_tool.httpx.get", side_effect=httpx.RequestError("boom")), \
            pytest.raises(Exception) as excinfo:
        serply_search_tool.forward("test query")

    assert "Serply API request failed" in str(excinfo.value)


def test_forward_http_status_error(serply_search_tool):
    """Test forward method when the Serply API returns a non-2xx status"""
    request = httpx.Request("GET", "https://api.serply.io/v1/search/")
    response = httpx.Response(401, request=request)
    with patch("sdk.nexent.core.tools.serply_search_tool.httpx.get", return_value=response), \
            pytest.raises(Exception) as excinfo:
        serply_search_tool.forward("test query")

    assert "Serply API HTTP error" in str(excinfo.value)
    assert "401" in str(excinfo.value)


def test_forward_invalid_json(serply_search_tool):
    """Test forward method when the Serply API returns a non-JSON body"""
    request = httpx.Request("GET", "https://api.serply.io/v1/search/")
    response = httpx.Response(200, content=b"not json", request=request)
    with patch("sdk.nexent.core.tools.serply_search_tool.httpx.get", return_value=response), \
            pytest.raises(Exception) as excinfo:
        serply_search_tool.forward("test query")

    assert "Failed to parse Serply API response" in str(excinfo.value)


def test_forward_results_not_a_list(serply_search_tool):
    """Test forward method when the Serply API returns a malformed results field"""
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": {"unexpected": "shape"}}
    with patch("sdk.nexent.core.tools.serply_search_tool.httpx.get", return_value=mock_response), \
            pytest.raises(Exception) as excinfo:
        serply_search_tool.forward("test query")

    assert "No results found" in str(excinfo.value)
