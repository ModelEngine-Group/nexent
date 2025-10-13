"""
Test cases for async knowledge summary functionality
"""

import sys
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import numpy as np

# Mock external dependencies before importing backend modules
sys.modules['boto3'] = MagicMock()

with patch('backend.database.client.MinioClient') as minio_mock, \
     patch('elasticsearch.Elasticsearch', return_value=MagicMock()) as es_mock:
    minio_mock.return_value = MagicMock()
    
    from backend.utils.async_knowledge_summary_utils import (
        AsyncLLMClient,
        DocumentClusterer,
        ChunkDivider,
        ChunkClusterer,
        KnowledgeIntegrator,
        async_vectorize_batch
    )


class TestAsyncLLMClient:
    """Test AsyncLLMClient"""
    
    @pytest.fixture
    def model_config(self):
        return {
            'api_key': 'test-key',
            'base_url': 'http://test.com',
            'model_name': 'test-model',
            'model_repo': ''
        }
    
    @patch('backend.utils.async_knowledge_summary_utils.get_async_knowledge_summary_prompt_template')
    def test_client_initialization(self, mock_get_prompts, model_config):
        """Test client initialization with prompt template loading"""
        # Mock prompt templates
        mock_prompts = {
            'SUMMARY_GENERATION_PROMPT': 'Test summary prompt',
            'KEYWORD_EXTRACTION_PROMPT': 'Test keyword prompt',
            'CLUSTER_INTEGRATION_PROMPT': 'Test cluster prompt',
            'GLOBAL_INTEGRATION_PROMPT': 'Test global prompt'
        }
        mock_get_prompts.return_value = mock_prompts
        
        client = AsyncLLMClient(model_config, language='zh')
        assert client.model_config == model_config
        assert client.model_name == 'test-model'
        assert client.language == 'zh'
        assert client.prompts == mock_prompts
        mock_get_prompts.assert_called_once_with('zh')
    


class TestDocumentClusterer:
    """Test DocumentClusterer"""
    
    def test_clusterer_initialization(self):
        """Test clusterer initialization"""
        clusterer = DocumentClusterer(max_clusters=5)
        assert clusterer.max_clusters == 5
    
    def test_cluster_documents(self):
        """Test document clustering"""
        clusterer = DocumentClusterer(max_clusters=3)
        
        # Create test vectors
        vectors = np.random.rand(10, 128)
        
        result = clusterer.cluster_documents(vectors)
        
        assert result is not None
        assert 'cluster_labels' in result
        assert 'n_clusters' in result
        assert len(result['cluster_labels']) == 10
        assert result['n_clusters'] <= 3
    
    def test_single_document_clustering(self):
        """Test single document returns single cluster"""
        clusterer = DocumentClusterer(max_clusters=5)
        
        # Single document vector
        vectors = np.random.rand(1, 128)
        
        result = clusterer.cluster_documents(vectors)
        
        assert result is not None
        assert result['n_clusters'] == 1
        assert len(result['cluster_labels']) == 1
        assert result['cluster_labels'][0] == 0


class TestChunkDivider:
    """Test ChunkDivider"""
    
    def test_divider_initialization(self):
        """Test divider initialization"""
        divider = ChunkDivider(window_size=300, overlap_ratio=0.3)
        assert divider.window_size == 300
        assert divider.overlap_ratio == 0.3
    
    def test_divide_documents(self):
        """Test document division into chunks"""
        divider = ChunkDivider(window_size=100, overlap_ratio=0.2)
        
        documents = [
            {
                'content': 'This is a test document. ' * 20,  # Long enough to create multiple chunks
                'filename': 'test1.txt',
                '_id': '1',
                'title': 'Test Document 1'
            }
        ]
        
        chunks = divider.divide_documents(documents)
        
        assert len(chunks) > 0
        assert all('content' in chunk for chunk in chunks)
        assert all('chunk_id' in chunk for chunk in chunks)


class TestChunkClusterer:
    """Test ChunkClusterer"""
    
    def test_clusterer_initialization(self):
        """Test clusterer initialization"""
        clusterer = ChunkClusterer(similarity_threshold=0.7)
        assert clusterer.similarity_threshold == 0.7
    
    def test_cluster_chunks_with_document_clusters(self):
        """Test document-cluster-aware chunk clustering"""
        clusterer = ChunkClusterer(similarity_threshold=0.7, min_cluster_size=1)
        
        # Create test vectors and chunks
        vectors = np.random.rand(6, 128)
        chunks = [
            {
                'content': f'test content {i}',
                'filename': 'doc1.txt' if i < 3 else 'doc2.txt',
                '_id': str(i),
                'chunk_id': f'chunk_{i}'
            }
            for i in range(6)
        ]
        
        # Simulate document clusters
        chunks_by_doc_cluster = {
            0: chunks[0:3],  # doc_cluster_0: chunks from doc1
            1: chunks[3:6]   # doc_cluster_1: chunks from doc2
        }
        
        result = clusterer.cluster_chunks_with_document_clusters(vectors, chunks, chunks_by_doc_cluster)
        
        assert 'chunk_clusters' in result
        assert 'n_clusters' in result
        assert result['n_clusters'] >= len(chunks_by_doc_cluster)  # At least 1 cluster per doc cluster
    
    def test_estimate_tokens_for_chunks(self):
        """Test token estimation for chunks"""
        clusterer = ChunkClusterer()
        
        chunks = [
            {'content': '这是一个测试文本' * 100},  # ~600 Chinese chars
            {'content': '另一个测试' * 50}          # ~200 Chinese chars
        ]
        
        tokens = clusterer._estimate_tokens_for_chunks(chunks)
        
        # Roughly 800 chars / 4 ≈ 200 tokens
        assert tokens > 0
        assert tokens < 500  # Should be reasonable


class TestKnowledgeIntegrator:
    """Test KnowledgeIntegrator"""
    
    @pytest.fixture
    def model_config(self):
        return {
            'api_key': 'test-key',
            'base_url': 'http://test.com',
            'model_name': 'test-model',
            'model_repo': ''
        }
    
    @pytest.fixture
    def llm_client(self, model_config):
        return AsyncLLMClient(model_config)
    
    def test_integrator_initialization(self, llm_client):
        """Test integrator initialization"""
        integrator = KnowledgeIntegrator(llm_client)
        assert integrator.llm_client == llm_client


class TestAsyncVectorizeBatch:
    """Test async vectorize batch function"""
    
    def test_vectorize_batch_function_exists(self):
        """Test that async_vectorize_batch function exists and is callable"""
        assert callable(async_vectorize_batch)


class TestPromptTemplateUsage:
    """Test prompt template usage in async knowledge summary"""
    
    @patch('backend.utils.async_knowledge_summary_utils.get_async_knowledge_summary_prompt_template')
    def test_summary_uses_template(self, mock_get_prompts):
        """Test that summary generation uses YAML templates"""
        mock_prompts = {
            'SUMMARY_GENERATION_PROMPT': 'Generate summary for: {{ text }}',
            'KEYWORD_EXTRACTION_PROMPT': 'Extract keywords',
            'CLUSTER_INTEGRATION_PROMPT': 'Integrate clusters',
            'GLOBAL_INTEGRATION_PROMPT': 'Generate global summary'
        }
        mock_get_prompts.return_value = mock_prompts
        
        model_config = {
            'api_key': 'test-key',
            'base_url': 'http://test.com',
            'model_name': 'test-model',
            'model_repo': ''
        }
        
        client = AsyncLLMClient(model_config, language='zh')
        
        # Verify prompts are loaded
        assert client.prompts == mock_prompts
        assert 'SUMMARY_GENERATION_PROMPT' in client.prompts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

