"""
Test module for cluster summarization

Tests for cluster summarization functionality.
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
    extract_cluster_content,
    summarize_cluster,
    summarize_clusters,
    merge_cluster_summaries
)


class TestClusterSummarization:
    """Test cluster summarization functionality"""
    
    def test_extract_cluster_content_single_doc(self):
        """Test extracting content from cluster with single document"""
        document_samples = {
            'doc_001': {
                'filename': 'doc1.pdf',
                'chunks': [
                    {'content': 'Content chunk 1'},
                    {'content': 'Content chunk 2'},
                    {'content': 'Content chunk 3'}
                ]
            }
        }
        
        cluster_doc_ids = ['doc_001']
        content = extract_cluster_content(document_samples, cluster_doc_ids, max_chunks_per_doc=3)
        
        assert 'doc1.pdf' in content
        assert 'Content chunk 1' in content
        assert 'Content chunk 2' in content
        assert 'Content chunk 3' in content
    
    def test_extract_cluster_content_multiple_docs(self):
        """Test extracting content from cluster with multiple documents"""
        document_samples = {
            'doc_001': {
                'filename': 'doc1.pdf',
                'chunks': [
                    {'content': 'Content chunk 1'},
                    {'content': 'Content chunk 2'}
                ]
            },
            'doc_002': {
                'filename': 'doc2.pdf',
                'chunks': [
                    {'content': 'Content chunk 3'},
                    {'content': 'Content chunk 4'}
                ]
            }
        }
        
        cluster_doc_ids = ['doc_001', 'doc_002']
        content = extract_cluster_content(document_samples, cluster_doc_ids, max_chunks_per_doc=3)
        
        assert 'doc1.pdf' in content
        assert 'doc2.pdf' in content
        assert 'Content chunk 1' in content
        assert 'Content chunk 4' in content
    
    def test_extract_cluster_content_long_chunks(self):
        """Test extracting content with long chunks"""
        long_content = 'A' * 1000
        document_samples = {
            'doc_001': {
                'filename': 'doc1.pdf',
                'chunks': [
                    {'content': long_content}
                ]
            }
        }
        
        cluster_doc_ids = ['doc_001']
        content = extract_cluster_content(document_samples, cluster_doc_ids, max_chunks_per_doc=3)
        
        # Content should be truncated
        assert len(content) < len(long_content) + 100
        assert '...' in content
    
    def test_extract_cluster_content_many_chunks(self):
        """Test extracting representative chunks when document has many chunks"""
        chunks = [{'content': f'Chunk {i}'} for i in range(10)]
        document_samples = {
            'doc_001': {
                'filename': 'doc1.pdf',
                'chunks': chunks
            }
        }
        
        cluster_doc_ids = ['doc_001']
        content = extract_cluster_content(document_samples, cluster_doc_ids, max_chunks_per_doc=3)
        
        # Should only include representative chunks (first, middle, last)
        assert 'Chunk 0' in content
        assert 'Chunk 9' in content
        # Middle chunk should be around chunk 4 or 5
        assert 'Chunk 4' in content or 'Chunk 5' in content
    
    def test_summarize_cluster_placeholder(self):
        """Test cluster summarization (placeholder implementation)"""
        document_summaries = ["Summary 1", "Summary 2"]
        summary = summarize_cluster(document_summaries, language="zh", max_words=150)
        
        assert summary is not None
        assert isinstance(summary, str)
        assert 'Cluster Summary' in summary or 'Based on' in summary
    
    def test_merge_cluster_summaries(self):
        """Test merging cluster summaries"""
        cluster_summaries = {
            0: "Cluster 0 summary",
            1: "Cluster 1 summary",
            2: "Cluster 2 summary"
        }
        
        merged = merge_cluster_summaries(cluster_summaries)
        
        assert merged is not None
        assert isinstance(merged, str)
        assert "Cluster 0 summary" in merged
        assert "Cluster 1 summary" in merged
        assert "Cluster 2 summary" in merged
    
    def test_merge_cluster_summaries_empty(self):
        """Test merging empty cluster summaries"""
        cluster_summaries = {}
        merged = merge_cluster_summaries(cluster_summaries)
        
        assert merged == ""
    
    def test_summarize_clusters(self):
        """Test summarizing multiple clusters"""
        document_samples = {
            'doc_001': {
                'filename': 'doc1.pdf',
                'chunks': [{'content': 'Content 1'}]
            },
            'doc_002': {
                'filename': 'doc2.pdf',
                'chunks': [{'content': 'Content 2'}]
            },
            'doc_003': {
                'filename': 'doc3.pdf',
                'chunks': [{'content': 'Content 3'}]
            }
        }
        
        clusters = {
            0: ['doc_001', 'doc_002'],
            1: ['doc_003']
        }
        
        summaries = summarize_clusters(document_samples, clusters, language="zh", max_words=150)
        
        assert len(summaries) == 2
        assert 0 in summaries
        assert 1 in summaries
        assert summaries[0] is not None
        assert summaries[1] is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

