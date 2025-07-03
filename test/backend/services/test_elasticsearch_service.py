import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import time
from fastapi import HTTPException, Response, status
from fastapi.responses import StreamingResponse, JSONResponse

# Mock MinioClient before importing modules that use it
import sys
from unittest.mock import patch

# Apply the patches before importing the module being tested
with patch('botocore.client.BaseClient._make_api_call'), \
     patch('backend.database.client.MinioClient'):
    from backend.services.elasticsearch_service import ElasticSearchService, get_es_core

class TestElasticSearchService(unittest.TestCase):
    def setUp(self):
        """
        Set up test environment before each test.

        This method initializes a fresh ElasticSearchService instance
        and prepares mock objects for the ES core and embedding model
        that will be used across test cases.
        """
        self.es_service = ElasticSearchService()
        self.mock_es_core = MagicMock()
        self.mock_es_core.embedding_model = MagicMock()
        self.mock_es_core.embedding_dim = 768

    @patch('backend.services.elasticsearch_service.create_knowledge_record')
    def test_create_index_success(self, mock_create_knowledge):
        """
        Test successful index creation.

        This test verifies that:
        1. The index is created when it doesn't already exist
        2. The vector index is properly configured with the correct embedding dimension
        3. A knowledge record is created for the new index
        4. The method returns a success status
        """
        # Setup
        self.mock_es_core.client.indices.exists.return_value = False
        self.mock_es_core.create_vector_index.return_value = True
        mock_create_knowledge.return_value = True

        # Execute
        result = ElasticSearchService.create_index(
            index_name="test_index",
            embedding_dim=768,
            es_core=self.mock_es_core,
            user_id="test_user"
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.mock_es_core.client.indices.exists.assert_called_once_with(index="test_index")
        self.mock_es_core.create_vector_index.assert_called_once_with("test_index", embedding_dim=768)
        mock_create_knowledge.assert_called_once()

    @patch('backend.services.elasticsearch_service.create_knowledge_record')
    def test_create_index_already_exists(self, mock_create_knowledge):
        """
        Test index creation when the index already exists.

        This test verifies that:
        1. An HTTPException with status code 500 is raised when the index already exists
        2. The exception message contains "already exists"
        3. No knowledge record is created
        """
        # Setup
        self.mock_es_core.client.indices.exists.return_value = True

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.create_index(
                index_name="test_index",
                embedding_dim=768,
                es_core=self.mock_es_core,
                user_id="test_user"
            )

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("already exists", context.exception.detail)
        mock_create_knowledge.assert_not_called()

    @patch('backend.services.elasticsearch_service.create_knowledge_record')
    def test_create_index_failure(self, mock_create_knowledge):
        """
        Test index creation failure.

        This test verifies that:
        1. An HTTPException with status code 500 is raised when index creation fails
        2. The exception message contains "Failed to create index"
        3. No knowledge record is created
        """
        # Setup
        self.mock_es_core.client.indices.exists.return_value = False
        self.mock_es_core.create_vector_index.return_value = False

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.create_index(
                index_name="test_index",
                embedding_dim=768,
                es_core=self.mock_es_core,
                user_id="test_user"
            )

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("Failed to create index", context.exception.detail)
        mock_create_knowledge.assert_not_called()

    @patch('backend.services.elasticsearch_service.delete_knowledge_record')
    def test_delete_index_success(self, mock_delete_knowledge):
        """
        Test successful index deletion.

        This test verifies that:
        1. The index is successfully deleted from Elasticsearch
        2. The corresponding knowledge record is deleted
        3. The method returns a success status
        """
        # Setup
        self.mock_es_core.delete_index.return_value = True
        mock_delete_knowledge.return_value = True

        # Execute
        result = ElasticSearchService.delete_index(
            index_name="test_index",
            es_core=self.mock_es_core,
            user_id="test_user"
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.mock_es_core.delete_index.assert_called_once_with("test_index")
        mock_delete_knowledge.assert_called_once()

    @patch('backend.services.elasticsearch_service.delete_knowledge_record')
    def test_delete_index_failure(self, mock_delete_knowledge):
        """
        Test index deletion failure.

        This test verifies that:
        1. An HTTPException with status code 500 is raised when index deletion fails
        2. No knowledge record is deleted
        """
        # Setup
        self.mock_es_core.delete_index.return_value = False

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.delete_index(
                index_name="test_index",
                es_core=self.mock_es_core,
                user_id="test_user"
            )

        self.assertEqual(context.exception.status_code, 500)
        mock_delete_knowledge.assert_not_called()

    @patch('backend.services.elasticsearch_service.delete_knowledge_record')
    def test_delete_index_knowledge_record_failure(self, mock_delete_knowledge):
        """
        Test deletion when the index is deleted but knowledge record deletion fails.

        This test verifies that:
        1. Even if the Elasticsearch index is deleted successfully
        2. An HTTPException with status code 500 is raised if knowledge record deletion fails
        3. The exception message contains "Error deleting knowledge record"
        """
        # Setup
        self.mock_es_core.delete_index.return_value = True
        mock_delete_knowledge.return_value = False

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.delete_index(
                index_name="test_index",
                es_core=self.mock_es_core,
                user_id="test_user"
            )

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("Error deleting knowledge record", context.exception.detail)

    @patch('backend.services.elasticsearch_service.get_knowledge_record')
    def test_list_indices_without_stats(self, mock_get_knowledge):
        """
        Test listing indices without including statistics.

        This test verifies that:
        1. The method retrieves indices matching the pattern
        2. The correct number of indices is returned
        3. No statistics are requested when include_stats is False
        """
        # Setup
        self.mock_es_core.get_user_indices.return_value = ["index1", "index2"]
        mock_get_knowledge.return_value = None  # Or appropriate mock data if needed

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            tenant_id=None,  # Explicitly set tenant_id to None
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        self.mock_es_core.get_user_indices.assert_called_once_with("*")
        self.mock_es_core.get_all_indices_stats.assert_not_called()

    @patch('backend.services.elasticsearch_service.get_knowledge_record')
    def test_list_indices_with_stats(self, mock_get_knowledge):
        """
        Test listing indices with statistics included.

        This test verifies that:
        1. The method retrieves indices matching the pattern
        2. Statistics for each index are also retrieved
        3. Both indices and their stats are included in the response
        """
        # Setup
        self.mock_es_core.get_user_indices.return_value = ["index1", "index2"]
        self.mock_es_core.get_index_stats.return_value = {
            "index1": {"doc_count": 10},
            "index2": {"doc_count": 20}
        }
        mock_get_knowledge.return_value = None  # Or appropriate mock data if needed

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            tenant_id=None,  # Explicitly set tenant_id to None
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["indices_info"]), 2)
        self.mock_es_core.get_user_indices.assert_called_once_with("*")
        self.mock_es_core.get_index_stats.assert_called_once_with(["index1", "index2"])

    def test_get_index_info_success(self):
        """
        Test successful retrieval of index information.

        This test verifies that:
        1. Index statistics are correctly retrieved
        2. Index mapping details are correctly retrieved
        3. The response contains both base information and field details
        4. All expected information is present in the response
        """
        # Setup
        self.mock_es_core.get_index_stats.return_value = {
            "test_index": {
                "base_info": {
                    "doc_count": 10,
                    "unique_sources_count": 5,
                    "store_size": "1MB",
                    "process_source": "Test",
                    "embedding_model": "Test"
                },
                "search_performance": {"avg_time": 10}
            }
        }
        self.mock_es_core.get_index_mapping.return_value = {
            "test_index": ["field1", "field2"]
        }

        # Execute
        result = ElasticSearchService.get_index_name(
            index_name="test_index",
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(result["base_info"]["doc_count"], 10)
        self.assertEqual(len(result["fields"]), 2)
        self.mock_es_core.get_index_stats.assert_called_once_with(["test_index"])
        self.mock_es_core.get_index_mapping.assert_called_once_with(["test_index"])


    def test_index_documents_success(self):
        """
        Test successful document indexing.

        This test verifies that:
        1. Documents are properly indexed when the index exists
        2. The indexing operation returns the correct count of indexed documents
        3. The response contains proper success status and document counts
        4. Documents with various metadata fields are handled correctly
        """
        # Setup
        self.mock_es_core.client.indices.exists.return_value = True
        self.mock_es_core.index_documents.return_value = 2
        test_data = [
            {
                "metadata": {
                    "title": "Test Document",
                    "languages": ["en"],
                    "author": "Test Author",
                    "date": "2023-01-01",
                    "creation_date": "2023-01-01T12:00:00"
                },
                "path_or_url": "test_path",
                "content": "Test content",
                "source_type": "file",
                "file_size": 1024,
                "filename": "test.txt"
            },
            {
                "metadata": {
                    "title": "Test Document 2"
                },
                "path_or_url": "test_path2",
                "content": "Test content 2"
            }
        ]

        # Execute
        result = ElasticSearchService.index_documents(
            index_name="test_index",
            data=test_data,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertTrue(result["success"])
        self.assertEqual(result["total_indexed"], 2)
        self.assertEqual(result["total_submitted"], 2)
        self.mock_es_core.index_documents.assert_called_once()

    def test_index_documents_empty_data(self):
        """
        Test document indexing with empty data.

        This test verifies that:
        1. When no documents are provided, the method handles it gracefully
        2. No documents are indexed when the data list is empty
        3. The response correctly indicates success with zero documents
        """
        # Setup
        test_data = []

        # Execute
        result = ElasticSearchService.index_documents(
            index_name="test_index",
            data=test_data,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertTrue(result["success"])
        self.assertEqual(result["total_indexed"], 0)
        self.assertEqual(result["total_submitted"], 0)
        self.mock_es_core.index_documents.assert_not_called()

    def test_index_documents_create_index(self):
        """
        Test document indexing when the index doesn't exist.

        This test verifies that:
        1. When the index doesn't exist, it's created automatically
        2. After creating the index, documents are indexed successfully
        3. The response contains the correct status and document counts
        """
        # Setup
        self.mock_es_core.client.indices.exists.return_value = False
        self.mock_es_core.create_vector_index.return_value = True
        self.mock_es_core.index_documents.return_value = 1
        test_data = [
            {
                "metadata": {"title": "Test"},
                "path_or_url": "test_path",
                "content": "Test content"
            }
        ]

        # Execute
        with patch('backend.services.elasticsearch_service.ElasticSearchService.create_index') as mock_create_index:
            mock_create_index.return_value = {"status": "success"}
            result = ElasticSearchService.index_documents(
                index_name="test_index",
                data=test_data,
                es_core=self.mock_es_core
            )

        # Assert
        self.assertTrue(result["success"])
        self.assertEqual(result["total_indexed"], 1)
        mock_create_index.assert_called_once()

    def test_index_documents_indexing_error(self):
        """
        Test document indexing when an error occurs during indexing.

        This test verifies that:
        1. When an error occurs during indexing, an appropriate exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "Error during indexing"
        """
        # Setup
        self.mock_es_core.client.indices.exists.return_value = True
        self.mock_es_core.index_documents.side_effect = Exception("Indexing error")
        test_data = [
            {
                "metadata": {"title": "Test"},
                "path_or_url": "test_path",
                "content": "Test content"
            }
        ]

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.index_documents(
                index_name="test_index",
                data=test_data,
                es_core=self.mock_es_core
            )

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("Error during indexing", context.exception.detail)

    @patch('backend.services.elasticsearch_service.get_all_files_status')
    def test_list_files_without_chunks(self, mock_get_files_status):
        """
        Test listing files without including document chunks.

        This test verifies that:
        1. Files indexed in Elasticsearch are retrieved correctly
        2. Files being processed (from Redis) are included in the results
        3. Files from both sources are combined in the response
        4. The status of each file is correctly set (COMPLETED or PROCESSING)
        """
        # Setup
        self.mock_es_core.get_file_list_with_details.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00"
            }
        ]
        mock_get_files_status.return_value = {"file2": "PROCESSING"}

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=False,
                search_redis=True,
                es_core=self.mock_es_core
            )

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(result["files"][0]["status"], "COMPLETED")
        self.assertEqual(result["files"][1]["status"], "PROCESSING")
        self.mock_es_core.get_file_list_with_details.assert_called_once_with("test_index")

    @patch('backend.services.elasticsearch_service.get_all_files_status')
    def test_list_files_with_chunks(self, mock_get_files_status):
        """
        Test listing files with document chunks included.

        This test verifies that:
        1. Files indexed in Elasticsearch are retrieved correctly
        2. Document chunks for each file are retrieved using msearch
        3. The chunks are included in the file details
        4. The chunk count is correctly calculated
        """
        # Setup
        self.mock_es_core.get_file_list_with_details.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00"
            }
        ]
        mock_get_files_status.return_value = {}

        # Mock msearch response
        msearch_response = {
            'responses': [
                {
                    'hits': {
                        'hits': [
                            {
                                '_source': {
                                    'id': 'doc1',
                                    'title': 'Title 1',
                                    'content': 'Content 1',
                                    'create_time': '2023-01-01T12:00:00'
                                }
                            }
                        ]
                    }
                }
            ]
        }
        self.mock_es_core.client.msearch.return_value = msearch_response

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=True,
                search_redis=True,
                es_core=self.mock_es_core
            )

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(len(result["files"][0]["chunks"]), 1)
        self.assertEqual(result["files"][0]["chunk_count"], 1)
        self.mock_es_core.client.msearch.assert_called_once()

    @patch('backend.services.elasticsearch_service.get_all_files_status')
    def test_list_files_msearch_error(self, mock_get_files_status):
        """
        Test listing files when msearch encounters an error.

        This test verifies that:
        1. When msearch fails, the method handles the error gracefully
        2. Files are still returned without chunks
        3. Chunk count is set to 0 for affected files
        4. The overall operation doesn't fail due to msearch errors
        """
        # Setup
        self.mock_es_core.get_file_list_with_details.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00"
            }
        ]
        mock_get_files_status.return_value = {}

        # Mock msearch error
        self.mock_es_core.client.msearch.side_effect = Exception("MSSearch Error")

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=True,
                search_redis=True,
                es_core=self.mock_es_core
            )

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(len(result["files"][0]["chunks"]), 0)
        self.assertEqual(result["files"][0]["chunk_count"], 0)

    def test_delete_documents(self):
        """
        Test document deletion by path or URL.

        This test verifies that:
        1. Documents with the specified path or URL are deleted
        2. The correct number of deleted documents is returned
        3. The response contains a success status
        """
        # Setup
        self.mock_es_core.delete_documents_by_path_or_url.return_value = 5

        # Execute
        result = ElasticSearchService.delete_documents(
            index_name="test_index",
            path_or_url="test_path",
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_count"], 5)
        self.mock_es_core.delete_documents_by_path_or_url.assert_called_once_with("test_index", "test_path")

    def test_accurate_search(self):
        """
        Test accurate (keyword-based) search functionality.

        This test verifies that:
        1. The accurate_search method correctly calls the core search implementation
        2. Search results are properly formatted in the response
        3. The response includes total count and query time
        4. The search is performed across the specified indices
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "test query"
        search_request.top_k = 10

        self.mock_es_core.accurate_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.95,
                "index": "test_index"
            }
        ]

        # Execute
        result = ElasticSearchService.accurate_search(
            request=search_request,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["total"], 1)
        self.assertTrue("query_time_ms" in result)
        self.mock_es_core.accurate_search.assert_called_once_with(
            ["test_index"], "test query", 10
        )

    def test_accurate_search_empty_query(self):
        """
        Test accurate search with an empty query.

        This test verifies that:
        1. When the query is empty or consists only of whitespace, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "Search query cannot be empty"
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "   "  # Empty query
        search_request.top_k = 10

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.accurate_search(
                request=search_request,
                es_core=self.mock_es_core
            )

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("Search query cannot be empty", context.exception.detail)

    def test_accurate_search_no_indices(self):
        """
        Test accurate search with no indices specified.

        This test verifies that:
        1. When no indices are specified, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "At least one index name is required"
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = []  # No indices
        search_request.query = "test query"
        search_request.top_k = 10

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.accurate_search(
                request=search_request,
                es_core=self.mock_es_core
            )

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("At least one index name is required", context.exception.detail)

    def test_semantic_search(self):
        """
        Test semantic (embedding-based) search functionality.

        This test verifies that:
        1. The semantic_search method correctly calls the core search implementation
        2. Search results are properly formatted in the response
        3. The response includes total count and query time
        4. The search is performed across the specified indices
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "test query"
        search_request.top_k = 10

        self.mock_es_core.semantic_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.85,
                "index": "test_index"
            }
        ]

        # Execute
        result = ElasticSearchService.semantic_search(
            request=search_request,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["total"], 1)
        self.assertTrue("query_time_ms" in result)
        self.mock_es_core.semantic_search.assert_called_once_with(
            ["test_index"], "test query", 10
        )

    def test_hybrid_search(self):
        """
        Test hybrid search (combining semantic and accurate search).

        This test verifies that:
        1. The hybrid_search method correctly calls the core search implementation
        2. The weight parameter for balancing semantic and accurate search is passed correctly
        3. Search results include individual scores for both semantic and accurate searches
        4. The response contains the expected structure with results, total, and timing information
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "test query"
        search_request.top_k = 10
        search_request.weight_accurate = 0.5

        self.mock_es_core.hybrid_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.90,
                "index": "test_index",
                "scores": {"accurate": 0.85, "semantic": 0.95}
            }
        ]

        # Execute
        result = ElasticSearchService.hybrid_search(
            request=search_request,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["total"], 1)
        self.assertTrue("query_time_ms" in result)
        self.assertEqual(result["results"][0]["score_details"]["accurate"], 0.85)
        self.assertEqual(result["results"][0]["score_details"]["semantic"], 0.95)
        self.mock_es_core.hybrid_search.assert_called_once_with(
            ["test_index"], "test query", 10, 0.5
        )

    def test_health_check_healthy(self):
        """
        Test health check when Elasticsearch is healthy.

        This test verifies that:
        1. The health check correctly reports a healthy status when Elasticsearch is available
        2. The response includes the connection status and indices count
        3. The health_check method returns without raising exceptions
        """
        # Setup
        self.mock_es_core.get_user_indices.return_value = ["index1", "index2"]

        # Execute
        result = ElasticSearchService.health_check(es_core=self.mock_es_core)

        # Assert
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["elasticsearch"], "connected")
        self.assertEqual(result["indices_count"], 2)

    def test_health_check_unhealthy(self):
        """
        Test health check when Elasticsearch is unhealthy.

        This test verifies that:
        1. When Elasticsearch is unavailable, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "Health check failed"
        """
        # Setup
        self.mock_es_core.get_user_indices.side_effect = Exception("Connection error")

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            ElasticSearchService.health_check(es_core=self.mock_es_core)

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("Health check failed", context.exception.detail)

    @patch('backend.services.elasticsearch_service.generate_knowledge_summary_stream')
    @patch('backend.services.elasticsearch_service.calculate_term_weights')
    def test_summary_index_name(self, mock_calculate_weights, mock_generate_summary):
        """
        Test generating a summary for an index.

        This test verifies that:
        1. Random documents are retrieved for summarization
        2. Term weights are calculated to identify important keywords
        3. The summary generation stream is properly initialized
        4. A StreamingResponse object is returned for streaming the summary tokens
        """
        # Setup
        mock_calculate_weights.return_value = {"keyword1": 0.8, "keyword2": 0.6}
        mock_generate_summary.return_value = ["Token1", "Token2", "END"]

        # Mock get_random_documents
        with patch.object(ElasticSearchService, 'get_random_documents') as mock_get_docs:
            mock_get_docs.return_value = {
                "documents": [
                    {"title": "Doc1", "filename": "file1.txt", "content": "Content1"},
                    {"title": "Doc2", "filename": "file2.txt", "content": "Content2"}
                ]
            }

            # Execute
            async def run_test():
                result = await self.es_service.summary_index_name(
                    index_name="test_index",
                    batch_size=1000,
                    es_core=self.mock_es_core,
                    language='en'
                )

                # Consume part of the stream to trigger the generator function
                generator = result.body_iterator
                # Get at least one item from the generator to trigger execution
                try:
                    await generator.__anext__()
                except StopAsyncIteration:
                    pass

                return result

            result = asyncio.run(run_test())

            # Assert
            self.assertIsInstance(result, StreamingResponse)
            mock_get_docs.assert_called_once()
            mock_calculate_weights.assert_called_once()
            mock_generate_summary.assert_called_once()

    def test_get_random_documents(self):
        """
        Test retrieving random documents from an index.

        This test verifies that:
        1. The method gets the total document count in the index
        2. A random sample of documents is retrieved
        3. The response contains both the total count and the sampled documents
        """
        # Setup
        count_response = {'count': 100}
        self.mock_es_core.client.count.return_value = count_response

        search_response = {
            'hits': {
                'hits': [
                    {
                        '_id': 'doc1',
                        '_source': {"title": "Doc1", "content": "Content1"}
                    },
                    {
                        '_id': 'doc2',
                        '_source': {"title": "Doc2", "content": "Content2"}
                    }
                ]
            }
        }
        self.mock_es_core.client.search.return_value = search_response

        # Execute
        result = ElasticSearchService.get_random_documents(
            index_name="test_index",
            batch_size=10,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(result["total"], 100)
        self.assertEqual(len(result["documents"]), 2)
        self.mock_es_core.client.count.assert_called_once_with(index="test_index")
        self.mock_es_core.client.search.assert_called_once()

    @patch('backend.services.elasticsearch_service.update_knowledge_record')
    def test_change_summary(self, mock_update_record):
        """
        Test changing the summary of a knowledge base.

        This test verifies that:
        1. The knowledge record is updated with the new summary
        2. The response includes a success status and the updated summary
        3. The update_knowledge_record function is called with correct parameters
        """
        # Setup
        mock_update_record.return_value = True

        # Execute
        result = self.es_service.change_summary(
            index_name="test_index",
            summary_result="Test summary",
            user_id="test_user"
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"], "Test summary")
        mock_update_record.assert_called_once()

    @patch('backend.services.elasticsearch_service.get_knowledge_record')
    def test_get_summary(self, mock_get_record):
        """
        Test retrieving the summary of a knowledge base.

        This test verifies that:
        1. The knowledge record is retrieved for the specified index
        2. The summary is extracted from the record
        3. The response includes a success status and the summary
        """
        # Setup
        mock_get_record.return_value = {
            "knowledge_describe": "Test summary"
        }

        # Execute
        result = self.es_service.get_summary(
            index_name="test_index",
            language='en'
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"], "Test summary")
        mock_get_record.assert_called_once_with({'index_name': 'test_index'})

    @patch('backend.services.elasticsearch_service.get_knowledge_record')
    def test_get_summary_not_found(self, mock_get_record):
        """
        Test retrieving a summary when the knowledge record doesn't exist.

        This test verifies that:
        1. When the knowledge record is not found, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "Unable to get summary"
        """
        # Setup
        mock_get_record.return_value = None

        # Execute and Assert
        with self.assertRaises(HTTPException) as context:
            self.es_service.get_summary(
                index_name="test_index",
                language='en'
            )

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("Unable to get summary", context.exception.detail)

    @patch('backend.services.elasticsearch_service.get_knowledge_record')
    @patch('fastapi.Response')
    def test_list_indices_success_status_200(self, mock_response, mock_get_knowledge):
        """
        Test list_indices method returns status code 200 on success.

        This test verifies that:
        1. The list_indices method successfully retrieves indices
        2. The response is a dictionary containing the expected data
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_es_core.get_user_indices.return_value = ["index1", "index2"]
        mock_response.status_code = 200
        mock_get_knowledge.return_value = None  # Or appropriate mock data if needed

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            tenant_id=None,  # Explicitly set tenant_id to None
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        # Verify no exception is raised, implying 200 status code
        self.assertIsInstance(result, dict)  # Success response is a dictionary
        self.mock_es_core.get_user_indices.assert_called_once_with("*")

    def test_health_check_success_status_200(self):
        """
        Test health_check method returns status code 200 on success.

        This test verifies that:
        1. The health_check method successfully checks Elasticsearch health
        2. The response is a dictionary with a "healthy" status
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_es_core.get_user_indices.return_value = ["index1", "index2"]

        # Execute
        result = ElasticSearchService.health_check(es_core=self.mock_es_core)

        # Assert
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["elasticsearch"], "connected")
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)  # Success response is a dictionary

    def test_get_random_documents_success_status_200(self):
        """
        Test get_random_documents method returns status code 200 on success.

        This test verifies that:
        1. The get_random_documents method successfully retrieves random documents
        2. The response contains the expected data structure with total and documents
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        count_response = {'count': 100}
        self.mock_es_core.client.count.return_value = count_response

        search_response = {
            'hits': {
                'hits': [
                    {
                        '_id': 'doc1',
                        '_source': {"title": "Doc1", "content": "Content1"}
                    }
                ]
            }
        }
        self.mock_es_core.client.search.return_value = search_response

        # Execute
        result = ElasticSearchService.get_random_documents(
            index_name="test_index",
            batch_size=10,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(result["total"], 100)
        self.assertEqual(len(result["documents"]), 1)
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)  # Success response is a dictionary
        self.assertIn("total", result)
        self.assertIn("documents", result)

    def test_semantic_search_success_status_200(self):
        """
        Test semantic_search method returns status code 200 on success.

        This test verifies that:
        1. The semantic_search method successfully performs a search
        2. The response contains the expected search results
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "valid query"
        search_request.top_k = 10

        self.mock_es_core.semantic_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.85,
                "index": "test_index"
            }
        ]

        # Execute
        result = ElasticSearchService.semantic_search(
            request=search_request,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertIn("results", result)
        self.assertIn("total", result)
        self.assertIn("query_time_ms", result)

    def test_index_documents_success_status_200(self):
        """
        Test index_documents method returns status code 200 on success.

        This test verifies that:
        1. The index_documents method successfully indexes multiple documents
        2. The response indicates success and correct document counts
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_es_core.client.indices.exists.return_value = True
        self.mock_es_core.index_documents.return_value = 3

        test_data = [
            {
                "metadata": {"title": "Test1", "languages": ["en"]},
                "path_or_url": "path1",
                "content": "Content1"
            },
            {
                "metadata": {"title": "Test2", "languages": ["zh"]},
                "path_or_url": "path2",
                "content": "Content2"
            },
            {
                "metadata": {"title": "Test3", "languages": ["fr"]},
                "path_or_url": "path3",
                "content": "Content3"
            }
        ]

        # Execute
        result = ElasticSearchService.index_documents(
            index_name="test_index",
            data=test_data,
            es_core=self.mock_es_core
        )

        # Assert
        self.assertTrue(result["success"])
        self.assertEqual(result["total_indexed"], 3)
        self.assertEqual(result["total_submitted"], 3)
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertTrue(result["success"])

    def test_delete_documents_success_status_200(self):
        """
        Test delete_documents method returns status code 200 on success.

        This test verifies that:
        1. The delete_documents method successfully deletes documents
        2. The response indicates success and the correct delete count
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_es_core.delete_documents_by_path_or_url.return_value = 5

        # Execute
        result = ElasticSearchService.delete_documents(
            index_name="test_index",
            path_or_url="test_path",
            es_core=self.mock_es_core
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_count"], 5)
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")

    @patch('backend.services.elasticsearch_service.get_knowledge_record')
    def test_get_summary_success_status_200(self, mock_get_record):
        """
        Test get_summary method returns status code 200 on success.

        This test verifies that:
        1. The get_summary method successfully retrieves a knowledge base summary
        2. The response indicates success and contains the summary
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        mock_get_record.return_value = {
            "knowledge_describe": "This is a test summary for knowledge base"
        }

        # Execute
        result = self.es_service.get_summary(
            index_name="test_index",
            language='en'
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"], "This is a test summary for knowledge base")
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")
        mock_get_record.assert_called_once_with({'index_name': 'test_index'})

if __name__ == '__main__':
    unittest.main()
