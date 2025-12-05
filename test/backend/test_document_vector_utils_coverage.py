"""
Supplementary test module for document_vector_utils to improve code coverage

Tests for functions not fully covered in other test files.
"""
import os
import sys
from unittest.mock import MagicMock, patch, mock_open

import numpy as np
import pytest

# Patch environment variables before any imports that might use them
os.environ.setdefault('MINIO_ENDPOINT', 'http://localhost:9000')
os.environ.setdefault('MINIO_ACCESS_KEY', 'minioadmin')
os.environ.setdefault('MINIO_SECRET_KEY', 'minioadmin')
os.environ.setdefault('MINIO_REGION', 'us-east-1')
os.environ.setdefault('MINIO_DEFAULT_BUCKET', 'test-bucket')

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

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
    merge_cluster_summaries,
    calculate_document_embedding,
    auto_determine_k,
    kmeans_cluster_documents,
    merge_duplicate_documents_in_clusters
)


class TestGetDocumentsFromES:
    """Test Elasticsearch document retrieval"""
    
    def test_get_documents_from_es_success(self):
        """Test successful document retrieval from ES"""
        mock_vdb_core = MagicMock()
        mock_vdb_core.search.return_value = {
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
        
        result = get_documents_from_es('test_index', mock_vdb_core, sample_doc_count=10)
        assert isinstance(result, dict)
        assert mock_vdb_core.search.called
    
    def test_get_documents_from_es_empty(self):
        """Test ES retrieval with no documents"""
        mock_vdb_core = MagicMock()
        mock_vdb_core.search.return_value = {
            'aggregations': {
                'unique_documents': {
                    'buckets': []
                }
            }
        }
        
        result = get_documents_from_es('test_index', mock_vdb_core)
        assert result == {}
    
    def test_get_documents_from_es_error(self):
        """Test ES retrieval error handling"""
        mock_vdb_core = MagicMock()
        mock_vdb_core.search.side_effect = Exception("ES error")
        
        with pytest.raises(Exception, match="Failed to retrieve documents from Elasticsearch"):
            get_documents_from_es('test_index', mock_vdb_core)


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
        
        mock_vdb_core = MagicMock()
        docs, embeddings = process_documents_for_clustering('test_index', mock_vdb_core)
        
        assert isinstance(docs, dict)
        assert isinstance(embeddings, dict)
        assert 'doc1' in docs
        assert 'doc1' in embeddings
    
    @patch('backend.utils.document_vector_utils.get_documents_from_es')
    def test_process_documents_empty(self, mock_get_docs):
        """Test processing with no documents"""
        mock_get_docs.return_value = {}
        
        mock_vdb_core = MagicMock()
        docs, embeddings = process_documents_for_clustering('test_index', mock_vdb_core)
        
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


class TestAdditionalCoverage:
    """Test additional coverage for uncovered code paths"""
    
    def test_get_documents_from_es_non_list_documents(self):
        """Test ES retrieval when all_documents is not a list"""
        mock_vdb_core = MagicMock()
        
        # Mock the first search call to return a tuple instead of list
        mock_vdb_core.client.search.side_effect = [
            {
                'aggregations': {
                    'unique_documents': {
                        'buckets': (  # This will trigger the isinstance check
                            {'key': '/path/doc1.pdf', 'doc_count': 3},
                        )
                    }
                }
            },
            {
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
        ]
        
        result = get_documents_from_es('test_index', mock_vdb_core)
        assert isinstance(result, dict)
    
    def test_get_documents_from_es_no_chunks(self):
        """Test ES retrieval when document has no chunks"""
        mock_vdb_core = MagicMock()
        mock_vdb_core.client.search.side_effect = [
            {
                'aggregations': {
                    'unique_documents': {
                        'buckets': [
                            {'key': '/path/doc1.pdf', 'doc_count': 0}
                        ]
                    }
                }
            },
            {
                'hits': {
                    'hits': []  # No chunks
                }
            }
        ]
        
        result = get_documents_from_es('test_index', mock_vdb_core)
        assert result == {}  # Should return empty dict when no chunks
    
    def test_calculate_document_embedding_exception(self):
        """Test calculate_document_embedding with exception"""
        chunks = [
            {'content': 'test content', 'embedding': [0.1, 0.2, 0.3]}
        ]
        
        # Mock numpy operations to raise exception
        with patch('numpy.array') as mock_array:
            mock_array.side_effect = Exception("Numpy error")
            
            result = calculate_document_embedding(chunks)
            assert result is None
    
    def test_auto_determine_k_small_dataset(self):
        """Test auto_determine_k with very small dataset"""
        # Create embeddings with only 2 samples (less than min_k=3)
        embeddings = np.array([[0.1, 0.2], [0.3, 0.4]])
        
        result = auto_determine_k(embeddings, min_k=3, max_k=5)
        assert result == 2  # Should return max(2, n_samples)
    
    def test_auto_determine_k_exception(self):
        """Test auto_determine_k with exception during calculation"""
        embeddings = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
        
        # Mock silhouette_score to raise exception
        with patch('sklearn.metrics.silhouette_score') as mock_silhouette:
            mock_silhouette.side_effect = Exception("Silhouette error")
            
            result = auto_determine_k(embeddings, min_k=2, max_k=3)
            # Should use heuristic fallback
            assert isinstance(result, int)
            assert result >= 2
    
    def test_kmeans_cluster_documents_empty(self):
        """Test kmeans_cluster_documents with empty embeddings"""
        result = kmeans_cluster_documents({})
        assert result == {}
    
    def test_kmeans_cluster_documents_exception(self):
        """Test kmeans_cluster_documents with exception"""
        doc_embeddings = {
            'doc1': np.array([0.1, 0.2, 0.3]),
            'doc2': np.array([0.4, 0.5, 0.6])
        }
        
        # Mock auto_determine_k to raise exception
        with patch('backend.utils.document_vector_utils.auto_determine_k') as mock_auto_k:
            mock_auto_k.side_effect = Exception("Auto K error")
            
            with pytest.raises(Exception, match="Failed to cluster documents"):
                kmeans_cluster_documents(doc_embeddings)
    
    def test_process_documents_for_clustering_exception(self):
        """Test process_documents_for_clustering with exception"""
        mock_vdb_core = MagicMock()
        mock_vdb_core.search.side_effect = Exception("ES error")
        
        with pytest.raises(Exception, match="Failed to process documents"):
            process_documents_for_clustering('test_index', mock_vdb_core)
    
    def test_process_documents_for_clustering_no_embeddings(self):
        """Test process_documents_for_clustering when some documents fail embedding calculation"""
        mock_vdb_core = MagicMock()
        mock_vdb_core.search.return_value = {
            'aggregations': {
                'unique_documents': {
                    'buckets': [
                        {'key': '/path/doc1.pdf', 'doc_count': 1}
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
        
        # Mock calculate_document_embedding to return None
        with patch('backend.utils.document_vector_utils.calculate_document_embedding') as mock_calc:
            mock_calc.return_value = None
            
            docs, embeddings = process_documents_for_clustering('test_index', mock_vdb_core)
            assert isinstance(docs, dict)
            assert isinstance(embeddings, dict)
            assert len(embeddings) == 0  # No successful embeddings
    
    def test_extract_cluster_content_missing_doc(self):
        """Test extract_cluster_content with missing document"""
        document_samples = {
            'doc1': {
                'chunks': [{'content': 'test content'}]
            }
        }
        cluster_doc_ids = ['doc1', 'missing_doc']
        
        result = extract_cluster_content(document_samples, cluster_doc_ids)
        assert isinstance(result, str)
        assert 'test content' in result
    
    def test_extract_cluster_content_no_chunks(self):
        """Test extract_cluster_content with document having no chunks"""
        document_samples = {
            'doc1': {
                'chunks': []
            }
        }
        cluster_doc_ids = ['doc1']
        
        result = extract_cluster_content(document_samples, cluster_doc_ids)
        assert isinstance(result, str)
    
    def test_extract_representative_chunks_smart_import_error(self):
        """Test extract_representative_chunks_smart with ImportError"""
        chunks = [
            {'content': 'chunk 1'},
            {'content': 'chunk 2'},
            {'content': 'chunk 3'}
        ]
        
        # Mock the import to raise ImportError
        with patch('builtins.__import__', side_effect=ImportError("Module not found")):
            result = extract_representative_chunks_smart(chunks, max_chunks=2)
            assert len(result) <= 2
            assert len(result) > 0
    
    def test_extract_representative_chunks_smart_short_content(self):
        """Test extract_representative_chunks_smart with short content"""
        chunks = [
            {'content': 'short'},
            {'content': 'also short'},
            {'content': 'very short content'}
        ]
        
        result = extract_representative_chunks_smart(chunks, max_chunks=2)
        assert len(result) <= 2
        assert len(result) > 0
    
    def test_analyze_cluster_coherence_empty(self):
        """Test analyze_cluster_coherence with empty cluster_doc_ids"""
        document_samples = {
            'doc1': {
                'chunks': [{'content': 'test content'}]
            }
        }
        cluster_doc_ids = []
        
        result = analyze_cluster_coherence(cluster_doc_ids, document_samples)
        assert result == {}
    
    def test_analyze_cluster_coherence_missing_doc(self):
        """Test analyze_cluster_coherence with missing document"""
        document_samples = {
            'doc1': {
                'chunks': [{'content': 'test content'}]
            }
        }
        cluster_doc_ids = ['doc1', 'missing_doc']
        
        result = analyze_cluster_coherence(cluster_doc_ids, document_samples)
        assert isinstance(result, dict)
    
    def test_analyze_cluster_coherence_no_chunks(self):
        """Test analyze_cluster_coherence with document having no chunks"""
        document_samples = {
            'doc1': {
                'chunks': []
            }
        }
        cluster_doc_ids = ['doc1']
        
        result = analyze_cluster_coherence(cluster_doc_ids, document_samples)
        assert isinstance(result, dict)
    
    def test_summarize_clusters_map_reduce_missing_doc(self):
        """Test summarize_clusters_map_reduce with missing document"""
        document_samples = {
            'doc1': {
                'chunks': [{'content': 'test content'}],
                'filename': 'test.pdf'
            }
        }
        clusters = {0: ['doc1', 'missing_doc']}
        
        with patch('backend.utils.document_vector_utils.summarize_document') as mock_sum_doc:
            mock_sum_doc.return_value = "Doc summary"
            
            with patch('backend.utils.document_vector_utils.summarize_cluster') as mock_sum_cluster:
                mock_sum_cluster.return_value = "Cluster summary"
                
                result = summarize_clusters_map_reduce(document_samples, clusters)
                assert isinstance(result, dict)
                assert 0 in result
    
    def test_summarize_clusters_map_reduce_few_chunks(self):
        """Test summarize_clusters_map_reduce with document having few chunks"""
        document_samples = {
            'doc1': {
                'chunks': [
                    {'content': 'chunk 1'},
                    {'content': 'chunk 2'}
                ],
                'filename': 'test.pdf'
            }
        }
        clusters = {0: ['doc1']}
        
        with patch('backend.utils.document_vector_utils.summarize_document') as mock_sum_doc:
            mock_sum_doc.return_value = "Doc summary"
            
            with patch('backend.utils.document_vector_utils.summarize_cluster') as mock_sum_cluster:
                mock_sum_cluster.return_value = "Cluster summary"
                
                result = summarize_clusters_map_reduce(document_samples, clusters)
                assert isinstance(result, dict)
                assert 0 in result
    
    def test_summarize_clusters_map_reduce_long_content(self):
        """Test summarize_clusters_map_reduce with long content"""
        long_content = 'x' * 1500  # Longer than 1000 chars
        document_samples = {
            'doc1': {
                'chunks': [
                    {'content': long_content}
                ],
                'filename': 'test.pdf'
            }
        }
        clusters = {0: ['doc1']}
        
        with patch('backend.utils.document_vector_utils.summarize_document') as mock_sum_doc:
            mock_sum_doc.return_value = "Doc summary"
            
            with patch('backend.utils.document_vector_utils.summarize_cluster') as mock_sum_cluster:
                mock_sum_cluster.return_value = "Cluster summary"
                
                result = summarize_clusters_map_reduce(document_samples, clusters)
                assert isinstance(result, dict)
                assert 0 in result
    
    def test_summarize_clusters_map_reduce_no_valid_docs(self):
        """Test summarize_clusters_map_reduce with no valid document summaries"""
        document_samples = {
            'doc1': {
                'chunks': [{'content': 'test content'}],
                'filename': 'test.pdf'
            }
        }
        clusters = {0: ['doc1']}
        
        with patch('backend.utils.document_vector_utils.summarize_document') as mock_sum_doc:
            mock_sum_doc.return_value = ""  # Empty summary
            
            with patch('backend.utils.document_vector_utils.summarize_cluster') as mock_sum_cluster:
                mock_sum_cluster.return_value = "Cluster summary"
                
                result = summarize_clusters_map_reduce(document_samples, clusters)
                assert isinstance(result, dict)
                assert 0 in result
    
    def test_summarize_cluster_legacy_exception(self):
        """Test summarize_cluster_legacy with exception"""
        cluster_content = "Test cluster content"
        
        # Mock file operations to raise exception
        with patch('builtins.open', side_effect=Exception("File error")):
            result = summarize_cluster_legacy(cluster_content)
            assert "Failed to generate summary" in result

