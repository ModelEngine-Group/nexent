import pytest
from unittest.mock import MagicMock, patch
import time
from typing import List, Dict, Any

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
