import unittest
from unittest.mock import patch, MagicMock, call
import json
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
    @patch('backend.services.redis_service.REDIS_URL', 'redis://localhost:6379/0')
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
            socket_connect_timeout=5,
            decode_responses=True
        )
        self.assertEqual(client, self.mock_redis_client)
        
        # Second call should reuse existing client
        self.redis_service.client
        mock_from_url.assert_called_once()  # Still only called once
    
    @patch('redis.from_url')
    @patch('backend.services.redis_service.REDIS_URL', None)
    def test_client_property_no_env_var(self, mock_from_url):
        """Test client property raises error when REDIS_URL is not set"""
        # Setup
        self.env_patcher.stop()
        with patch.dict('os.environ', {}, clear=True):
            # Create a fresh instance to ensure it uses the new environment
            from backend.services.redis_service import RedisService
            redis_service = RedisService()
            
            # Execute & Verify
            with self.assertRaises(ValueError):
                _ = redis_service.client
    
    @patch('redis.from_url')
    @patch('backend.services.redis_service.REDIS_BACKEND_URL', 'redis://localhost:6379/1')
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
    @patch('backend.services.redis_service.REDIS_BACKEND_URL', None)
    @patch('backend.services.redis_service.REDIS_URL', 'redis://localhost:6379/0')
    def test_backend_client_fallback(self, mock_from_url):
        """Test backend_client falls back to REDIS_URL when REDIS_BACKEND_URL is not set"""
        # Setup
        mock_from_url.return_value = self.mock_backend_client
        self.env_patcher.stop()
        with patch.dict('os.environ', {'REDIS_URL': 'redis://localhost:6379/0'}):
            # Create a fresh instance to ensure it uses the new environment
            from backend.services.redis_service import RedisService
            redis_service = RedisService()
            
            # Execute
            client = redis_service.backend_client
            
            # Verify
            mock_from_url.assert_called_once_with(
                'redis://localhost:6379/0', 
                socket_timeout=5, 
                socket_connect_timeout=5
            )
            self.assertEqual(client, self.mock_backend_client)
    
    @patch('redis.from_url')
    @patch('backend.services.redis_service.REDIS_BACKEND_URL', None)
    @patch('backend.services.redis_service.REDIS_URL', None)
    def test_backend_client_no_env_vars(self, mock_from_url):
        """Test backend_client raises error when no Redis URLs are set"""
        # Setup
        self.env_patcher.stop()
        with patch.dict('os.environ', {}, clear=True):
            # Create a fresh instance to ensure it uses the new environment
            from backend.services.redis_service import RedisService
            redis_service = RedisService()
            
            # Execute & Verify
            with self.assertRaises(ValueError):
                _ = redis_service.backend_client

    @patch('redis.from_url')
    @patch('backend.services.redis_service.REDIS_URL', 'redis://localhost:6379/0')
    def test_mark_and_check_task_cancelled(self, mock_from_url):
        """mark_task_cancelled should set flag and is_task_cancelled should read it."""
        mock_client = MagicMock()
        mock_client.setex.return_value = True
        mock_client.get.return_value = b"1"
        mock_from_url.return_value = mock_client

        service = RedisService()
        ok = service.mark_task_cancelled("task-1", ttl_hours=1)
        self.assertTrue(ok)
        self.assertTrue(service.is_task_cancelled("task-1"))
        mock_client.setex.assert_called_once()
        mock_client.get.assert_called_once()

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
    
    def test_cleanup_single_task_related_keys_outer_exception(self):
        """Outer handler logs when warning path itself fails."""
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        self.mock_redis_client.delete.side_effect = redis.RedisError(
            "delete failed")

        with patch('backend.services.redis_service.logger.warning', side_effect=Exception("warn boom")), \
                patch('backend.services.redis_service.logger.error') as mock_error:
            result = self.redis_service._cleanup_single_task_related_keys(
                "task123")

        mock_error.assert_called_once()
        self.assertEqual(result, 0)

    def test_cleanup_celery_tasks(self):
        """Test _cleanup_celery_tasks method"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        # Create mock task data
        task_keys = [b'celery-task-meta-1',
                     b'celery-task-meta-2', b'celery-task-meta-3']

        # Task 1 matches our index
        task1_data = json.dumps({
            'result': {'index_name': 'test_index', 'some_key': 'some_value'},
            'parent_id': '2'  # This will trigger a parent lookup
        }).encode()

        # Task 2 has index name in a different location
        task2_data = json.dumps({
            'index_name': 'test_index',
            'result': {'some_key': 'some_value'},
            'parent_id': None  # No parent
        }).encode()

        # Task 3 is for a different index
        task3_data = json.dumps({
            'result': {'index_name': 'other_index', 'some_key': 'some_value'}
        }).encode()

        # Configure mock responses
        self.mock_backend_client.keys.return_value = task_keys
        # Two passes over keys: provide payloads for both passes (6 gets)
        self.mock_backend_client.get.side_effect = [
            task1_data, task2_data, task3_data,
            task1_data, task2_data, task3_data,
        ]

        # We expect delete to be called and return 1 each time
        self.mock_backend_client.delete.return_value = 1

        # Execute
        with patch.object(self.redis_service, '_recursively_delete_task_and_parents') as mock_recursive_delete:
            mock_recursive_delete.side_effect = [(1, {'1'}), (1, {'2'})]
            result = self.redis_service._cleanup_celery_tasks("test_index")

        # Verify
        self.mock_backend_client.keys.assert_called_once_with(
            'celery-task-meta-*')
        # Implementation fetches task payloads in both passes; expect 6 total (3 keys * 2 passes)
        self.assertEqual(self.mock_backend_client.get.call_count, 6)

        # Should have called recursive delete for matched tasks
        self.assertGreaterEqual(mock_recursive_delete.call_count, 2)

        # Return value should match deleted tasks count
        self.assertEqual(result, mock_recursive_delete.call_count)

    def test_cleanup_celery_tasks_get_exception_and_cancel_failure(self):
        """First-pass get failure and cancel failure are both handled."""
        self.redis_service._backend_client = self.mock_backend_client
        self.redis_service._client = self.mock_redis_client

        task_keys = [b'celery-task-meta-err', b'celery-task-meta-2']
        valid_task = json.dumps({
            'result': {'index_name': 'test_index'},
            'parent_id': None
        }).encode()

        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [
            redis.RedisError("boom"),
            valid_task,
            redis.RedisError("boom-second"),
            valid_task,
        ]

        with patch.object(self.redis_service, 'mark_task_cancelled', side_effect=ValueError("cancel fail")) as mock_cancel, \
                patch.object(self.redis_service, '_recursively_delete_task_and_parents', return_value=(1, {'2'})) as mock_delete, \
                patch.object(self.redis_service, '_cleanup_single_task_related_keys') as mock_cleanup:

            result = self.redis_service._cleanup_celery_tasks("test_index")

        mock_cancel.assert_called_once_with('2')
        mock_delete.assert_called_once_with('2')
        mock_cleanup.assert_called_once_with('2')
        self.assertEqual(result, 1)

    def test_cleanup_celery_tasks_exc_message_bad_json(self):
        """JSON decode failure inside exc_message parsing does not crash."""
        self.redis_service._backend_client = self.mock_backend_client
        self.redis_service._client = self.mock_redis_client

        task_keys = [b'celery-task-meta-1']
        bad_json_payload = json.dumps({
            'result': {
                # Contains brace to enter parsing block
                'exc_message': '{bad json'
            }
        }).encode()

        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [
            bad_json_payload, bad_json_payload]

        with patch.object(self.redis_service, '_recursively_delete_task_and_parents', return_value=(0, set())) as mock_delete:
            result = self.redis_service._cleanup_celery_tasks("test_index")

        # Bad JSON should be tolerated; no deletions occur
        mock_delete.assert_not_called()
        self.assertEqual(result, 0)

    def test_cleanup_celery_tasks_cleanup_single_task_error(self):
        """Failures during related-key cleanup are logged and skipped."""
        self.redis_service._backend_client = self.mock_backend_client
        self.redis_service._client = self.mock_redis_client

        task_keys = [b'celery-task-meta-1']
        task_payload = json.dumps({
            'result': {'index_name': 'test_index'}
        }).encode()

        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [task_payload, task_payload]

        with patch.object(self.redis_service, '_recursively_delete_task_and_parents', return_value=(1, {'1'})), \
                patch.object(self.redis_service, '_cleanup_single_task_related_keys', side_effect=Exception("cleanup boom")) as mock_cleanup:
            result = self.redis_service._cleanup_celery_tasks("test_index")

        mock_cleanup.assert_called_once_with('1')
        self.assertEqual(result, 1)

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
        # Each delete operation deletes 1 key
        self.mock_redis_client.delete.return_value = 1

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
        self.mock_redis_client.delete.assert_has_calls(
            expected_calls, any_order=True)

        # Return value should be the number of deleted keys
        self.assertEqual(result, 4)  # 4 successful delete operations

    def test_cleanup_document_celery_tasks(self):
        """Test _cleanup_document_celery_tasks method"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        # Create mock task data
        task_keys = [b'celery-task-meta-1',
                     b'celery-task-meta-2', b'celery-task-meta-3']

        # Task 1 matches our index and document
        task1_data = json.dumps({
            'result': {
                'index_name': 'test_index',
                'source': 'path/to/doc.pdf'
            },
            'parent_id': '2'  # This will trigger a parent lookup
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
            },
            'parent_id': None  # No parent
        }).encode()

        # Configure mock responses
        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [
            task1_data, task2_data, task3_data]

        # We expect delete to be called and return 1 each time
        self.mock_backend_client.delete.return_value = 1

        # Execute
        with patch.object(self.redis_service, '_recursively_delete_task_and_parents') as mock_recursive_delete:
            mock_recursive_delete.side_effect = [(1, {'1'}), (1, {'3'})]
            result = self.redis_service._cleanup_document_celery_tasks(
                "test_index", "path/to/doc.pdf")

        # Verify
        self.mock_backend_client.keys.assert_called_once_with(
            'celery-task-meta-*')
        # We expect 3 calls - one for each task key
        self.assertEqual(self.mock_backend_client.get.call_count, 3)

        # Should have called recursive delete twice (for task1 and task3)
        self.assertEqual(mock_recursive_delete.call_count, 2)

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
        # Each delete operation deletes 1 key
        self.mock_redis_client.delete.return_value = 1

        # Execute
        result = self.redis_service._cleanup_document_cache_keys(
            "test_index", "path/to/doc.pdf")

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
        self.mock_backend_client.keys.assert_called_once_with(
            'celery-task-meta-*')
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

        self.mock_redis_client.ping.side_effect = redis.RedisError(
            "Connection failed")

        # Execute
        result = self.redis_service.ping()

        # Verify
        self.mock_redis_client.ping.assert_called_once()
        # Should not be called after first ping fails
        self.mock_backend_client.ping.assert_not_called()
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
        # Should return same instance
        self.assertEqual(service2, mock_instance)

    def test_recursively_delete_task_and_parents_no_parent(self):
        """Test _recursively_delete_task_and_parents with task that has no parent"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        task_data = json.dumps({
            'result': {'some_data': 'value'},
            'parent_id': None
        }).encode()

        self.mock_backend_client.get.return_value = task_data
        self.mock_backend_client.delete.return_value = 1

        # Execute
        deleted_count, processed_ids = self.redis_service._recursively_delete_task_and_parents(
            "task123")

        # Verify
        self.assertEqual(deleted_count, 1)
        self.assertEqual(processed_ids, {"task123"})
        self.mock_backend_client.get.assert_called_once_with(
            'celery-task-meta-task123')
        self.mock_backend_client.delete.assert_called_once_with(
            'celery-task-meta-task123')

    def test_recursively_delete_task_and_parents_with_cycle_detection(self):
        """Test _recursively_delete_task_and_parents detects and breaks cycles"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        # Create a cycle: task1 -> task2 -> task1
        task1_data = json.dumps({'parent_id': 'task2'}).encode()
        task2_data = json.dumps({'parent_id': 'task1'}).encode()

        self.mock_backend_client.get.side_effect = [task1_data, task2_data]
        self.mock_backend_client.delete.return_value = 1

        # Execute
        deleted_count, processed_ids = self.redis_service._recursively_delete_task_and_parents(
            "task1")

        # Verify - should stop when cycle is detected
        self.assertEqual(deleted_count, 2)
        self.assertEqual(processed_ids, {"task1", "task2"})
        self.assertEqual(self.mock_backend_client.delete.call_count, 2)

    def test_recursively_delete_task_and_parents_json_decode_error(self):
        """Test _recursively_delete_task_and_parents handles JSON decode errors"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        # Invalid JSON data
        invalid_json_data = b'invalid json data'

        self.mock_backend_client.get.return_value = invalid_json_data
        self.mock_backend_client.delete.return_value = 1

        # Execute
        deleted_count, processed_ids = self.redis_service._recursively_delete_task_and_parents(
            "task123")

        # Verify - should still delete the task even if JSON parsing fails
        self.assertEqual(deleted_count, 1)
        self.assertEqual(processed_ids, {"task123"})
        self.mock_backend_client.delete.assert_called_once_with(
            'celery-task-meta-task123')

    def test_recursively_delete_task_and_parents_redis_error(self):
        """Test _recursively_delete_task_and_parents handles Redis errors"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        # Simulate Redis error
        self.mock_backend_client.get.side_effect = redis.RedisError(
            "Connection lost")

        # Execute
        deleted_count, processed_ids = self.redis_service._recursively_delete_task_and_parents(
            "task123")

        # Verify - should return 0 when Redis error occurs
        self.assertEqual(deleted_count, 0)
        self.assertEqual(processed_ids, {"task123"})

    def test_cleanup_celery_tasks_with_failed_task_metadata(self):
        """Test _cleanup_celery_tasks handles failed tasks with exception metadata"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        task_keys = [b'celery-task-meta-1']

        # Task with exception metadata containing index name
        task_data = json.dumps({
            'result': {
                'exc_message': 'Error processing task: {"index_name": "test_index", "error": "failed"}'
            }
        }).encode()

        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.return_value = task_data

        # Execute
        with patch.object(self.redis_service, '_recursively_delete_task_and_parents') as mock_recursive_delete:
            mock_recursive_delete.return_value = (1, {'1'})
            result = self.redis_service._cleanup_celery_tasks("test_index")

        # Verify
        self.assertEqual(result, 1)
        mock_recursive_delete.assert_called_once_with('1')

    def test_cleanup_celery_tasks_invalid_exception_metadata(self):
        """Test _cleanup_celery_tasks handles invalid exception metadata gracefully"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client

        task_keys = [b'celery-task-meta-1']

        # Task with invalid exception metadata
        task_data = json.dumps({
            'result': {
                'exc_message': 'Invalid JSON metadata'
            }
        }).encode()

        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.return_value = task_data

        # Execute
        result = self.redis_service._cleanup_celery_tasks("test_index")

        # Verify - should not crash and return 0
        self.assertEqual(result, 0)

    def test_cleanup_cache_keys_partial_failure(self):
        """Test _cleanup_cache_keys handles partial failures gracefully"""
        # Setup
        self.redis_service._client = self.mock_redis_client

        # First pattern succeeds, second fails, third succeeds
        def mock_keys_side_effect(pattern):
            if pattern == 'kb:test_index:*':
                raise redis.RedisError("Connection error")
            elif pattern == '*test_index*':
                return [b'key1', b'key2']
            elif pattern == 'index:test_index:*':
                return [b'key3']
            else:
                return []

        self.mock_redis_client.keys.side_effect = mock_keys_side_effect
        self.mock_redis_client.delete.return_value = 1

        # Execute
        result = self.redis_service._cleanup_cache_keys("test_index")

        # Verify - should continue processing despite one pattern failing
        self.assertEqual(result, 2)  # 2 successful delete operations

    def test_cleanup_cache_keys_all_patterns_fail(self):
        """Test _cleanup_cache_keys handles errors gracefully when all patterns fail"""
        # Setup
        self.redis_service._client = self.mock_redis_client

        # Simulate an error for all pattern calls
        # Each call to keys() will fail but be caught by inner try-catch
        self.mock_redis_client.keys.side_effect = redis.RedisError(
            "Redis connection failed")

        # Execute - should not raise exception but return 0
        result = self.redis_service._cleanup_cache_keys("test_index")

        # Verify - should handle gracefully and return 0
        self.assertEqual(result, 0)
        # Should have tried all 4 patterns
        self.assertEqual(self.mock_redis_client.keys.call_count, 4)

    def test_cleanup_document_celery_tasks_cancel_fail_and_processing_error(self):
        """Document cleanup logs processing errors and cancel failures."""
        self.redis_service._backend_client = self.mock_backend_client
        self.redis_service._client = self.mock_redis_client

        task_keys = [b'celery-task-meta-err', b'celery-task-meta-1']
        good_payload = json.dumps({
            'result': {
                'index_name': 'kb1',
                'path_or_url': 'doc1'
            }
        }).encode()

        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.side_effect = [
            redis.RedisError("get boom"),
            good_payload
        ]

        with patch.object(self.redis_service, 'mark_task_cancelled', side_effect=ValueError("cancel fail")) as mock_cancel, \
                patch.object(self.redis_service, '_recursively_delete_task_and_parents', return_value=(1, {'1'})) as mock_delete, \
                patch.object(self.redis_service, '_cleanup_single_task_related_keys') as mock_cleanup:

            result = self.redis_service._cleanup_document_celery_tasks(
                "kb1", "doc1")

        mock_cancel.assert_called_once_with('1')
        mock_delete.assert_called_once_with('1')
        mock_cleanup.assert_called_once_with('1')
        self.assertEqual(result, 1)


    def test_cleanup_document_cache_keys_empty_patterns(self):
        """Test _cleanup_document_cache_keys handles empty key patterns"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        
        # All patterns return empty results
        self.mock_redis_client.keys.return_value = []
        
        # Execute
        result = self.redis_service._cleanup_document_cache_keys("test_index", "path/to/doc.pdf")
        
        # Verify
        self.assertEqual(result, 0)
        self.assertEqual(self.mock_redis_client.keys.call_count, 6)  # All 6 patterns checked
        self.mock_redis_client.delete.assert_not_called()
    
    def test_get_knowledgebase_task_count_with_backend_errors(self):
        """Test get_knowledgebase_task_count handles backend errors gracefully"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Setup backend client to fail - this will be caught by outer try block
        self.mock_backend_client.keys.side_effect = redis.RedisError("Backend connection failed")
        
        # Setup regular client to succeed (but it won't be reached due to outer exception)
        self.mock_redis_client.keys.return_value = [b'key1', b'key2', b'key3']
        
        # Execute
        result = self.redis_service.get_knowledgebase_task_count("test_index")
        
        # Verify - when backend_client.keys() fails, the outer try catches it
        # and the method returns 0 without processing cache keys
        self.assertEqual(result, 0)
        
        # Verify that backend keys was called and failed
        self.mock_backend_client.keys.assert_called_once_with('celery-task-meta-*')
        # Verify that regular client keys was NOT called due to the exception
        self.mock_redis_client.keys.assert_not_called()
    
    def test_get_knowledgebase_task_count_complete_failure(self):
        """Test get_knowledgebase_task_count handles complete Redis failure"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Both clients fail
        self.mock_backend_client.keys.side_effect = redis.RedisError("Backend failed")
        self.mock_redis_client.keys.side_effect = redis.RedisError("Cache failed")
        
        # Execute
        result = self.redis_service.get_knowledgebase_task_count("test_index")
        
        # Verify - should return 0 and not crash
        self.assertEqual(result, 0)
    
    def test_ping_backend_client_failure(self):
        """Test ping method when backend client fails but main client succeeds"""
        # Setup
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        self.mock_redis_client.ping.return_value = True
        self.mock_backend_client.ping.side_effect = redis.RedisError("Backend connection failed")
        
        # Execute
        result = self.redis_service.ping()
        
        # Verify
        self.mock_redis_client.ping.assert_called_once()
        self.mock_backend_client.ping.assert_called_once()
        self.assertFalse(result)  # Should return False if any client fails
    
    def test_init_method(self):
        """Test RedisService initialization"""
        # Execute
        service = RedisService()
        
        # Verify
        self.assertIsNone(service._client)
        self.assertIsNone(service._backend_client)
    
    def test_cleanup_celery_tasks_non_dict_result(self):
        """Test _cleanup_celery_tasks handles non-dict result values"""
        # Setup
        self.redis_service._backend_client = self.mock_backend_client
        
        task_keys = [b'celery-task-meta-1']
        
        # Task with non-dict result
        task_data = json.dumps({
            'result': "string result instead of dict"
        }).encode()
        
        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.return_value = task_data
        
        # Execute
        result = self.redis_service._cleanup_celery_tasks("test_index")
        
        # Verify - should handle gracefully and return 0
        self.assertEqual(result, 0)

    def test_cleanup_cache_keys_all_failures(self):
        """Test _cleanup_cache_keys returns 0 when all patterns fail"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.keys.side_effect = redis.RedisError("Redis connection failed")

        result = self.redis_service._cleanup_cache_keys("test_index")
        self.assertEqual(result, 0)
        self.assertEqual(self.mock_redis_client.keys.call_count, 4)

    def test_ping_backend_failure(self):
        """Test ping returns False if backend client fails but main client succeeds"""
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client

        self.mock_redis_client.ping.return_value = True
        self.mock_backend_client.ping.side_effect = redis.RedisError("Backend connection failed")

        result = self.redis_service.ping()
        self.assertFalse(result)
        self.mock_redis_client.ping.assert_called_once()
        self.mock_backend_client.ping.assert_called_once()

    # ------------------------------------------------------------------
    # Test mark_task_cancelled edge cases
    # ------------------------------------------------------------------

    def test_mark_task_cancelled_empty_task_id(self):
        """Test mark_task_cancelled returns False when task_id is empty"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.mark_task_cancelled("")
        self.assertFalse(result)
        self.mock_redis_client.setex.assert_not_called()

    def test_mark_task_cancelled_redis_error(self):
        """Test mark_task_cancelled handles Redis errors gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.side_effect = redis.RedisError("Connection failed")
        
        result = self.redis_service.mark_task_cancelled("task-123")
        self.assertFalse(result)
        self.mock_redis_client.setex.assert_called_once()

    def test_mark_task_cancelled_custom_ttl(self):
        """Test mark_task_cancelled with custom TTL hours"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.return_value = True
        
        result = self.redis_service.mark_task_cancelled("task-123", ttl_hours=48)
        self.assertTrue(result)
        # Verify TTL is calculated correctly (48 hours = 172800 seconds)
        call_args = self.mock_redis_client.setex.call_args
        self.assertEqual(call_args[0][1], 48 * 3600)  # TTL in seconds

    # ------------------------------------------------------------------
    # Test is_task_cancelled edge cases
    # ------------------------------------------------------------------

    def test_is_task_cancelled_empty_task_id(self):
        """Test is_task_cancelled returns False when task_id is empty"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.is_task_cancelled("")
        self.assertFalse(result)
        self.mock_redis_client.get.assert_not_called()

    def test_is_task_cancelled_none_value(self):
        """Test is_task_cancelled returns False when key doesn't exist"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.return_value = None
        
        result = self.redis_service.is_task_cancelled("task-123")
        self.assertFalse(result)

    def test_is_task_cancelled_empty_string_value(self):
        """Test is_task_cancelled returns False when value is empty string"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.return_value = ""
        
        result = self.redis_service.is_task_cancelled("task-123")
        self.assertFalse(result)

    def test_is_task_cancelled_redis_error(self):
        """Test is_task_cancelled handles Redis errors gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.side_effect = redis.RedisError("Connection failed")
        
        result = self.redis_service.is_task_cancelled("task-123")
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # Test _cleanup_single_task_related_keys
    # ------------------------------------------------------------------

    def test_cleanup_single_task_related_keys_success(self):
        """Test _cleanup_single_task_related_keys deletes all related keys"""
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # Mock successful deletions
        self.mock_redis_client.delete.side_effect = [1, 1, 1]  # progress, error, cancel
        self.mock_backend_client.delete.return_value = 1  # chunk cache
        
        result = self.redis_service._cleanup_single_task_related_keys("task-123")
        
        # Should delete 4 keys total
        self.assertEqual(result, 4)
        # Verify all keys were attempted
        self.assertEqual(self.mock_redis_client.delete.call_count, 3)
        self.mock_backend_client.delete.assert_called_once_with("dp:task-123:chunks")

    def test_cleanup_single_task_related_keys_empty_task_id(self):
        """Test _cleanup_single_task_related_keys returns 0 for empty task_id"""
        result = self.redis_service._cleanup_single_task_related_keys("")
        self.assertEqual(result, 0)

    def test_cleanup_single_task_related_keys_partial_failure(self):
        """Test _cleanup_single_task_related_keys handles partial failures"""
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # First key succeeds, second fails, third succeeds, chunk cache fails
        self.mock_redis_client.delete.side_effect = [1, redis.RedisError("Error"), 1]
        self.mock_backend_client.delete.side_effect = redis.RedisError("Backend error")
        
        result = self.redis_service._cleanup_single_task_related_keys("task-123")
        
        # Should return count of successful deletions (2)
        self.assertEqual(result, 2)

    def test_cleanup_single_task_related_keys_all_fail(self):
        """Test _cleanup_single_task_related_keys handles all failures gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        self.mock_redis_client.delete.side_effect = redis.RedisError("All failed")
        self.mock_backend_client.delete.side_effect = redis.RedisError("Backend failed")
        
        result = self.redis_service._cleanup_single_task_related_keys("task-123")
        
        # Should return 0 but not raise exception
        self.assertEqual(result, 0)

    def test_cleanup_single_task_related_keys_no_keys_exist(self):
        """Test _cleanup_single_task_related_keys when keys don't exist"""
        self.redis_service._client = self.mock_redis_client
        self.redis_service._backend_client = self.mock_backend_client
        
        # All deletions return 0 (key doesn't exist)
        self.mock_redis_client.delete.side_effect = [0, 0, 0]
        self.mock_backend_client.delete.return_value = 0
        
        result = self.redis_service._cleanup_single_task_related_keys("task-123")
        
        # Should return 0
        self.assertEqual(result, 0)

    # ------------------------------------------------------------------
    # Test save_error_info
    # ------------------------------------------------------------------

    def test_save_error_info_success(self):
        """Test save_error_info successfully saves error information"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.return_value = True
        self.mock_redis_client.get.return_value = "Test error reason"
        
        result = self.redis_service.save_error_info("task-123", "Test error reason")
        
        self.assertTrue(result)
        self.mock_redis_client.setex.assert_called_once()
        # Verify TTL is 30 days in seconds
        call_args = self.mock_redis_client.setex.call_args
        self.assertEqual(call_args[0][1], 30 * 24 * 60 * 60)
        self.assertEqual(call_args[0][2], "Test error reason")
        # Verify get was called to verify the save
        self.mock_redis_client.get.assert_called_once()

    def test_save_error_info_empty_task_id(self):
        """Test save_error_info returns False when task_id is empty"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.save_error_info("", "Error reason")
        self.assertFalse(result)
        self.mock_redis_client.setex.assert_not_called()

    def test_save_error_info_empty_error_reason(self):
        """Test save_error_info returns False when error_reason is empty"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.save_error_info("task-123", "")
        self.assertFalse(result)
        self.mock_redis_client.setex.assert_not_called()

    def test_save_error_info_custom_ttl(self):
        """Test save_error_info with custom TTL days"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.return_value = True
        self.mock_redis_client.get.return_value = "Error"
        
        result = self.redis_service.save_error_info("task-123", "Error", ttl_days=7)
        
        self.assertTrue(result)
        call_args = self.mock_redis_client.setex.call_args
        # Verify TTL is 7 days in seconds
        self.assertEqual(call_args[0][1], 7 * 24 * 60 * 60)

    def test_save_error_info_setex_returns_false(self):
        """Test save_error_info handles setex returning False"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.return_value = False
        
        result = self.redis_service.save_error_info("task-123", "Error")
        self.assertFalse(result)

    def test_save_error_info_verification_fails(self):
        """Test save_error_info when verification get returns None"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.return_value = True
        self.mock_redis_client.get.return_value = None  # Verification fails
        
        result = self.redis_service.save_error_info("task-123", "Error")
        # Should still return True because setex succeeded
        self.assertTrue(result)

    def test_save_error_info_redis_error(self):
        """Test save_error_info handles Redis errors gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.side_effect = redis.RedisError("Connection failed")
        
        result = self.redis_service.save_error_info("task-123", "Error")
        self.assertFalse(result)

    def test_save_error_info_verification_redis_error(self):
        """Test save_error_info returns False when verification raises Redis error"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.return_value = True
        self.mock_redis_client.get.side_effect = redis.RedisError("Connection failed")
        
        # Should return False because verification failed with exception
        result = self.redis_service.save_error_info("task-123", "Error")
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # Test save_progress_info
    # ------------------------------------------------------------------

    def test_save_progress_info_success(self):
        """Test save_progress_info successfully saves progress"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.save_progress_info("task-123", 50, 100)
        
        self.assertTrue(result)
        self.mock_redis_client.setex.assert_called_once()
        call_args = self.mock_redis_client.setex.call_args
        # Verify TTL is 24 hours in seconds
        self.assertEqual(call_args[0][1], 24 * 3600)
        # Verify JSON data
        progress_data = json.loads(call_args[0][2])
        self.assertEqual(progress_data['processed_chunks'], 50)
        self.assertEqual(progress_data['total_chunks'], 100)

    def test_save_progress_info_empty_task_id(self):
        """Test save_progress_info returns False when task_id is empty"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.save_progress_info("", 50, 100)
        self.assertFalse(result)
        self.mock_redis_client.setex.assert_not_called()

    def test_save_progress_info_custom_ttl(self):
        """Test save_progress_info with custom TTL hours"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.save_progress_info("task-123", 25, 50, ttl_hours=48)
        
        self.assertTrue(result)
        call_args = self.mock_redis_client.setex.call_args
        # Verify TTL is 48 hours in seconds
        self.assertEqual(call_args[0][1], 48 * 3600)

    def test_save_progress_info_zero_progress(self):
        """Test save_progress_info with zero progress"""
        self.redis_service._client = self.mock_redis_client
        
        result = self.redis_service.save_progress_info("task-123", 0, 100)
        
        self.assertTrue(result)
        call_args = self.mock_redis_client.setex.call_args
        progress_data = json.loads(call_args[0][2])
        self.assertEqual(progress_data['processed_chunks'], 0)
        self.assertEqual(progress_data['total_chunks'], 100)

    def test_save_progress_info_redis_error(self):
        """Test save_progress_info handles Redis errors gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.setex.side_effect = redis.RedisError("Connection failed")
        
        result = self.redis_service.save_progress_info("task-123", 50, 100)
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # Test get_progress_info
    # ------------------------------------------------------------------

    def test_get_progress_info_success(self):
        """Test get_progress_info successfully retrieves progress"""
        self.redis_service._client = self.mock_redis_client
        progress_json = json.dumps({'processed_chunks': 50, 'total_chunks': 100})
        self.mock_redis_client.get.return_value = progress_json
        
        result = self.redis_service.get_progress_info("task-123")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['processed_chunks'], 50)
        self.assertEqual(result['total_chunks'], 100)

    def test_get_progress_info_not_found(self):
        """Test get_progress_info returns None when key doesn't exist"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.return_value = None
        
        result = self.redis_service.get_progress_info("task-123")
        self.assertIsNone(result)

    def test_get_progress_info_bytes_response(self):
        """Test get_progress_info handles bytes response (when decode_responses=False)"""
        self.redis_service._client = self.mock_redis_client
        progress_json = json.dumps({'processed_chunks': 75, 'total_chunks': 150})
        self.mock_redis_client.get.return_value = progress_json.encode('utf-8')
        
        result = self.redis_service.get_progress_info("task-123")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['processed_chunks'], 75)
        self.assertEqual(result['total_chunks'], 150)

    def test_get_progress_info_invalid_json(self):
        """Test get_progress_info handles invalid JSON gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.return_value = "invalid json"
        
        result = self.redis_service.get_progress_info("task-123")
        self.assertIsNone(result)

    def test_get_progress_info_redis_error(self):
        """Test get_progress_info handles Redis errors gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.side_effect = redis.RedisError("Connection failed")
        
        result = self.redis_service.get_progress_info("task-123")
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Test get_error_info
    # ------------------------------------------------------------------

    def test_get_error_info_success(self):
        """Test get_error_info successfully retrieves error reason"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.return_value = "Test error reason"
        
        result = self.redis_service.get_error_info("task-123")
        
        self.assertEqual(result, "Test error reason")
        self.mock_redis_client.get.assert_called_once_with("error:reason:task-123")

    def test_get_error_info_not_found(self):
        """Test get_error_info returns None when key doesn't exist"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.return_value = None
        
        result = self.redis_service.get_error_info("task-123")
        self.assertIsNone(result)

    def test_get_error_info_empty_string(self):
        """Test get_error_info returns None when value is empty string"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.return_value = ""
        
        result = self.redis_service.get_error_info("task-123")
        self.assertIsNone(result)

    def test_get_error_info_redis_error(self):
        """Test get_error_info handles Redis errors gracefully"""
        self.redis_service._client = self.mock_redis_client
        self.mock_redis_client.get.side_effect = redis.RedisError("Connection failed")
        
        result = self.redis_service.get_error_info("task-123")
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Test _cleanup_celery_tasks edge cases
    # ------------------------------------------------------------------

    def test_cleanup_celery_tasks_mark_cancelled_failure(self):
        """Test _cleanup_celery_tasks handles mark_task_cancelled failures"""
        self.redis_service._backend_client = self.mock_backend_client
        self.redis_service._client = self.mock_redis_client
        
        task_keys = [b'celery-task-meta-1']
        task_data = json.dumps({
            'result': {'index_name': 'test_index'},
            'parent_id': None
        }).encode()
        
        self.mock_backend_client.keys.return_value = task_keys
        # Provide data for both passes
        self.mock_backend_client.get.side_effect = [task_data, task_data]
        self.mock_backend_client.delete.return_value = 1
        
        # Mock mark_task_cancelled to fail
        with patch.object(self.redis_service, 'mark_task_cancelled', return_value=False):
            with patch.object(self.redis_service, '_recursively_delete_task_and_parents', return_value=(1, {'1'})):
                with patch.object(self.redis_service, '_cleanup_single_task_related_keys', return_value=0):
                    result = self.redis_service._cleanup_celery_tasks("test_index")
        
        # Should still proceed with deletion despite cancellation failure
        self.assertEqual(result, 1)

    def test_cleanup_celery_tasks_no_matching_tasks(self):
        """Test _cleanup_celery_tasks when no tasks match the index"""
        self.redis_service._backend_client = self.mock_backend_client
        
        task_keys = [b'celery-task-meta-1']
        task_data = json.dumps({
            'result': {'index_name': 'other_index'}
        }).encode()
        
        self.mock_backend_client.keys.return_value = task_keys
        # Provide data for both passes
        self.mock_backend_client.get.side_effect = [task_data, task_data]
        
        result = self.redis_service._cleanup_celery_tasks("test_index")
        
        self.assertEqual(result, 0)

    # ------------------------------------------------------------------
    # Test _cleanup_document_celery_tasks edge cases
    # ------------------------------------------------------------------

    def test_cleanup_document_celery_tasks_no_matching_document(self):
        """Test _cleanup_document_celery_tasks when no tasks match document"""
        self.redis_service._backend_client = self.mock_backend_client
        
        task_keys = [b'celery-task-meta-1']
        task_data = json.dumps({
            'result': {
                'index_name': 'test_index',
                'source': 'other/doc.pdf'
            }
        }).encode()
        
        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.return_value = task_data
        
        result = self.redis_service._cleanup_document_celery_tasks("test_index", "path/to/doc.pdf")
        
        self.assertEqual(result, 0)

    def test_cleanup_document_celery_tasks_mark_cancelled_failure(self):
        """Test _cleanup_document_celery_tasks handles mark_task_cancelled failures"""
        self.redis_service._backend_client = self.mock_backend_client
        
        task_keys = [b'celery-task-meta-1']
        task_data = json.dumps({
            'result': {
                'index_name': 'test_index',
                'source': 'path/to/doc.pdf'
            }
        }).encode()
        
        self.mock_backend_client.keys.return_value = task_keys
        self.mock_backend_client.get.return_value = task_data
        self.mock_backend_client.delete.return_value = 1
        
        # Mock mark_task_cancelled to fail
        with patch.object(self.redis_service, 'mark_task_cancelled', return_value=False):
            with patch.object(self.redis_service, '_recursively_delete_task_and_parents', return_value=(1, {'1'})):
                with patch.object(self.redis_service, '_cleanup_single_task_related_keys', return_value=0):
                    result = self.redis_service._cleanup_document_celery_tasks("test_index", "path/to/doc.pdf")
        
        # Should still proceed with deletion
        self.assertEqual(result, 1)


if __name__ == '__main__':
    unittest.main()
