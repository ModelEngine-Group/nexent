import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[4]

def _pkg(name, path):
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules.setdefault(name, mod)
    return mod

sdk_pkg = _pkg("sdk", REPO_ROOT / "sdk")
nexent_pkg = _pkg("sdk.nexent", REPO_ROOT / "sdk" / "nexent")
core_pkg = _pkg("sdk.nexent.core", REPO_ROOT / "sdk" / "nexent" / "core")
tools_pkg = _pkg("sdk.nexent.core.tools", REPO_ROOT / "sdk" / "nexent" / "core" / "tools")
utils_pkg = _pkg("sdk.nexent.core.utils", REPO_ROOT / "sdk" / "nexent" / "core" / "utils")
models_pkg = _pkg("sdk.nexent.core.models", REPO_ROOT / "sdk" / "nexent" / "core" / "models")
vector_pkg = _pkg("sdk.nexent.vector_database", REPO_ROOT / "sdk" / "nexent" / "vector_database")
sdk_pkg.nexent = nexent_pkg
nexent_pkg.core = core_pkg
nexent_pkg.vector_database = vector_pkg
core_pkg.tools = tools_pkg
core_pkg.utils = utils_pkg
core_pkg.models = models_pkg

class MessageObserver:
    def add_message(self, *args, **kwargs):
        pass

class _ProcessType:
    TOOL = "TOOL"
    CARD = "CARD"
    SEARCH_CONTENT = "SEARCH_CONTENT"
    PICTURE_WEB = "PICTURE_WEB"

ProcessType = _ProcessType

observer_mod = types.ModuleType("sdk.nexent.core.utils.observer")
observer_mod.MessageObserver = MessageObserver
observer_mod.ProcessType = _ProcessType
sys.modules["sdk.nexent.core.utils.observer"] = observer_mod
utils_pkg.observer = observer_mod

class _EnumValue:
    def __init__(self, value):
        self.value = value

class _ToolCategory:
    SEARCH = _EnumValue("search")

class _ToolSign:
    KNOWLEDGE_BASE = _EnumValue("knowledge_base")

class SearchResultTextMessage:
    def __init__(self, **kwargs):
        self.data = {
            "title": kwargs.get("title", ""),
            "content": kwargs.get("text", ""),
            "source_type": kwargs.get("source_type", ""),
            "url": kwargs.get("url", ""),
            "filename": kwargs.get("filename", ""),
            "published_date": kwargs.get("published_date", ""),
            "score": kwargs.get("score", 0),
            "score_details": kwargs.get("score_details", {}),
            "cite_index": kwargs.get("cite_index", 0),
            "search_type": kwargs.get("search_type", ""),
            "tool_sign": kwargs.get("tool_sign", ""),
        }

    def to_dict(self):
        return dict(self.data)

    def to_model_dict(self):
        return dict(self.data)

tools_common_mod = types.ModuleType("sdk.nexent.core.utils.tools_common_message")
tools_common_mod.SearchResultTextMessage = SearchResultTextMessage
tools_common_mod.ToolCategory = _ToolCategory
tools_common_mod.ToolSign = _ToolSign
sys.modules["sdk.nexent.core.utils.tools_common_message"] = tools_common_mod
utils_pkg.tools_common_message = tools_common_mod

constants_mod = types.ModuleType("sdk.nexent.core.utils.constants")
constants_mod.RERANK_OVERSEARCH_MULTIPLIER = 2
sys.modules["sdk.nexent.core.utils.constants"] = constants_mod
utils_pkg.constants = constants_mod

class BaseEmbedding:
    pass

class BaseRerank:
    pass

embedding_mod = types.ModuleType("sdk.nexent.core.models.embedding_model")
embedding_mod.BaseEmbedding = BaseEmbedding
sys.modules["sdk.nexent.core.models.embedding_model"] = embedding_mod
models_pkg.embedding_model = embedding_mod

rerank_mod = types.ModuleType("sdk.nexent.core.models.rerank_model")
rerank_mod.BaseRerank = BaseRerank
sys.modules["sdk.nexent.core.models.rerank_model"] = rerank_mod
models_pkg.rerank_model = rerank_mod

class VectorDatabaseCore:
    pass

vector_base_mod = types.ModuleType("sdk.nexent.vector_database.base")
vector_base_mod.VectorDatabaseCore = VectorDatabaseCore
sys.modules["sdk.nexent.vector_database.base"] = vector_base_mod
vector_pkg.base = vector_base_mod

smolagents_mod = types.ModuleType("smolagents")
smolagents_tools_mod = types.ModuleType("smolagents.tools")

class Tool:
    def __init__(self, *args, **kwargs):
        pass

smolagents_tools_mod.Tool = Tool
smolagents_mod.tools = smolagents_tools_mod
sys.modules["smolagents"] = smolagents_mod
sys.modules["smolagents.tools"] = smolagents_tools_mod

MODULE_PATH = REPO_ROOT / "sdk" / "nexent" / "core" / "tools" / "knowledge_base_search_tool.py"
MODULE_NAME = "sdk.nexent.core.tools.knowledge_base_search_tool"
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
knowledge_base_search_tool_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = knowledge_base_search_tool_module
assert spec and spec.loader
spec.loader.exec_module(knowledge_base_search_tool_module)
tools_pkg.knowledge_base_search_tool = knowledge_base_search_tool_module
KnowledgeBaseSearchTool = knowledge_base_search_tool_module.KnowledgeBaseSearchTool


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
        search_mode="hybrid",
        rerank=False,
        display_name_to_index_map={},
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
            search_mode="semantic",
            rerank=False,
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
            search_mode="hybrid",
            rerank=False,
        )

        assert tool.index_names == []

    def test_search_hybrid_success(self, knowledge_base_search_tool):
        """Test successful hybrid search"""
        # Mock search results
        mock_results = create_mock_search_result(3)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        result = knowledge_base_search_tool.search_hybrid("test query", ["test_index1"], top_k=5)

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

        result = knowledge_base_search_tool.search_accurate("test query", ["test_index1"], top_k=5)

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

        result = knowledge_base_search_tool.search_semantic("test query", ["test_index1"], top_k=5)

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
            knowledge_base_search_tool.search_hybrid("test query", ["test_index1"], top_k=5)

        assert "Error during hybrid search" in str(excinfo.value)

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

    def test_forward_no_results(self, knowledge_base_search_tool):
        """Test forward method with no search results"""
        # Mock empty search results
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = []

        with pytest.raises(Exception) as excinfo:
            knowledge_base_search_tool.forward("test query")

        assert "No results found" in str(excinfo.value)

    def test_forward_with_custom_index_names(self, knowledge_base_search_tool):
        """Test forward method uses configured custom index names."""
        # Mock search results
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.index_names = ["custom_index1", "custom_index2"]

        knowledge_base_search_tool.forward("test query")

        # Verify vdb_core was called with the index names as-is
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
        
    def test_forward_adds_picture_web_for_images(self, knowledge_base_search_tool, monkeypatch):
        """Forward should add picture messages when image results are present."""
        monkeypatch.setenv("DATA_PROCESS_SERVICE", "https://data-process")
        knowledge_base_search_tool.data_process_service = "https://data-process"

        mock_results = [
            {
                "document": {
                    "title": "Image Doc",
                    "content": json.dumps({"image_url": "s3://bucket/img.png"}),
                    "filename": "img.png",
                    "path_or_url": "/path/img.png",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file",
                    "process_source": "UniversalImageExtractor",
                },
                "score": 0.9,
                "index": "test_index"
            }
        ]
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        with patch.object(knowledge_base_search_tool, "_filter_images", return_value=["s3://bucket/img.png"]):
            knowledge_base_search_tool.forward("find images")

        calls = knowledge_base_search_tool.observer.add_message.call_args_list
        assert any(call.args[1] == ProcessType.PICTURE_WEB for call in calls)


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
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo
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
            top_k=3,
            rerank=True,
            rerank_model_name="gte-rerank-v2",
            rerank_model=mock_rerank_model,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
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
            display_name_to_index_map={},
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
            top_k=3,
            rerank=True,
            rerank_model=mock_rerank_model,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )

        # Should not raise, should continue with original results
        result = tool.forward("test query")
        assert result is not None

    def test_forward_uses_instance_index_names(self, knowledge_base_search_tool):
        """Test forward method uses instance index_names when not provided"""
        # Mock search results
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        # Call forward without index_names - should use instance's index_names
        result = knowledge_base_search_tool.forward("test query")

        # Verify it used instance index_names
        assert result is not None
        knowledge_base_search_tool.vdb_core.hybrid_search.assert_called_once()

    def test_forward_empty_index_names_string(self, knowledge_base_search_tool):
        """Test forward method with empty index_names string returns no results"""
        knowledge_base_search_tool.index_names = ""

        result = knowledge_base_search_tool.forward("test query")

        # Should return no results message
        assert result == json.dumps("No knowledge base selected. No relevant information found.", ensure_ascii=False)

    def test_forward_single_index_name(self, knowledge_base_search_tool):
        """Test forward method with single index name"""
        # Mock search results
        mock_results = create_mock_search_result(1)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.index_names = ["single_index"]

        knowledge_base_search_tool.forward("test query")

        # Verify vdb_core was called with single index
        knowledge_base_search_tool.vdb_core.hybrid_search.assert_called_once_with(
            index_names=["single_index"],
            query_text="test query",
            embedding_model=knowledge_base_search_tool.embedding_model,
            top_k=5
        )

class TestConvertToIndexNames:
    """Tests for _convert_to_index_names method."""

    def test_convert_with_empty_map(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test conversion when display_name_to_index_map is empty."""
        tool = KnowledgeBaseSearchTool(
            index_names=["index1", "index2"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )

        result = tool._convert_to_index_names(["index1", "index2"])

        assert result == ["index1", "index2"]

    def test_convert_with_matching_names(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test conversion when names are in the map."""
        tool = KnowledgeBaseSearchTool(
            index_names=[],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={
                "Knowledge A": "es_index_knowledge_a",
                "Knowledge B": "es_index_knowledge_b",
            },
        )

        result = tool._convert_to_index_names(["Knowledge A", "Knowledge B"])

        assert result == ["es_index_knowledge_a", "es_index_knowledge_b"]

    def test_convert_with_mixed_names(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test conversion when some names are in the map and some are not."""
        tool = KnowledgeBaseSearchTool(
            index_names=[],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={
                "Knowledge A": "es_index_knowledge_a",
            },
        )

        result = tool._convert_to_index_names(["Knowledge A", "raw_index_name"])

        assert result == ["es_index_knowledge_a", "raw_index_name"]

    def test_convert_with_unmatched_names(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test conversion when no names are in the map."""
        tool = KnowledgeBaseSearchTool(
            index_names=[],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={
                "Knowledge A": "es_index_knowledge_a",
            },
        )

        result = tool._convert_to_index_names(["raw_index1", "raw_index2"])

        assert result == ["raw_index1", "raw_index2"]

    def test_convert_forward_integration(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test that forward method uses _convert_to_index_names correctly."""
        mock_results = create_mock_search_result(1)
        mock_vdb_core.hybrid_search.return_value = mock_results

        tool = KnowledgeBaseSearchTool(
            index_names=["Knowledge A"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={
                "Knowledge A": "es_index_knowledge_a",
            },
        )

        tool.forward("test query")

        mock_vdb_core.hybrid_search.assert_called_once_with(
            index_names=["es_index_knowledge_a"],
            query_text="test query",
            embedding_model=mock_embedding_model,
            top_k=3
        )


class TestEffectiveTopK:
    """Tests for effective_top_k calculation with rerank."""

    def test_effective_top_k_increases_with_rerank(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test that effective_top_k is multiplied when rerank is enabled."""
        from sdk.nexent.core.utils.constants import RERANK_OVERSEARCH_MULTIPLIER

        mock_results = create_mock_search_result(10)
        mock_vdb_core.hybrid_search.return_value = mock_results

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            top_k=5,
            rerank=True,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )

        tool.forward("test query")

        call_kwargs = mock_vdb_core.hybrid_search.call_args[1]
        assert call_kwargs["top_k"] == 5 * RERANK_OVERSEARCH_MULTIPLIER

    def test_effective_top_k_unchanged_without_rerank(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test that effective_top_k remains the same when rerank is disabled."""
        mock_results = create_mock_search_result(5)
        mock_vdb_core.hybrid_search.return_value = mock_results

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            top_k=5,
            rerank=False,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )

        tool.forward("test query")

        call_kwargs = mock_vdb_core.hybrid_search.call_args[1]
        assert call_kwargs["top_k"] == 5


class TestSourceTypeConversion:
    """Tests for source_type conversion (local/minio -> file)."""

    def test_source_type_local_converted_to_file(self, knowledge_base_search_tool, mock_vdb_core):
        """Test that source_type 'local' is converted to 'file'."""
        mock_results = [
            {
                "document": {
                    "title": "Local Doc",
                    "content": "Content from local file",
                    "filename": "local.txt",
                    "path_or_url": "/path/local.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "local"
                },
                "score": 0.9,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.vdb_core = mock_vdb_core

        knowledge_base_search_tool.forward("test query")

        # Check the SEARCH_CONTENT message which contains full results via to_dict()
        search_content_call = [
            call for call in knowledge_base_search_tool.observer.add_message.call_args_list
            if call[0][1] == ProcessType.SEARCH_CONTENT
        ][0]
        full_results = json.loads(search_content_call[0][2])

        assert full_results[0]["source_type"] == "file"


class TestKnowledgeBaseSearchToolMissingBranches:
    def test_convert_to_index_names_with_fieldinfo_default_factory(self, mock_observer, mock_vdb_core, mock_embedding_model):
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo

        tool = KnowledgeBaseSearchTool(
            index_names=["Knowledge A", "raw_index"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map=FieldInfo(default_factory=lambda: {"Knowledge A": "es_index_a"}),
        )

        assert tool._convert_to_index_names(["Knowledge A", "raw_index"]) == ["es_index_a", "raw_index"]

    def test_apply_rerank_empty_and_invalid_results(self, mock_observer, mock_vdb_core, mock_embedding_model):
        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            rerank=True,
            rerank_model=MagicMock(),
            display_name_to_index_map={},
        )

        kb_search_results = create_mock_search_result(2)
        tool.rerank_model.rerank.return_value = []
        assert tool._apply_rerank("query", kb_search_results, top_k=2) == kb_search_results

        tool.rerank_model.rerank.return_value = [{"index": 99, "relevance_score": 0.5}]
        assert tool._apply_rerank("query", kb_search_results, top_k=2) == kb_search_results

    def test_extract_image_url_success_and_failure(self):
        assert KnowledgeBaseSearchTool._extract_image_url(
            {
                "process_source": "UniversalImageExtractor",
                "content": json.dumps({"image_url": "s3://bucket/img.png"}),
            }
        ) == "s3://bucket/img.png"

        assert KnowledgeBaseSearchTool._extract_image_url(
            {
                "process_source": "UniversalImageExtractor",
                "content": "not-json",
            }
        ) is None

        assert KnowledgeBaseSearchTool._extract_image_url(
            {
                "process_source": "file",
                "content": json.dumps({"image_url": "s3://bucket/img.png"}),
            }
        ) is None

    def test_record_search_results_image_filter_paths(self, mock_observer, mock_vdb_core, mock_embedding_model):
        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )

        search_results = [{"title": "Doc", "content": "Body"}]
        tool._record_search_results(search_results, [], "query")
        mock_observer.add_message.assert_called_once()
        mock_observer.add_message.reset_mock()

        with patch.object(tool, "_filter_images", return_value=[]):
            tool._record_search_results(search_results, ["img1"], "query")
        assert any(call.args[1] == ProcessType.PICTURE_WEB for call in mock_observer.add_message.call_args_list)
        mock_observer.add_message.reset_mock()

        with patch.object(tool, "_filter_images", side_effect=Exception("boom")):
            tool._record_search_results(search_results, ["img2"], "query")
        assert any(call.args[1] == ProcessType.PICTURE_WEB for call in mock_observer.add_message.call_args_list)

    def test_search_error_wrappers(self, mock_observer, mock_vdb_core, mock_embedding_model):
        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )

        mock_vdb_core.accurate_search.side_effect = Exception("accurate boom")
        with pytest.raises(Exception, match="Error during accurate search"):
            tool.search_accurate("query", ["kb1"], top_k=1)

        mock_vdb_core.accurate_search.side_effect = None
        mock_vdb_core.semantic_search.side_effect = Exception("semantic boom")
        with pytest.raises(Exception, match="Error during semantic search"):
            tool.search_semantic("query", ["kb1"], top_k=1)

    def test_filter_images_success_and_event_loop_failure(self, mock_observer, mock_vdb_core, mock_embedding_model, monkeypatch, mocker):
        import asyncio

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )
        tool.data_process_service = "https://data-process"

        class FakeResponse:
            def __init__(self, status, payload=None):
                self.status = status
                self._payload = payload or {}

            async def json(self):
                return self._payload

        class FakePostContext:
            def __init__(self, url):
                self.url = url

            async def __aenter__(self):
                if self.url == "raise":
                    raise RuntimeError("request boom")
                if self.url == "bad":
                    return FakeResponse(500, {})
                if self.url == "skip":
                    return FakeResponse(200, {"is_important": False})
                return FakeResponse(200, {"is_important": True})

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def post(self, api_url, data):
                return FakePostContext(data["image_url"])

        fake_aiohttp = types.ModuleType("aiohttp")
        fake_aiohttp.TCPConnector = lambda limit=0: object()
        fake_aiohttp.ClientTimeout = lambda total=0: object()
        fake_aiohttp.ClientSession = FakeSession
        monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)

        assert tool._filter_images(["keep", "skip", "bad", "raise"], "query") == ["keep"]

        mocker.patch("asyncio.new_event_loop", side_effect=RuntimeError("loop boom"))
        assert tool._filter_images(["keep"], "query") == []

    def test_source_type_minio_converted_to_file(self, knowledge_base_search_tool, mock_vdb_core):
        """Test that source_type 'minio' is converted to 'file'."""
        mock_results = [
            {
                "document": {
                    "title": "Minio Doc",
                    "content": "Content from minio storage",
                    "filename": "minio.txt",
                    "path_or_url": "/minio/bucket/minio.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "minio"
                },
                "score": 0.9,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.vdb_core = mock_vdb_core

        knowledge_base_search_tool.forward("test query")

        # Check the SEARCH_CONTENT message
        search_content_call = [
            call for call in knowledge_base_search_tool.observer.add_message.call_args_list
            if call[0][1] == ProcessType.SEARCH_CONTENT
        ][0]
        full_results = json.loads(search_content_call[0][2])

        assert full_results[0]["source_type"] == "file"

    def test_source_type_other_unchanged(self, knowledge_base_search_tool, mock_vdb_core):
        """Test that source_type other than local/minio remains unchanged."""
        mock_results = [
            {
                "document": {
                    "title": "Web Doc",
                    "content": "Content from web",
                    "filename": "web.html",
                    "path_or_url": "https://example.com/page.html",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "web"
                },
                "score": 0.9,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.vdb_core = mock_vdb_core

        knowledge_base_search_tool.forward("test query")

        # Check the SEARCH_CONTENT message
        search_content_call = [
            call for call in knowledge_base_search_tool.observer.add_message.call_args_list
            if call[0][1] == ProcessType.SEARCH_CONTENT
        ][0]
        full_results = json.loads(search_content_call[0][2])

        assert full_results[0]["source_type"] == "web"


class TestRecordOps:
    """Tests for record_ops counter functionality."""

    def test_record_ops_increments_by_result_count(self, knowledge_base_search_tool):
        """Test that record_ops increases by the number of results returned."""
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        initial_ops = knowledge_base_search_tool.record_ops

        knowledge_base_search_tool.forward("test query")

        assert knowledge_base_search_tool.record_ops == initial_ops + 2

    def test_record_ops_accumulates_across_calls(self, knowledge_base_search_tool):
        """Test that record_ops accumulates across multiple forward calls."""
        mock_results = create_mock_search_result(1)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        knowledge_base_search_tool.record_ops = 0
        knowledge_base_search_tool.forward("query1")
        first_call_ops = knowledge_base_search_tool.record_ops

        knowledge_base_search_tool.forward("query2")
        second_call_ops = knowledge_base_search_tool.record_ops

        # Each call with 1 result adds 1 to record_ops
        assert first_call_ops == 1
        assert second_call_ops == 2

    def test_cite_index_in_results(self, knowledge_base_search_tool):
        """Test that cite_index in results starts from record_ops + index + 1."""
        mock_results = create_mock_search_result(2)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        # record_ops starts at 1, so cite_index should be 1+0+1=1, 1+1+1=2
        knowledge_base_search_tool.forward("test query")

        # Check the SEARCH_CONTENT message for cite_index values
        search_content_call = [
            call for call in knowledge_base_search_tool.observer.add_message.call_args_list
            if call[0][1] == ProcessType.SEARCH_CONTENT
        ][0]
        full_results = json.loads(search_content_call[0][2])

        assert full_results[0]["cite_index"] == 1
        assert full_results[1]["cite_index"] == 2


class TestSearchContentObserver:
    """Tests for SEARCH_CONTENT observer message."""

    def test_forward_sends_search_content_to_observer(self, knowledge_base_search_tool):
        """Test that forward sends SEARCH_CONTENT message to observer."""
        mock_results = create_mock_search_result(1)
        knowledge_base_search_tool.vdb_core.hybrid_search.return_value = mock_results

        knowledge_base_search_tool.forward("test query")

        search_content_calls = [
            call for call in knowledge_base_search_tool.observer.add_message.call_args_list
            if call[0][1] == ProcessType.SEARCH_CONTENT
        ]

        assert len(search_content_calls) == 1
        message = search_content_calls[0][0][2]
        parsed = json.loads(message)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_forward_no_search_content_without_observer(self, mock_vdb_core, mock_embedding_model):
        """Test that forward works without observer and doesn't send SEARCH_CONTENT."""
        mock_results = create_mock_search_result(1)
        mock_vdb_core.hybrid_search.return_value = mock_results

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=None,
            display_name_to_index_map={},
        )

        result = tool.forward("test query")

        assert result is not None


class TestToolMetadata:
    """Tests for tool metadata attributes."""

    def test_tool_name(self, knowledge_base_search_tool):
        """Test tool name is correctly set."""
        assert knowledge_base_search_tool.name == "knowledge_base_search"

    def test_tool_category(self, knowledge_base_search_tool):
        """Test tool category is SEARCH."""
        from sdk.nexent.core.utils.tools_common_message import ToolCategory
        assert knowledge_base_search_tool.category == ToolCategory.SEARCH.value

    def test_tool_sign(self, knowledge_base_search_tool):
        """Test tool_sign is KNOWLEDGE_BASE."""
        from sdk.nexent.core.utils.tools_common_message import ToolSign
        assert knowledge_base_search_tool.tool_sign == ToolSign.KNOWLEDGE_BASE.value

    def test_output_type(self, knowledge_base_search_tool):
        """Test output_type is string."""
        assert knowledge_base_search_tool.output_type == "string"

    def test_inputs_contain_required_fields(self):
        """Test that inputs dict contains required fields."""
        assert "query" in KnowledgeBaseSearchTool.inputs
        assert KnowledgeBaseSearchTool.inputs["query"]["type"] == "string"

    def test_running_prompts(self, knowledge_base_search_tool):
        """Test running prompts for both languages."""
        assert knowledge_base_search_tool.running_prompt_zh == "知识库检索中..."
        assert knowledge_base_search_tool.running_prompt_en == "Searching the knowledge base..."


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_forward_with_score_details(self, knowledge_base_search_tool, mock_vdb_core):
        """Test forward includes score_details in results via SEARCH_CONTENT."""
        mock_results = [
            {
                "document": {
                    "title": "Doc",
                    "content": "Content",
                    "filename": "doc.txt",
                    "path_or_url": "/path/doc.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file",
                    "score_details": {"bm25": 0.5, "knn": 0.4}
                },
                "score": 0.9,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.vdb_core = mock_vdb_core

        knowledge_base_search_tool.forward("test query")

        # Check the SEARCH_CONTENT message which contains full results via to_dict()
        search_content_call = [
            call for call in knowledge_base_search_tool.observer.add_message.call_args_list
            if call[0][1] == ProcessType.SEARCH_CONTENT
        ][0]
        full_results = json.loads(search_content_call[0][2])

        assert "score_details" in full_results[0]
        assert full_results[0]["score_details"]["bm25"] == 0.5

    def test_forward_with_empty_content(self, knowledge_base_search_tool, mock_vdb_core):
        """Test forward handles empty content gracefully."""
        mock_results = [
            {
                "document": {
                    "title": "Doc with no content",
                    "content": "",
                    "filename": "empty.txt",
                    "path_or_url": "/path/empty.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file"
                },
                "score": 0.5,
                "index": "kb1"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.vdb_core = mock_vdb_core

        result = knowledge_base_search_tool.forward("test query")
        search_results = json.loads(result)

        assert search_results[0]["content"] == ""

    def test_forward_multiple_indices(self, knowledge_base_search_tool, mock_vdb_core):
        """Test forward searches across multiple indices."""
        mock_results = [
            {
                "document": {
                    "title": "Doc from index1",
                    "content": "Content",
                    "filename": "doc1.txt",
                    "path_or_url": "/path/doc1.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file",
                },
                "score": 0.9,
                "index": "index1"
            },
            {
                "document": {
                    "title": "Doc from index2",
                    "content": "Content",
                    "filename": "doc2.txt",
                    "path_or_url": "/path/doc2.txt",
                    "create_time": "2024-01-01T12:00:00Z",
                    "source_type": "file",
                },
                "score": 0.8,
                "index": "index2"
            }
        ]
        mock_vdb_core.hybrid_search.return_value = mock_results
        knowledge_base_search_tool.vdb_core = mock_vdb_core

        result = knowledge_base_search_tool.forward("test query")
        search_results = json.loads(result)

        assert len(search_results) == 2

    def test_rerank_trims_to_top_k(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test that rerank results are trimmed to original top_k."""
        mock_results = create_mock_search_result(10)
        mock_vdb_core.hybrid_search.return_value = mock_results

        mock_rerank_model = MagicMock()
        mock_rerank_model.rerank.return_value = [
            {"index": i, "relevance_score": 0.9 - i * 0.05}
            for i in range(10)
        ]

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            top_k=3,
            rerank=True,
            rerank_model=mock_rerank_model,
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )

        result = tool.forward("test query")
        search_results = json.loads(result)

        assert len(search_results) == 3


class TestFieldInfoDefaultFactory:
    """Tests for FieldInfo default_factory handling.

    smolagents Tool may not properly expand Field defaults, so the code
    handles FieldInfo objects with both .default and .default_factory attributes.
    These tests verify the correct handling of both cases.
    """

    def test_convert_to_index_names_with_fieldinfo_default_factory(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test _convert_to_index_names handles FieldInfo with default_factory correctly."""
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo

        # Create a FieldInfo with default_factory only (Pydantic doesn't allow both)
        field_info_with_factory = FieldInfo(
            default_factory=lambda: {"Knowledge X": "es_index_x", "Knowledge Y": "es_index_y"}
        )

        tool = KnowledgeBaseSearchTool(
            index_names=[],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map=field_info_with_factory,
        )

        result = tool._convert_to_index_names(["Knowledge X", "Knowledge Y"])

        # Should convert using the factory result
        assert result == ["es_index_x", "es_index_y"]

    def test_convert_to_index_names_with_fieldinfo_default_only(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test _convert_to_index_names handles FieldInfo with only default correctly."""
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo

        # Create a FieldInfo with default only (no factory)
        field_info_with_default = FieldInfo(
            default={"Knowledge A": "es_index_a"}
        )

        tool = KnowledgeBaseSearchTool(
            index_names=[],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map=field_info_with_default,
        )

        result = tool._convert_to_index_names(["Knowledge A"])

        # Should convert using the default value
        assert result == ["es_index_a"]

    def test_forward_with_fieldinfo_top_k_default_factory(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test forward handles FieldInfo top_k with default_factory correctly."""
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo

        mock_results = create_mock_search_result(3)
        mock_vdb_core.hybrid_search.return_value = mock_results

        # Create FieldInfo with default_factory only (Pydantic doesn't allow both)
        field_info_top_k = FieldInfo(
            default_factory=lambda: 5
        )

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )
        # Override top_k with FieldInfo
        tool.top_k = field_info_top_k

        result = tool.forward("test query")

        # Should use the factory result (5) for top_k
        call_kwargs = mock_vdb_core.hybrid_search.call_args[1]
        assert call_kwargs["top_k"] == 5

    def test_forward_with_fieldinfo_rerank_default_factory(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test forward handles FieldInfo rerank with default_factory correctly."""
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo

        mock_results = create_mock_search_result(10)
        mock_vdb_core.hybrid_search.return_value = mock_results

        # Create FieldInfo with default_factory only (Pydantic doesn't allow both)
        field_info_rerank = FieldInfo(
            default_factory=lambda: True
        )

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )
        # Override rerank with FieldInfo
        tool.rerank = field_info_rerank

        from sdk.nexent.core.utils.constants import RERANK_OVERSEARCH_MULTIPLIER

        result = tool.forward("test query")

        # Should use the factory result (True) and multiply top_k
        call_kwargs = mock_vdb_core.hybrid_search.call_args[1]
        # top_k from default is 3, multiplied by RERANK_OVERSEARCH_MULTIPLIER
        assert call_kwargs["top_k"] == 3 * RERANK_OVERSEARCH_MULTIPLIER

    def test_forward_with_fieldinfo_top_k_default_only(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test forward handles FieldInfo top_k with only default correctly."""
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo

        mock_results = create_mock_search_result(5)
        mock_vdb_core.hybrid_search.return_value = mock_results

        # Create FieldInfo with default only (no factory)
        field_info_top_k = FieldInfo(default=10)

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )
        # Override top_k with FieldInfo
        tool.top_k = field_info_top_k

        result = tool.forward("test query")

        # Should use the default value (10)
        call_kwargs = mock_vdb_core.hybrid_search.call_args[1]
        assert call_kwargs["top_k"] == 10

    def test_forward_with_fieldinfo_rerank_default_only(self, mock_observer, mock_vdb_core, mock_embedding_model):
        """Test forward handles FieldInfo rerank with only default correctly."""
        try:
            from pydantic import FieldInfo
        except ImportError:
            from pydantic.fields import FieldInfo

        mock_results = create_mock_search_result(5)
        mock_vdb_core.hybrid_search.return_value = mock_results

        # Create FieldInfo with default only (no factory)
        field_info_rerank = FieldInfo(default=True)

        tool = KnowledgeBaseSearchTool(
            index_names=["kb1"],
            search_mode="hybrid",
            vdb_core=mock_vdb_core,
            embedding_model=mock_embedding_model,
            observer=mock_observer,
            display_name_to_index_map={},
        )
        # Override rerank with FieldInfo
        tool.rerank = field_info_rerank

        from sdk.nexent.core.utils.constants import RERANK_OVERSEARCH_MULTIPLIER

        result = tool.forward("test query")

        # Should use the default value (True) and multiply top_k
        call_kwargs = mock_vdb_core.hybrid_search.call_args[1]
        # top_k from default is 3, multiplied by RERANK_OVERSEARCH_MULTIPLIER
        assert call_kwargs["top_k"] == 3 * RERANK_OVERSEARCH_MULTIPLIER
