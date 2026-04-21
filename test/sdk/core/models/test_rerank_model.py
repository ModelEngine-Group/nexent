import asyncio
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# Add SDK to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sdk_dir = os.path.abspath(os.path.join(current_dir, "../../../sdk"))
sys.path.insert(0, sdk_dir)


class TestOpenAICompatibleRerank:
    """Test cases for OpenAICompatibleRerank class."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key-123",
            ssl_verify=True
        )

        assert rerank.model == "gte-rerank-v1"
        assert rerank.api_url == "https://api.example.com/v1/rerank"
        assert rerank.api_key == "test-key-123"
        assert rerank.ssl_verify is True
        assert rerank.headers["Authorization"] == "Bearer test-key-123"

    def test_init_with_default_ssl_verify(self):
        """Test initialization with default ssl_verify."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        assert rerank.ssl_verify is True

    def test_prepare_request_dashscope_format(self):
        """Test request preparation for DashScope API format."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="qwen3-rerank",
            base_url="https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank",
            api_key="test-key"
        )

        result = rerank._prepare_request(
            query="test query",
            documents=["doc1", "doc2", "doc3"],
            top_n=3
        )

        assert result["model"] == "qwen3-rerank"
        assert result["input"]["query"] == "test query"
        assert result["input"]["documents"] == ["doc1", "doc2", "doc3"]
        assert result["parameters"]["top_n"] == 3

    def test_prepare_request_openai_format(self):
        """Test request preparation for OpenAI-compatible API format."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.openai.com/v1/rerank",
            api_key="test-key"
        )

        result = rerank._prepare_request(
            query="test query",
            documents=["doc1", "doc2"],
            top_n=2
        )

        assert result["model"] == "gte-rerank-v1"
        assert result["query"] == "test query"
        assert result["documents"] == ["doc1", "doc2"]
        assert result["top_n"] == 2

    def test_prepare_request_with_default_top_n(self):
        """Test request preparation with default top_n (uses document count)."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key"
        )

        result = rerank._prepare_request(
            query="query",
            documents=["a", "b", "c", "d"]
        )

        assert result["top_n"] == 4

    @patch('nexent.core.models.rerank_model.requests.post')
    def test_rerank_openai_format_success(self, mock_post):
        """Test successful rerank with OpenAI format response."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.95, "document": "doc1"},
                {"index": 2, "relevance_score": 0.85, "document": "doc3"},
                {"index": 1, "relevance_score": 0.75, "document": "doc2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key"
        )

        results = rerank.rerank(
            query="test query",
            documents=["doc1", "doc2", "doc3"],
            top_n=3
        )

        assert len(results) == 3
        assert results[0]["index"] == 0
        assert results[0]["relevance_score"] == 0.95
        assert results[0]["document"] == "doc1"

    @patch('nexent.core.models.rerank_model.requests.post')
    def test_rerank_dashscope_format_success(self, mock_post):
        """Test successful rerank with DashScope format response."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "output": {
                "results": [
                    {"index": 1, "relevance_score": 0.9, "document": {"text": "doc2"}},
                    {"index": 0, "relevance_score": 0.8, "document": {"text": "doc1"}},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        rerank = OpenAICompatibleRerank(
            model_name="qwen3-rerank",
            base_url="https://dashscope.aliyuncs.com/api/v1/services/rerank",
            api_key="test-key"
        )

        results = rerank.rerank(
            query="test query",
            documents=["doc1", "doc2"]
        )

        assert len(results) == 2
        assert results[0]["index"] == 1
        assert results[0]["document"] == "doc2"

    def test_rerank_empty_documents(self):
        """Test rerank with empty documents list."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        results = rerank.rerank(query="query", documents=[])

        assert results == []

    @patch('nexent.core.models.rerank_model.requests.post')
    def test_rerank_timeout_retry(self, mock_post):
        """Test rerank with timeout and retry logic."""
        import requests
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        # First two calls timeout, third succeeds
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        mock_post.side_effect = [
            requests.exceptions.Timeout(),
            requests.exceptions.Timeout(),
            mock_response
        ]

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        # Should eventually succeed after retries
        results = rerank.rerank(query="test", documents=["doc1"])
        assert results == []
        assert mock_post.call_count == 3

    @patch('nexent.core.models.rerank_model.requests.post')
    def test_rerank_request_exception(self, mock_post):
        """Test rerank with request exception."""
        import requests
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        mock_post.side_effect = requests.exceptions.RequestException("Connection error")

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        with pytest.raises(requests.exceptions.RequestException):
            rerank.rerank(query="test", documents=["doc1"])

    @pytest.mark.asyncio
    @patch('nexent.core.models.rerank_model.requests.post')
    async def test_connectivity_check_success(self, mock_post):
        """Test connectivity check with successful connection."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": [{"index": 0, "relevance_score": 0.9, "document": "test"}]}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        result = await rerank.connectivity_check(timeout=5.0)

        assert result is True

    @pytest.mark.asyncio
    @patch('nexent.core.models.rerank_model.requests.post')
    async def test_connectivity_check_timeout(self, mock_post):
        """Test connectivity check with timeout."""
        import requests
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        mock_post.side_effect = requests.exceptions.Timeout()

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        result = await rerank.connectivity_check(timeout=5.0)

        assert result is False

    @pytest.mark.asyncio
    @patch('nexent.core.models.rerank_model.requests.post')
    async def test_connectivity_check_connection_error(self, mock_post):
        """Test connectivity check with connection error."""
        import requests
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        mock_post.side_effect = requests.exceptions.ConnectionError()

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        result = await rerank.connectivity_check(timeout=5.0)

        assert result is False

    @pytest.mark.asyncio
    @patch('nexent.core.models.rerank_model.requests.post')
    async def test_connectivity_check_generic_error(self, mock_post):
        """Test connectivity check with generic error."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        mock_post.side_effect = Exception("Unknown error")

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        result = await rerank.connectivity_check(timeout=5.0)

        assert result is False

    @pytest.mark.asyncio
    @patch('nexent.core.models.rerank_model.requests.post')
    async def test_rerank_async(self, mock_post):
        """Test async rerank method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": [{"index": 0, "relevance_score": 0.9, "document": "test"}]}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="test-model",
            base_url="https://api.example.com",
            api_key="test-key"
        )

        results = await rerank.rerank_async(
            query="test query",
            documents=["doc1", "doc2"]
        )

        assert len(results) == 1
        assert results[0]["index"] == 0


class TestJinaRerank:
    """Test cases for JinaRerank class."""

    def test_init(self):
        """Test JinaRerank initialization."""
        from nexent.core.models.rerank_model import JinaRerank

        rerank = JinaRerank(
            api_key="jina-api-key",
            model_name="jina-rerank-v2-base",
            base_url="https://api.jina.ai/v1/rerank"
        )

        assert rerank.model == "jina-rerank-v2-base"
        assert rerank.api_url == "https://api.jina.ai/v1/rerank"
        assert rerank.api_key == "jina-api-key"

    def test_init_with_defaults(self):
        """Test JinaRerank initialization with default values."""
        from nexent.core.models.rerank_model import JinaRerank

        rerank = JinaRerank(api_key="test-key")

        assert rerank.model == "jina-rerank-v2-base"
        assert rerank.api_url == "https://api.jina.ai/v1/rerank"


class TestCohereRerank:
    """Test cases for CohereRerank class."""

    def test_init(self):
        """Test CohereRerank initialization."""
        from nexent.core.models.rerank_model import CohereRerank

        rerank = CohereRerank(
            api_key="cohere-api-key",
            model_name="rerank-multilingual-v3.0",
            base_url="https://api.cohere.ai/v1/rerank"
        )

        assert rerank.model == "rerank-multilingual-v3.0"
        assert rerank.api_url == "https://api.cohere.ai/v1/rerank"
        assert rerank.api_key == "cohere-api-key"

    def test_init_with_defaults(self):
        """Test CohereRerank initialization with default values."""
        from nexent.core.models.rerank_model import CohereRerank

        rerank = CohereRerank(api_key="test-key")

        assert rerank.model == "rerank-multilingual-v3.0"
        assert rerank.api_url == "https://api.cohere.ai/v1/rerank"


class TestBaseRerank:
    """Test cases for BaseRerank abstract class."""

    def test_base_class_is_abstract(self):
        """Test that BaseRerank cannot be instantiated directly."""
        from nexent.core.models.rerank_model import BaseRerank

        with pytest.raises(TypeError):
            BaseRerank()


class TestOpenAICompatibleRerankEdgeCases:
    """Additional edge case tests for OpenAICompatibleRerank."""

    def test_prepare_request_openai_format(self):
        """Test _prepare_request with OpenAI-compatible format."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key",
        )

        result = rerank._prepare_request(
            query="test query",
            documents=["doc1", "doc2", "doc3"],
            top_n=3
        )

        assert result["model"] == "gte-rerank-v1"
        assert result["query"] == "test query"
        assert result["documents"] == ["doc1", "doc2", "doc3"]
        assert result["top_n"] == 3

    def test_prepare_request_dashscope_format(self):
        """Test _prepare_request with DashScope format."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="qwen3-rerank",
            base_url="https://dashscope.aliyuncs.com/api/v1",
            api_key="test-key",
        )

        result = rerank._prepare_request(
            query="test query",
            documents=["doc1", "doc2"],
            top_n=2
        )

        # DashScope format has nested input
        assert "input" in result
        assert result["input"]["query"] == "test query"
        assert result["input"]["documents"] == ["doc1", "doc2"]
        assert "parameters" in result
        assert result["parameters"]["top_n"] == 2

    def test_prepare_request_empty_top_n(self):
        """Test _prepare_request when top_n is None (defaults to len of documents)."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key",
        )

        result = rerank._prepare_request(
            query="test query",
            documents=["doc1", "doc2", "doc3"],
            top_n=None
        )

        # Should default to len of documents
        assert result["top_n"] == 3

    def test_rerank_empty_documents(self):
        """Test rerank returns empty list when documents is empty."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key",
        )

        result = rerank.rerank(query="test", documents=[], top_n=1)

        assert result == []

    def test_rerank_response_with_output_results(self):
        """Test rerank handles DashScope response format with output.results."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank
        import requests

        rerank = OpenAICompatibleRerank(
            model_name="qwen3-rerank",
            base_url="https://dashscope.aliyuncs.com/api/v1/services/rerank",
            api_key="test-key",
        )

        # Mock the response to simulate DashScope format
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "output": {
                "results": [
                    {"index": 0, "relevance_score": 0.95, "document": {"text": "doc1"}},
                    {"index": 1, "relevance_score": 0.85, "document": {"text": "doc2"}},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(requests, 'post', return_value=mock_response):
            result = rerank.rerank(
                query="test query",
                documents=["doc1", "doc2"],
                top_n=2
            )

        assert len(result) == 2
        assert result[0]["index"] == 0
        assert result[0]["relevance_score"] == 0.95

    def test_rerank_response_with_string_document(self):
        """Test rerank handles response where document is a string (not dict)."""
        from nexent.core.models.rerank_model import OpenAICompatibleRerank
        import requests

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key",
        )

        # Mock the response where document is a string
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.95, "document": "doc1_text"},
                {"index": 1, "relevance_score": 0.85, "document": "doc2_text"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(requests, 'post', return_value=mock_response):
            result = rerank.rerank(
                query="test query",
                documents=["doc1", "doc2"],
                top_n=2
            )

        assert len(result) == 2
        assert result[0]["document"] == "doc1_text"

    @pytest.mark.asyncio
    async def test_connectivity_check_timeout(self):
        """Test connectivity_check handles timeout."""
        import requests
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key",
        )

        # Mock a timeout exception
        with patch.object(requests, 'post', side_effect=requests.exceptions.Timeout("timeout")):
            result = await rerank.connectivity_check(timeout=5.0)

        assert result is False

    @pytest.mark.asyncio
    async def test_connectivity_check_connection_error(self):
        """Test connectivity_check handles connection error."""
        import requests
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key",
        )

        # Mock a connection error
        with patch.object(requests, 'post', side_effect=requests.exceptions.ConnectionError("connection error")):
            result = await rerank.connectivity_check(timeout=5.0)

        assert result is False

    @pytest.mark.asyncio
    async def test_connectivity_check_generic_exception(self):
        """Test connectivity_check handles generic exception."""
        import requests
        from nexent.core.models.rerank_model import OpenAICompatibleRerank

        rerank = OpenAICompatibleRerank(
            model_name="gte-rerank-v1",
            base_url="https://api.example.com/v1/rerank",
            api_key="test-key",
        )

        # Mock a generic exception
        with patch.object(requests, 'post', side_effect=Exception("generic error")):
            result = await rerank.connectivity_check(timeout=5.0)

        assert result is False
