"""
Unit tests for auto_summary_scheduler module.

Tests the background scheduler that periodically regenerates
knowledge base summaries based on configured frequency.
"""
import sys
import os
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# =============================================================================
# MOCK external dependencies BEFORE importing modules under test
# =============================================================================

# Mock psycopg2 before backend.database.client is imported
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.pool'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['psycopg2.extensions'] = MagicMock()


def _create_package_mock(name):
    """Helper to create a package-like mock module."""
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    return pkg


nexent_mock = _create_package_mock('nexent')
sys.modules['nexent'] = nexent_mock

# Mock nexent.monitor module
monitor_module = types.ModuleType('nexent.monitor')
monitor_module.set_monitoring_context = MagicMock()
monitor_module.set_monitoring_operation = MagicMock()
sys.modules['nexent.monitor'] = monitor_module
setattr(nexent_mock, 'monitor', monitor_module)

# Mock nexent.memory module
memory_service_module = types.ModuleType('nexent.memory.memory_service')
memory_service_module.clear_memory = MagicMock()
memory_service_module.add_memory = MagicMock()
memory_service_module.get_memory = MagicMock()
nexent_memory_module = _create_package_mock('nexent.memory')
sys.modules['nexent.memory'] = nexent_memory_module
sys.modules['nexent.memory.memory_service'] = memory_service_module
setattr(nexent_memory_module, 'memory_service', memory_service_module)

# Mock nexent.vector_database.base
vector_db_base_module = types.ModuleType('nexent.vector_database.base')


class MockVectorDatabaseCore:
    def __init__(self, *args, **kwargs):
        pass


vector_db_base_module.VectorDatabaseCore = MockVectorDatabaseCore
sys.modules['nexent.vector_database.base'] = vector_db_base_module

# Mock nexent.vector_database.elasticsearch_core
vector_db_elasticsearch_module = types.ModuleType('nexent.vector_database.elasticsearch_core')


class MockElasticSearchCore:
    def __init__(self, *args, **kwargs):
        pass


vector_db_elasticsearch_module.ElasticSearchCore = MockElasticSearchCore
sys.modules['nexent.vector_database.elasticsearch_core'] = vector_db_elasticsearch_module

# Mock nexent.vector_database.datamate_core
vector_db_datamate_module = types.ModuleType('nexent.vector_database.datamate_core')


class MockDataMateCore:
    def __init__(self, *args, **kwargs):
        self.base_url = kwargs.get('base_url', '')


vector_db_datamate_module.DataMateCore = MockDataMateCore
sys.modules['nexent.vector_database.datamate_core'] = vector_db_datamate_module

# Build nexent.vector_database package
nexent_vector_db_module = _create_package_mock('nexent.vector_database')
nexent_vector_db_module.base = vector_db_base_module
nexent_vector_db_module.elasticsearch_core = vector_db_elasticsearch_module
nexent_vector_db_module.datamate_core = vector_db_datamate_module
nexent_vector_db_module.VectorDatabaseCore = MockVectorDatabaseCore
nexent_vector_db_module.ElasticSearchCore = MockElasticSearchCore
nexent_vector_db_module.DataMateCore = MockDataMateCore
sys.modules['nexent.vector_database'] = nexent_vector_db_module
setattr(nexent_mock, 'vector_database', nexent_vector_db_module)

# Mock nexent.storage module
nexent_storage_module = _create_package_mock('nexent.storage')
sys.modules['nexent.storage'] = nexent_storage_module

storage_factory_module = types.ModuleType('nexent.storage.storage_client_factory')
storage_config_module = types.ModuleType('nexent.storage.minio_config')


class MockMinIOStorageConfig:
    def __init__(self, *args, **kwargs):
        pass

    def validate(self):
        pass


storage_factory_module.create_storage_client_from_config = MagicMock()
storage_factory_module.MinIOStorageConfig = MockMinIOStorageConfig
storage_config_module.MinIOStorageConfig = MockMinIOStorageConfig
sys.modules['nexent.storage.storage_client_factory'] = storage_factory_module
sys.modules['nexent.storage.minio_config'] = storage_config_module
nexent_storage_module.storage_client_factory = storage_factory_module
nexent_storage_module.minio_config = storage_config_module
setattr(nexent_mock, 'storage', nexent_storage_module)

# Mock nexent.core.models
core_mod = types.ModuleType('nexent.core')
models_mod = types.ModuleType('nexent.core.models')
sys.modules['nexent.core'] = core_mod
sys.modules['nexent.core.models'] = models_mod


class StubModel:
    def __init__(self, *a, **k):
        pass


models_mod.OpenAIModel = StubModel
models_mod.OpenAIVLModel = StubModel
models_mod.OpenAILongContextModel = StubModel
setattr(core_mod, 'models', models_mod)

# Mock embedding model
embedding_mod = types.ModuleType('nexent.core.models.embedding_model')


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
sys.modules['nexent.core.models.embedding_model'] = embedding_mod

# Mock rerank model
rerank_mod = types.ModuleType('nexent.core.models.rerank_model')


class StubBaseRerank:
    pass


class StubOpenAICompatibleRerank(StubBaseRerank):
    def __init__(self, *a, **k):
        pass


rerank_mod.BaseRerank = StubBaseRerank
rerank_mod.OpenAICompatibleRerank = StubOpenAICompatibleRerank
sys.modules['nexent.core.models.rerank_model'] = rerank_mod

# Mock stt and tts models
stt_mod = types.ModuleType('nexent.core.models.stt_model')
tts_mod = types.ModuleType('nexent.core.models.tts_model')
sys.modules['nexent.core.models.stt_model'] = stt_mod
sys.modules['nexent.core.models.tts_model'] = tts_mod

# Mock agent modules
agent_model_mod = types.ModuleType('nexent.core.agents.agent_model')
agent_model_mod.ToolConfig = object
sys.modules['nexent.core.agents'] = types.ModuleType('nexent.core.agents')
sys.modules['nexent.core.agents.agent_model'] = agent_model_mod

# Mock jinja2
jinja2_mod = types.ModuleType('jinja2')
jinja2_mod.StrictUndefined = object
jinja2_mod.Template = lambda text, undefined=None: MagicMock()
sys.modules['jinja2'] = jinja2_mod

# Mock boto3
boto3_mock = types.SimpleNamespace()
sys.modules['boto3'] = boto3_mock

# Mock redis
sys.modules['redis'] = MagicMock()
sys.modules['redis.client'] = MagicMock()
sys.modules['redis.connection'] = MagicMock()
sys.modules['redis.lock'] = MagicMock()

# Mock supabase
sys.modules['supabase'] = MagicMock()

# Mock services modules
sys.modules['services'] = _create_package_mock('services')

# Mock services.redis_service
redis_service_mock = types.ModuleType('services.redis_service')
redis_service_mock.get_redis_service = MagicMock(return_value=MagicMock(
    is_task_cancelled=MagicMock(return_value=False),
    save_progress_info=MagicMock(return_value=True),
    delete_knowledgebase_records=MagicMock(return_value={'total_deleted': 0, 'tasks_cancelled': 0}),
    get_progress_info=MagicMock(return_value=None),
    get_error_info=MagicMock(return_value=None),
))
sys.modules['services.redis_service'] = redis_service_mock
setattr(sys.modules['services'], 'redis_service', redis_service_mock)

# Mock services.group_service
group_service_mock = types.ModuleType('services.group_service')
group_service_mock.get_tenant_default_group_id = MagicMock(return_value=1)
sys.modules['services.group_service'] = group_service_mock
setattr(sys.modules['services'], 'group_service', group_service_mock)

# Mock services.vectordatabase_service
vectordatabase_service_mock = types.ModuleType('services.vectordatabase_service')


class MockElasticSearchService:
    def __init__(self, *args, **kwargs):
        pass


vectordatabase_service_mock.ElasticSearchService = MockElasticSearchService
vectordatabase_service_mock.get_vector_db_core = MagicMock()
sys.modules['services.vectordatabase_service'] = vectordatabase_service_mock
setattr(sys.modules['services'], 'vectordatabase_service', vectordatabase_service_mock)

# Mock utils modules
sys.modules['utils'] = types.ModuleType('utils')
sys.modules['backend.utils'] = sys.modules['utils']

# Create document_vector_utils mock
document_vector_utils_mock = types.ModuleType('backend.utils.document_vector_utils')
document_vector_utils_mock.process_documents_for_clustering = MagicMock(return_value=([], []))
document_vector_utils_mock.kmeans_cluster_documents = MagicMock(return_value=[])
document_vector_utils_mock.summarize_clusters_map_reduce = MagicMock(return_value="test summary")
document_vector_utils_mock.merge_cluster_summaries = MagicMock(return_value="merged summary")
sys.modules['backend.utils.document_vector_utils'] = document_vector_utils_mock
sys.modules['utils.document_vector_utils'] = document_vector_utils_mock
setattr(sys.modules['utils'], 'document_vector_utils', document_vector_utils_mock)

str_utils_mock = types.ModuleType('utils.str_utils')
str_utils_mock.convert_list_to_string = lambda items: ",".join(str(item) for item in items) if items else ""
str_utils_mock.convert_string_to_list = lambda s: [int(x.strip()) for x in s.split(',') if x.strip().isdigit()] if s and s.strip() else []
sys.modules['utils.str_utils'] = str_utils_mock
setattr(sys.modules['utils'], 'str_utils', str_utils_mock)

config_utils_mock = types.ModuleType('utils.config_utils')
config_utils_mock.tenant_config_manager = MagicMock()
config_utils_mock.tenant_config_manager.get_app_config = MagicMock(return_value='')
config_utils_mock.tenant_config_manager.get_model_config = MagicMock(return_value={})
config_utils_mock.get_model_name_from_config = MagicMock(return_value='')
sys.modules['utils.config_utils'] = config_utils_mock
setattr(sys.modules['utils'], 'config_utils', config_utils_mock)

# =============================================================================
# Import actual backend modules
# =============================================================================
import importlib
backend_module = importlib.import_module('backend')
sys.modules['backend'] = backend_module
backend_database_module = importlib.import_module('backend.database')
sys.modules['backend.database'] = backend_database_module
backend_database_client_module = importlib.import_module('backend.database.client')
sys.modules['backend.database.client'] = backend_database_client_module

# Mock MinioClient after loading the module
minio_client_mock = MagicMock()
with patch.object(backend_database_client_module, 'MinioClient', minio_client_mock):
    pass

# =============================================================================
# Import modules under test
# =============================================================================
from backend.services.auto_summary_scheduler import (
    _parse_last_summary_time,
    _is_due_for_summary,
    _run_auto_summary_for_kb,
    _scheduler_loop,
    AutoSummaryScheduler,
    FREQUENCY_MAP,
    _in_flight,
    CHECK_INTERVAL_SECONDS,
)
from backend.database.knowledge_db import get_knowledge_bases_for_auto_summary
from backend.consts.scheduler import SCHEDULER_CHECK_INTERVAL_SECONDS


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

    def test_parse_datetime_with_timezone(self):
        """datetime with timezone should have tzinfo removed."""
        from datetime import timezone
        dt = datetime(2025, 4, 30, 10, 30, 0, tzinfo=timezone.utc)
        result = _parse_last_summary_time(dt)
        assert result.tzinfo is None
        assert result == dt.replace(tzinfo=None)

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

    def test_parse_iso_string_with_timezone(self):
        """ISO string with timezone should be parsed correctly."""
        iso_str = "2025-04-30T10:30:00+08:00"
        result = _parse_last_summary_time(iso_str)
        assert result is not None
        assert result.year == 2025
        assert result.month == 4
        assert result.day == 30


class TestIsDueForSummary:
    """Test _is_due_for_summary function."""

    def test_due_when_never_summarized(self):
        """Should be due if last_summary_time is None."""
        result = _is_due_for_summary(None, "3h", None)
        assert result is True

    def test_due_when_interval_elapsed(self):
        """Should be due when time elapsed exceeds frequency and has new docs."""
        last_time = datetime.now() - timedelta(hours=4)
        doc_update = datetime.now() - timedelta(hours=2)
        result = _is_due_for_summary(last_time, "3h", doc_update)
        assert result is True

    def test_not_due_when_interval_not_elapsed(self):
        """Should not be due when time elapsed is less than frequency."""
        last_time = datetime.now() - timedelta(hours=2)
        doc_update = datetime.now()
        result = _is_due_for_summary(last_time, "3h", doc_update)
        assert result is False

    def test_not_due_when_no_doc_changes(self):
        """Should not be due when no document changes since last summary."""
        last_time = datetime.now() - timedelta(hours=4)
        doc_update = last_time - timedelta(hours=1)
        result = _is_due_for_summary(last_time, "3h", doc_update)
        assert result is False

    def test_due_when_new_docs_after_last_summary(self):
        """Should be due when new documents added after last summary."""
        last_time = datetime.now() - timedelta(hours=4)
        doc_update = datetime.now() - timedelta(hours=1)
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

    def test_due_when_no_doc_update_recorded(self):
        """Should be due when last_doc_update_time is None."""
        last_time = datetime.now() - timedelta(hours=4)
        result = _is_due_for_summary(last_time, "3h", None)
        assert result is True

    def test_not_due_for_1h_frequency(self):
        """Should not be due when interval not elapsed and no new docs after last summary."""
        last_time = datetime.now() - timedelta(hours=2)
        doc_update = datetime.now() - timedelta(hours=3)  # Doc update before last summary
        result = _is_due_for_summary(last_time, "1h", doc_update)
        assert result is False

    def test_due_for_6h_frequency(self):
        """Should correctly check 6 hour frequency."""
        last_time = datetime.now() - timedelta(hours=8)
        doc_update = datetime.now() - timedelta(hours=1)
        result = _is_due_for_summary(last_time, "6h", doc_update)
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

            assert "test_index" not in _in_flight

    def test_removes_from_in_flight_on_exception(self):
        """Should remove from in-flight set even when exception occurs."""
        mock_vdb = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', side_effect=Exception("Error")):

            _run_auto_summary_for_kb("test_index", "tenant_id")

            assert "test_index" not in _in_flight

    def test_skips_when_no_documents_found(self):
        """Should skip processing when no documents are found."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=([], [])):

            _run_auto_summary_for_kb("test_index", "tenant_id")

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

            mock_summarize.assert_called_once()
            call_kwargs = mock_summarize.call_args.kwargs
            assert call_kwargs.get('model_id') == 8

    def test_handles_empty_tenant_id(self):
        """Should handle empty tenant_id without crashing."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=(["doc"], [[0.1]])), \
             patch('utils.document_vector_utils.kmeans_cluster_documents', return_value=[0]), \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce', return_value=["summary"]) as mock_summarize, \
             patch('utils.document_vector_utils.merge_cluster_summaries', return_value="final"), \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', side_effect=Exception("No config")):

            _run_auto_summary_for_kb("test_index", "")

            call_kwargs = mock_summarize.call_args.kwargs
            assert call_kwargs.get('model_id') is None

    def test_handles_none_tenant_id(self):
        """Should handle None tenant_id without crashing."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=(["doc"], [[0.1]])), \
             patch('utils.document_vector_utils.kmeans_cluster_documents', return_value=[0]), \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce', return_value=["summary"]) as mock_summarize, \
             patch('utils.document_vector_utils.merge_cluster_summaries', return_value="final"), \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', side_effect=Exception("No config")):

            _run_auto_summary_for_kb("test_index", None)

            call_kwargs = mock_summarize.call_args.kwargs
            assert call_kwargs.get('model_id') is None

    def test_handles_missing_llm_id_in_config(self):
        """Should handle missing LLM_ID in tenant config."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=(["doc"], [[0.1]])), \
             patch('utils.document_vector_utils.kmeans_cluster_documents', return_value=[0]), \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce', return_value=["summary"]) as mock_summarize, \
             patch('utils.document_vector_utils.merge_cluster_summaries', return_value="final"), \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', return_value={}):

            _run_auto_summary_for_kb("test_index", "tenant_id")

            call_kwargs = mock_summarize.call_args.kwargs
            assert call_kwargs.get('model_id') is None

    def test_handles_exception_loading_tenant_config(self):
        """Should handle exceptions when loading tenant config."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=(["doc"], [[0.1]])), \
             patch('utils.document_vector_utils.kmeans_cluster_documents', return_value=[0]), \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce', return_value=["summary"]) as mock_summarize, \
             patch('utils.document_vector_utils.merge_cluster_summaries', return_value="final"), \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', side_effect=Exception("Config error")):

            _run_auto_summary_for_kb("test_index", "tenant_id")

            call_kwargs = mock_summarize.call_args.kwargs
            assert call_kwargs.get('model_id') is None

    def test_exception_during_document_processing(self):
        """Should handle exceptions during document processing."""
        mock_vdb = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', side_effect=Exception("Processing error")):

            _run_auto_summary_for_kb("test_index", "tenant_id")

            assert "test_index" not in _in_flight

    def test_exception_during_clustering(self):
        """Should handle exceptions during clustering."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', side_effect=Exception("Clustering error")):

            _run_auto_summary_for_kb("test_index", "tenant_id")

            assert "test_index" not in _in_flight


class TestSchedulerLoop:
    """Test _scheduler_loop function."""

    def setup_method(self):
        """Clear in-flight set before each test."""
        _in_flight.clear()

    def test_processes_due_knowledge_bases(self):
        """Should process knowledge bases that are due for summary."""
        import threading

        stop_event = threading.Event()
        mock_kb = {
            "index_name": "test_kb",
            "tenant_id": "tenant_1",
            "summary_frequency": "3h",
            "last_summary_time": None,
            "last_doc_update_time": None,
        }

        with patch('backend.services.auto_summary_scheduler.get_knowledge_bases_for_auto_summary', return_value=[mock_kb]), \
             patch('backend.services.auto_summary_scheduler._run_auto_summary_for_kb') as mock_run, \
             patch('backend.services.auto_summary_scheduler.CHECK_INTERVAL_SECONDS', 0.01), \
             patch('backend.services.auto_summary_scheduler.SCHEDULER_CHECK_INTERVAL_SECONDS', 0.01):

            loop_thread = threading.Thread(target=_scheduler_loop, args=(stop_event,))
            loop_thread.start()
            stop_event.set()
            loop_thread.join(timeout=2)

            mock_run.assert_called()

    def test_skips_non_due_knowledge_bases(self):
        """Should skip knowledge bases that are not due for summary."""
        import threading

        stop_event = threading.Event()
        mock_kb = {
            "index_name": "test_kb",
            "tenant_id": "tenant_1",
            "summary_frequency": "3h",
            "last_summary_time": datetime.now() - timedelta(hours=1),
            "last_doc_update_time": datetime.now() - timedelta(hours=2),
        }

        with patch('backend.services.auto_summary_scheduler.get_knowledge_bases_for_auto_summary', return_value=[mock_kb]), \
             patch('backend.services.auto_summary_scheduler._run_auto_summary_for_kb') as mock_run, \
             patch('backend.services.auto_summary_scheduler.CHECK_INTERVAL_SECONDS', 0.01), \
             patch('backend.services.auto_summary_scheduler.SCHEDULER_CHECK_INTERVAL_SECONDS', 0.01):

            loop_thread = threading.Thread(target=_scheduler_loop, args=(stop_event,))
            loop_thread.start()
            stop_event.set()
            loop_thread.join(timeout=2)

            mock_run.assert_not_called()

    def test_handles_exception_in_get_knowledge_bases(self):
        """Should handle exceptions when getting knowledge bases."""
        import threading

        stop_event = threading.Event()

        with patch('backend.services.auto_summary_scheduler.get_knowledge_bases_for_auto_summary', side_effect=Exception("DB error")), \
             patch('backend.services.auto_summary_scheduler._run_auto_summary_for_kb') as mock_run, \
             patch('backend.services.auto_summary_scheduler.CHECK_INTERVAL_SECONDS', 0.01), \
             patch('backend.services.auto_summary_scheduler.SCHEDULER_CHECK_INTERVAL_SECONDS', 0.01):

            loop_thread = threading.Thread(target=_scheduler_loop, args=(stop_event,))
            loop_thread.start()
            stop_event.set()
            loop_thread.join(timeout=2)

            mock_run.assert_not_called()

    def test_respects_stop_event(self):
        """Should respect stop event and exit cleanly."""
        import threading

        stop_event = threading.Event()
        stop_event.set()

        with patch('backend.services.auto_summary_scheduler.get_knowledge_bases_for_auto_summary') as mock_get, \
             patch('backend.services.auto_summary_scheduler.CHECK_INTERVAL_SECONDS', 10), \
             patch('backend.services.auto_summary_scheduler.SCHEDULER_CHECK_INTERVAL_SECONDS', 10):

            loop_thread = threading.Thread(target=_scheduler_loop, args=(stop_event,))
            loop_thread.start()
            loop_thread.join(timeout=1)

            mock_get.assert_not_called()

    def test_stop_event_checked_during_iteration(self):
        """Should check stop_event during KB iteration and break if set."""
        import threading

        stop_event = threading.Event()
        mock_kb = {
            "index_name": "test_kb",
            "tenant_id": "tenant_1",
            "summary_frequency": "3h",
            "last_summary_time": None,
            "last_doc_update_time": None,
        }

        # Track whether break was executed
        break_executed = []

        def mock_run_with_stop_check(*args, **kwargs):
            # Check if stop_event is set during processing
            if stop_event.is_set():
                break_executed.append(True)

        with patch('backend.services.auto_summary_scheduler.get_knowledge_bases_for_auto_summary', return_value=[mock_kb]), \
             patch('backend.services.auto_summary_scheduler._run_auto_summary_for_kb', side_effect=mock_run_with_stop_check), \
             patch('backend.services.auto_summary_scheduler.CHECK_INTERVAL_SECONDS', 0.001), \
             patch('backend.services.auto_summary_scheduler.SCHEDULER_CHECK_INTERVAL_SECONDS', 0.001):

            loop_thread = threading.Thread(target=_scheduler_loop, args=(stop_event,))
            loop_thread.start()

            # Set stop_event during iteration
            import time
            time.sleep(0.05)
            stop_event.set()
            loop_thread.join(timeout=2)

            # If break_executed has True, it means stop_event was checked during iteration


class TestAutoSummaryScheduler:
    """Test AutoSummaryScheduler class."""

    def test_scheduler_initial_state(self):
        """Scheduler should start in stopped state."""
        scheduler = AutoSummaryScheduler()
        assert scheduler._thread is None
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

    def test_stop_with_no_thread(self):
        """Stop should work even when thread is None."""
        scheduler = AutoSummaryScheduler()
        scheduler._thread = None

        scheduler.stop()

        assert scheduler._stop_event.is_set() is True


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
            mock_as_dict.side_effect = [
                {"index_name": "kb1", "summary_frequency": "3h"},
                {"index_name": "kb2", "summary_frequency": "1d"}
            ]

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

    def test_1h_frequency_value(self):
        """1h frequency should be 1 hour."""
        assert FREQUENCY_MAP["1h"] == timedelta(hours=1)

    def test_6h_frequency_value(self):
        """6h frequency should be 6 hours."""
        assert FREQUENCY_MAP["6h"] == timedelta(hours=6)


class TestAutoSummaryIntegration:
    """Integration tests for auto summary workflow."""

    def setup_method(self):
        """Clear in-flight set before each test."""
        _in_flight.clear()

    def test_full_summary_workflow(self):
        """Test complete summary generation workflow."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process, \
             patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_kmeans, \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
             patch('utils.document_vector_utils.merge_cluster_summaries') as mock_merge, \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', return_value={"LLM_ID": "3"}):

            mock_process.return_value = (
                ["doc1", "doc2", "doc3"],
                [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
            )
            mock_kmeans.return_value = [0, 0, 1]
            mock_summarize.return_value = ["Cluster 0 summary", "Cluster 1 summary"]
            mock_merge.return_value = "Final merged summary"

            _run_auto_summary_for_kb("test_kb", "tenant_id")

            mock_process.assert_called_once()
            mock_kmeans.assert_called_once()
            mock_summarize.assert_called_once()
            mock_merge.assert_called_once()
            mock_service.change_summary.assert_called_once()

            assert "test_kb" not in _in_flight

    def test_multiple_knowledge_bases_processed_in_sequence(self):
        """Test processing multiple knowledge bases in sequence."""
        mock_vdb = MagicMock()
        mock_service = MagicMock()

        call_order = []

        def track_calls(*args, **kwargs):
            call_order.append(args[0] if args else kwargs.get('index_name', 'unknown'))

        mock_service.change_summary = track_calls

        with patch('backend.services.auto_summary_scheduler.get_vector_db_core', return_value=mock_vdb), \
             patch('backend.services.auto_summary_scheduler.ElasticSearchService', return_value=mock_service), \
             patch('utils.document_vector_utils.process_documents_for_clustering', return_value=(["doc"], [[0.1]])), \
             patch('utils.document_vector_utils.kmeans_cluster_documents', return_value=[0]), \
             patch('utils.document_vector_utils.summarize_clusters_map_reduce', return_value=["summary"]), \
             patch('utils.document_vector_utils.merge_cluster_summaries', return_value="final"), \
             patch('backend.services.auto_summary_scheduler.tenant_config_manager.load_config', return_value={"LLM_ID": "1"}):

            _run_auto_summary_for_kb("kb_1", "tenant_1")
            _run_auto_summary_for_kb("kb_2", "tenant_2")

            assert len(call_order) == 2
            assert "kb_1" in call_order
            assert "kb_2" in call_order


class TestCheckIntervalSeconds:
    """Test CHECK_INTERVAL_SECONDS configuration."""

    def test_check_interval_is_defined(self):
        """CHECK_INTERVAL_SECONDS should be defined."""
        assert CHECK_INTERVAL_SECONDS is not None
        assert isinstance(CHECK_INTERVAL_SECONDS, int)

    def test_check_interval_matches_scheduler_config(self):
        """CHECK_INTERVAL_SECONDS should match SCHEDULER_CHECK_INTERVAL_SECONDS."""
        assert CHECK_INTERVAL_SECONDS == SCHEDULER_CHECK_INTERVAL_SECONDS
