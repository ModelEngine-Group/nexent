import unittest
from unittest.mock import patch, MagicMock, call
import json
import os
import redis

from backend.services.redis_service import RedisService, get_redis_service


class TestRedisService(unittest.TestCase):
    
    def setUp(self):
        # Reset environment variables before each test
        self.env_patcher = patch.dict('os.environ', {
            'REDIS_URL': 'redis://localhost:6379/0',
            'REDIS_BACKEND_URL': 'redis://localhost:6379/1'
        })
        self.env_patcher.start()
        
        # Create a fresh instance for each test
        self.redis_service = RedisService()
        
        # Common mocks that can be used by multiple tests
        self.mock_redis_client = MagicMock()
        self.mock_backend_client = MagicMock()
    
    def tearDown(self):
        self.env_patcher.stop()
    
    @patch('redis.from_url')
    def test_client_property(self, mock_from_url):
        """Test client property creates and returns Redis client"""
        # Setup
        mock_from_url.return_value = self.mock_redis_client
        
        # Execute
        client = self.redis_service.client
        
        # Verify
        mock_from_url.assert_called_once_with(
            'redis://localhost:6379/0', 
            socket_timeout=5, 
            socket_connect_timeout=5
        )
        self.assertEqual(client, self.mock_redis_client)
        
        # Second call should reuse existing client
        self.redis_service.client
        mock_from_url.assert_called_once()  # Still only called once
    
    @patch('redis.from_url')
    def test_client_property_no_env_var(self, mock_from_url):
        """Test client property raises error when REDIS_URL is not set"""
        # Setup
        self.env_patcher.stop()
        with patch.dict('os.environ', {}, clear=True):
            # Execute & Verify
            with self.assertRaises(ValueError):
                _ = self.redis_service.client
    
    @patch('redis.from_url')
    def test_backend_client_property(self, mock_from_url):
        """Test backend_client property creates and returns Redis client"""
        # Setup
        mock_from_url.return_value = self.mock_backend_client
        
        # Execute
        client = self.redis_service.backend_client
        
        # Verify
        mock_from_url.assert_called_once_with(
            'redis://localhost:6379/1', 
            socket_timeout=5, 
            socket_connect_timeout=5
        )
        self.assertEqual(client, self.mock_backend_client)
        
        # Second call should reuse existing client
        self.redis_service.backend_client
        mock_from_url.assert_called_once()  # Still only called once
    
    @patch('redis.from_url')
    def test_backend_client_fallback(self, mock_from_url):
        """Test backend_client falls back to REDIS_URL when REDIS_BACKEND_URL is not set"""
        # Setup
        mock_from_url.return_value = self.mock_backend_client
        self.env_patcher.stop()
        with patch.dict('os.environ', {'REDIS_URL': 'redis://localhost:6379/0'}):
            # Execute
            client = self.redis_service.backend_client
            
            # Verify
            mock_from_url.assert_called_once_with(
                'redis://localhost:6379/0', 
                socket_timeout=5, 
                socket_connect_timeout=5
            )
            self.assertEqual(client, self.mock_backend_client)
    
    @patch('redis.from_url')
    def test_backend_client_no_env_vars(self, mock_from_url):
        """Test backend_client raises error when no Redis URLs are set"""
        # Setup
        self.env_patcher.stop()
        with patch.dict('os.environ', {}, clear=True):
            # Execute & Verify
            with self.assertRaises(ValueError):
                _ = self.redis_service.backend_client
    
    def test_delete_knowledgebase_records(self):
        """Test delete_knowledgebase_records method"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Mock the internal methods
        self.redis_service._cleanup_celery_tasks = MagicMock(return_value=5)
        self.redis_service._cleanup_cache_keys = MagicMock(return_value=10)
        
        # Execute
        result = self.redis_service.delete_knowledgebase_records("test_index")
        
        # Verify
        self.redis_service._cleanup_celery_tasks.assert_called_once_with("test_index")
        self.redis_service._cleanup_cache_keys.assert_called_once_with("test_index")
        
        self.assertEqual(result["index_name"], "test_index")
        self.assertEqual(result["celery_tasks_deleted"], 5)
        self.assertEqual(result["cache_keys_deleted"], 10)
        self.assertEqual(result["total_deleted"], 15)
        self.assertEqual(result["errors"], [])
    
    def test_delete_knowledgebase_records_with_error(self):
        """Test delete_knowledgebase_records handles errors properly"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Mock the internal methods to raise an exception
        self.redis_service._cleanup_celery_tasks = MagicMock(side_effect=Exception("Test error"))
        
        # Execute
        result = self.redis_service.delete_knowledgebase_records("test_index")
        
        # Verify
        self.assertEqual(result["index_name"], "test_index")
        self.assertEqual(result["celery_tasks_deleted"], 0)
        self.assertEqual(result["cache_keys_deleted"], 0)
        self.assertEqual(result["total_deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Test error", result["errors"][0])
    
    def test_delete_document_records(self):
        """Test delete_document_records method"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Mock the internal methods
        self.redis_service._cleanup_document_celery_tasks = MagicMock(return_value=3)
        self.redis_service._cleanup_document_cache_keys = MagicMock(return_value=7)
        
        # Execute
        result = self.redis_service.delete_document_records("test_index", "path/to/doc.pdf")
        
        # Verify
        self.redis_service._cleanup_document_celery_tasks.assert_called_once_with("test_index", "path/to/doc.pdf")
        self.redis_service._cleanup_document_cache_keys.assert_called_once_with("test_index", "path/to/doc.pdf")
        
        self.assertEqual(result["index_name"], "test_index")
        self.assertEqual(result["document_path"], "path/to/doc.pdf")
        self.assertEqual(result["celery_tasks_deleted"], 3)
        self.assertEqual(result["cache_keys_deleted"], 7)
        self.assertEqual(result["total_deleted"], 10)
        self.assertEqual(result["errors"], [])
    
    def test_delete_document_records_with_error(self):
        """Test delete_document_records handles errors properly"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Mock the internal methods to raise an exception
        self.redis_service._cleanup_document_celery_tasks = MagicMock(side_effect=Exception("Test error"))
        
        # Execute
        result = self.redis_service.delete_document_records("test_index", "path/to/doc.pdf")
        
        # Verify
        self.assertEqual(result["index_name"], "test_index")
        self.assertEqual(result["document_path"], "path/to/doc.pdf")
        self.assertEqual(result["celery_tasks_deleted"], 0)
        self.assertEqual(result["cache_keys_deleted"], 0)
        self.assertEqual(result["total_deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Test error", result["errors"][0])
    
    def test_cleanup_celery_tasks(self):
        """Test _cleanup_celery_tasks method"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client
        
        # Create mock task data
        task_keys = [b'celery-task-meta-1', b'celery-task-meta-2', b'celery-task-meta-3']
        
        # Task 1 matches our index
        task1_data = json.dumps({
            'result': {'index_name': 'test_index', 'some_key': 'some_value'}
        }).encode()
        
        # Task 2 has index name in a different location
        task2_data = json.dumps({
            'index_name': 'test_index', 
            'result': {'some_key': 'some_value'}
        }).encode()
        
        # Task 3 is for a different index
        task3_data = json.dumps({
            'result': {'index_name': 'other_index', 'some_key': 'some_value'}
        }).encode()
        
        # Configure mock responses
        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [task1_data, task2_data, task3_data]
        
        # Execute
        result = self.redis_service._cleanup_celery_tasks("test_index")
        
        # Verify
        self.mock_backend_client.keys.assert_called_once_with('celery-task-meta-*')
        self.assertEqual(self.mock_backend_client.get.call_count, 3)
        
        # Should delete only task1 and task2
        self.assertEqual(self.mock_backend_client.delete.call_count, 2)
        self.mock_backend_client.delete.assert_any_call(b'celery-task-meta-1')
        self.mock_backend_client.delete.assert_any_call(b'celery-task-meta-2')
        
        # Return value should be the number of deleted tasks
        self.assertEqual(result, 2)
    
    def test_cleanup_cache_keys(self):
        """Test _cleanup_cache_keys method"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        
        # Configure mock responses for each pattern
        pattern_keys = {
            '*test_index*': [b'key1', b'key2'],
            'kb:test_index:*': [b'key3', b'key4', b'key5'],
            'index:test_index:*': [b'key6'],
            'search:test_index:*': [b'key7', b'key8']
        }
        
        def mock_keys_side_effect(pattern):
            return pattern_keys.get(pattern, [])
        
        self.mock_redis_client.keys.side_effect = mock_keys_side_effect
        self.mock_redis_client.delete.return_value = 1  # Each delete operation deletes 1 key
        
        # Execute
        result = self.redis_service._cleanup_cache_keys("test_index")
        
        # Verify
        self.assertEqual(self.mock_redis_client.keys.call_count, 4)
        
        # All keys should be deleted (8 keys total)
        expected_calls = [
            call(b'key1', b'key2'),
            call(b'key3', b'key4', b'key5'),
            call(b'key6'),
            call(b'key7', b'key8')
        ]
        self.mock_redis_client.delete.assert_has_calls(expected_calls, any_order=True)
        
        # Return value should be the number of deleted keys
        self.assertEqual(result, 4)  # 4 successful delete operations
    
    def test_cleanup_document_celery_tasks(self):
        """Test _cleanup_document_celery_tasks method"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client
        
        # Create mock task data
        task_keys = [b'celery-task-meta-1', b'celery-task-meta-2', b'celery-task-meta-3']
        
        # Task 1 matches our index and document
        task1_data = json.dumps({
            'result': {
                'index_name': 'test_index',
                'source': 'path/to/doc.pdf'
            }
        }).encode()
        
        # Task 2 has the right index but wrong document
        task2_data = json.dumps({
            'result': {
                'index_name': 'test_index',
                'source': 'other/doc.pdf'
            }
        }).encode()
        
        # Task 3 has document path in a different field
        task3_data = json.dumps({
            'result': {
                'index_name': 'test_index',
                'path_or_url': 'path/to/doc.pdf'
            }
        }).encode()
        
        # Configure mock responses
        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [task1_data, task2_data, task3_data]
        
        # Execute
        result = self.redis_service._cleanup_document_celery_tasks("test_index", "path/to/doc.pdf")
        
        # Verify
        self.mock_backend_client.keys.assert_called_once_with('celery-task-meta-*')
        self.assertEqual(self.mock_backend_client.get.call_count, 3)
        
        # Should delete only task1 and task3
        self.assertEqual(self.mock_backend_client.delete.call_count, 2)
        self.mock_backend_client.delete.assert_any_call(b'celery-task-meta-1')
        self.mock_backend_client.delete.assert_any_call(b'celery-task-meta-3')
        
        # Return value should be the number of deleted tasks
        self.assertEqual(result, 2)
    
    @patch('hashlib.md5')
    @patch('urllib.parse.quote')
    def test_cleanup_document_cache_keys(self, mock_quote, mock_md5):
        """Test _cleanup_document_cache_keys method"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        
        # Mock the path hashing and quoting
        mock_quote.return_value = 'safe_path'
        mock_md5_instance = MagicMock()
        mock_md5_instance.hexdigest.return_value = 'path_hash'
        mock_md5.return_value = mock_md5_instance
        
        # Configure mock responses for each pattern
        pattern_keys = {
            '*test_index*safe_path*': [b'key1'],
            '*test_index*path_hash*': [b'key2', b'key3'],
            'kb:test_index:doc:safe_path*': [b'key4'],
            'kb:test_index:doc:path_hash*': [b'key5'],
            'doc:safe_path:*': [b'key6', b'key7'],
            'doc:path_hash:*': [b'key8']
        }
        
        def mock_keys_side_effect(pattern):
            return pattern_keys.get(pattern, [])
        
        self.mock_redis_client.keys.side_effect = mock_keys_side_effect
        self.mock_redis_client.delete.return_value = 1  # Each delete operation deletes 1 key
        
        # Execute
        result = self.redis_service._cleanup_document_cache_keys("test_index", "path/to/doc.pdf")
        
        # Verify
        self.assertEqual(self.mock_redis_client.keys.call_count, 6)
        
        # Return value should be the number of deleted keys
        self.assertEqual(result, 6)  # 6 successful delete operations
    
    def test_get_knowledgebase_task_count(self):
        """Test get_knowledgebase_task_count method"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Create mock task data
        task_keys = [b'celery-task-meta-1', b'celery-task-meta-2']
        
        # Task 1 matches our index
        task1_data = json.dumps({
            'result': {'index_name': 'test_index'}
        }).encode()
        
        # Task 2 is for a different index
        task2_data = json.dumps({
            'result': {'index_name': 'other_index'}
        }).encode()
        
        # Configure mock responses for Celery tasks
        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [task1_data, task2_data]
        
        # Configure mock responses for cache keys
        cache_keys = {
            '*test_index*': [b'key1', b'key2'],
            'kb:test_index:*': [b'key3', b'key4'],
            'index:test_index:*': [b'key5']
        }
        
        def mock_keys_side_effect(pattern):
            return cache_keys.get(pattern, [])
        
        self.mock_redis_client.keys.side_effect = mock_keys_side_effect
        
        # Execute
        result = self.redis_service.get_knowledgebase_task_count("test_index")
        
        # Verify
        self.mock_backend_client.keys.assert_called_once_with('celery-task-meta-*')
        self.assertEqual(self.mock_backend_client.get.call_count, 2)
        
        # Should count 1 matching task and 5 cache keys
        self.assertEqual(result, 6)
    
    def test_ping_success(self):
        """Test ping method when connection is successful"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        self.mock_redis_client.ping.return_value = True
        self.mock_backend_client.ping.return_value = True
        
        # Execute
        result = self.redis_service.ping()
        
        # Verify
        self.mock_redis_client.ping.assert_called_once()
        self.mock_backend_client.ping.assert_called_once()
        self.assertTrue(result)
    
    def test_ping_failure(self):
        """Test ping method when connection fails"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        self.mock_redis_client.ping.side_effect = redis.RedisError("Connection failed")
        
        # Execute
        result = self.redis_service.ping()
        
        # Verify
        self.mock_redis_client.ping.assert_called_once()
        self.mock_backend_client.ping.assert_not_called()  # Should not be called after first ping fails
        self.assertFalse(result)
    
    @patch('backend.services.redis_service._redis_service', None)
    @patch('backend.services.redis_service.RedisService')
    def test_get_redis_service(self, mock_redis_service_class):
        """Test get_redis_service function creates and returns singleton instance"""
        # Setup
        mock_instance = MagicMock()
        mock_redis_service_class.return_value = mock_instance
        
        # Execute
        service1 = get_redis_service()
        service2 = get_redis_service()
        
        # Verify
        mock_redis_service_class.assert_called_once()  # Only created once
        self.assertEqual(service1, mock_instance)
        self.assertEqual(service2, mock_instance)  # Should return same instance


if __name__ == '__main__':
    unittest.main()
