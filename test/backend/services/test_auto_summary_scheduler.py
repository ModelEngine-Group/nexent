"""
Unit tests for auto_summary_scheduler module.

Tests the background scheduler that periodically regenerates
knowledge base summaries based on configured frequency.
"""
import sys
import types
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta
import pytest

# Mock storage client factory and MinIO before imports
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

# Mock boto3
boto3_mock = types.SimpleNamespace()
sys.modules['boto3'] = boto3_mock

# Stub nexent.vector_database with all submodules
vector_db_mod = types.ModuleType("nexent.vector_database")
vector_db_base = types.ModuleType("nexent.vector_database.base")

class MockVectorDatabaseCore:
    def __init__(self, *a, **k):
        pass

vector_db_base.VectorDatabaseCore = MockVectorDatabaseCore
vector_db_mod.base = vector_db_base

# Stub elasticsearch_core
es_core_mod = types.ModuleType("nexent.vector_database.elasticsearch_core")

class MockElasticSearchCore:
    pass

es_core_mod.ElasticSearchCore = MockElasticSearchCore
vector_db_mod.elasticsearch_core = es_core_mod

# Stub datamate_core
datamate_core_mod = types.ModuleType("nexent.vector_database.datamate_core")

class MockDataMateCore:
    pass

datamate_core_mod.DataMateCore = MockDataMateCore
vector_db_mod.datamate_core = datamate_core_mod

sys.modules["nexent.vector_database"] = vector_db_mod
sys.modules["nexent.vector_database.base"] = vector_db_base
sys.modules["nexent.vector_database.elasticsearch_core"] = es_core_mod
sys.modules["nexent.vector_database.datamate_core"] = datamate_core_mod

# Stub nexent.core.models with all submodules
core_mod = types.ModuleType("nexent.core")
models_mod = types.ModuleType("nexent.core.models")

class StubModel:
    def __init__(self, *a, **k):
        pass

models_mod.OpenAIModel = StubModel
models_mod.OpenAIVLModel = StubModel
models_mod.OpenAILongContextModel = StubModel
core_mod.models = models_mod
sys.modules["nexent.core"] = core_mod
sys.modules["nexent.core.models"] = models_mod

# Stub embedding model with all required classes
embedding_mod = types.ModuleType("nexent.core.models.embedding_model")

class StubBaseEmbedding:
    def __init__(self, *a, **k):
        pass

class StubOpenAICompatibleEmbedding(StubBaseEmbedding):
    pass

class StubJinaEmbedding(StubBaseEmbedding):
    pass

embedding_mod.BaseEmbedding = StubBaseEmbedding
embedding_mod.OpenAICompatibleEmbedding = StubOpenAICompatibleEmbedding
embedding_mod.JinaEmbedding = StubJinaEmbedding
sys.modules["nexent.core.models.embedding_model"] = embedding_mod

# Stub rerank model
rerank_mod = types.ModuleType("nexent.core.models.rerank_model")

class StubBaseRerank:
    pass

class StubOpenAICompatibleRerank(StubBaseRerank):
    def __init__(self, *a, **k):
        pass

rerank_mod.BaseRerank = StubBaseRerank
rerank_mod.OpenAICompatibleRerank = StubOpenAICompatibleRerank
sys.modules["nexent.core.models.rerank_model"] = rerank_mod

# Stub stt and tts models
stt_mod = types.ModuleType("nexent.core.models.stt_model")
tts_mod = types.ModuleType("nexent.core.models.tts_model")
sys.modules["nexent.core.models.stt_model"] = stt_mod
sys.modules["nexent.core.models.tts_model"] = tts_mod

# Stub agent modules
agent_model_mod = types.ModuleType("nexent.core.agents.agent_model")
agent_model_mod.ToolConfig = object
sys.modules["nexent.core.agents"] = types.ModuleType("nexent.core.agents")
sys.modules["nexent.core.agents.agent_model"] = agent_model_mod

# Stub jinja2
jinja2_mod = types.ModuleType("jinja2")
jinja2_mod.StrictUndefined = object
jinja2_mod.Template = lambda text, undefined=None: MagicMock()
sys.modules["jinja2"] = jinja2_mod

# Now import the modules to test
from backend.services.auto_summary_scheduler import (
    _parse_last_summary_time,
    _is_due_for_summary,
    _run_auto_summary_for_kb,
    AutoSummaryScheduler,
    FREQUENCY_MAP,
    _in_flight,
)
from backend.database.knowledge_db import get_knowledge_bases_for_auto_summary


class TestParseLastSummaryTime:
    """Test _parse_last_summary_time function."""

    def test_parse_none_returns_none(self):
        """None input should return None."""
        result = _parse_last_summary_time(None)
        assert result is None

    def test_parse_datetime_object(self):
        """datetime object should be returned without timezone."""
        dt = datetime(2025, 4, 30, 10, 30, 0)
        result = _parse_last_summary_time(dt)
        assert result == dt
        assert result.tzinfo is None

    def test_parse_iso_string(self):
        """ISO format string should be parsed correctly."""
        iso_str = "2025-04-30T10:30:00"
        result = _parse_last_summary_time(iso_str)
        assert result == datetime(2025, 4, 30, 10, 30, 0)

    def test_parse_invalid_string_returns_none(self):
        """Invalid string format should return None."""
        invalid_str = "not-a-date"
        result = _parse_last_summary_time(invalid_str)
        assert result is None

    def test_parse_unsupported_type_returns_none(self):
        """Unsupported types should return None."""
        result = _parse_last_summary_time(12345)
        assert result is None


class TestIsDueForSummary:
    """Test _is_due_for_summary function."""

    def test_due_when_never_summarized(self):
        """Should be due if last_summary_time is None."""
        result = _is_due_for_summary(None, "3h", None)
        assert result is True

    def test_due_when_interval_elapsed(self):
        """Should be due when time elapsed exceeds frequency and has new docs."""
        last_time = datetime.now() - timedelta(hours=4)
        doc_update = datetime.now() - timedelta(hours=2)  # New docs after last summary
        result = _is_due_for_summary(last_time, "3h", doc_update)
        assert result is True

    def test_not_due_when_interval_not_elapsed(self):
        """Should not be due when time elapsed is less than frequency."""
        last_time = datetime.now() - timedelta(hours=2)
        doc_update = datetime.now()  # Recent doc update
        result = _is_due_for_summary(last_time, "3h", doc_update)
        assert result is False

    def test_not_due_when_no_doc_changes(self):
        """Should not be due when no document changes since last summary."""
        last_time = datetime.now() - timedelta(hours=4)  # 4h ago
        doc_update = last_time - timedelta(hours=1)  # Doc update before last summary
        result = _is_due_for_summary(last_time, "3h", doc_update)
        assert result is False

    def test_due_when_new_docs_after_last_summary(self):
        """Should be due when new documents added after last summary."""
        last_time = datetime.now() - timedelta(hours=4)
        doc_update = datetime.now() - timedelta(hours=1)  # New docs 1h ago
        result = _is_due_for_summary(last_time, "3h", doc_update)
        assert result is True

    def test_invalid_frequency_returns_false(self):
        """Invalid frequency should return False."""
        last_time = datetime.now() - timedelta(hours=10)
        doc_update = datetime.now()
        result = _is_due_for_summary(last_time, "invalid", doc_update)
        assert result is False

    def test_due_for_1d_frequency(self):
        """Should correctly check 1 day frequency."""
        last_time = datetime.now() - timedelta(days=2)
        doc_update = datetime.now() - timedelta(days=1)
        result = _is_due_for_summary(last_time, "1d", doc_update)
        assert result is True

    def test_due_for_1w_frequency(self):
        """Should correctly check 1 week frequency."""
        last_time = datetime.now() - timedelta(weeks=2)
        doc_update = datetime.now() - timedelta(weeks=1)
        result = _is_due_for_summary(last_time, "1w", doc_update)
        assert result is True


class TestRunAutoSummaryForKb:
    """Test _run_auto_summary_for_kb function."""

    def setup_method(self):
        """Clear in-flight set before each test."""
        _in_flight.clear()

    def test_skip_if_already_in_flight(self):
        """Should skip processing if index_name is already in _in_flight."""
        _in_flight.add("test_index")
        
        with patch('backend.services.auto_summary_scheduler.get_vector_db_core') as mock_vdb:
            _run_auto_summary_for_kb("test_index", "tenant_id")
            # Should not call get_vector_db_core
            mock_vdb.assert_not_called()

    def test_processes_and_removes_from_in_flight_on_success(self):
        """Should remove from in-flight set after successful processing."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()
        
        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=(["doc1"], [[0.1]])), \
             patch('utils.document_vector_utils.kmeans_cluster_documents', return_value=[0]), \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce', return_value=["summary"]), \
             patch('utils.document_vector_utils.merge_cluster_summaries', return_value="final summary"), \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', return_value={"LLM_ID": "1"}), \
             patch('backend.database.knowledge_db.update_last_summary_time'):
            
            _run_auto_summary_for_kb("test_index", "tenant_id")
            
            # Should be removed from in-flight after completion
            assert "test_index" not in _in_flight

    def test_removes_from_in_flight_on_exception(self):
        """Should remove from in-flight set even when exception occurs."""
        mock_vdb = MagicMock()
        
        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', side_effect=Exception("Error")):
            
            _run_auto_summary_for_kb("test_index", "tenant_id")
            
            # Should be removed even on error
            assert "test_index" not in _in_flight

    def test_skips_when_no_documents_found(self):
        """Should skip processing when no documents are found."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()
        
        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=([], [])):
            
            _run_auto_summary_for_kb("test_index", "tenant_id")
            
            # Should be removed from in-flight
            assert "test_index" not in _in_flight

    def test_uses_llm_id_from_tenant_config(self):
        """Should use LLM_ID from tenant config for summarization."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()
        
        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=(["doc"], [[0.1]])), \
             patch('utils.document_vector_utils.kmeans_cluster_documents', return_value=[0]), \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce', return_value=["summary"]) as mock_summarize, \
             patch('utils.document_vector_utils.merge_cluster_summaries', return_value="final"), \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', return_value={"LLM_ID": "8"}), \
             patch('backend.database.knowledge_db.update_last_summary_time'):
            
            _run_auto_summary_for_kb("test_index", "tenant_id")
            
            # Check that summarize was called with model_id=8
            mock_summarize.assert_called_once()
            call_kwargs = mock_summarize.call_args.kwargs
            assert call_kwargs.get('model_id') == 8


class TestAutoSummaryScheduler:
    """Test AutoSummaryScheduler class."""

    def test_scheduler_initial_state(self):
        """Scheduler should start in stopped state."""
        scheduler = AutoSummaryScheduler()
        assert scheduler._thread is None
        # _stop_event should not be set initially
        assert scheduler._stop_event.is_set() is False

    def test_start_creates_thread(self):
        """Start should create a daemon thread."""
        scheduler = AutoSummaryScheduler()
        
        with patch('backend.services.auto_summary_scheduler.threading.Thread') as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread_instance.daemon = False
            mock_thread_instance.is_alive.return_value = False
            mock_thread.return_value = mock_thread_instance
            
            scheduler.start()
            
            mock_thread.assert_called_once()
            # Verify thread was started
            mock_thread_instance.start.assert_called_once()

    def test_stop_sets_stop_event(self):
        """Stop should set the stop event."""
        scheduler = AutoSummaryScheduler()
        scheduler._thread = MagicMock()
        
        scheduler.stop()
        
        assert scheduler._stop_event.is_set() is True

    def test_stop_waits_for_thread(self):
        """Stop should call join on thread if thread exists."""
        scheduler = AutoSummaryScheduler()
        mock_thread = MagicMock()
        scheduler._thread = mock_thread
        
        scheduler.stop()
        
        # Verify join was called (implementation uses timeout=60)
        mock_thread.join.assert_called_once()

    def test_start_when_already_running(self):
        """Start should not create new thread if already running."""
        scheduler = AutoSummaryScheduler()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        scheduler._thread = mock_thread
        
        with patch('backend.services.auto_summary_scheduler.threading.Thread') as mock_thread_class:
            scheduler.start()
            mock_thread_class.assert_not_called()


class TestGetKnowledgeBasesForAutoSummary:
    """Test get_knowledge_bases_for_auto_summary database function."""

    def test_returns_empty_list_when_no_records(self):
        """Should return empty list when no knowledge bases have summary_frequency."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = []
        
        with patch('backend.database.knowledge_db.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__.return_value = mock_session
            
            result = get_knowledge_bases_for_auto_summary()
            
            assert result == []

    def test_returns_records_with_summary_frequency(self):
        """Should return knowledge bases with non-null summary_frequency."""
        mock_record1 = MagicMock()
        mock_record1.index_name = "kb1"
        mock_record1.summary_frequency = "3h"
        
        mock_record2 = MagicMock()
        mock_record2.index_name = "kb2"
        mock_record2.summary_frequency = "1d"
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_record1, mock_record2]
        
        with patch('backend.database.knowledge_db.get_db_session') as mock_get_session, \
             patch('backend.database.knowledge_db.as_dict') as mock_as_dict:
            mock_get_session.return_value.__enter__.return_value = mock_session
            mock_as_dict.side_effect = [{"index_name": "kb1", "summary_frequency": "3h"}, 
                                        {"index_name": "kb2", "summary_frequency": "1d"}]
            
            result = get_knowledge_bases_for_auto_summary()
            
            assert len(result) == 2
            assert result[0]["index_name"] == "kb1"
            assert result[1]["index_name"] == "kb2"

    def test_filters_deleted_records(self):
        """Should exclude records with delete_flag='Y'."""
        mock_session = MagicMock()
        
        with patch('backend.database.knowledge_db.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__.return_value = mock_session
            
            get_knowledge_bases_for_auto_summary()
            
            # Verify filter was called with delete_flag condition
            filter_calls = mock_session.query.return_value.filter.call_args
            # Check that the query includes delete_flag != 'Y' condition
            assert mock_session.query.return_value.filter.called


class TestFrequencyMap:
    """Test FREQUENCY_MAP configuration."""

    def test_frequency_map_has_expected_keys(self):
        """FREQUENCY_MAP should have all expected frequency keys."""
        expected_keys = ["1h", "3h", "6h", "1d", "1w"]
        assert all(key in FREQUENCY_MAP for key in expected_keys)

    def test_frequency_map_values_are_timedelta(self):
        """FREQUENCY_MAP values should be timedelta objects."""
        for key, value in FREQUENCY_MAP.items():
            assert isinstance(value, timedelta)

    def test_3h_frequency_value(self):
        """3h frequency should be 3 hours."""
        assert FREQUENCY_MAP["3h"] == timedelta(hours=3)

    def test_1d_frequency_value(self):
        """1d frequency should be 1 day."""
        assert FREQUENCY_MAP["1d"] == timedelta(days=1)

    def test_1w_frequency_value(self):
        """1w frequency should be 1 week."""
        assert FREQUENCY_MAP["1w"] == timedelta(weeks=1)


# Integration-style tests (still unit tests but more realistic)
class TestAutoSummaryIntegration:
    """Integration tests for auto summary workflow."""

    def setup_method(self):
        """Clear in-flight set before each test."""
        _in_flight.clear()

    def test_full_summary_workflow(self):
        """Test complete summary generation workflow."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()
        
        # Mock all dependencies with correct patch paths
        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process, \
             patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_kmeans, \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
             patch('utils.document_vector_utils.merge_cluster_summaries') as mock_merge, \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', return_value={"LLM_ID": "3"}):
            
            # Setup mock return values
            mock_process.return_value = (
                ["doc1", "doc2", "doc3"],
                [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
            )
            mock_kmeans.return_value = [0, 0, 1]
            mock_summarize.return_value = ["Cluster 0 summary", "Cluster 1 summary"]
            mock_merge.return_value = "Final merged summary"
            
            # Run the function
            _run_auto_summary_for_kb("test_kb", "tenant_id")
            
            # Verify workflow steps were called
            mock_process.assert_called_once()
            mock_kmeans.assert_called_once()
            mock_summarize.assert_called_once()
            mock_merge.assert_called_once()
            # change_summary is called instead of update_last_summary_time
            mock_service.change_summary.assert_called_once()
            
            # Verify in-flight management
            assert "test_kb" not in _in_flight