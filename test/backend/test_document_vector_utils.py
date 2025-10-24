"""
Test module for document_vector_utils

Tests for document-level vector operations and clustering functionality.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Add backend to path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../backend"))
sys.path.insert(0, backend_dir)

from backend.utils.document_vector_utils import (
    calculate_document_embedding,
    auto_determine_k,
    kmeans_cluster_documents,
    extract_representative_chunks_smart,
    summarize_document,
    summarize_cluster,
    summarize_clusters_map_reduce,
    merge_cluster_summaries,
    get_documents_from_es,
    process_documents_for_clustering,
    extract_cluster_content,
    analyze_cluster_coherence
)


class TestDocumentEmbedding:
    """Test document embedding calculation"""
    
    def test_calculate_document_embedding_simple_average(self):
        """Test simple average embedding calculation"""
        chunks = [
            {'embedding': [1.0, 2.0, 3.0], 'content': 'Content 1'},
            {'embedding': [4.0, 5.0, 6.0], 'content': 'Content 2'},
            {'embedding': [7.0, 8.0, 9.0], 'content': 'Content 3'}
        ]
        
        result = calculate_document_embedding(chunks, use_weighted=False)
        
        assert result is not None
        assert np.allclose(result, [4.0, 5.0, 6.0])  # Average of all embeddings
    
    def test_calculate_document_embedding_weighted(self):
        """Test weighted average embedding calculation"""
        chunks = [
            {'embedding': [1.0, 2.0], 'content': 'Short'},
            {'embedding': [3.0, 4.0], 'content': 'Long content with more words'},
            {'embedding': [5.0, 6.0], 'content': 'Medium length content'}
        ]
        
        result = calculate_document_embedding(chunks, use_weighted=True)
        
        assert result is not None
        assert len(result) == 2
    
    def test_calculate_document_embedding_empty_chunks(self):
        """Test handling of empty chunks"""
        chunks = []
        result = calculate_document_embedding(chunks)
        assert result is None
    
    def test_calculate_document_embedding_no_embeddings(self):
        """Test handling of chunks without embeddings"""
        chunks = [
            {'content': 'Content 1'},
            {'content': 'Content 2'}
        ]
        result = calculate_document_embedding(chunks)
        assert result is None


class TestAutoDetermineK:
    """Test automatic K determination"""
    
    def test_auto_determine_k_small_dataset(self):
        """Test K determination for small dataset"""
        embeddings = np.random.rand(10, 128)
        k = auto_determine_k(embeddings, min_k=3, max_k=15)
        
        assert 3 <= k <= 15
    
    def test_auto_determine_k_large_dataset(self):
        """Test K determination for large dataset"""
        embeddings = np.random.rand(200, 128)
        k = auto_determine_k(embeddings, min_k=3, max_k=15)
        
        assert 3 <= k <= 15
    
    def test_auto_determine_k_very_small_dataset(self):
        """Test K determination for very small dataset"""
        embeddings = np.random.rand(5, 128)
        k = auto_determine_k(embeddings, min_k=3, max_k=15)
        
        assert k >= 2
        assert k <= 5
    
    def test_auto_determine_k_minimum(self):
        """Test K determination respects minimum"""
        embeddings = np.random.rand(100, 128)
        k = auto_determine_k(embeddings, min_k=5, max_k=15)
        
        assert k >= 5


class TestKMeansClustering:
    """Test K-means clustering"""
    
    def test_kmeans_cluster_documents(self):
        """Test basic K-means clustering"""
        doc_embeddings = {
            'doc1': np.array([1.0, 1.0]),
            'doc2': np.array([1.1, 1.1]),
            'doc3': np.array([5.0, 5.0]),
            'doc4': np.array([5.1, 5.1]),
            'doc5': np.array([9.0, 9.0]),
            'doc6': np.array([9.1, 9.1])
        }
        
        clusters = kmeans_cluster_documents(doc_embeddings, k=3)
        
        assert len(clusters) == 3
        assert sum(len(docs) for docs in clusters.values()) == 6
    
    def test_kmeans_cluster_documents_auto_k(self):
        """Test K-means clustering with auto-determined K"""
        doc_embeddings = {
            f'doc{i}': np.random.rand(128) for i in range(50)
        }
        
        clusters = kmeans_cluster_documents(doc_embeddings, k=None)
        
        assert len(clusters) > 0
        assert sum(len(docs) for docs in clusters.values()) == 50
    
    def test_kmeans_cluster_documents_empty(self):
        """Test handling of empty embeddings"""
        doc_embeddings = {}
        clusters = kmeans_cluster_documents(doc_embeddings)
        
        assert clusters == {}
    
    def test_kmeans_cluster_documents_single(self):
        """Test handling of single document"""
        doc_embeddings = {
            'doc1': np.array([1.0, 1.0, 1.0])
        }
        clusters = kmeans_cluster_documents(doc_embeddings)
        
        # Should return single cluster with one document
        assert len(clusters) == 1
        assert 0 in clusters
        assert len(clusters[0]) == 1
        assert clusters[0][0] == 'doc1'


class TestExtractRepresentativeChunksSmart:
    """Test smart chunk selection"""

    def test_extract_representative_chunks_smart_basic(self):
        """Test basic smart chunk selection"""
        chunks = [
            {'content': 'First chunk content'},
            {'content': 'Second chunk content'},
            {'content': 'Third chunk content'},
            {'content': 'Fourth chunk content'}
        ]

        result = extract_representative_chunks_smart(chunks, max_chunks=3)

        assert len(result) <= 3
        assert result[0] == chunks[0]  # First chunk always included
        assert result[-1] == chunks[-1]  # Last chunk included

    def test_extract_representative_chunks_smart_import_error(self):
        """Test fallback when calculate_term_weights import fails"""
        chunks = [
            {'content': 'First chunk content'},
            {'content': 'Second chunk content'},
            {'content': 'Third chunk content'},
            {'content': 'Fourth chunk content'}
        ]

        # Mock the import to fail
        with patch.dict('sys.modules', {'nexent.core.nlp.tokenizer': None}):
            result = extract_representative_chunks_smart(chunks, max_chunks=3)

            # The fallback logic actually returns 3 chunks (first, middle, last)
            assert len(result) == 3
            assert result[0] == chunks[0]  # First chunk
            assert result[-1] == chunks[-1]  # Last chunk


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
        result = summarize_document(
            document_content="Test content for summarization",
            filename="test.pdf",
            model_id=999,  # Non-existent model
            tenant_id="test_tenant"
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestSummarizeCluster:
    """Test cluster summarization"""

    def test_summarize_cluster_no_model(self):
        """Test cluster summarization without model"""
        result = summarize_cluster(
            document_summaries=["Summary 1", "Summary 2"],
            model_id=None,
            tenant_id=None
        )
        assert isinstance(result, str)
        assert "Summary" in result

    def test_summarize_cluster_with_model_placeholder(self):
        """Test cluster summarization with model ID but no actual LLM call"""
        result = summarize_cluster(
            document_summaries=["Summary 1", "Summary 2"],
            model_id=999,  # Non-existent model
            tenant_id="test_tenant"
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestSummarizeClustersMapReduce:
    """Test map-reduce cluster summarization"""

    def test_summarize_clusters_map_reduce_basic(self):
        """Test basic map-reduce summarization"""
        document_samples = {
            'doc1': {
                'chunks': [{'content': 'Content 1'}],
                'filename': 'doc1.pdf',
                'path_or_url': '/path/doc1.pdf'
            },
            'doc2': {
                'chunks': [{'content': 'Content 2'}],
                'filename': 'doc2.pdf',
                'path_or_url': '/path/doc2.pdf'
            }
        }
        clusters = {0: ['doc1', 'doc2']}

        with patch('backend.utils.document_vector_utils.summarize_document') as mock_summarize_doc, \
             patch('backend.utils.document_vector_utils.summarize_cluster') as mock_summarize_cluster:

            mock_summarize_doc.return_value = "Document summary"
            mock_summarize_cluster.return_value = "Cluster summary"

            result = summarize_clusters_map_reduce(
                document_samples=document_samples,
                clusters=clusters,
                model_id=1,
                tenant_id="test_tenant"
            )

            assert isinstance(result, dict)
            assert 0 in result
            assert result[0] == "Cluster summary"

    def test_summarize_clusters_map_reduce_no_valid_documents(self):
        """Test map-reduce when no valid documents in cluster"""
        document_samples = {
            'doc1': {
                'chunks': [],
                'filename': 'doc1.pdf'
            }
        }
        clusters = {0: ['doc1']}

        with patch('backend.utils.document_vector_utils.summarize_document') as mock_summarize_doc, \
             patch('backend.utils.document_vector_utils.summarize_cluster') as mock_summarize_cluster:

            mock_summarize_doc.return_value = ""
            mock_summarize_cluster.return_value = "Mock cluster summary"

            result = summarize_clusters_map_reduce(
                document_samples=document_samples,
                clusters=clusters,
                model_id=1,
                tenant_id="test_tenant"
            )

            assert isinstance(result, dict)
            assert 0 in result
            assert result[0] == "Mock cluster summary"


class TestMergeClusterSummaries:
    """Test cluster summary merging"""

    def test_merge_cluster_summaries(self):
        """Test merging multiple cluster summaries"""
        cluster_summaries = {
            0: "First cluster summary",
            1: "Second cluster summary",
            2: "Third cluster summary"
        }

        result = merge_cluster_summaries(cluster_summaries)

        assert isinstance(result, str)
        assert "First cluster summary" in result
        assert "Second cluster summary" in result
        assert "Third cluster summary" in result
        assert "<p>" in result  # Should use HTML p tags


class TestGetDocumentsFromEs:
    """Test ES document retrieval"""

    def test_get_documents_from_es_mock(self):
        """Test ES document retrieval with mocked client"""
        mock_es_core = MagicMock()
        mock_es_core.client.search.return_value = {
            'hits': {
                'hits': [
                    {
                        '_source': {
                            'path_or_url': '/path/doc1.pdf',
                            'filename': 'doc1.pdf',
                            'content': 'Content 1',
                            'embedding': [1.0, 2.0, 3.0]
                        }
                    }
                ]
            },
            'aggregations': {
                'unique_documents': {
                    'buckets': [
                        {
                            'key': '/path/doc1.pdf',
                            'doc_count': 1
                        }
                    ]
                }
            }
        }

        result = get_documents_from_es('test_index', mock_es_core, sample_doc_count=10)

        assert isinstance(result, dict)
        # The function returns a dict with document IDs as keys, not 'documents' key
        assert len(result) > 0
        # Check that we have document data
        first_doc = list(result.values())[0]
        assert 'chunks' in first_doc


class TestProcessDocumentsForClustering:
    """Test document processing for clustering"""

    def test_process_documents_for_clustering_mock(self):
        """Test document processing with mocked functions"""
        mock_es_core = MagicMock()
        mock_es_core.client.search.return_value = {
            'hits': {
                'hits': [
                    {
                        '_source': {
                            'path_or_url': '/path/doc1.pdf',
                            'filename': 'doc1.pdf',
                            'content': 'Content 1',
                            'embedding': [1.0, 2.0, 3.0]
                        }
                    }
                ]
            },
            'aggregations': {
                'unique_documents': {
                    'buckets': [
                        {
                            'key': '/path/doc1.pdf',
                            'doc_count': 1
                        }
                    ]
                }
            }
        }

        with patch('backend.utils.document_vector_utils.calculate_document_embedding') as mock_calc_embedding:
            mock_calc_embedding.return_value = np.array([1.0, 2.0, 3.0])

            documents, embeddings = process_documents_for_clustering(
                'test_index', mock_es_core, sample_doc_count=10
            )

            assert isinstance(documents, dict)
            assert isinstance(embeddings, dict)
            assert len(documents) == len(embeddings)


class TestExtractClusterContent:
    """Test cluster content extraction"""

    def test_extract_cluster_content(self):
        """Test extracting content from cluster documents"""
        document_samples = {
            'doc1': {
                'chunks': [{'content': 'Content 1'}],
                'filename': 'doc1.pdf'
            },
            'doc2': {
                'chunks': [{'content': 'Content 2'}],
                'filename': 'doc2.pdf'
            }
        }
        doc_ids = ['doc1', 'doc2']

        result = extract_cluster_content(document_samples, doc_ids)

        assert isinstance(result, str)  # The function returns a formatted string
        assert 'Content 1' in result
        assert 'Content 2' in result
        assert 'doc1.pdf' in result
        assert 'doc2.pdf' in result


class TestAnalyzeClusterCoherence:
    """Test cluster coherence analysis"""

    def test_analyze_cluster_coherence(self):
        """Test cluster coherence analysis"""
        document_samples = {
            'doc1': {
                'filename': 'doc1.pdf',
                'path_or_url': '/path/doc1.pdf'
            },
            'doc2': {
                'filename': 'doc2.pdf',
                'path_or_url': '/path/doc2.pdf'
            }
        }
        doc_ids = ['doc1', 'doc2']

        result = analyze_cluster_coherence(doc_ids, document_samples)

        assert isinstance(result, dict)
        assert 'doc_count' in result
        assert result['doc_count'] == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

