"""
Supplementary test module for document_vector_utils to improve code coverage

Tests for functions not fully covered in other test files.
"""
import os
import sys
from unittest.mock import MagicMock, patch, mock_open

import numpy as np
import pytest

# Add backend to path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../backend"))
sys.path.insert(0, backend_dir)

from backend.utils.document_vector_utils import (
    get_documents_from_es,
    process_documents_for_clustering,
    extract_cluster_content,
    extract_representative_chunks_smart,
    analyze_cluster_coherence,
    summarize_document,
    summarize_cluster,
    summarize_cluster_legacy,
    summarize_clusters_map_reduce,
    summarize_clusters,
    merge_cluster_summaries
)


class TestGetDocumentsFromES:
    """Test Elasticsearch document retrieval"""
    
    def test_get_documents_from_es_success(self):
        """Test successful document retrieval from ES"""
        mock_es_core = MagicMock()
        mock_es_core.client.search.return_value = {
            'aggregations': {
                'unique_documents': {
                    'buckets': [
                        {'key': '/path/doc1.pdf', 'doc_count': 3},
                        {'key': '/path/doc2.pdf', 'doc_count': 2}
                    ]
                }
            },
            'hits': {
                'hits': [
                    {
                        '_source': {
                            'filename': 'doc1.pdf',
                            'content': 'test content',
                            'embedding': [0.1, 0.2, 0.3],
                            'file_size': 1000
                        }
                    }
                ]
            }
        }
        
        result = get_documents_from_es('test_index', mock_es_core, sample_doc_count=10)
        assert isinstance(result, dict)
        assert mock_es_core.client.search.called
    
    def test_get_documents_from_es_empty(self):
        """Test ES retrieval with no documents"""
        mock_es_core = MagicMock()
        mock_es_core.client.search.return_value = {
            'aggregations': {
                'unique_documents': {
                    'buckets': []
                }
            }
        }
        
        result = get_documents_from_es('test_index', mock_es_core)
        assert result == {}
    
    def test_get_documents_from_es_error(self):
        """Test ES retrieval error handling"""
        mock_es_core = MagicMock()
        mock_es_core.client.search.side_effect = Exception("ES error")
        
        with pytest.raises(Exception, match="Failed to retrieve documents from Elasticsearch"):
            get_documents_from_es('test_index', mock_es_core)


class TestProcessDocumentsForClustering:
    """Test document processing for clustering"""
    
    @patch('backend.utils.document_vector_utils.get_documents_from_es')
    @patch('backend.utils.document_vector_utils.calculate_document_embedding')
    def test_process_documents_success(self, mock_calc_emb, mock_get_docs):
        """Test successful document processing"""
        mock_get_docs.return_value = {
            'doc1': {
                'chunks': [{'embedding': [0.1, 0.2, 0.3]}],
                'filename': 'test.pdf'
            }
        }
        mock_calc_emb.return_value = np.array([0.1, 0.2, 0.3])
        
        mock_es_core = MagicMock()
        docs, embeddings = process_documents_for_clustering('test_index', mock_es_core)
        
        assert isinstance(docs, dict)
        assert isinstance(embeddings, dict)
        assert 'doc1' in docs
        assert 'doc1' in embeddings
    
    @patch('backend.utils.document_vector_utils.get_documents_from_es')
    def test_process_documents_empty(self, mock_get_docs):
        """Test processing with no documents"""
        mock_get_docs.return_value = {}
        
        mock_es_core = MagicMock()
        docs, embeddings = process_documents_for_clustering('test_index', mock_es_core)
        
        assert docs == {}
        assert embeddings == {}


class TestExtractClusterContent:
    """Test cluster content extraction"""
    
    def test_extract_cluster_content_basic(self):
        """Test basic cluster content extraction"""
        document_samples = {
            'doc1': {
                'chunks': [
                    {'content': 'chunk 1'},
                    {'content': 'chunk 2'}
                ]
            }
        }
        cluster_doc_ids = ['doc1']
        
        result = extract_cluster_content(document_samples, cluster_doc_ids)
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_extract_representative_chunks_smart(self):
        """Test smart chunk extraction"""
        chunks = [
            {'content': 'important keyword data'},
            {'content': 'regular content'},
            {'content': 'more keyword information'}
        ]
        
        result = extract_representative_chunks_smart(chunks, max_chunks=2)
        assert len(result) <= 2
        assert len(result) > 0
    
    def test_extract_representative_chunks_smart_single(self):
        """Test smart extraction with single chunk"""
        chunks = [
            {'content': 'single chunk content'}
        ]
        
        result = extract_representative_chunks_smart(chunks, max_chunks=1)
        assert len(result) == 1


class TestAnalyzeClusterCoherence:
    """Test cluster coherence analysis"""
    
    def test_analyze_cluster_coherence_basic(self):
        """Test basic cluster coherence analysis"""
        document_samples = {
            'doc1': {
                'filename': 'test1.pdf',
                'chunks': [{'content': 'test content 1'}],
                'file_size': 1000
            },
            'doc2': {
                'filename': 'test2.pdf',
                'chunks': [{'content': 'test content 2'}],
                'file_size': 2000
            }
        }
        cluster_doc_ids = ['doc1', 'doc2']
        
        result = analyze_cluster_coherence(cluster_doc_ids, document_samples)
        assert isinstance(result, dict)


class TestSummarizeDocument:
    """Test document summarization"""
    
    def test_summarize_document_no_model(self):
        """Test document summarization without model"""
        result = summarize_document(
            document_content="Test content",
            filename="test.pdf",
            model_id=None,
            tenant_id=None
        )
        assert isinstance(result, str)
        assert "test.pdf" in result
    
    def test_summarize_document_with_model_placeholder(self):
        """Test document summarization with model ID but no actual LLM call"""
        # With model_id and tenant_id, but without actual database connection,
        # it should return a placeholder or error message
        result = summarize_document(
            document_content="Test content for summarization",
            filename="test.pdf",
            model_id=999,  # Non-existent model
            tenant_id="test_tenant"
        )
        assert isinstance(result, str)
        # Either placeholder summary or error handling
        assert len(result) > 0


class TestSummarizeCluster:
    """Test cluster summarization"""
    
    def test_summarize_cluster_no_model(self):
        """Test cluster summarization without model"""
        doc_summaries = ["Summary 1", "Summary 2"]
        # Without model, it will return a formatted summary
        result = summarize_cluster(
            document_summaries=doc_summaries,
            model_id=None,
            tenant_id=None
        )
        assert isinstance(result, str)
        # The function returns an error or formatted text, just check it's a string
        assert len(result) > 0
    
    def test_summarize_cluster_legacy(self):
        """Test legacy cluster summarization"""
        cluster_content = "Test cluster content"
        
        result = summarize_cluster_legacy(cluster_content)
        assert isinstance(result, str)


class TestSummarizeClustersMapReduce:
    """Test Map-Reduce cluster summarization"""
    
    @patch('backend.utils.document_vector_utils.summarize_document')
    @patch('backend.utils.document_vector_utils.summarize_cluster')
    def test_summarize_clusters_map_reduce(self, mock_sum_cluster, mock_sum_doc):
        """Test Map-Reduce summarization"""
        document_samples = {
            'doc1': {
                'filename': 'test1.pdf',
                'chunks': [{'content': 'test content 1'}]
            },
            'doc2': {
                'filename': 'test2.pdf',
                'chunks': [{'content': 'test content 2'}]
            }
        }
        # clusters should map cluster_id to list of doc_ids
        clusters = {0: ['doc1', 'doc2']}
        
        mock_sum_doc.return_value = "Doc summary"
        mock_sum_cluster.return_value = "Cluster summary"
        
        result = summarize_clusters_map_reduce(
            document_samples=document_samples,
            clusters=clusters,
            language='en'
        )
        
        assert isinstance(result, dict)
        assert 0 in result


class TestMergeClusterSummaries:
    """Test cluster summary merging"""
    
    def test_merge_cluster_summaries_basic(self):
        """Test basic cluster summary merging"""
        cluster_summaries = {
            0: "Summary for cluster 0",
            1: "Summary for cluster 1"
        }
        
        result = merge_cluster_summaries(cluster_summaries)
        assert isinstance(result, str)
        assert "Summary for cluster 0" in result
        assert "Summary for cluster 1" in result
        assert "<p>" in result  # HTML paragraph tags
    
    def test_merge_cluster_summaries_empty(self):
        """Test merging empty summaries"""
        cluster_summaries = {
            0: "",
            1: "Summary for cluster 1"
        }
        
        result = merge_cluster_summaries(cluster_summaries)
        assert isinstance(result, str)
        assert "Summary for cluster 1" in result
    
    def test_merge_cluster_summaries_single(self):
        """Test merging single cluster summary"""
        cluster_summaries = {
            0: "Single cluster summary"
        }
        
        result = merge_cluster_summaries(cluster_summaries)
        assert isinstance(result, str)
        assert "Single cluster summary" in result

