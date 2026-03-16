import pytest
from unittest.mock import MagicMock, patch
import json

# Import target module
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool


@pytest.fixture
def mock_observer():
    """Create a mock observer for testing"""
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def mock_vdb_core():
    """Create a mock ElasticSearchCore for testing"""
    vdb_core = MagicMock()
    return vdb_core


@pytest.fixture
def mock_embedding_model():
    """Create a mock embedding model for testing"""
    model = MagicMock()
    return model


@pytest.fixture
def knowledge_base_search_tool(mock_observer, mock_vdb_core, mock_embedding_model):
    """Create KnowledgeBaseSearchTool instance for testing"""
    tool = KnowledgeBaseSearchTool(
        top_k=5,
        index_names=["test_index1", "test_index2"],
        observer=mock_observer,
        embedding_model=mock_embedding_model,
        vdb_core=mock_vdb_core,
        search_mode="hybrid"
    )
    return tool


def create_mock_search_result(count=3):
    """Helper method to create mock search results"""
    results = []
    for i in range(count):
        result = {
            "document": {
                "title": f"Test Document {i}",
                "content": f"This is test content {i}",
                "filename": f"test_file_{i}.txt",
                "path_or_url": f"/path/to/file_{i}.txt",
                "create_time": "2024-01-01T12:00:00Z",
                "source_type": "file"
            },
            "score": 0.9 - (i * 0.1),
            "index": f"test_index_{i % 2 + 1}"
        }
        results.append(result)
    return results


class TestKnowledgeBaseSearchTool:
    """Test KnowledgeBaseSearchTool functionality"""

    def test_forward_with_observer_adds_messages(self, knowledge_base_search_tool):
        """forward should send TOOL and CARD messages when observer is present"""
        mock_results = create_mock_search_result(1)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        knowledge_base_search_tool.forward("hello world")

        knowledge_base_search_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "Searching the knowledge base..."
        )
        knowledge_base_search_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps([{"icon": "search", "text": "hello world"}], ensure_ascii=False)
        )

    def test_init_with_custom_values(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test initialization with custom values"""
        tool = KnowledgeBaseSearchTool(
            top_k=10,
            index_names=["index1", "index2", "index3"],
            observer=mock_observer,
            embedding_model=mock_embedding_model,
            vdb_core=mock_vdb_core,
            search_mode="semantic"
        )

        assert tool.top_k == 10
        assert tool.index_names == ["index1", "index2", "index3"]
        assert tool.observer == mock_observer
        assert tool.embedding_model == mock_embedding_model
        assert tool.vdb_core == mock_vdb_core
        assert tool.search_mode == "semantic"

    def test_init_with_none_index_names(self, mock_vdb_core, mock_embedding_model):
        """Test initialization with None index_names"""
        tool = KnowledgeBaseSearchTool(
            top_k=5,
            index_names=None,
            observer=None,
            embedding_model=mock_embedding_model,
            vdb_core=mock_vdb_core,
            search_mode="hybrid"
        )

        assert tool.index_names == []

    def test_search_hybrid_success(self, knowledge_base_search_tool):
        """Test successful hybrid search"""
        # Mock search results
        mock_results = create_mock_search_result(3)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        result = knowledge_base_search_tool.search_hybrid("test query", ["test_index1"])

        # Verify result structure
        assert result["total"] == 3
        assert len(result["results"]) == 3

        # Verify each result has required fields
        for i, doc in enumerate(result["results"]):
            assert "title" in doc
            assert "content" in doc
            assert "score" in doc
            assert "index" in doc
            assert doc["title"] == f"Test Document {i}"

        # Verify vdb_core was called correctly
        knowledge_base_search_tool.vdb_core.hybrid_search.assert_called_once_with(
            index_names=["test_index1"],
            query_text="test query",
            embedding_model=knowledge_base_search_tool.embedding_model,
            top_k=5
        )

    def test_search_accurate_success(self, knowledge_base_search_tool):
        """Test successful accurate search"""
        # Mock search results
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.accurate_search.return_value = mock_results

        result = knowledge_base_search_tool.search_accurate("test query", ["test_index1"])

        # Verify result structure
        assert result["total"] == 2
        assert len(result["results"]) == 2

        # Verify vdb_core was called correctly
        knowledge_base_search_tool.vdb_core.accurate_search.assert_called_once_with(
            index_names=["test_index1"],
            query_text="test query",
            top_k=5
        )

    def test_search_semantic_success(self, knowledge_base_search_tool):
        """Test successful semantic search"""
        # Mock search results
        mock_results = create_mock_search_result(4)
        knowledge_base_search_tool.vdb_core.semantic_search.return_value = mock_results

        result = knowledge_base_search_tool.search_semantic("test query", ["test_index1"])

        # Verify result structure
        assert result["total"] == 4
        assert len(result["results"]) == 4

        # Verify vdb_core was called correctly
        knowledge_base_search_tool.vdb_core.semantic_search.assert_called_once_with(
            index_names=["test_index1"],
            query_text="test query",
            embedding_model=knowledge_base_search_tool.embedding_model,
            top_k=5
        )

    def test_search_hybrid_error(self, knowledge_base_search_tool):
        """Test hybrid search with error"""
        knowledge_base_search_tool.vdb_core.hybrid_search.side_effect = Exception("Search error")

        with pytest.raises(Exception) as excinfo:
            knowledge_base_search_tool.search_hybrid("test query", ["test_index1"])

        assert "Error during semantic search" in str(excinfo.value)

    def test_forward_accurate_mode_success(self, knowledge_base_search_tool):
        """Test forward method with accurate search mode"""
        # Set search_mode to accurate
        knowledge_base_search_tool.search_mode = "accurate"

        # Mock search results
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.accurate_search.return_value = mock_results

        result = knowledge_base_search_tool.forward("test query")

        # Parse result
        search_results = json.loads(result)

        # Verify result structure
        assert len(search_results) == 2

    def test_forward_semantic_mode_success(self, knowledge_base_search_tool):
        """Test forward method with semantic search mode"""
        # Set search_mode to semantic
        knowledge_base_search_tool.search_mode = "semantic"

        # Mock search results
        mock_results = create_mock_search_result(4)
        knowledge_base_search_tool.vdb_core.semantic_search.return_value = mock_results

        result = knowledge_base_search_tool.forward("test query")

        # Parse result
        search_results = json.loads(result)

        # Verify result structure
        assert len(search_results) == 4

    def test_forward_invalid_search_mode(self, knowledge_base_search_tool):
        """Test forward method with invalid search mode"""
        # Set invalid search_mode
        knowledge_base_search_tool.search_mode = "invalid"

        with pytest.raises(Exception) as excinfo:
            knowledge_base_search_tool.forward("test query")

        assert "Invalid search mode" in str(excinfo.value)
        assert "hybrid, accurate, semantic" in str(excinfo.value)

    def test_forward_no_index_names(self, knowledge_base_search_tool):
        """Test forward method with no index names"""
        # Set empty index names
        knowledge_base_search_tool.index_names = []

        result = knowledge_base_search_tool.forward("test query")

        # Should return no results message
        assert result == json.dumps("No knowledge base selected. No relevant information found.", ensure_ascii=False)

    def test_forward_no_results(self, knowledge_base_search_tool):
        """Test forward method with no search results"""
        # Mock empty search results
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = []

        with pytest.raises(Exception) as excinfo:
            knowledge_base_search_tool.forward("test query")

        assert "No results found" in str(excinfo.value)

    def test_forward_with_custom_index_names(self, knowledge_base_search_tool):
        """Test forward method with custom index names"""
        # Set custom index names
        knowledge_base_search_tool.index_names = ["custom_index1", "custom_index2"]

        # Mock search results
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        result = knowledge_base_search_tool.forward("test query")

        # Verify vdb_core was called with custom index names
        knowledge_base_search_tool.vdb_core.hybrid_search.assert_called_once_with(
            index_names=["custom_index1", "custom_index2"],
            query_text="test query",
            embedding_model=knowledge_base_search_tool.embedding_model,
            top_k=5
        )

    def test_forward_chinese_language_observer(self, knowledge_base_search_tool):
        """Test forward method with Chinese language observer"""
        # Set observer language to Chinese
        knowledge_base_search_tool.observer.lang = "zh"

        # Mock search results
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        result = knowledge_base_search_tool.forward("test query")

        # Verify Chinese running prompt
        knowledge_base_search_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "知识库检索中..."
        )

    def test_forward_title_fallback(self, knowledge_base_search_tool):
        """Test forward method with title fallback to filename"""
        # Mock search results without title
        mock_results = [
            {
                "document": {
                    "title": None,  # No title
                    "content": "Test content",
                    "filename": "test.txt",  # Should be used as title
                    "path_or_url": "/path/test.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file"
                },
                "score": 0.9,
                "index": "test_index"
            }
        ]
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        result = knowledge_base_search_tool.forward("test query")

        # Parse result
        search_results = json.loads(result)

        # Verify title fallback
        assert len(search_results) == 1
        assert search_results[0]["title"] == "test.txt"


class TestKnowledgeBaseSearchToolRerank:
    """Tests for KnowledgeBaseSearchTool rerank functionality."""

    def test_init_with_rerank_params(self, mock_observer):
        """Test initialization with rerank parameters."""
        tool = KnowledgeBaseSearchTool(
            index_names=["kb1", "kb2"],
            search_mode="hybrid",
            rerank=True,
            rerank_model_name="gte-rerank-v2",
            rerank_model=None,
            vdb_core=None,
            embedding_model=None,
            observer=mock_observer,
        )

        assert tool.rerank is True
        assert tool.rerank_model_name == "gte-rerank-v2"
        assert tool.rerank_model is None

    def test_init_without_rerank_params(self, mock_observer):
        """Test initialization without rerank parameters (defaults)."""
        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="semantic",
            vdb_core=None,
            embedding_model=None,
            observer=mock_observer,
        )

        # smolagents Tool doesn't properly handle Field defaults, so we check FieldInfo.default
        from pydantic import FieldInfo
        assert isinstance(tool.rerank, FieldInfo)
        assert tool.rerank.default is False
        assert tool.rerank_model_name.default == ""
        assert tool.rerank_model.default is None

    def test_forward_with_rerank_enabled(self, mock_observer, mock_vdb_core, mock_embedding_model, mocker):
        """Test forward method when rerank is enabled and model is provided."""
        # Mock search results
        mock_results = [
            {
                "document": {
                    "title": "doc1",
                    "content": "content 1 about machine learning",
                    "filename": "doc1.txt",
                    "path_or_url": "/path/doc1.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file"
                },
                "score": 0.9,
                "index": "kb1"
            },
            {
                "document": {
                    "title": "doc2",
                    "content": "content 2 about deep learning",
                    "filename": "doc2.txt",
                    "path_or_url": "/path/doc2.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file"
                },
                "score": 0.8,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results

        # Create mock rerank model
        mock_rerank_model = MagicMock()
        mock_rerank_model.rerank.return_value = [
            {"index": 1, "relevance_score": 0.95, "document": "content 2 about deep learning"},
            {"index": 0, "relevance_score": 0.85, "document": "content 1 about machine learning"},
        ]

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            rerank=True,
            rerank_model_name="gte-rerank-v2",
            rerank_model=mock_rerank_model,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
        )

        result = tool.forward("test query")
        results = json.loads(result)

        # Verify rerank was called
        mock_rerank_model.rerank.assert_called_once()
        call_args = mock_rerank_model.rerank.call_args
        assert call_args[1]["query"] == "test query"
        assert len(call_args[1]["documents"]) == 2

    def test_forward_rerank_disabled(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test forward method when rerank is disabled."""
        # Mock search results
        mock_results = [
            {
                "document": {
                    "title": "doc1",
                    "content": "content 1",
                    "filename": "doc1.txt",
                    "path_or_url": "/path/doc1.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file"
                },
                "score": 0.9,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            rerank=False,
            rerank_model=None,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
        )

        result = tool.forward("test query")

        # Should work normally without reranking
        assert result is not None

    def test_forward_rerank_error_continues(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test that forward continues when rerank raises an exception."""
        # Mock search results
        mock_results = [
            {
                "document": {
                    "title": "doc1",
                    "content": "content 1",
                    "filename": "doc1.txt",
                    "path_or_url": "/path/doc1.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file"
                },
                "score": 0.9,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results

        # Create mock rerank model that raises exception
        mock_rerank_model = MagicMock()
        mock_rerank_model.rerank.side_effect = Exception("Rerank API error")

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            rerank=True,
            rerank_model=mock_rerank_model,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
        )

        # Should not raise, should continue with original results
        result = tool.forward("test query")
        assert result is not None
