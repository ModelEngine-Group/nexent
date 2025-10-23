"""
Test LLM integration for knowledge base summarization
"""

import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from utils.document_vector_utils import summarize_document, summarize_cluster


class TestLLMIntegration:
    """Test LLM integration functionality"""
    
    def test_summarize_document_without_llm(self):
        """Test document summarization without LLM (fallback mode)"""
        content = "This is a test document with some content about machine learning and AI."
        filename = "test_doc.txt"
        
        result = summarize_document(content, filename, language="zh", max_words=50)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Document Summary: test_doc.txt]" in result
        assert "max 50 words" in result
        assert "Content:" in result
    
    def test_summarize_document_with_llm_params_no_config(self):
        """Test document summarization with LLM parameters but no model config"""
        content = "This is a test document with some content about machine learning and AI."
        filename = "test_doc.txt"
        
        # Test with model_id and tenant_id but no actual LLM call (will fail due to missing config)
        result = summarize_document(
            content, filename, language="zh", max_words=50, 
            model_id=1, tenant_id="test_tenant"
        )
        
        # Should return error message when model config not found
        assert "Failed to generate summary" in result or "No model configuration found" in result
    
    def test_summarize_cluster_without_llm(self):
        """Test cluster summarization without LLM (fallback mode)"""
        document_summaries = [
            "Document 1 is about machine learning algorithms.",
            "Document 2 discusses neural networks and deep learning.",
            "Document 3 covers AI applications in healthcare."
        ]
        
        result = summarize_cluster(document_summaries, language="zh", max_words=100)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Cluster Summary]" in result
        assert "max 100 words" in result
        assert "Based on 3 documents" in result
    
    def test_summarize_cluster_with_llm_params_no_config(self):
        """Test cluster summarization with LLM parameters but no model config"""
        document_summaries = [
            "Document 1 is about machine learning algorithms.",
            "Document 2 discusses neural networks and deep learning."
        ]
        
        result = summarize_cluster(
            document_summaries, language="zh", max_words=100,
            model_id=1, tenant_id="test_tenant"
        )
        
        # Should return error message when model config not found
        assert "Failed to generate summary" in result or "No model configuration found" in result
    
    def test_summarize_document_english(self):
        """Test document summarization in English"""
        content = "This is a test document with some content about machine learning and AI."
        filename = "test_doc.txt"
        
        result = summarize_document(content, filename, language="en", max_words=50)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Document Summary: test_doc.txt]" in result
        assert "max 50 words" in result
        assert "Content:" in result
    
    def test_summarize_cluster_english(self):
        """Test cluster summarization in English"""
        document_summaries = [
            "Document 1 is about machine learning algorithms.",
            "Document 2 discusses neural networks and deep learning."
        ]
        
        result = summarize_cluster(document_summaries, language="en", max_words=100)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Cluster Summary]" in result
        assert "max 100 words" in result
        assert "Based on 2 documents" in result
