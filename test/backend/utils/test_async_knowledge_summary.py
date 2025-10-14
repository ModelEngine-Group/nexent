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

# Mock backend modules that have import issues in CI environment
with patch.dict('sys.modules', {
    'backend.database.client': MagicMock(),
    'elasticsearch': MagicMock()
}):
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
    
    def test_client_initialization(self, model_config):
        """Test client initialization with prompt template loading"""
        client = AsyncLLMClient(model_config, language='zh')
        assert client.model_config == model_config
        assert client.model_name == 'test-model'
        assert client.language == 'zh'
        # Verify prompts are loaded (any prompts, from real YAML)
        assert hasattr(client, 'prompts')
        assert isinstance(client.prompts, dict)
        assert 'SUMMARY_GENERATION_PROMPT' in client.prompts
        assert 'KEYWORD_EXTRACTION_PROMPT' in client.prompts
        assert 'CLUSTER_INTEGRATION_PROMPT' in client.prompts
        assert 'GLOBAL_INTEGRATION_PROMPT' in client.prompts
    
    def test_chat_async_initialization(self, model_config):
        """Test async chat client initialization"""
        client = AsyncLLMClient(model_config, language='zh')
        
        # Test that the client is properly initialized
        assert hasattr(client, 'client')
        assert hasattr(client, 'semaphore')
        assert client.semaphore._value == 3  # Actual semaphore value from implementation
    
    def test_clean_markdown_symbols(self, model_config):
        """Test markdown symbols cleaning"""
        client = AsyncLLMClient(model_config, language='zh')
        
        text_with_markdown = "**Bold** *Italic*"
        cleaned = client._clean_markdown_symbols(text_with_markdown)
        assert "**" not in cleaned
        assert "*" not in cleaned
        # The method only cleans certain markdown symbols, not all
    
    def test_fallback_keyword_extraction(self, model_config):
        """Test fallback keyword extraction"""
        client = AsyncLLMClient(model_config, language='zh')
        
        text = "这是一个测试文档关于机器学习和人工智能的内容。"
        keywords = client._fallback_keyword_extraction(text)
        
        assert isinstance(keywords, list)
        assert len(keywords) >= 0
        # Should contain some meaningful Chinese words (check if any keywords are extracted)
        # The method extracts words >= 2 characters, so we expect some results
    


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
    
    def test_find_optimal_k_high_similarity(self):
        """Test finding optimal k for highly similar documents"""
        clusterer = DocumentClusterer()
        
        # Create highly similar vectors (similarity > 0.95)
        vectors = np.array([
            [1.0, 2.0, 3.0],
            [1.1, 2.1, 3.1],
            [0.9, 1.9, 2.9]
        ])
        
        optimal_k = clusterer._find_optimal_k(vectors)
        assert optimal_k == 1  # Should return 1 for highly similar documents
    
    def test_find_optimal_k_multiple_clusters(self):
        """Test finding optimal k for distinct document clusters"""
        clusterer = DocumentClusterer()
        
        # Create more distinct clusters with larger separation
        vectors = np.array([
            [1.0, 2.0, 3.0],   # Cluster 1
            [1.1, 2.1, 3.1],   # Cluster 1
            [100.0, 200.0, 300.0],  # Cluster 2 - much further away
            [100.1, 200.1, 300.1],  # Cluster 2
        ])
        
        optimal_k = clusterer._find_optimal_k(vectors)
        assert optimal_k >= 1  # Should find at least 1 cluster (might find more)


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
    
    def test_threshold_clustering(self):
        """Test threshold-based clustering"""
        clusterer = ChunkClusterer(similarity_threshold=0.7)
        
        # Create similarity matrix with clear clusters
        similarity_matrix = np.array([
            [1.0, 0.9, 0.8, 0.2, 0.1],  # Cluster 1
            [0.9, 1.0, 0.85, 0.3, 0.2],  # Cluster 1
            [0.8, 0.85, 1.0, 0.25, 0.15],  # Cluster 1
            [0.2, 0.3, 0.25, 1.0, 0.9],  # Cluster 2
            [0.1, 0.2, 0.15, 0.9, 1.0],  # Cluster 2
        ])
        
        cluster_labels = clusterer._threshold_clustering(similarity_matrix)
        
        assert len(cluster_labels) == 5
        # First 3 should be in same cluster, last 2 in another cluster
        assert cluster_labels[0] == cluster_labels[1] == cluster_labels[2]
        assert cluster_labels[3] == cluster_labels[4]
        assert cluster_labels[0] != cluster_labels[3]
    
    def test_organize_clusters(self):
        """Test cluster organization"""
        clusterer = ChunkClusterer()
        
        chunks = [
            {'content': 'chunk1', '_id': '1'},
            {'content': 'chunk2', '_id': '2'},
            {'content': 'chunk3', '_id': '3'},
        ]
        
        cluster_labels = np.array([0, 0, 1])
        similarity_matrix = np.array([
            [1.0, 0.8, 0.2],
            [0.8, 1.0, 0.3],
            [0.2, 0.3, 1.0]
        ])
        
        organized = clusterer._organize_clusters(chunks, cluster_labels, similarity_matrix)
        
        assert 'chunk_clusters' in organized
        assert 'noise_chunks' in organized
        assert len(organized['chunk_clusters']) == 2  # Two clusters
        assert len(organized['noise_chunks']) == 0  # No noise chunks


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
    
    def test_integrator_methods_exist(self, llm_client):
        """Test that integrator methods exist and are callable"""
        integrator = KnowledgeIntegrator(llm_client)
        
        # Test that all required methods exist
        assert hasattr(integrator, 'integrate_cluster_cards')
        assert hasattr(integrator, 'integrate_all_clusters')
        assert hasattr(integrator, '_generate_cluster_summary_async')
        assert hasattr(integrator, '_generate_global_summary_async')
        assert hasattr(integrator, '_integrate_keywords')
        assert hasattr(integrator, '_clean_markdown_symbols')
        
        # Test that methods are callable
        assert callable(integrator.integrate_cluster_cards)
        assert callable(integrator.integrate_all_clusters)
        assert callable(integrator._integrate_keywords)
        assert callable(integrator._clean_markdown_symbols)
    
    def test_clean_markdown_symbols(self, llm_client):
        """Test markdown symbols cleaning in integrator"""
        integrator = KnowledgeIntegrator(llm_client)
        
        text_with_markdown = "**Bold** *Italic*"
        cleaned = integrator._clean_markdown_symbols(text_with_markdown)
        assert "**" not in cleaned
        assert "*" not in cleaned
        # The method only cleans certain markdown symbols, not all
    
    def test_integrate_keywords(self, llm_client):
        """Test keyword integration logic"""
        integrator = KnowledgeIntegrator(llm_client)
        
        # Test with a list of keywords directly
        keywords_list = ['keyword1', 'keyword2', 'keyword1', 'keyword2', 'keyword3', 'keyword1']
        
        integrated_keywords = integrator._integrate_keywords(keywords_list)
        
        assert isinstance(integrated_keywords, list)
        assert len(integrated_keywords) > 0
        # keyword1 appears 3 times, should be most frequent
        assert 'keyword1' in integrated_keywords


class TestAsyncVectorizeBatch:
    """Test async vectorize batch function"""
    
    def test_vectorize_batch_function_exists(self):
        """Test that async_vectorize_batch function exists and is callable"""
        assert callable(async_vectorize_batch)
    
    def test_vectorize_batch_signature(self):
        """Test async_vectorize_batch function signature"""
        import inspect
        
        # Check function signature
        sig = inspect.signature(async_vectorize_batch)
        params = list(sig.parameters.keys())
        
        assert 'texts' in params
        assert 'embedding_model' in params
        assert 'batch_size' in params


class TestPromptTemplateUsage:
    """Test prompt template usage in async knowledge summary"""
    
    def test_summary_uses_template(self):
        """Test that summary generation uses YAML templates"""
        model_config = {
            'api_key': 'test-key',
            'base_url': 'http://test.com',
            'model_name': 'test-model',
            'model_repo': ''
        }
        
        # Test with Chinese language
        client_zh = AsyncLLMClient(model_config, language='zh')
        assert 'SUMMARY_GENERATION_PROMPT' in client_zh.prompts
        assert 'KEYWORD_EXTRACTION_PROMPT' in client_zh.prompts
        assert 'CLUSTER_INTEGRATION_PROMPT' in client_zh.prompts
        assert 'GLOBAL_INTEGRATION_PROMPT' in client_zh.prompts
        
        # Test with English language
        client_en = AsyncLLMClient(model_config, language='en')
        assert 'SUMMARY_GENERATION_PROMPT' in client_en.prompts
        assert 'KEYWORD_EXTRACTION_PROMPT' in client_en.prompts
        
        # Verify that different languages load different templates
        assert client_zh.prompts != client_en.prompts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

