"""
Supplementary test module for elasticsearch_core to improve code coverage

Tests for functions not fully covered in the main test file.
"""
import pytest
from unittest.mock import MagicMock, patch, mock_open
import time
import os
import sys
from typing import List, Dict, Any
from datetime import datetime, timedelta

# Add the project root to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../.."))
sys.path.insert(0, project_root)

# Import the class under test
from sdk.nexent.vector_database.elasticsearch_core import ElasticSearchCore, BulkOperation
from sdk.nexent.vector_database.models import IndexStatsSummary
from elasticsearch import exceptions


class TestElasticSearchCoreCoverage:
    """Test class for improving elasticsearch_core coverage"""
    
    @pytest.fixture
    def vdb_core(self):
        """Create an ElasticSearchCore instance for testing."""
        return ElasticSearchCore(
            host="http://localhost:9200",
            api_key="test_api_key",
            verify_certs=False,
            ssl_show_warn=False
        )
    
    def test_force_refresh_with_retry_success(self, vdb_core):
        """Test _force_refresh_with_retry successful refresh"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.refresh.return_value = {"_shards": {"total": 1, "successful": 1}}
        
        result = vdb_core._force_refresh_with_retry("test_index")
        assert result is True
        vdb_core.client.indices.refresh.assert_called_once_with(index="test_index")
    
    def test_force_refresh_with_retry_failure_retry(self, vdb_core):
        """Test _force_refresh_with_retry with retries"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.refresh.side_effect = [
            Exception("Connection error"),
            Exception("Still failing"),
            {"_shards": {"total": 1, "successful": 1}}
        ]
        
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = vdb_core._force_refresh_with_retry("test_index", max_retries=3)
            assert result is True
            assert vdb_core.client.indices.refresh.call_count == 3
    
    def test_force_refresh_with_retry_max_retries_exceeded(self, vdb_core):
        """Test _force_refresh_with_retry when max retries exceeded"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.refresh.side_effect = Exception("Persistent error")
        
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = vdb_core._force_refresh_with_retry("test_index", max_retries=2)
            assert result is False
            assert vdb_core.client.indices.refresh.call_count == 2
    
    def test_ensure_index_ready_success(self, vdb_core):
        """Test _ensure_index_ready successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.cluster.health.return_value = {"status": "green"}
        vdb_core.client.search.return_value = {"hits": {"total": {"value": 0}}}
        
        result = vdb_core._ensure_index_ready("test_index")
        assert result is True
    
    def test_ensure_index_ready_yellow_status(self, vdb_core):
        """Test _ensure_index_ready with yellow status"""
        vdb_core.client = MagicMock()
        vdb_core.client.cluster.health.return_value = {"status": "yellow"}
        vdb_core.client.search.return_value = {"hits": {"total": {"value": 0}}}
        
        result = vdb_core._ensure_index_ready("test_index")
        assert result is True
    
    def test_ensure_index_ready_timeout(self, vdb_core):
        """Test _ensure_index_ready timeout scenario"""
        vdb_core.client = MagicMock()
        vdb_core.client.cluster.health.return_value = {"status": "red"}
        
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = vdb_core._ensure_index_ready("test_index", timeout=1)
            assert result is False
    
    def test_ensure_index_ready_exception(self, vdb_core):
        """Test _ensure_index_ready with exception"""
        vdb_core.client = MagicMock()
        vdb_core.client.cluster.health.side_effect = Exception("Connection error")
        
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = vdb_core._ensure_index_ready("test_index", timeout=1)
            assert result is False
    
    def test_apply_bulk_settings_success(self, vdb_core):
        """Test _apply_bulk_settings successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.put_settings.return_value = {"acknowledged": True}
        
        vdb_core._apply_bulk_settings("test_index")
        vdb_core.client.indices.put_settings.assert_called_once()
    
    def test_apply_bulk_settings_failure(self, vdb_core):
        """Test _apply_bulk_settings with exception"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.put_settings.side_effect = Exception("Settings error")
        
        # Should not raise exception, just log warning
        vdb_core._apply_bulk_settings("test_index")
        vdb_core.client.indices.put_settings.assert_called_once()
    
    def test_restore_normal_settings_success(self, vdb_core):
        """Test _restore_normal_settings successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.put_settings.return_value = {"acknowledged": True}
        vdb_core._force_refresh_with_retry = MagicMock(return_value=True)
        
        vdb_core._restore_normal_settings("test_index")
        vdb_core.client.indices.put_settings.assert_called_once()
        vdb_core._force_refresh_with_retry.assert_called_once_with("test_index")
    
    def test_restore_normal_settings_failure(self, vdb_core):
        """Test _restore_normal_settings with exception"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.put_settings.side_effect = Exception("Settings error")
        
        # Should not raise exception, just log warning
        vdb_core._restore_normal_settings("test_index")
        vdb_core.client.indices.put_settings.assert_called_once()
    
    def test_delete_index_success(self, vdb_core):
        """Test delete_index successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.delete.return_value = {"acknowledged": True}
        
        result = vdb_core.delete_index("test_index")
        assert result is True
        vdb_core.client.indices.delete.assert_called_once_with(index="test_index")
    
    def test_delete_index_not_found(self, vdb_core):
        """Test delete_index when index not found"""
        vdb_core.client = MagicMock()
        # Create a proper NotFoundError with required parameters
        not_found_error = exceptions.NotFoundError(404, "Index not found", {"error": {"type": "index_not_found_exception"}})
        vdb_core.client.indices.delete.side_effect = not_found_error
        
        result = vdb_core.delete_index("test_index")
        assert result is False
        vdb_core.client.indices.delete.assert_called_once_with(index="test_index")
    
    def test_delete_index_general_exception(self, vdb_core):
        """Test delete_index with general exception"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.delete.side_effect = Exception("General error")
        
        result = vdb_core.delete_index("test_index")
        assert result is False
        vdb_core.client.indices.delete.assert_called_once_with(index="test_index")
    
    def test_handle_bulk_errors_no_errors(self, vdb_core):
        """Test _handle_bulk_errors when no errors in response"""
        response = {"errors": False, "items": []}
        vdb_core._handle_bulk_errors(response)
        # Should not raise any exceptions
    
    def test_handle_bulk_errors_with_version_conflict(self, vdb_core):
        """Test _handle_bulk_errors with version conflict (should be ignored)"""
        response = {
            "errors": True,
            "items": [
                {
                    "index": {
                        "error": {
                            "type": "version_conflict_engine_exception",
                            "reason": "Document already exists",
                            "caused_by": {
                                "type": "version_conflict",
                                "reason": "Document version conflict"
                            }
                        }
                    }
                }
            ]
        }
        vdb_core._handle_bulk_errors(response)
        # Should not raise any exceptions for version conflicts
    
    def test_handle_bulk_errors_with_fatal_error(self, vdb_core):
        """Test _handle_bulk_errors with fatal error"""
        response = {
            "errors": True,
            "items": [
                {
                    "index": {
                        "error": {
                            "type": "mapper_parsing_exception",
                            "reason": "Failed to parse field",
                            "caused_by": {
                                "type": "json_parse_exception",
                                "reason": "Unexpected character"
                            }
                        }
                    }
                }
            ]
        }
        with pytest.raises(Exception) as exc_info:
            vdb_core._handle_bulk_errors(response)
        assert "Bulk indexing failed" in str(exc_info.value)
    
    def test_handle_bulk_errors_with_caused_by(self, vdb_core):
        """Test _handle_bulk_errors with caused_by information"""
        response = {
            "errors": True,
            "items": [
                {
                    "index": {
                        "error": {
                            "type": "illegal_argument_exception",
                            "reason": "Invalid argument",
                            "caused_by": {
                                "type": "json_parse_exception",
                                "reason": "JSON parsing failed"
                            }
                        }
                    }
                }
            ]
        }
        with pytest.raises(Exception) as exc_info:
            vdb_core._handle_bulk_errors(response)
        assert "Invalid argument" in str(exc_info.value)
        assert "JSON parsing failed" in str(exc_info.value)
    
    def test_delete_documents_success(self, vdb_core):
        """Test delete_documents successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.delete_by_query.return_value = {"deleted": 5}
        
        result = vdb_core.delete_documents("test_index", "/path/to/file.pdf")
        assert result == 5
        vdb_core.client.delete_by_query.assert_called_once()
    
    def test_delete_documents_exception(self, vdb_core):
        """Test delete_documents with exception"""
        vdb_core.client = MagicMock()
        vdb_core.client.delete_by_query.side_effect = Exception("Delete error")
        
        result = vdb_core.delete_documents("test_index", "/path/to/file.pdf")
        assert result == 0
        vdb_core.client.delete_by_query.assert_called_once()

    def test_get_index_chunks_not_found(self, vdb_core):
        """Ensure get_index_chunks handles missing index gracefully."""
        vdb_core.client = MagicMock()
        vdb_core.client.count.side_effect = exceptions.NotFoundError(
            404, "missing", {})

        result = vdb_core.get_index_chunks("missing-index")

        assert result == {"chunks": [], "total": 0,
                          "page": None, "page_size": None}
        vdb_core.client.clear_scroll.assert_not_called()

    def test_get_index_chunks_cleanup_warning(self, vdb_core):
        """Ensure clear_scroll errors are swallowed."""
        vdb_core.client = MagicMock()
        vdb_core.client.count.return_value = {"count": 1}
        vdb_core.client.search.return_value = {
            "_scroll_id": "scroll123",
            "hits": {"hits": [{"_id": "doc-1", "_source": {"content": "A"}}]}
        }
        vdb_core.client.scroll.return_value = {
            "_scroll_id": "scroll123",
            "hits": {"hits": []}
        }
        vdb_core.client.clear_scroll.side_effect = Exception("cleanup-failed")

        result = vdb_core.get_index_chunks("kb-index")

        assert len(result["chunks"]) == 1
        assert result["chunks"][0]["id"] == "doc-1"
        vdb_core.client.clear_scroll.assert_called_once_with(
            scroll_id="scroll123")

    def test_create_index_request_error_existing(self, vdb_core):
        """Ensure RequestError with resource already exists still succeeds."""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.exists.return_value = False
        meta = MagicMock(status=400)
        vdb_core.client.indices.create.side_effect = exceptions.RequestError(
            "resource_already_exists_exception", meta, {"error": {"reason": "exists"}}
        )
        vdb_core._ensure_index_ready = MagicMock(return_value=True)

        assert vdb_core.create_index("test_index") is True
        vdb_core._ensure_index_ready.assert_called_once_with("test_index")

    def test_create_index_request_error_failure(self, vdb_core):
        """Ensure create_index returns False for non recoverable RequestError."""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.exists.return_value = False
        meta = MagicMock(status=400)
        vdb_core.client.indices.create.side_effect = exceptions.RequestError(
            "validation_exception", meta, {"error": {"reason": "bad"}}
        )

        assert vdb_core.create_index("test_index") is False

    def test_create_index_general_exception(self, vdb_core):
        """Ensure unexpected exception from create_index returns False."""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.exists.return_value = False
        vdb_core.client.indices.create.side_effect = Exception("boom")

        assert vdb_core.create_index("test_index") is False

    def test_force_refresh_with_retry_zero_attempts(self, vdb_core):
        """Ensure guard clause without attempts returns False."""
        vdb_core.client = MagicMock()
        result = vdb_core._force_refresh_with_retry("idx", max_retries=0)
        assert result is False

    def test_bulk_operation_context_preexisting_operation(self, vdb_core):
        """Ensure context skips apply/restore when operations remain."""
        existing = BulkOperation(
            index_name="test_index",
            operation_id="existing",
            start_time=datetime.utcnow(),
            expected_duration=timedelta(seconds=30),
        )
        vdb_core._bulk_operations = {"test_index": [existing]}

        with patch.object(vdb_core, "_apply_bulk_settings") as mock_apply, \
                patch.object(vdb_core, "_restore_normal_settings") as mock_restore:

            with vdb_core.bulk_operation_context("test_index") as op_id:
                assert op_id != existing.operation_id

        mock_apply.assert_not_called()
        mock_restore.assert_not_called()
        assert vdb_core._bulk_operations["test_index"] == [existing]

    def test_get_user_indices_exception(self, vdb_core):
        """Ensure get_user_indices returns empty list on failure."""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.get_alias.side_effect = Exception("failure")

        assert vdb_core.get_user_indices() == []

    def test_check_index_exists(self, vdb_core):
        """Ensure check_index_exists delegates to client."""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.exists.return_value = True

        assert vdb_core.check_index_exists("idx") is True
        vdb_core.client.indices.exists.assert_called_once_with(index="idx")

    def test_small_batch_insert_sets_embedding_model_name(self, vdb_core):
        """_small_batch_insert should attach embedding model name."""
        vdb_core.client = MagicMock()
        vdb_core.client.bulk.return_value = {"errors": False, "items": []}
        vdb_core._preprocess_documents = MagicMock(return_value=[{"content": "body"}])
        vdb_core._handle_bulk_errors = MagicMock()

        mock_embedding_model = MagicMock()
        mock_embedding_model.get_embeddings.return_value = [[0.1, 0.2]]
        mock_embedding_model.embedding_model_name = "demo-model"

        vdb_core._small_batch_insert("idx", [{"content": "body"}], "content", mock_embedding_model)
        operations = vdb_core.client.bulk.call_args.kwargs["operations"]
        inserted_doc = operations[1]
        assert inserted_doc["embedding_model_name"] == "demo-model"

    def test_large_batch_insert_sets_default_embedding_model_name(self, vdb_core):
        """_large_batch_insert should fall back to 'unknown' when attr missing."""
        vdb_core.client = MagicMock()
        vdb_core.client.bulk.return_value = {"errors": False, "items": []}
        vdb_core._preprocess_documents = MagicMock(return_value=[{"content": "body"}])
        vdb_core._handle_bulk_errors = MagicMock()

        class SimpleEmbedding:
            def get_embeddings(self, texts):
                return [[0.1 for _ in texts]]

        embedding_model = SimpleEmbedding()

        vdb_core._large_batch_insert("idx", [{"content": "body"}], 10, "content", embedding_model)
        operations = vdb_core.client.bulk.call_args.kwargs["operations"]
        inserted_doc = operations[1]
        assert inserted_doc["embedding_model_name"] == "unknown"

    def test_large_batch_insert_bulk_exception(self, vdb_core):
        """Ensure bulk exceptions are handled and indexing continues."""
        vdb_core.client = MagicMock()
        vdb_core.client.bulk.side_effect = Exception("bulk error")
        vdb_core._preprocess_documents = MagicMock(return_value=[{"content": "body"}])

        mock_embedding_model = MagicMock()
        mock_embedding_model.get_embeddings.return_value = [[0.1]]

        with pytest.raises(Exception) as exc_info:
            vdb_core._large_batch_insert("idx", [{"content": "body"}], 1, "content", mock_embedding_model)
        assert "bulk error" in str(exc_info.value)

    def test_large_batch_insert_preprocess_exception(self, vdb_core):
        """Ensure outer exception handler returns zero on preprocess failure."""
        vdb_core._preprocess_documents = MagicMock(side_effect=Exception("fail"))

        mock_embedding_model = MagicMock()
        with pytest.raises(Exception) as exc_info:
            vdb_core._large_batch_insert("idx", [{"content": "body"}], 10, "content", mock_embedding_model)
        assert "fail" in str(exc_info.value)

    def test_count_documents_success(self, vdb_core):
        """Ensure count_documents returns ES count."""
        vdb_core.client = MagicMock()
        vdb_core.client.count.return_value = {"count": 42}

        assert vdb_core.count_documents("idx") == 42

    def test_count_documents_exception(self, vdb_core):
        """Ensure count_documents returns zero on error."""
        vdb_core.client = MagicMock()
        vdb_core.client.count.side_effect = Exception("fail")

        assert vdb_core.count_documents("idx") == 0

    def test_search_and_multi_search_passthrough(self, vdb_core):
        """Ensure search helpers delegate to the client."""
        vdb_core.client = MagicMock()
        vdb_core.client.search.return_value = {"hits": {}}
        vdb_core.client.msearch.return_value = {"responses": []}

        assert vdb_core.search("idx", {"query": {"match_all": {}}}) == {"hits": {}}
        assert vdb_core.multi_search([{"query": {"match_all": {}}}], "idx") == {"responses": []}

    def test_exec_query_formats_results(self, vdb_core):
        """Ensure exec_query strips metadata and exposes scores."""
        vdb_core.client = MagicMock()
        vdb_core.client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_score": 1.23,
                        "_index": "idx",
                        "_source": {"id": "doc1", "content": "body"},
                    }
                ]
            }
        }

        results = vdb_core.exec_query("idx", {"query": {}})
        assert results == [
            {"score": 1.23, "document": {"id": "doc1", "content": "body"}, "index": "idx"}
        ]

    def test_hybrid_search_missing_fields_logged_for_accurate(self, vdb_core):
        """Ensure hybrid_search tolerates missing accurate fields."""
        mock_embedding_model = MagicMock()
        with patch.object(vdb_core, "accurate_search", return_value=[{"score": 1.0}]), \
                patch.object(vdb_core, "semantic_search", return_value=[]):
            assert vdb_core.hybrid_search(["idx"], "query", mock_embedding_model) == []

    def test_hybrid_search_missing_fields_logged_for_semantic(self, vdb_core):
        """Ensure hybrid_search tolerates missing semantic fields."""
        mock_embedding_model = MagicMock()
        with patch.object(vdb_core, "accurate_search", return_value=[]), \
                patch.object(vdb_core, "semantic_search", return_value=[{"score": 0.5}]):
            assert vdb_core.hybrid_search(["idx"], "query", mock_embedding_model) == []

    def test_hybrid_search_faulty_combined_results(self, vdb_core):
        """Inject faulty combined result to hit KeyError handling in final loop."""
        mock_embedding_model = MagicMock()
        accurate_payload = [
            {"score": 1.0, "document": {"id": "doc1"}, "index": "idx"}
        ]

        with patch.object(vdb_core, "accurate_search", return_value=accurate_payload), \
                patch.object(vdb_core, "semantic_search", return_value=[]):

            injected = {"done": False}

            def tracer(frame, event, arg):
                if (
                    frame.f_code.co_name == "hybrid_search"
                    and event == "line"
                    and frame.f_lineno == 788
                    and not injected["done"]
                ):
                    frame.f_locals["combined_results"]["faulty"] = {
                        "accurate_score": 0,
                        "semantic_score": 0,
                    }
                    injected["done"] = True
                return tracer

            sys.settrace(tracer)
            try:
                results = vdb_core.hybrid_search(["idx"], "query", mock_embedding_model)
            finally:
                sys.settrace(None)

            assert len(results) == 1

    def test_get_documents_detail_exception(self, vdb_core):
        """Ensure get_documents_detail returns empty list on failure."""
        vdb_core.client = MagicMock()
        vdb_core.client.search.side_effect = Exception("fail")

        assert vdb_core.get_documents_detail("idx") == []

    def test_get_indices_detail_success(self, vdb_core):
        """Test get_indices_detail successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.stats.return_value = {
            "indices": {
                "test_index": {
                    "primaries": {
                        "docs": {"count": 100},
                        "store": {"size_in_bytes": 1024},
                        "search": {"query_total": 50},
                        "request_cache": {"hit_count": 25}
                    }
                }
            }
        }
        vdb_core.client.indices.get_settings.return_value = {
            "test_index": {
                "settings": {
                    "index": {
                        "number_of_shards": "1",
                        "number_of_replicas": "0",
                        "creation_date": "1640995200000"
                    }
                }
            }
        }
        vdb_core.client.search.return_value = {
            "aggregations": {
                "unique_path_or_url_count": {"value": 10},
                "process_sources": {"buckets": [{"key": "test_source"}]},
                "embedding_models": {"buckets": [{"key": "test_model"}]}
            }
        }
        
        result = vdb_core.get_indices_detail(["test_index"])
        assert "test_index" in result
        assert isinstance(result["test_index"], IndexStatsSummary)
        assert result["test_index"].base_info.doc_count == 10
        assert result["test_index"].search_performance.total_search_count == 50
    
    def test_get_indices_detail_exception(self, vdb_core):
        """Test get_indices_detail with exception"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.stats.side_effect = Exception("Stats error")
        
        result = vdb_core.get_indices_detail(["test_index"])
        assert "test_index" in result
        assert isinstance(result["test_index"], IndexStatsSummary)
        assert result["test_index"].error == "Stats error"
    
    def test_get_indices_detail_with_embedding_dim(self, vdb_core):
        """Test get_indices_detail with embedding dimension"""
        vdb_core.client = MagicMock()
        vdb_core.client.indices.stats.return_value = {
            "indices": {
                "test_index": {
                    "primaries": {
                        "docs": {"count": 100},
                        "store": {"size_in_bytes": 1024},
                        "search": {"query_total": 50},
                        "request_cache": {"hit_count": 25}
                    }
                }
            }
        }
        vdb_core.client.indices.get_settings.return_value = {
            "test_index": {
                "settings": {
                    "index": {
                        "number_of_shards": "1",
                        "number_of_replicas": "0",
                        "creation_date": "1640995200000"
                    }
                }
            }
        }
        vdb_core.client.search.return_value = {
            "aggregations": {
                "unique_path_or_url_count": {"value": 10},
                "process_sources": {"buckets": [{"key": "test_source"}]},
                "embedding_models": {"buckets": [{"key": "test_model"}]}
            }
        }
        
        result = vdb_core.get_indices_detail(["test_index"], embedding_dim=512)
        assert "test_index" in result
        assert isinstance(result["test_index"], IndexStatsSummary)
        assert result["test_index"].base_info.embedding_dim == 512
    
    def test_bulk_operation_context_success(self, vdb_core):
        """Test bulk_operation_context successful case"""
        vdb_core._bulk_operations = {}
        vdb_core._operation_counter = 0
        vdb_core._settings_lock = MagicMock()
        vdb_core._apply_bulk_settings = MagicMock()
        vdb_core._restore_normal_settings = MagicMock()
        
        with vdb_core.bulk_operation_context("test_index") as operation_id:
            assert operation_id is not None
            assert "test_index" in vdb_core._bulk_operations
            vdb_core._apply_bulk_settings.assert_called_once_with("test_index")
        
        # After context exit, should restore settings
        vdb_core._restore_normal_settings.assert_called_once_with("test_index")
    
    def test_bulk_operation_context_multiple_operations(self, vdb_core):
        """Test bulk_operation_context with multiple operations"""
        vdb_core._bulk_operations = {}
        vdb_core._operation_counter = 0
        vdb_core._settings_lock = MagicMock()
        vdb_core._apply_bulk_settings = MagicMock()
        vdb_core._restore_normal_settings = MagicMock()
        
        # First operation
        with vdb_core.bulk_operation_context("test_index") as op1:
            assert op1 is not None
            vdb_core._apply_bulk_settings.assert_called_once()
        
        # After first operation exits, settings should be restored
        vdb_core._restore_normal_settings.assert_called_once_with("test_index")
        
        # Second operation - will apply settings again since first operation is done
        with vdb_core.bulk_operation_context("test_index") as op2:
            assert op2 is not None
            # Should call apply_bulk_settings again since first operation is done
            assert vdb_core._apply_bulk_settings.call_count == 2
        
        # After second operation exits, should restore settings again
        assert vdb_core._restore_normal_settings.call_count == 2
    
    def test_small_batch_insert_success(self, vdb_core):
        """Test _small_batch_insert successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.bulk.return_value = {"items": [], "errors": False}
        vdb_core._preprocess_documents = MagicMock(return_value=[
            {"content": "test content", "title": "test"}
        ])
        vdb_core._handle_bulk_errors = MagicMock()
        
        mock_embedding_model = MagicMock()
        mock_embedding_model.get_embeddings.return_value = [[0.1, 0.2, 0.3]]
        mock_embedding_model.embedding_model_name = "test_model"
        
        documents = [{"content": "test content", "title": "test"}]
        
        result = vdb_core._small_batch_insert("test_index", documents, "content", mock_embedding_model)
        assert result == 1
        vdb_core.client.bulk.assert_called_once()
    
    def test_small_batch_insert_exception(self, vdb_core):
        """Test _small_batch_insert with exception"""
        vdb_core._preprocess_documents = MagicMock(side_effect=Exception("Preprocess error"))
        
        mock_embedding_model = MagicMock()
        documents = [{"content": "test content", "title": "test"}]
        
        with pytest.raises(Exception) as exc_info:
            vdb_core._small_batch_insert("test_index", documents, "content", mock_embedding_model)
        assert "Preprocess error" in str(exc_info.value)
    
    def test_large_batch_insert_success(self, vdb_core):
        """Test _large_batch_insert successful case"""
        vdb_core.client = MagicMock()
        vdb_core.client.bulk.return_value = {"items": [], "errors": False}
        vdb_core._preprocess_documents = MagicMock(return_value=[
            {"content": "test content", "title": "test"}
        ])
        vdb_core._handle_bulk_errors = MagicMock()
        
        mock_embedding_model = MagicMock()
        mock_embedding_model.get_embeddings.return_value = [[0.1, 0.2, 0.3]]
        mock_embedding_model.embedding_model_name = "test_model"
        
        documents = [{"content": "test content", "title": "test"}]
        
        result = vdb_core._large_batch_insert("test_index", documents, 10, "content", mock_embedding_model)
        assert result == 1
        vdb_core.client.bulk.assert_called_once()
    
    def test_large_batch_insert_embedding_error(self, vdb_core):
        """Test _large_batch_insert with embedding API error"""
        vdb_core.client = MagicMock()
        vdb_core._preprocess_documents = MagicMock(return_value=[
            {"content": "test content", "title": "test"}
        ])
        
        mock_embedding_model = MagicMock()
        mock_embedding_model.get_embeddings.side_effect = Exception("Embedding API error")
        
        documents = [{"content": "test content", "title": "test"}]
        
        result = vdb_core._large_batch_insert("test_index", documents, 10, "content", mock_embedding_model)
        assert result == 0  # No documents indexed due to embedding error
    
    def test_large_batch_insert_no_embeddings(self, vdb_core):
        """Test _large_batch_insert with no successful embeddings"""
        vdb_core.client = MagicMock()
        vdb_core._preprocess_documents = MagicMock(return_value=[
            {"content": "test content", "title": "test"}
        ])
        
        mock_embedding_model = MagicMock()
        mock_embedding_model.get_embeddings.side_effect = Exception("Embedding API error")
        
        documents = [{"content": "test content", "title": "test"}]
        
        result = vdb_core._large_batch_insert("test_index", documents, 10, "content", mock_embedding_model)
        assert result == 0  # No documents indexed
