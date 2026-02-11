import pytest
from unittest.mock import MagicMock, patch
import time
from typing import List, Dict, Any
from elasticsearch import exceptions

# Import the class under test
from sdk.nexent.vector_database.elasticsearch_core import ElasticSearchCore

# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

@pytest.fixture
def elasticsearch_core_instance():
    """Create an ElasticSearchCore instance for testing."""
    return ElasticSearchCore(
        host="http://localhost:9200",
        api_key="test_api_key",
        verify_certs=False,
        ssl_show_warn=False
    )


@pytest.fixture
def sample_documents():
    """Sample documents for testing."""
    return [
        {
            "content": "This is test content 1",
            "title": "Test Document 1",
            "filename": "test1.pdf",
            "path_or_url": "/path/to/test1.pdf"
        },
        {
            "content": "This is test content 2",
            "title": "Test Document 2",
            "filename": "test2.pdf",
            "path_or_url": "/path/to/test2.pdf",
            "file_size": 1024,
            "create_time": "2025-01-15T10:30:00",
            "date": "2025-01-15",
            "process_source": "CustomProcessor",
            "id": "existing_id_123"
        }
    ]


# ----------------------------------------------------------------------------
# Tests for _preprocess_documents method
# ----------------------------------------------------------------------------

def test_preprocess_documents_with_complete_document(elasticsearch_core_instance, sample_documents):
    """Test preprocessing a document that already has all required fields."""
    # Use the second document which has all fields
    complete_doc = [sample_documents[1]]
    content_field = "content"

    result = elasticsearch_core_instance._preprocess_documents(complete_doc, content_field)

    assert len(result) == 1
    doc = result[0]

    # Should preserve existing values
    assert doc["content"] == "This is test content 2"
    assert doc["title"] == "Test Document 2"
    assert doc["filename"] == "test2.pdf"
    assert doc["path_or_url"] == "/path/to/test2.pdf"
    assert doc["file_size"] == 1024
    assert doc["create_time"] == "2025-01-15T10:30:00"
    assert doc["date"] == "2025-01-15"
    assert doc["process_source"] == "CustomProcessor"
    assert doc["id"] == "existing_id_123"


def test_preprocess_documents_with_incomplete_document(elasticsearch_core_instance, sample_documents):
    """Test preprocessing a document missing required fields."""
    # Use the first document which is missing several fields
    incomplete_doc = [sample_documents[0]]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
         patch('time.time') as mock_time, \
         patch('time.gmtime') as mock_gmtime:

        # Mock time functions
        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(incomplete_doc, content_field)

    assert len(result) == 1
    doc = result[0]

    # Should preserve existing values
    assert doc["content"] == "This is test content 1"
    assert doc["title"] == "Test Document 1"
    assert doc["filename"] == "test1.pdf"
    assert doc["path_or_url"] == "/path/to/test1.pdf"

    # Should add missing fields with default values
    assert doc["create_time"] == "2025-01-15T10:30:00"
    assert doc["date"] == "2025-01-15"
    assert doc["file_size"] == 0
    assert doc["process_source"] == "Unstructured"

    # Should generate an ID
    assert "id" in doc
    assert doc["id"].startswith("1642234567_")
    assert len(doc["id"]) <= 20


def test_preprocess_documents_with_multiple_documents(elasticsearch_core_instance, sample_documents):
    """Test preprocessing multiple documents."""
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
         patch('time.time') as mock_time, \
         patch('time.gmtime') as mock_gmtime:

        # Mock time functions
        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(sample_documents, content_field)

    assert len(result) == 2

    # First document should have defaults added
    doc1 = result[0]
    assert doc1["create_time"] == "2025-01-15T10:30:00"
    assert doc1["date"] == "2025-01-15"
    assert doc1["file_size"] == 0
    assert doc1["process_source"] == "Unstructured"
    assert "id" in doc1

    # Second document should preserve existing values
    doc2 = result[1]
    assert doc2["create_time"] == "2025-01-15T10:30:00"
    assert doc2["date"] == "2025-01-15"
    assert doc2["file_size"] == 1024
    assert doc2["process_source"] == "CustomProcessor"
    assert doc2["id"] == "existing_id_123"


def test_preprocess_documents_preserves_original_data(elasticsearch_core_instance):
    """Test that original documents are not modified."""
    original_docs = [
        {
            "content": "Original content",
            "title": "Original title"
        }
    ]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
         patch('time.time') as mock_time, \
         patch('time.gmtime') as mock_gmtime:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(original_docs, content_field)

    # Original document should remain unchanged
    assert original_docs[0] == {"content": "Original content", "title": "Original title"}

    # Result should be a new document with added fields
    assert result[0]["content"] == "Original content"
    assert result[0]["title"] == "Original title"
    assert "create_time" in result[0]
    assert "date" in result[0]
    assert "file_size" in result[0]
    assert "process_source" in result[0]
    assert "id" in result[0]


def test_preprocess_documents_with_empty_list(elasticsearch_core_instance):
    """Test preprocessing an empty list of documents."""
    content_field = "content"

    result = elasticsearch_core_instance._preprocess_documents([], content_field)

    assert result == []


def test_preprocess_documents_id_generation(elasticsearch_core_instance):
    """Test that ID generation works correctly with different content."""
    docs = [
        {"content": "Content 1"},
        {"content": "Content 2"},
        {"content": "Content 1"}  # Same content as first
    ]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
         patch('time.time') as mock_time, \
         patch('time.gmtime') as mock_gmtime:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(docs, content_field)

    assert len(result) == 3

    # All documents should have IDs
    assert "id" in result[0]
    assert "id" in result[1]
    assert "id" in result[2]

    # IDs should be different for different content
    assert result[0]["id"] != result[1]["id"]

    # Same content should generate same hash part (but might be different due to time)
    id1_parts = result[0]["id"].split("_")
    id3_parts = result[2]["id"].split("_")
    assert len(id1_parts) == 2
    assert len(id3_parts) == 2
    assert id1_parts[1] == id3_parts[1]  # Hash part should be same


def test_preprocess_documents_with_none_values(elasticsearch_core_instance):
    """Test preprocessing documents with None values."""
    docs = [
        {
            "content": "Test content",
            "file_size": None,
            "create_time": None,
            "date": None,
            "process_source": None
        }
    ]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
         patch('time.time') as mock_time, \
         patch('time.gmtime') as mock_gmtime:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(docs, content_field)

    doc = result[0]

    # None values should be replaced with defaults
    assert doc["file_size"] == 0
    assert doc["create_time"] == "2025-01-15T10:30:00"
    assert doc["date"] == "2025-01-15"
    assert doc["process_source"] == "Unstructured"
    assert "id" in doc


def test_preprocess_documents_with_zero_values(elasticsearch_core_instance):
    """Test that zero values are preserved and not replaced."""
    docs = [
        {
            "content": "Test content",
            "file_size": 0,
            "create_time": "2025-01-15T10:30:00",
            "date": "2025-01-15",
            "process_source": "CustomProcessor"
        }
    ]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
         patch('time.time') as mock_time, \
         patch('time.gmtime') as mock_gmtime:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(docs, content_field)

    doc = result[0]

    # Zero values should be preserved
    assert doc["file_size"] == 0
    assert doc["create_time"] == "2025-01-15T10:30:00"
    assert doc["date"] == "2025-01-15"
    assert doc["process_source"] == "CustomProcessor"


def test_preprocess_large_batch_of_documents(elasticsearch_core_instance):
    """Test preprocessing a large batch of documents (100+ chunks scenario)."""
    # Simulate processing a large file that generates 150 chunks
    large_docs = [
        {
            "content": f"Chunk content number {i}",
            "title": f"Document chunk {i}",
            "filename": "large_document.pdf",
            "path_or_url": "/path/to/large_document.pdf"
        }
        for i in range(150)
    ]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
            patch('time.time') as mock_time, \
            patch('time.gmtime') as mock_gmtime:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(
            large_docs, content_field)

    # Should process all 150 documents
    assert len(result) == 150

    # Verify each document has required fields
    for i, doc in enumerate(result):
        assert doc["content"] == f"Chunk content number {i}"
        assert doc["title"] == f"Document chunk {i}"
        assert doc["filename"] == "large_document.pdf"
        assert doc["path_or_url"] == "/path/to/large_document.pdf"
        assert "create_time" in doc
        assert "date" in doc
        assert "file_size" in doc
        assert "process_source" in doc
        assert "id" in doc


def test_preprocess_documents_performance_with_large_batch(elasticsearch_core_instance):
    """Test that preprocessing performance is acceptable for large batches."""
    import time as time_module

    # Create 200 documents to test performance
    large_docs = [
        {
            "content": f"Content {i}" * 100,  # Longer content
            "title": f"Title {i}",
            "filename": f"file_{i}.txt"
        }
        for i in range(200)
    ]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
            patch('time.time') as mock_time, \
            patch('time.gmtime') as mock_gmtime:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        start = time_module.time()
        result = elasticsearch_core_instance._preprocess_documents(
            large_docs, content_field)
        elapsed = time_module.time() - start

    # Should complete in reasonable time (< 5 seconds for 200 docs)
    assert elapsed < 5.0

    # All documents should be processed
    assert len(result) == 200


def test_preprocess_documents_maintains_order(elasticsearch_core_instance):
    """Test that document order is preserved during preprocessing."""
    docs = [
        {"content": f"Content {i}", "sequence": i}
        for i in range(50)
    ]
    content_field = "content"

    with patch('time.strftime') as mock_strftime, \
            patch('time.time') as mock_time, \
            patch('time.gmtime') as mock_gmtime:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_gmtime.return_value = None

        result = elasticsearch_core_instance._preprocess_documents(
            docs, content_field)

    # Verify order is maintained
    for i, doc in enumerate(result):
        assert doc["sequence"] == i
        assert doc["content"] == f"Content {i}"


# ----------------------------------------------------------------------------
# Tests for index management methods
# ----------------------------------------------------------------------------

def test_create_index_success(elasticsearch_core_instance):
    """Test creating a new vector index successfully."""
    with patch.object(elasticsearch_core_instance.client.indices, 'exists') as mock_exists, \
            patch.object(elasticsearch_core_instance.client.indices, 'create') as mock_create, \
            patch.object(elasticsearch_core_instance, '_force_refresh_with_retry') as mock_refresh, \
            patch.object(elasticsearch_core_instance, '_ensure_index_ready') as mock_ready:

        mock_exists.return_value = False
        mock_create.return_value = {"acknowledged": True}
        mock_refresh.return_value = True
        mock_ready.return_value = True

        result = elasticsearch_core_instance.create_index(
            "test_index", embedding_dim=1024)

        assert result is True
        mock_exists.assert_called_once_with(index="test_index")
        mock_create.assert_called_once()
        mock_refresh.assert_called_once_with("test_index")
        mock_ready.assert_called_once_with("test_index")


def test_create_index_already_exists(elasticsearch_core_instance):
    """Test creating an index that already exists."""
    with patch.object(elasticsearch_core_instance.client.indices, 'exists') as mock_exists, \
            patch.object(elasticsearch_core_instance, '_ensure_index_ready') as mock_ready:

        mock_exists.return_value = True
        mock_ready.return_value = True

        result = elasticsearch_core_instance.create_index(
            "existing_index")

        assert result is True
        mock_exists.assert_called_once_with(index="existing_index")
        mock_ready.assert_called_once_with("existing_index")


def test_delete_index_success(elasticsearch_core_instance):
    """Test deleting an index successfully."""
    with patch.object(elasticsearch_core_instance.client.indices, 'delete') as mock_delete:
        mock_delete.return_value = {"acknowledged": True}

        result = elasticsearch_core_instance.delete_index("test_index")

        assert result is True
        mock_delete.assert_called_once_with(index="test_index")


def test_delete_index_not_found(elasticsearch_core_instance):
    """Test deleting an index that doesn't exist."""
    with patch.object(elasticsearch_core_instance.client.indices, 'delete') as mock_delete:
        mock_delete.side_effect = exceptions.NotFoundError(
            "Index not found", {}, {})

        result = elasticsearch_core_instance.delete_index("nonexistent_index")

        assert result is False
        mock_delete.assert_called_once_with(index="nonexistent_index")


def test_get_user_indices_success(elasticsearch_core_instance):
    """Test getting user indices successfully."""
    with patch.object(elasticsearch_core_instance.client.indices, 'get_alias') as mock_get_alias:
        mock_get_alias.return_value = {
            "user_index_1": {},
            "user_index_2": {},
            ".system_index": {}
        }

        result = elasticsearch_core_instance.get_user_indices()

        assert len(result) == 2
        assert "user_index_1" in result
        assert "user_index_2" in result
        assert ".system_index" not in result


# ----------------------------------------------------------------------------
# Tests for _force_refresh_with_retry method
# ----------------------------------------------------------------------------

def test_force_refresh_with_retry_success_first_attempt(elasticsearch_core_instance):
    """Test _force_refresh_with_retry succeeds on first attempt."""
    with patch.object(elasticsearch_core_instance.client.indices, 'refresh') as mock_refresh:
        mock_refresh.return_value = {"_shards": {"successful": 1}}

        result = elasticsearch_core_instance._force_refresh_with_retry("test_index")

        assert result is True
        mock_refresh.assert_called_once_with(index="test_index")


def test_force_refresh_with_retry_success_after_one_failure(elasticsearch_core_instance):
    """Test _force_refresh_with_retry succeeds on second attempt after first failure."""
    with patch.object(elasticsearch_core_instance.client.indices, 'refresh') as mock_refresh, \
            patch('time.sleep') as mock_sleep:
        # First call fails, second call succeeds
        mock_refresh.side_effect = [
            Exception("Connection refused"),
            {"_shards": {"successful": 1}}
        ]

        result = elasticsearch_core_instance._force_refresh_with_retry("test_index", max_retries=3)

        assert result is True
        assert mock_refresh.call_count == 2
        mock_sleep.assert_called_once_with(0.5)  # First retry delay is 0.5 * (0 + 1)


def test_force_refresh_with_retry_all_attempts_fail(elasticsearch_core_instance, caplog):
    """Test _force_refresh_with_retry returns False when all retries fail."""
    with patch.object(elasticsearch_core_instance.client.indices, 'refresh') as mock_refresh, \
            patch('time.sleep') as mock_sleep:
        # All attempts fail
        mock_refresh.side_effect = Exception("Connection refused")

        result = elasticsearch_core_instance._force_refresh_with_retry("test_index", max_retries=3)

        assert result is False
        assert mock_refresh.call_count == 3
        # Should sleep twice (between 3 attempts)
        assert mock_sleep.call_count == 2
        assert any("Failed to refresh index test_index" in m for m in caplog.messages)


def test_force_refresh_with_retry_success_after_two_failures(elasticsearch_core_instance):
    """Test _force_refresh_with_retry succeeds on third attempt after two failures."""
    with patch.object(elasticsearch_core_instance.client.indices, 'refresh') as mock_refresh, \
            patch('time.sleep') as mock_sleep:
        # First two fail, third succeeds
        mock_refresh.side_effect = [
            Exception("Fail 1"),
            Exception("Fail 2"),
            {"_shards": {"successful": 1}}
        ]

        result = elasticsearch_core_instance._force_refresh_with_retry("test_index", max_retries=3)

        assert result is True
        assert mock_refresh.call_count == 3
        assert mock_sleep.call_count == 2
        # Verify sleep delays: 0.5, 1.0
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)


# ----------------------------------------------------------------------------
# Tests for _ensure_index_ready method
# ----------------------------------------------------------------------------

def test_ensure_index_ready_success_green_status(elasticsearch_core_instance):
    """Test _ensure_index_ready succeeds when cluster health is green."""
    with patch.object(elasticsearch_core_instance.client.cluster, 'health') as mock_health, \
            patch.object(elasticsearch_core_instance.client, 'search') as mock_search:
        mock_health.return_value = {"status": "green"}
        mock_search.return_value = {"hits": {"total": {"value": 0}}}

        result = elasticsearch_core_instance._ensure_index_ready("test_index", timeout=10)

        assert result is True
        mock_health.assert_called_once()
        mock_search.assert_called_once()


def test_ensure_index_ready_success_yellow_status(elasticsearch_core_instance):
    """Test _ensure_index_ready succeeds when cluster health is yellow."""
    with patch.object(elasticsearch_core_instance.client.cluster, 'health') as mock_health, \
            patch.object(elasticsearch_core_instance.client, 'search') as mock_search:
        mock_health.return_value = {"status": "yellow"}
        mock_search.return_value = {"hits": {"total": {"value": 0}}}

        result = elasticsearch_core_instance._ensure_index_ready("test_index", timeout=10)

        assert result is True
        mock_health.assert_called_once()
        mock_search.assert_called_once()


def test_ensure_index_ready_red_status_continues_loop(elasticsearch_core_instance):
    """Test _ensure_index_ready continues loop when health status is red."""
    import time as time_module

    with patch.object(elasticsearch_core_instance.client.cluster, 'health') as mock_health, \
            patch.object(elasticsearch_core_instance.client, 'search') as mock_search, \
            patch('time.time') as mock_time:
        # First call returns red, second call returns green
        mock_health.side_effect = [
            {"status": "red"},
            {"status": "green"}
        ]
        mock_search.return_value = {"hits": {"total": {"value": 0}}}

        # Mock time to simulate elapsed time
        call_count = [0]
        def time_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return 1000.0  # start_time
            elif call_count[0] == 2:
                return 1000.5  # First loop iteration (less than timeout)
            else:
                return 1010.0  # Second iteration (exceeds timeout)

        mock_time.side_effect = time_side_effect

        result = elasticsearch_core_instance._ensure_index_ready("test_index", timeout=5)

        # Should return False because timeout was exceeded
        assert result is False


def test_ensure_index_ready_timeout(elasticsearch_core_instance, caplog):
    """Test _ensure_index_ready returns False when timeout is exceeded."""
    import time as time_module

    with patch.object(elasticsearch_core_instance.client.cluster, 'health') as mock_health, \
            patch('time.time') as mock_time, \
            patch('time.sleep') as mock_sleep:
        # Always return red status so it keeps looping
        mock_health.return_value = {"status": "red"}

        # Mock time to simulate timeout
        mock_time.side_effect = [1000.0, 1000.1, 1005.1, 1005.2, 1010.1]  # Simulates timeout exceeded

        result = elasticsearch_core_instance._ensure_index_ready("test_index", timeout=5)

        assert result is False
        assert any(f"Index test_index may not be fully ready after 5s" in m for m in caplog.messages)


def test_ensure_index_ready_health_exception_continues_loop(elasticsearch_core_instance):
    """Test _ensure_index_ready continues loop when health check throws exception."""
    import time as time_module

    with patch.object(elasticsearch_core_instance.client.cluster, 'health') as mock_health, \
            patch.object(elasticsearch_core_instance.client, 'search') as mock_search, \
            patch('time.time') as mock_time, \
            patch('time.sleep') as mock_sleep:
        # First call throws exception, second call returns green
        mock_health.side_effect = [
            Exception("Connection failed"),
            {"status": "green"}
        ]
        mock_search.return_value = {"hits": {"total": {"value": 0}}}

        # Mock time to simulate elapsed time
        call_count = [0]
        def time_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return 1000.0  # start_time
            elif call_count[0] == 2:
                return 1000.05  # First loop (exception caught, short sleep)
            elif call_count[0] == 3:
                return 1000.1  # After sleep
            else:
                return 1001.0  # After green status returned

        mock_time.side_effect = time_side_effect

        result = elasticsearch_core_instance._ensure_index_ready("test_index", timeout=10)

        assert result is True
        assert mock_health.call_count == 2
        mock_sleep.assert_called_once_with(0.1)


def test_ensure_index_ready_search_exception_on_double_check(elasticsearch_core_instance):
    """Test _ensure_index_ready handles exception during search double check."""
    import time as time_module

    with patch.object(elasticsearch_core_instance.client.cluster, 'health') as mock_health, \
            patch.object(elasticsearch_core_instance.client, 'search') as mock_search, \
            patch('time.time') as mock_time, \
            patch('time.sleep') as mock_sleep:
        # Health returns green but search fails
        mock_health.return_value = {"status": "green"}
        mock_search.side_effect = Exception("Search failed")

        # Mock time to simulate timeout after retry
        call_count = [0]
        def time_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return 1000.0  # start_time
            elif call_count[0] == 2:
                return 1000.05  # First loop (search fails, short sleep)
            else:
                return 1005.0  # Timeout

        mock_time.side_effect = time_side_effect

        result = elasticsearch_core_instance._ensure_index_ready("test_index", timeout=5)

        # Should timeout after retries
        assert result is False


# ----------------------------------------------------------------------------
# Tests for document operations
# ----------------------------------------------------------------------------

def test_vectorize_documents_empty_list(elasticsearch_core_instance):
    """Test indexing an empty list of documents."""
    mock_embedding_model = MagicMock()

    result = elasticsearch_core_instance.vectorize_documents(
        "test_index",
        mock_embedding_model,
        [],
        content_field="content"
    )

    assert result == 0


def test_vectorize_documents_small_batch(elasticsearch_core_instance):
    """Test indexing a small batch of documents (< 64)."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024] * 3
    mock_embedding_model.embedding_model_name = "test-model"

    documents = [
        {"content": "Test content 1", "title": "Test 1"},
        {"content": "Test content 2", "title": "Test 2"},
        {"content": "Test content 3", "title": "Test 3"}
    ]

    with patch.object(elasticsearch_core_instance.client, 'bulk') as mock_bulk, \
            patch('time.strftime') as mock_strftime, \
            patch('time.time') as mock_time:

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_bulk.return_value = {"errors": False, "items": []}

        result = elasticsearch_core_instance.vectorize_documents(
            "test_index",
            mock_embedding_model,
            documents,
            content_field="content"
        )

        assert result == 3
        mock_embedding_model.get_embeddings.assert_called_once()
        mock_bulk.assert_called_once()

def test_small_batch_progress_callback_exception(elasticsearch_core_instance, caplog):
    """Progress callback errors should be logged without failing the insert."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 3]
    mock_embedding_model.embedding_model_name = "m"

    documents = [{"content": "a"}]

    def bad_progress(_, __):
        raise RuntimeError("boom")

    with patch.object(elasticsearch_core_instance.client, "bulk") as mock_bulk, \
         patch("time.strftime", lambda *a, **k: "2025-01-15T10:30:00"), \
         patch("time.time", lambda: 1642234567):
        mock_bulk.return_value = {"errors": False, "items": []}
        result = elasticsearch_core_instance._small_batch_insert(
            "idx", documents, "content", mock_embedding_model, progress_callback=bad_progress
        )

    assert result == 1
    assert any("Progress callback failed in small batch" in m for m in caplog.messages)

def test_small_batch_error_path_logs_and_raises(elasticsearch_core_instance, caplog):
    """Small batch should log errors and re-raise when bulk fails."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 3]
    mock_embedding_model.embedding_model_name = "m"

    documents = [{"content": "x"}]

    with patch.object(elasticsearch_core_instance, "client") as mock_client, \
         patch("time.strftime", lambda *a, **k: "2025-01-15T10:30:00"), \
         patch("time.time", lambda: 1642234567):
        mock_client.bulk.side_effect = RuntimeError("bulk boom")
        with pytest.raises(RuntimeError):
            elasticsearch_core_instance._small_batch_insert(
                "idx", documents, "content", mock_embedding_model
            )

    assert any("Small batch insert failed: bulk boom" in m for m in caplog.messages)


def test_vectorize_documents_large_batch(elasticsearch_core_instance):
    """Test indexing a large batch of documents (>= 64)."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024] * 64
    mock_embedding_model.embedding_model_name = "test-model"

    documents = [
        {"content": f"Test content {i}", "title": f"Test {i}"}
        for i in range(100)
    ]

    with patch.object(elasticsearch_core_instance.client, 'bulk') as mock_bulk, \
            patch.object(elasticsearch_core_instance, '_force_refresh_with_retry') as mock_refresh, \
            patch('time.strftime') as mock_strftime, \
            patch('time.time') as mock_time, \
            patch('time.sleep'):

        mock_strftime.side_effect = lambda fmt, t: "2025-01-15T10:30:00" if "T" in fmt else "2025-01-15"
        mock_time.return_value = 1642234567
        mock_bulk.return_value = {"errors": False, "items": []}
        mock_refresh.return_value = True

        result = elasticsearch_core_instance.vectorize_documents(
            "test_index",
            mock_embedding_model,
            documents,
            batch_size=64,
            content_field="content"
        )

        assert result == 100
        assert mock_embedding_model.get_embeddings.call_count >= 2
        mock_bulk.assert_called()
        mock_refresh.assert_called_once_with("test_index")

def test_large_batch_progress_callback_invoked(elasticsearch_core_instance):
    """Progress callback should be triggered during embedding phase."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = [[0.1], [0.2]]

    docs = [{"content": "a"}, {"content": "b"}]
    progress_calls = []

    with patch.object(elasticsearch_core_instance.client, "bulk") as mock_bulk, \
         patch.object(elasticsearch_core_instance, "_force_refresh_with_retry"):
        mock_bulk.return_value = {"errors": False, "items": []}
        elasticsearch_core_instance._large_batch_insert(
            "idx", docs, batch_size=5, content_field="content",
            embedding_model=mock_embedding_model, embedding_batch_size=2,
            progress_callback=lambda done, total: progress_calls.append((done, total))
        )

    assert progress_calls == [(2, 2)]

def test_large_batch_progress_callback_exception_logged(elasticsearch_core_instance, caplog):
    """Embedding progress callback errors should be logged and not stop indexing."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = [[0.1]]

    docs = [{"content": "a"}]

    def bad_progress(_, __):
        raise RuntimeError("cb fail")

    with patch.object(elasticsearch_core_instance.client, "bulk") as mock_bulk, \
         patch.object(elasticsearch_core_instance, "_force_refresh_with_retry"):
        mock_bulk.return_value = {"errors": False, "items": []}
        elasticsearch_core_instance._large_batch_insert(
            "idx", docs, batch_size=1, content_field="content",
            embedding_model=mock_embedding_model, embedding_batch_size=1,
            progress_callback=bad_progress
        )

    assert any("Progress callback failed during embedding" in m for m in caplog.messages)

def test_large_batch_retry_logs_warning(elasticsearch_core_instance, caplog):
    """Embedding retries should emit warnings before succeeding."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    call_counter = {"n": 0}

    def get_embeddings(_):
        call_counter["n"] += 1
        if call_counter["n"] < 3:
            raise RuntimeError("embed fail")
        return [[0.1]]

    mock_embedding_model.get_embeddings.side_effect = get_embeddings

    docs = [{"content": "a"}]

    with patch.object(elasticsearch_core_instance.client, "bulk") as mock_bulk, \
         patch.object(elasticsearch_core_instance, "_force_refresh_with_retry"), \
         patch("time.sleep", lambda *a, **k: None):
        mock_bulk.return_value = {"errors": False, "items": []}
        elasticsearch_core_instance._large_batch_insert(
            "idx", docs, batch_size=1, content_field="content",
            embedding_model=mock_embedding_model, embedding_batch_size=1,
        )

    assert call_counter["n"] == 3
    assert any("Embedding API error (attempt 1/3)" in m for m in caplog.messages)


def test_delete_documents_success(elasticsearch_core_instance):
    """Test deleting documents by path_or_url successfully."""
    with patch.object(elasticsearch_core_instance.client, 'delete_by_query') as mock_delete:
        mock_delete.return_value = {"deleted": 5}

        result = elasticsearch_core_instance.delete_documents(
            "test_index",
            "/path/to/file.pdf"
        )

        assert result == 5
        mock_delete.assert_called_once()


def test_create_chunk_success(elasticsearch_core_instance):
    """Test creating a single chunk document."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.index.return_value = {
        "_id": "es-id-1",
        "result": "created",
        "_version": 1,
    }

    payload = {"id": "chunk-1", "content": "A"}
    result = elasticsearch_core_instance.create_chunk("kb-index", payload)

    assert result["id"] == "es-id-1"
    assert result["result"] == "created"
    elasticsearch_core_instance.client.index.assert_called_once()


def test_update_chunk_success(elasticsearch_core_instance):
    """Test updating an existing chunk document."""
    elasticsearch_core_instance.client = MagicMock()
    with patch.object(
        elasticsearch_core_instance,
        "_resolve_chunk_document_id",
        return_value="es-id-1",
    ):
        elasticsearch_core_instance.client.update.return_value = {
            "_id": "es-id-1",
            "result": "updated",
            "_version": 2,
        }

        updates = {"content": "updated"}
        result = elasticsearch_core_instance.update_chunk(
            "kb-index", "chunk-1", updates
        )

        assert result["id"] == "es-id-1"
        assert result["result"] == "updated"
        elasticsearch_core_instance.client.update.assert_called_once()


def test_delete_chunk_success(elasticsearch_core_instance):
    """Test deleting a chunk document successfully."""
    elasticsearch_core_instance.client = MagicMock()
    with patch.object(
        elasticsearch_core_instance,
        "_resolve_chunk_document_id",
        return_value="es-id-1",
    ):
        elasticsearch_core_instance.client.delete.return_value = {
            "result": "deleted"
        }

        result = elasticsearch_core_instance.delete_chunk("kb-index", "chunk-1")

        assert result is True
        elasticsearch_core_instance.client.delete.assert_called_once()


def test_delete_chunk_not_found(elasticsearch_core_instance):
    """Test deleting a missing chunk returns False."""
    elasticsearch_core_instance.client = MagicMock()
    with patch.object(
        elasticsearch_core_instance,
        "_resolve_chunk_document_id",
        side_effect=exceptions.NotFoundError(404, "not found", {}),
    ):
        result = elasticsearch_core_instance.delete_chunk("kb-index", "missing")

        assert result is False


def test_create_chunk_exception(elasticsearch_core_instance):
    """Test create_chunk raises exception when client.index fails."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.index.side_effect = Exception("Index operation failed")

    payload = {"id": "chunk-1", "content": "A"}

    with pytest.raises(Exception) as exc_info:
        elasticsearch_core_instance.create_chunk("kb-index", payload)

    assert "Index operation failed" in str(exc_info.value)
    elasticsearch_core_instance.client.index.assert_called_once()


def test_update_chunk_exception_from_resolve(elasticsearch_core_instance):
    """Test update_chunk raises exception when _resolve_chunk_document_id fails."""
    elasticsearch_core_instance.client = MagicMock()
    with patch.object(
        elasticsearch_core_instance,
        "_resolve_chunk_document_id",
        side_effect=Exception("Resolve failed"),
    ):
        updates = {"content": "updated"}

        with pytest.raises(Exception) as exc_info:
            elasticsearch_core_instance.update_chunk("kb-index", "chunk-1", updates)

        assert "Resolve failed" in str(exc_info.value)
        elasticsearch_core_instance.client.update.assert_not_called()


def test_update_chunk_exception_from_update(elasticsearch_core_instance):
    """Test update_chunk raises exception when client.update fails."""
    elasticsearch_core_instance.client = MagicMock()
    with patch.object(
        elasticsearch_core_instance,
        "_resolve_chunk_document_id",
        return_value="es-id-1",
    ):
        elasticsearch_core_instance.client.update.side_effect = Exception("Update operation failed")

        updates = {"content": "updated"}

        with pytest.raises(Exception) as exc_info:
            elasticsearch_core_instance.update_chunk("kb-index", "chunk-1", updates)

        assert "Update operation failed" in str(exc_info.value)
        elasticsearch_core_instance.client.update.assert_called_once()


def test_delete_chunk_exception_from_resolve(elasticsearch_core_instance):
    """Test delete_chunk raises exception when _resolve_chunk_document_id fails with non-NotFoundError."""
    elasticsearch_core_instance.client = MagicMock()
    with patch.object(
        elasticsearch_core_instance,
        "_resolve_chunk_document_id",
        side_effect=Exception("Resolve failed"),
    ):
        with pytest.raises(Exception) as exc_info:
            elasticsearch_core_instance.delete_chunk("kb-index", "chunk-1")

        assert "Resolve failed" in str(exc_info.value)
        elasticsearch_core_instance.client.delete.assert_not_called()


def test_delete_chunk_exception_from_delete(elasticsearch_core_instance):
    """Test delete_chunk raises exception when client.delete fails with non-NotFoundError."""
    elasticsearch_core_instance.client = MagicMock()
    with patch.object(
        elasticsearch_core_instance,
        "_resolve_chunk_document_id",
        return_value="es-id-1",
    ):
        elasticsearch_core_instance.client.delete.side_effect = Exception("Delete operation failed")

        with pytest.raises(Exception) as exc_info:
            elasticsearch_core_instance.delete_chunk("kb-index", "chunk-1")

        assert "Delete operation failed" in str(exc_info.value)
        elasticsearch_core_instance.client.delete.assert_called_once()


def test_resolve_chunk_document_id_direct_hit(elasticsearch_core_instance):
    """Test _resolve_chunk_document_id returns given id when ES _id exists."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.get.return_value = {}

    doc_id = elasticsearch_core_instance._resolve_chunk_document_id(
        "kb-index", "chunk-1"
    )

    assert doc_id == "chunk-1"
    elasticsearch_core_instance.client.search.assert_not_called()


def test_resolve_chunk_document_id_via_search(elasticsearch_core_instance):
    """Test _resolve_chunk_document_id falls back to searching by stored id."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.get.side_effect = exceptions.NotFoundError(
        404, "not found", {}
    )
    elasticsearch_core_instance.client.search.return_value = {
        "hits": {"hits": [{"_id": "es-id-1"}]}
    }

    doc_id = elasticsearch_core_instance._resolve_chunk_document_id(
        "kb-index", "chunk-1"
    )

    assert doc_id == "es-id-1"
    elasticsearch_core_instance.client.search.assert_called_once()


def test_resolve_chunk_document_id_not_found(elasticsearch_core_instance):
    """Test _resolve_chunk_document_id raises when no matching document is found."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.get.side_effect = exceptions.NotFoundError(
        404, "not found", {}
    )
    elasticsearch_core_instance.client.search.return_value = {
        "hits": {"hits": []}
    }

    with pytest.raises(exceptions.NotFoundError):
        elasticsearch_core_instance._resolve_chunk_document_id(
            "kb-index", "missing"
        )


def test_get_index_chunks_success(elasticsearch_core_instance):
    """Test fetching chunks via scroll API."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.count.return_value = {"count": 2}
    elasticsearch_core_instance.client.search.return_value = {
        "_scroll_id": "scroll123",
        "hits": {
            "hits": [
                {"_id": "doc-1", "_source": {"id": "chunk-1", "content": "A"}},
                {"_id": "doc-2", "_source": {"content": "B"}}
            ]
        }
    }
    elasticsearch_core_instance.client.scroll.return_value = {
        "_scroll_id": "scroll123",
        "hits": {"hits": []}
    }

    result = elasticsearch_core_instance.get_index_chunks("kb-index")

    assert result["chunks"] == [
        {"id": "chunk-1", "content": "A"},
        {"content": "B", "id": "doc-2"}
    ]
    assert result["total"] == 2
    elasticsearch_core_instance.client.search.assert_called_once()
    elasticsearch_core_instance.client.scroll.assert_called_once_with(scroll_id="scroll123", scroll="2m")
    elasticsearch_core_instance.client.clear_scroll.assert_called_once_with(scroll_id="scroll123")


def test_get_index_chunks_paginated(elasticsearch_core_instance):
    """Test fetching chunks with pagination parameters."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.count.return_value = {"count": 5}
    elasticsearch_core_instance.client.search.return_value = {
        "hits": {
            "hits": [
                {"_id": "doc-2", "_source": {"content": "B"}},
            ]
        }
    }

    result = elasticsearch_core_instance.get_index_chunks(
        "kb-index", page=2, page_size=1)

    assert result["chunks"] == [{"content": "B", "id": "doc-2"}]
    assert result["page"] == 2
    assert result["page_size"] == 1
    assert result["total"] == 5
    elasticsearch_core_instance.client.scroll.assert_not_called()
    elasticsearch_core_instance.client.clear_scroll.assert_not_called()


def test_get_index_chunks_not_found(elasticsearch_core_instance):
    """Test fetching chunks when index does not exist."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.count.side_effect = exceptions.NotFoundError(
        404, "not found", {})

    chunks = elasticsearch_core_instance.get_index_chunks("missing-index")

    assert chunks == {"chunks": [], "total": 0,
                      "page": None, "page_size": None}
    elasticsearch_core_instance.client.clear_scroll.assert_not_called()


def test_get_index_chunks_cleanup_failure(elasticsearch_core_instance):
    """Test cleanup warning path when clear_scroll raises."""
    elasticsearch_core_instance.client = MagicMock()
    elasticsearch_core_instance.client.count.return_value = {"count": 1}
    elasticsearch_core_instance.client.search.return_value = {
        "_scroll_id": "scroll123",
        "hits": {
            "hits": [
                {"_id": "doc-1", "_source": {"content": "A"}}
            ]
        }
    }
    elasticsearch_core_instance.client.scroll.return_value = {
        "_scroll_id": "scroll123",
        "hits": {"hits": []}
    }
    elasticsearch_core_instance.client.clear_scroll.side_effect = Exception("cleanup error")

    chunks = elasticsearch_core_instance.get_index_chunks("kb-index")

    assert len(chunks["chunks"]) == 1
    assert chunks["chunks"][0]["id"] == "doc-1"
    elasticsearch_core_instance.client.clear_scroll.assert_called_once_with(scroll_id="scroll123")


# ----------------------------------------------------------------------------
# Tests for search operations
# ----------------------------------------------------------------------------

def test_accurate_search_success(elasticsearch_core_instance):
    """Test accurate search with text matching."""
    with patch.object(elasticsearch_core_instance, 'exec_query') as mock_exec, \
            patch('sdk.nexent.vector_database.elasticsearch_core.calculate_term_weights') as mock_weights, \
            patch('sdk.nexent.vector_database.elasticsearch_core.build_weighted_query') as mock_build:

        mock_weights.return_value = {"test": 1.0}
        mock_build.return_value = {
            "query": {"match": {"content": "test query"}}}
        mock_exec.return_value = [
            {
                "score": 10.5,
                "document": {"content": "Test document", "title": "Test"},
                "index": "test_index"
            }
        ]

        result = elasticsearch_core_instance.accurate_search(
            ["test_index"],
            "test query",
            top_k=5
        )

        assert len(result) == 1
        assert result[0]["score"] == 10.5
        mock_weights.assert_called_once_with("test query")
        mock_build.assert_called_once_with("test query", {"test": 1.0})
        mock_exec.assert_called_once()


def test_accurate_search_builds_multi_index_query(elasticsearch_core_instance):
    """Ensure accurate_search joins indices and applies top_k sizing."""
    with patch.object(elasticsearch_core_instance, 'exec_query') as mock_exec, \
            patch('sdk.nexent.vector_database.elasticsearch_core.calculate_term_weights') as mock_weights, \
            patch('sdk.nexent.vector_database.elasticsearch_core.build_weighted_query') as mock_build:

        mock_weights.return_value = {"test": 0.5}
        mock_build.return_value = {"query": {"match_all": {}}}
        mock_exec.return_value = []

        elasticsearch_core_instance.accurate_search(
            ["index_a", "index_b"],
            "multi query",
            top_k=7,
        )

        mock_weights.assert_called_once_with("multi query")
        mock_build.assert_called_once_with("multi query", {"test": 0.5})
        mock_exec.assert_called_once()

        index_pattern, search_query = mock_exec.call_args[0]
        assert index_pattern == "index_a,index_b"
        assert search_query["size"] == 7
        assert search_query["_source"]["excludes"] == ["embedding"]


def test_semantic_search_success(elasticsearch_core_instance):
    """Test semantic search with vector similarity."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024]

    with patch.object(elasticsearch_core_instance, 'exec_query') as mock_exec:
        mock_exec.return_value = [
            {
                "score": 0.95,
                "document": {"content": "Similar document", "title": "Doc"},
                "index": "test_index"
            }
        ]

        result = elasticsearch_core_instance.semantic_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5
        )

        assert len(result) == 1
        assert result[0]["score"] == 0.95
        mock_embedding_model.get_embeddings.assert_called_once_with(
            "test query")
        mock_exec.assert_called_once()


def test_semantic_search_sets_knn_parameters(elasticsearch_core_instance):
    """Ensure semantic_search sets k and num_candidates based on top_k."""
    mock_embedding_model = MagicMock()
    mock_embedding_model.get_embeddings.return_value = [[0.2] * 8]

    with patch.object(elasticsearch_core_instance, 'exec_query') as mock_exec:
        mock_exec.return_value = []

        elasticsearch_core_instance.semantic_search(
            ["index_x"],
            "query terms",
            mock_embedding_model,
            top_k=4,
        )

        mock_embedding_model.get_embeddings.assert_called_once_with(
            "query terms")
        mock_exec.assert_called_once()

        _, search_query = mock_exec.call_args[0]
        assert search_query["knn"]["k"] == 4
        assert search_query["knn"]["num_candidates"] == 8
        assert search_query["size"] == 4
        assert search_query["_source"]["excludes"] == ["embedding"]


def test_hybrid_search_success(elasticsearch_core_instance):
    """Test hybrid search combining accurate and semantic results."""
    mock_embedding_model = MagicMock()

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic:

        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            }
        ]

        mock_semantic.return_value = [
            {
                "score": 0.9,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            },
            {
                "score": 0.8,
                "document": {"id": "doc2", "content": "Test doc 2"},
                "index": "test_index"
            }
        ]

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        assert len(result) == 2
        assert all("score" in r for r in result)
        assert all("document" in r for r in result)
        mock_accurate.assert_called_once()
        mock_semantic.assert_called_once()


def test_hybrid_search_with_missing_embeddings_generates_and_stores(elasticsearch_core_instance):
    """
    Test hybrid search when chunks exist in accurate results but not in semantic results
    (e.g., manually added chunks without embeddings).
    The system should generate embeddings, store them in ES, and re-execute semantic search.
    """
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024]

    # Initial accurate search returns doc1, semantic search only returns doc2 (doc1 missing)
    # This simulates a chunk that was manually added without embedding
    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic, \
            patch.object(elasticsearch_core_instance, 'client') as mock_client:

        # First call: accurate returns doc1 (with content), semantic returns only doc2
        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1 - needs embedding"},
                "index": "test_index"
            }
        ]

        # First semantic search doesn't find doc1 because it has no embedding
        mock_semantic.side_effect = [
            # First call returns doc2 only (doc1 missing because no embedding)
            [
                {
                    "score": 0.8,
                    "document": {"id": "doc2", "content": "Test doc 2"},
                    "index": "test_index"
                }
            ],
            # Second call (after generating embedding) finds doc1
            [
                {
                    "score": 0.9,
                    "document": {"id": "doc1", "content": "Test doc 1 - needs embedding"},
                    "index": "test_index"
                },
                {
                    "score": 0.8,
                    "document": {"id": "doc2", "content": "Test doc 2"},
                    "index": "test_index"
                }
            ]
        ]

        # Mock client.index for storing embedding
        mock_client.index.return_value = {"result": "created"}

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # Verify semantic_search was called twice (initial + after embedding)
        assert mock_semantic.call_count == 2

        # Verify client.index was called to store the embedding
        mock_client.index.assert_called_once()
        call_args = mock_client.index.call_args
        assert call_args.kwargs["id"] == "doc1"
        assert "embedding" in call_args.kwargs["document"]

        # Verify result includes doc1 with semantic_score
        assert len(result) >= 1
        doc_ids = [r["document"]["id"] for r in result]
        assert "doc1" in doc_ids


def test_hybrid_search_no_missing_embeddings_no_retry(elasticsearch_core_instance):
    """
    Test hybrid search when all chunks have embeddings (no missing embeddings).
    Semantic search should only be called once.
    """
    mock_embedding_model = MagicMock()

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic:

        # Both searches return the same documents
        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            }
        ]

        mock_semantic.return_value = [
            {
                "score": 0.9,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            }
        ]

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # Semantic search should only be called once (no retry needed)
        assert mock_semantic.call_count == 1
        assert len(result) == 1
        assert result[0]["document"]["id"] == "doc1"


def test_hybrid_search_handles_embedding_generation_failure(elasticsearch_core_instance):
    """
    Test hybrid search when embedding generation fails for chunks without embeddings.
    The search should still complete (gracefully handle failures).
    """
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = []  # Empty embedding

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic, \
            patch.object(elasticsearch_core_instance, 'client') as mock_client:

        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            }
        ]

        # Semantic only finds doc1 on second call
        mock_semantic.side_effect = [
            [],  # First call: doc1 not found (no embedding)
            [
                {
                    "score": 0.9,
                    "document": {"id": "doc1", "content": "Test doc 1"},
                    "index": "test_index"
                }
            ]
        ]

        mock_client.index.return_value = {"result": "created"}

        # Should not raise exception even if embedding generation fails initially
        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # Verify the search completed
        assert mock_semantic.call_count == 2


def test_hybrid_search_empty_results(elasticsearch_core_instance):
    """Test hybrid search with empty results from both searches."""
    mock_embedding_model = MagicMock()

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic:

        mock_accurate.return_value = []
        mock_semantic.return_value = []

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        assert len(result) == 0


# ----------------------------------------------------------------------------
# Tests for statistics and monitoring
# ----------------------------------------------------------------------------

def test_get_documents_detail_success(elasticsearch_core_instance):
    """Test getting file list with details."""
    with patch.object(elasticsearch_core_instance.client, 'search') as mock_search:
        mock_search.return_value = {
            "aggregations": {
                "unique_sources": {
                    "buckets": [
                        {
                            "doc_count": 3,
                            "file_sample": {
                                "hits": {
                                    "hits": [
                                        {
                                            "_source": {
                                                "path_or_url": "/path/to/file1.pdf",
                                                "filename": "file1.pdf",
                                                "file_size": 1024,
                                                "create_time": "2025-01-15T10:30:00"
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            }
        }

        result = elasticsearch_core_instance.get_documents_detail(
            "test_index")

        assert len(result) == 1
        assert result[0]["path_or_url"] == "/path/to/file1.pdf"
        assert result[0]["filename"] == "file1.pdf"
        assert result[0]["file_size"] == 1024
        assert result[0]["chunk_count"] == 3
        mock_search.assert_called_once()


def test_get_indices_detail_success(elasticsearch_core_instance):
    """Test getting index statistics."""
    with patch.object(elasticsearch_core_instance.client.indices, 'stats') as mock_stats, \
            patch.object(elasticsearch_core_instance.client.indices, 'get_settings') as mock_settings, \
            patch.object(elasticsearch_core_instance.client, 'search') as mock_search:

        mock_stats.return_value = {
            "indices": {
                "test_index": {
                    "primaries": {
                        "docs": {"count": 100},
                        "store": {"size_in_bytes": 1024000},
                        "search": {"query_total": 50},
                        "request_cache": {"hit_count": 25}
                    }
                }
            }
        }

        mock_settings.return_value = {
            "test_index": {
                "settings": {
                    "index": {
                        "creation_date": "1642234567000"
                    }
                }
            }
        }

        mock_search.return_value = {
            "aggregations": {
                "unique_path_or_url_count": {"value": 10},
                "process_sources": {"buckets": [{"key": "Unstructured"}]},
                "embedding_models": {"buckets": [{"key": "test-model"}]}
            }
        }

        result = elasticsearch_core_instance.get_indices_detail(
            ["test_index"], embedding_dim=1024)

        assert "test_index" in result
        assert result["test_index"]["base_info"]["doc_count"] == 10
        assert result["test_index"]["base_info"]["chunk_count"] == 100
        mock_stats.assert_called_once()
        mock_settings.assert_called_once()
        mock_search.assert_called_once()


# ----------------------------------------------------------------------------
# Tests for error handling
# ----------------------------------------------------------------------------

def test_handle_bulk_errors_with_errors(elasticsearch_core_instance):
    """Test handling bulk operation errors."""
    response = {
        "errors": True,
        "items": [
            {
                "index": {
                    "error": {
                        "type": "mapper_parsing_exception",
                        "reason": "Failed to parse mapping"
                    }
                }
            }
        ]
    }

    with pytest.raises(Exception) as exc_info:
        elasticsearch_core_instance._handle_bulk_errors(response)

    err_payload = str(exc_info.value)
    assert "Bulk indexing failed: Failed to parse mapping" in err_payload
    assert "es_bulk_failed" in err_payload


def test_handle_bulk_errors_version_conflict(elasticsearch_core_instance):
    """Test handling version conflict errors (should be ignored)."""
    response = {
        "errors": True,
        "items": [
            {
                "index": {
                    "error": {
                        "type": "version_conflict_engine_exception",
                        "reason": "Version conflict"
                    }
                }
            }
        ]
    }

    # Should not raise exception or log error for version conflicts
    elasticsearch_core_instance._handle_bulk_errors(response)


def test_handle_bulk_errors_skips_items_without_error(elasticsearch_core_instance):
    """Items without error key should be ignored."""
    response = {
        "errors": True,
        "items": [{"index": {}}],
    }
    # Should not raise
    elasticsearch_core_instance._handle_bulk_errors(response)


def test_handle_bulk_errors_dim_mismatch_sets_specific_code(elasticsearch_core_instance):
    """Dense vector dimension mismatch should produce es_dim_mismatch code."""
    response = {
        "errors": True,
        "items": [
            {
                "index": {
                    "error": {
                        "type": "illegal_argument_exception",
                        "reason": "field [embedding] has different number of dimensions than vector",
                        "caused_by": {"reason": "dense_vector different number of dimensions"},
                    }
                }
            }
        ],
    }

    with pytest.raises(Exception) as exc_info:
        elasticsearch_core_instance._handle_bulk_errors(response)

    payload = str(exc_info.value)
    assert "es_dim_mismatch" in payload
    assert "Bulk indexing failed" in payload

def test_bulk_operation_context(elasticsearch_core_instance):
    """Test bulk operation context manager."""
    with patch.object(elasticsearch_core_instance, '_apply_bulk_settings') as mock_apply, \
            patch.object(elasticsearch_core_instance, '_restore_normal_settings') as mock_restore:

        with elasticsearch_core_instance.bulk_operation_context("test_index", estimated_duration=60) as operation_id:
            assert operation_id is not None
            assert "bulk_" in operation_id

        mock_apply.assert_called_once_with("test_index")
        mock_restore.assert_called_once_with("test_index")


def test_exec_query_returns_formatted_results(elasticsearch_core_instance):
    """Test exec_query method returns correctly formatted results."""
    with patch.object(elasticsearch_core_instance.client, 'search') as mock_search:
        mock_search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_score": 10.5,
                        "_source": {"content": "Test document 1", "id": "doc1"},
                        "_index": "test_index"
                    },
                    {
                        "_score": 8.3,
                        "_source": {"content": "Test document 2", "id": "doc2"},
                        "_index": "test_index"
                    }
                ]
            }
        }

        result = elasticsearch_core_instance.exec_query("test_index", {"query": {"match_all": {}}})

        assert len(result) == 2
        assert result[0]["score"] == 10.5
        assert result[0]["document"]["content"] == "Test document 1"
        assert result[0]["document"]["id"] == "doc1"
        assert result[0]["index"] == "test_index"
        assert result[1]["score"] == 8.3
        assert result[1]["document"]["content"] == "Test document 2"
        assert result[1]["document"]["id"] == "doc2"
        assert result[1]["index"] == "test_index"
        mock_search.assert_called_once_with(index="test_index", body={"query": {"match_all": {}}})


def test_exec_query_empty_results(elasticsearch_core_instance):
    """Test exec_query method with empty results."""
    with patch.object(elasticsearch_core_instance.client, 'search') as mock_search:
        mock_search.return_value = {
            "hits": {
                "hits": []
            }
        }

        result = elasticsearch_core_instance.exec_query("test_index", {"query": {"match": {"content": "test"}}})

        assert result == []
        mock_search.assert_called_once()


def test_exec_query_with_multi_index_pattern(elasticsearch_core_instance):
    """Test exec_query method with multiple indices."""
    with patch.object(elasticsearch_core_instance.client, 'search') as mock_search:
        mock_search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_score": 5.0,
                        "_source": {"content": "Doc from index1", "id": "doc1"},
                        "_index": "index1"
                    },
                    {
                        "_score": 6.0,
                        "_source": {"content": "Doc from index2", "id": "doc2"},
                        "_index": "index2"
                    }
                ]
            }
        }

        result = elasticsearch_core_instance.exec_query("index1,index2", {"query": {"match_all": {}}})

        assert len(result) == 2
        assert result[0]["index"] == "index1"
        assert result[1]["index"] == "index2"
        mock_search.assert_called_once_with(index="index1,index2", body={"query": {"match_all": {}}})


# ----------------------------------------------------------------------------
# Tests for hybrid_search edge cases
# ----------------------------------------------------------------------------

def test_hybrid_search_skips_semantic_result_with_missing_fields(elasticsearch_core_instance, caplog):
    """
    Test hybrid_search skips semantic results with missing required fields (line 1060).
    When processing semantic_results and a result is missing 'document' field,
    KeyError should be caught and logged, then continue to next result.
    """
    mock_embedding_model = MagicMock()

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic:

        # Accurate returns doc1
        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            }
        ]

        # Semantic returns a result with missing 'document' field (triggers KeyError)
        # and another valid result
        mock_semantic.return_value = [
            {
                "score": 0.9,
                # Missing "document" field - will cause KeyError
            },
            {
                "score": 0.8,
                "document": {"id": "doc2", "content": "Test doc 2"},
                "index": "test_index"
            }
        ]

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # Should complete without exception and include doc2
        assert len(result) >= 1
        doc_ids = [r["document"]["id"] for r in result]
        assert "doc2" in doc_ids
        # Warning should be logged for missing field
        assert any("Missing required field in semantic result" in m for m in caplog.messages)


def test_hybrid_search_stores_embedding_failure_continues_processing(elasticsearch_core_instance, caplog):
    """
    Test hybrid_search continues processing when storing embedding fails (lines 1101-1104).
    When client.index raises exception during embedding storage, it should log warning
    and continue to next document instead of failing the entire search.
    """
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024]

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic, \
            patch.object(elasticsearch_core_instance, 'client') as mock_client:

        # Accurate returns doc1 (will need embedding storage)
        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1 - needs embedding"},
                "index": "test_index"
            }
        ]

        # Semantic returns empty first (doc1 needs embedding), then returns doc1 after storage
        mock_semantic.side_effect = [
            [],  # First call: doc1 not found (no embedding)
            [
                {
                    "score": 0.9,
                    "document": {"id": "doc1", "content": "Test doc 1 - needs embedding"},
                    "index": "test_index"
                }
            ]
        ]

        # First index call fails, second succeeds
        mock_client.index.side_effect = [
            Exception("Index storage failed"),  # This should trigger the warning and continue
            {"result": "created"}
        ]

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # Should complete successfully despite storage failure
        assert mock_semantic.call_count == 2
        # Warning should be logged about failed embedding storage
        assert any("Failed to store embedding for chunk doc1" in m for m in caplog.messages)
        assert len(result) >= 1


def test_hybrid_search_adds_new_documents_from_semantic_results(elasticsearch_core_instance):
    """
    Test hybrid_search adds documents from semantic_results that don't exist in accurate results (lines 1124-1133).
    When processing updated semantic_results, if a doc_id is not in combined_results,
    it should create a new entry with accurate_score=0.
    """
    mock_embedding_model = MagicMock()

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic:

        # Accurate returns doc1
        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            }
        ]

        # Semantic returns doc1 (exists in accurate) AND doc2 (new document, not in accurate)
        mock_semantic.return_value = [
            {
                "score": 0.9,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            },
            {
                "score": 0.8,
                "document": {"id": "doc2", "content": "Test doc 2 - from semantic only"},
                "index": "test_index"
            }
        ]

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # Should include both doc1 and doc2
        assert len(result) == 2
        doc_ids = [r["document"]["id"] for r in result]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids

        # Find doc2 in results and verify it has accurate_score=0
        doc2_result = next(r for r in result if r["document"]["id"] == "doc2")
        assert doc2_result["scores"]["accurate"] == 0


def test_hybrid_search_missing_embedding_stores_with_model_name(elasticsearch_core_instance):
    """
    Test that hybrid_search correctly stores embedding_model_name when storing embeddings.
    """
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "jina-embeddings-v2"
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024]

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic, \
            patch.object(elasticsearch_core_instance, 'client') as mock_client:

        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test doc 1"},
                "index": "test_index"
            }
        ]

        mock_semantic.side_effect = [
            [],  # First call: doc1 not found
            [
                {
                    "score": 0.9,
                    "document": {"id": "doc1", "content": "Test doc 1"},
                    "index": "test_index"
                }
            ]
        ]

        mock_client.index.return_value = {"result": "created"}

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # Verify client.index was called with correct embedding_model_name
        mock_client.index.assert_called_once()
        call_args = mock_client.index.call_args
        assert call_args.kwargs["document"]["embedding_model_name"] == "jina-embeddings-v2"


def test_hybrid_search_empty_content_skips_embedding_generation(elasticsearch_core_instance, caplog):
    """
    Test hybrid_search skips embedding generation for chunks with empty content.
    When chunk_content is empty, the embedding generation should be skipped.
    """
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024]

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic, \
            patch.object(elasticsearch_core_instance, 'client') as mock_client:

        # Accurate returns a doc with empty content
        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": ""},  # Empty content
                "index": "test_index"
            }
        ]

        mock_semantic.return_value = [
            {
                "score": 0.9,
                "document": {"id": "doc1", "content": ""},
                "index": "test_index"
            }
        ]

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # client.index should NOT be called because content is empty
        mock_client.index.assert_not_called()
        # Should still return result
        assert len(result) == 1


def test_hybrid_search_empty_index_name_skips_embedding_generation(elasticsearch_core_instance, caplog):
    """
    Test hybrid_search skips embedding generation when index_name is empty.
    """
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = [[0.1] * 1024]

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic, \
            patch.object(elasticsearch_core_instance, 'client') as mock_client:

        # Accurate returns a doc with empty index_name
        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test content"},
                "index": ""  # Empty index name
            }
        ]

        mock_semantic.return_value = [
            {
                "score": 0.9,
                "document": {"id": "doc1", "content": "Test content"},
                "index": ""
            }
        ]

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # client.index should NOT be called because index_name is empty
        mock_client.index.assert_not_called()
        assert len(result) == 1


def test_hybrid_search_empty_embedding_skips_storage(elasticsearch_core_instance, caplog):
    """
    Test hybrid_search skips embedding storage when embedding generation returns empty.
    """
    mock_embedding_model = MagicMock()
    mock_embedding_model.embedding_model_name = "test-model"
    mock_embedding_model.get_embeddings.return_value = []  # Empty embedding

    with patch.object(elasticsearch_core_instance, 'accurate_search') as mock_accurate, \
            patch.object(elasticsearch_core_instance, 'semantic_search') as mock_semantic, \
            patch.object(elasticsearch_core_instance, 'client') as mock_client:

        mock_accurate.return_value = [
            {
                "score": 10.0,
                "document": {"id": "doc1", "content": "Test content"},
                "index": "test_index"
            }
        ]

        mock_semantic.side_effect = [
            [],  # First call: doc1 not found
            [
                {
                    "score": 0.9,
                    "document": {"id": "doc1", "content": "Test content"},
                    "index": "test_index"
                }
            ]
        ]

        mock_client.index.return_value = {"result": "created"}

        result = elasticsearch_core_instance.hybrid_search(
            ["test_index"],
            "test query",
            mock_embedding_model,
            top_k=5,
            weight_accurate=0.3
        )

        # client.index should NOT be called because embedding is empty
        mock_client.index.assert_not_called()
        # Should still complete search
        assert mock_semantic.call_count == 2