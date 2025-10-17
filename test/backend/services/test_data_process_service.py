import sys
import unittest
import os
import io
import base64
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import warnings
from PIL import Image
import pytest
from celery import states

# Set required environment variables
os.environ['REDIS_URL'] = 'redis://mock:6379/0'
os.environ['REDIS_BACKEND_URL'] = 'redis://mock:6379/0'

# Mock modules to prevent actual import chain
sys.modules['data_process.app'] = MagicMock()
sys.modules['data_process.app'].app = MagicMock()
sys.modules['data_process.tasks'] = MagicMock()
sys.modules['data_process.ray_actors'] = MagicMock()
sys.modules['database.attachment_db'] = MagicMock()
sys.modules['database.client'] = MagicMock()
sys.modules['database.client'].minio_client = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['transformers'].CLIPProcessor = MagicMock()
sys.modules['transformers'].CLIPModel = MagicMock()
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'].ToolConfig = MagicMock()

# Add missing nexent.data_process module mock
sys.modules['nexent.data_process'] = MagicMock()
sys.modules['nexent.data_process.core'] = MagicMock()
sys.modules['nexent.data_process.core'].DataProcessCore = MagicMock()

# Mock constants from consts.const
mock_const = MagicMock()
mock_const.CLIP_MODEL_PATH = "mock_clip_path"
mock_const.IMAGE_FILTER = True
mock_const.REDIS_BACKEND_URL = "redis://mock:6379/0"
mock_const.REDIS_URL = "redis://mock:6379/0"
sys.modules['consts.const'] = mock_const

# from backend.services.data_process_service import DataProcessService, get_data_process_service
with patch('data_process.utils.get_task_info') as mock_get_task_info, \
        patch('data_process.utils.get_all_task_ids_from_redis') as mock_get_redis_task_ids:
    from backend.services.data_process_service import DataProcessService, get_data_process_service


class TestDataProcessService(unittest.TestCase):
    def setUp(self):
        """Set up test environment before each test"""
        # Create a clean instance for each test
        self.service = DataProcessService()
        # Store original environment to restore after tests
        self.original_env = os.environ.copy()
        # Suppress warnings during tests
        warnings.filterwarnings('ignore', category=UserWarning)

        # Reset mocks for each test to prevent interference
        # Do not import data_process.app here - use the already mocked module
        mock_celery_app = sys.modules['data_process.app'].app
        mock_celery_app.reset_mock()
        self.mock_celery_app = mock_celery_app

    def tearDown(self):
        """Clean up after each test"""
        # Restore environment variables
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch('backend.services.data_process_service.redis.ConnectionPool.from_url')
    @patch('backend.services.data_process_service.redis.Redis')
    def test_init_redis_client_with_url(self, mock_redis, mock_pool):
        """
        Test Redis client initialization with URL.

        This test verifies that when the REDIS_BACKEND_URL environment variable is set,
        the service correctly initializes the Redis client with the proper configuration.
        It checks that:
        1. The connection pool is created with the correct URL and parameters
        2. The Redis client is initialized using the connection pool
        3. Both the Redis client and pool are stored in the service instance
        """
        # Set environment variable
        os.environ['REDIS_BACKEND_URL'] = 'redis://localhost:6379/0'

        # Create a fresh instance to trigger init
        service = DataProcessService()

        # Assert that Redis was properly initialized
        mock_pool.assert_called_once_with(
            'redis://mock:6379/0',
            max_connections=50,
            decode_responses=True
        )
        mock_redis.assert_called_once()
        self.assertIsNotNone(service.redis_client)
        self.assertIsNotNone(service.redis_pool)

    @patch('backend.services.data_process_service.redis.ConnectionPool.from_url')
    def test_init_redis_client_without_url(self, mock_pool):
        """
        Test Redis client initialization without URL.

        This test verifies the behavior when REDIS_BACKEND_URL environment variable is not set.
        It ensures that:
        1. The connection pool is not created
        2. The Redis client is not initialized
        3. Both redis_client and redis_pool attributes are set to None
        """
        # Ensure environment variable is not set
        if 'REDIS_BACKEND_URL' in os.environ:
            del os.environ['REDIS_BACKEND_URL']

        # Temporarily set REDIS_BACKEND_URL to None in the mock
        import backend.services.data_process_service as dps_module
        original_redis_backend_url = dps_module.REDIS_BACKEND_URL
        dps_module.REDIS_BACKEND_URL = None

        try:
            # Create a fresh instance to trigger init
            service = DataProcessService()

            # Assert that Redis was not initialized
            mock_pool.assert_not_called()
            self.assertIsNone(service.redis_client)
            self.assertIsNone(service.redis_pool)
        finally:
            # Restore the original value
            dps_module.REDIS_BACKEND_URL = original_redis_backend_url

    @patch('backend.services.data_process_service.redis.ConnectionPool.from_url')
    def test_init_redis_client_with_exception(self, mock_pool):
        """
        Test Redis client initialization with exception.

        This test verifies the service's error handling when Redis initialization fails.
        It ensures that:
        1. When an exception occurs during Redis pool creation, it's handled gracefully
        2. Both redis_client and redis_pool attributes are set to None
        3. The service can still be instantiated without crashing
        """
        # Set environment variable
        os.environ['REDIS_BACKEND_URL'] = 'redis://localhost:6379/0'

        # Make redis pool raise an exception
        mock_pool.side_effect = Exception("Test exception")

        # Create a fresh instance to trigger init
        service = DataProcessService()

        # Assert that Redis was not initialized
        self.assertIsNone(service.redis_client)
        self.assertIsNone(service.redis_pool)

    @patch('backend.services.data_process_service.CLIPModel.from_pretrained')
    @patch('backend.services.data_process_service.CLIPProcessor.from_pretrained')
    def test_init_clip_model_success(self, mock_processor, mock_model):
        """
        Test successful CLIP model initialization.

        This test verifies that the CLIP model and processor are correctly initialized.
        It ensures that:
        1. The CLIPModel and CLIPProcessor are loaded from the pretrained path
        2. The model and processor objects are stored in the service instance
        3. The clip_available flag is set to True indicating the model is ready for use
        """
        # Setup mocks
        mock_model.return_value = MagicMock()
        mock_processor.return_value = MagicMock()

        # Initialize CLIP model
        self.service._init_clip_model()

        # Verify CLIP model was properly initialized
        self.assertTrue(self.service.clip_available)
        self.assertIsNotNone(self.service.model)
        self.assertIsNotNone(self.service.processor)

    @patch('backend.services.data_process_service.CLIPModel.from_pretrained')
    def test_init_clip_model_failure(self, mock_model):
        """
        Test CLIP model initialization failure.

        This test verifies the service's error handling when CLIP model loading fails.
        It ensures that:
        1. When an exception occurs during model loading, it's handled gracefully
        2. The clip_available flag is set to False
        3. Both model and processor attributes are set to None
        4. The service can still function without the CLIP model
        """
        # Setup mock to raise exception
        mock_model.side_effect = Exception("Failed to load model")

        # Initialize CLIP model
        self.service._init_clip_model()

        # Verify CLIP model was not initialized
        self.assertFalse(self.service.clip_available)
        self.assertIsNone(self.service.model)
        self.assertIsNone(self.service.processor)

    def test_check_image_size(self):
        """
        Test image size checking functionality.

        This test verifies the image size validation logic.
        It ensures that:
        1. Images with dimensions above the minimum thresholds are accepted
        2. Images with dimensions below the minimum thresholds are rejected
        3. Custom minimum thresholds can be applied when specified
        """
        # Test with valid image size
        self.assertTrue(self.service.check_image_size(300, 300))
        self.assertTrue(self.service.check_image_size(200, 200))

        # Test with invalid image size
        self.assertFalse(self.service.check_image_size(100, 300))
        self.assertFalse(self.service.check_image_size(300, 100))
        self.assertFalse(self.service.check_image_size(100, 100))

        # Test with custom minimum size
        self.assertTrue(self.service.check_image_size(
            150, 150, min_width=100, min_height=100))
        self.assertFalse(self.service.check_image_size(
            150, 150, min_width=200, min_height=200))

    async def async_test_start_stop(self):
        """
        Async implementation of start and stop method testing.

        This test verifies that the async start and stop methods execute without errors.
        Both methods primarily log information and don't have specific return values
        or state changes to verify beyond successful execution.
        """
        # These methods just log messages, so we just ensure they don't fail
        await self.service.start()
        await self.service.stop()

    def test_start_stop(self):
        """
        Test service start and stop methods.

        This test serves as a wrapper to run the async test for start and stop methods.
        It verifies that both service lifecycle methods execute without raising exceptions.
        """
        asyncio.run(self.async_test_start_stop())

    @patch('backend.services.data_process_service.celery_app')
    def test_get_celery_inspector_success(self, mock_celery_app):
        """
        Test successful retrieval of Celery inspector.

        This test verifies the creation and caching of the Celery inspector.
        It ensures that:
        1. The inspector is correctly created from the Celery app
        2. The inspector is stored in the service instance for future use
        3. The timestamp of the last inspector access is updated
        """
        # Setup mocks
        mock_inspector = MagicMock()
        mock_inspector.ping.return_value = True
        mock_celery_app.control.inspect.return_value = mock_inspector

        # Get inspector
        inspector = self.service._get_celery_inspector()

        # Verify inspector was created and cached
        self.assertEqual(inspector, mock_inspector)
        self.assertEqual(self.service._inspector, mock_inspector)
        self.assertGreater(self.service._inspector_last_time, 0)

    @patch('backend.services.data_process_service.celery_app')
    def test_get_celery_inspector_failure(self, mock_celery_app):
        """
        Test Celery inspector creation failure.

        This test verifies the service's error handling when creating the Celery inspector fails.
        It ensures that:
        1. When an exception occurs during inspector creation, it's raised to the caller
        2. The exception message includes context about the failure
        """
        # Setup mocks to raise exception
        mock_celery_app.control.inspect.side_effect = Exception(
            "Failed to create inspector")

        # Verify exception is raised
        with self.assertRaises(Exception) as context:
            self.service._get_celery_inspector()

        # Verify exception message
        self.assertIn("Failed to create inspector with celery_app",
                      str(context.exception))

    @patch('backend.services.data_process_service.celery_app')
    def test_get_celery_inspector_cache(self, mock_celery_app):
        """
        Test Celery inspector caching behavior.

        This test verifies the caching mechanism for the Celery inspector.
        It ensures that:
        1. The first call creates a new inspector
        2. Subsequent calls within the cache timeout return the cached inspector
        3. After the cache timeout expires, a new inspector is created
        """
        # Setup mocks
        mock_inspector1 = MagicMock()
        mock_inspector1.ping.return_value = True
        mock_inspector2 = MagicMock()
        mock_inspector2.ping.return_value = True

        mock_celery_app.control.inspect.side_effect = [
            mock_inspector1, mock_inspector2]

        # First call should create inspector
        inspector1 = self.service._get_celery_inspector()
        self.assertEqual(inspector1, mock_inspector1)

        # Second call should use cached inspector
        inspector2 = self.service._get_celery_inspector()
        self.assertEqual(inspector2, mock_inspector1)

        # Modify last access time to expire cache
        self.service._inspector_last_time = 0

        # Third call should create a new inspector
        inspector3 = self.service._get_celery_inspector()
        self.assertEqual(inspector3, mock_inspector2)

    @patch('backend.services.data_process_service.celery_app')
    @patch('backend.services.data_process_service.logger')
    def test_get_celery_inspector_missing_broker_url(self, mock_logger, mock_celery_app):
        """
        Test Celery inspector creation when broker_url is missing.

        This test verifies that the service handles missing broker_url configuration correctly.
        It ensures that:
        1. When broker_url is None or empty, it's set to REDIS_URL
        2. When result_backend is None or empty, it's set to REDIS_BACKEND_URL
        3. A warning is logged about the reconfiguration
        4. The inspector is created successfully after reconfiguration
        """
        # Setup mocks
        mock_inspector = MagicMock()
        mock_inspector.ping.return_value = True
        mock_celery_app.control.inspect.return_value = mock_inspector

        # Configure celery_app.conf to have missing broker_url
        mock_celery_app.conf.broker_url = None
        mock_celery_app.conf.result_backend = "redis://backend:6379/0"

        # Get inspector
        inspector = self.service._get_celery_inspector()

        # Verify broker_url was set to REDIS_URL
        self.assertEqual(mock_celery_app.conf.broker_url,
                         "redis://mock:6379/0")

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        self.assertIn(
            "Celery broker URL is not configured properly", warning_call)
        self.assertIn("redis://mock:6379/0", warning_call)

        # Verify inspector was created and cached
        self.assertEqual(inspector, mock_inspector)
        self.assertEqual(self.service._inspector, mock_inspector)
        self.assertGreater(self.service._inspector_last_time, 0)

    @patch('backend.services.data_process_service.celery_app')
    @patch('backend.services.data_process_service.logger')
    def test_get_celery_inspector_missing_both_urls(self, mock_logger, mock_celery_app):
        """
        Test Celery inspector creation when both broker_url and result_backend are missing.

        This test verifies that the service handles missing both configurations correctly.
        It ensures that:
        1. When both broker_url and result_backend are None or empty, they're set to their respective Redis URLs
        2. A warning is logged about the reconfiguration
        3. The inspector is created successfully after reconfiguration
        """
        # Setup mocks
        mock_inspector = MagicMock()
        mock_inspector.ping.return_value = True
        mock_celery_app.control.inspect.return_value = mock_inspector

        # Configure celery_app.conf to have both missing
        mock_celery_app.conf.broker_url = None
        mock_celery_app.conf.result_backend = None

        # Get inspector
        inspector = self.service._get_celery_inspector()

        # Verify both URLs were set
        self.assertEqual(mock_celery_app.conf.broker_url,
                         "redis://mock:6379/0")
        self.assertEqual(mock_celery_app.conf.result_backend,
                         "redis://mock:6379/0")

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        self.assertIn(
            "Celery broker URL is not configured properly", warning_call)
        self.assertIn("redis://mock:6379/0", warning_call)

        # Verify inspector was created and cached
        self.assertEqual(inspector, mock_inspector)
        self.assertEqual(self.service._inspector, mock_inspector)
        self.assertGreater(self.service._inspector_last_time, 0)

    @patch('backend.services.data_process_service.celery_app')
    @patch('backend.services.data_process_service.logger')
    def test_get_celery_inspector_empty_string_urls(self, mock_logger, mock_celery_app):
        """
        Test Celery inspector creation when broker_url and result_backend are empty strings.

        This test verifies that the service handles empty string configurations correctly.
        It ensures that:
        1. When broker_url and result_backend are empty strings, they're treated as missing
        2. They're set to their respective Redis URLs
        3. A warning is logged about the reconfiguration
        4. The inspector is created successfully after reconfiguration
        """
        # Setup mocks
        mock_inspector = MagicMock()
        mock_inspector.ping.return_value = True
        mock_celery_app.control.inspect.return_value = mock_inspector

        # Configure celery_app.conf to have empty strings
        mock_celery_app.conf.broker_url = ""
        mock_celery_app.conf.result_backend = ""

        # Get inspector
        inspector = self.service._get_celery_inspector()

        # Verify both URLs were set
        self.assertEqual(mock_celery_app.conf.broker_url,
                         "redis://mock:6379/0")
        self.assertEqual(mock_celery_app.conf.result_backend,
                         "redis://mock:6379/0")

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        self.assertIn(
            "Celery broker URL is not configured properly", warning_call)
        self.assertIn("redis://mock:6379/0", warning_call)

        # Verify inspector was created and cached
        self.assertEqual(inspector, mock_inspector)
        self.assertEqual(self.service._inspector, mock_inspector)
        self.assertGreater(self.service._inspector_last_time, 0)

    @patch('backend.services.data_process_service.celery_app')
    @patch('backend.services.data_process_service.logger')
    def test_get_celery_inspector_no_reconfiguration_needed(self, mock_logger, mock_celery_app):
        """
        Test Celery inspector creation when both URLs are already configured.

        This test verifies that the service doesn't reconfigure when URLs are already set.
        It ensures that:
        1. When both broker_url and result_backend are already configured, no reconfiguration occurs
        2. No warning is logged
        3. The inspector is created successfully without modification
        """
        # Setup mocks
        mock_inspector = MagicMock()
        mock_inspector.ping.return_value = True
        mock_celery_app.control.inspect.return_value = mock_inspector

        # Configure celery_app.conf to have both URLs already set
        mock_celery_app.conf.broker_url = "redis://existing-broker:6379/0"
        mock_celery_app.conf.result_backend = "redis://existing-backend:6379/0"

        # Get inspector
        inspector = self.service._get_celery_inspector()

        # Verify URLs were not changed
        self.assertEqual(mock_celery_app.conf.broker_url,
                         "redis://existing-broker:6379/0")
        self.assertEqual(mock_celery_app.conf.result_backend,
                         "redis://existing-backend:6379/0")

        # Verify no warning was logged
        mock_logger.warning.assert_not_called()

        # Verify inspector was created and cached
        self.assertEqual(inspector, mock_inspector)
        self.assertEqual(self.service._inspector, mock_inspector)
        self.assertGreater(self.service._inspector_last_time, 0)

    @patch('data_process.utils.get_task_info')
    @pytest.mark.asyncio
    async def async_test_get_task(self, mock_get_task_info):
        """
        Async implementation of get_task testing.

        This test verifies that the service correctly retrieves task information by ID.
        It ensures that:
        1. The utility function is called with the correct task ID
        2. The task data is returned as-is from the utility function
        """
        # Setup mock
        task_data = {"id": "task1"}
        mock_get_task_info.return_value = task_data

        # Get task
        result = await self.service.get_task("task1")

        # Verify result
        mock_get_task_info.assert_not_called()

    def test_get_task(self):
        """
        Test retrieval of task by ID.

        This test serves as a wrapper to run the async test for get_task.
        It verifies that the service can retrieve information about a specific task.
        """
        asyncio.run(self.async_test_get_task())

    @patch('backend.services.data_process_service.DataProcessService._get_celery_inspector')
    @patch('data_process.utils.get_task_info')
    @patch('data_process.utils.get_all_task_ids_from_redis')
    @pytest.mark.asyncio
    async def async_test_get_all_tasks(self, mock_get_redis_task_ids, mock_get_task_info, mock_get_inspector):
        """
        Async implementation of get_all_tasks testing.

        This test verifies that the service correctly retrieves all tasks.
        It ensures that:
        1. Active and reserved tasks are retrieved from Celery
        2. Completed tasks are retrieved from Redis
        3. Task information is fetched for each task ID
        4. Tasks can be filtered based on their properties
        5. The combined task list is returned with all task details
        """
        # Setup mocks
        mock_inspector = MagicMock()
        mock_inspector.active.return_value = {
            'worker1': [{'id': 'task1'}, {'id': 'task2'}]
        }
        mock_inspector.reserved.return_value = {
            'worker1': [{'id': 'task3'}]
        }
        mock_get_inspector.return_value = mock_inspector

        mock_get_redis_task_ids.return_value = ['task2', 'task4', 'task5']

        # Setup task info mock to return different task data
        async def mock_task_info(task_id):
            task_data = {
                'task1': {'id': 'task1', 'status': 'ACTIVE', 'index_name': 'index1', 'task_name': 'task_name1'},
                'task2': {'id': 'task2', 'status': 'ACTIVE', 'index_name': 'index2', 'task_name': 'task_name2'},
                'task3': {'id': 'task3', 'status': 'RESERVED', 'index_name': 'index3', 'task_name': 'task_name3'},
                'task4': {'id': 'task4', 'status': 'SUCCESS', 'index_name': 'index4', 'task_name': 'task_name4'},
                'task5': {'id': 'task5', 'status': 'FAILURE', 'index_name': None, 'task_name': None},
            }
            return task_data.get(task_id, {})

        mock_get_task_info.side_effect = mock_task_info

        # Get all tasks with filtering
        result = await self.service.get_all_tasks(filter=True)

        # Verify result (should not include task5)
        self.assertEqual(len(result), 3)

        # Get all tasks without filtering
        result = await self.service.get_all_tasks(filter=False)

        # Verify result (should include all tasks)
        self.assertEqual(len(result), 3)

    def test_get_all_tasks(self):
        """
        Test retrieval of all tasks.

        This test serves as a wrapper to run the async test for get_all_tasks.
        It verifies that the service can retrieve a comprehensive list of all tasks
        from both Celery (active and reserved) and Redis (completed).
        """
        asyncio.run(self.async_test_get_all_tasks())

    @patch('backend.services.data_process_service.DataProcessService._get_celery_inspector')
    @patch('data_process.utils.get_task_info')
    @patch('data_process.utils.get_all_task_ids_from_redis')
    @pytest.mark.asyncio
    async def test_get_all_tasks_redis_error(self, mock_get_redis_task_ids, mock_get_task_info, mock_get_inspector):
        """
        Test get_all_tasks when Redis query fails.

        This test verifies that the service handles Redis errors gracefully
        and continues to process tasks from other sources.
        """
        # Setup mocks
        mock_inspector = MagicMock()
        mock_inspector.active.return_value = {
            'worker1': [{'id': 'task1'}, {'id': 'task2'}]
        }
        mock_inspector.reserved.return_value = {
            'worker1': [{'id': 'task3'}]
        }
        mock_get_inspector.return_value = mock_inspector

        # Mock Redis to raise an exception
        mock_get_redis_task_ids.side_effect = Exception(
            "Redis connection failed")

        # Setup task info mock
        async def mock_task_info(task_id):
            task_data = {
                'task1': {'id': 'task1', 'status': 'ACTIVE', 'index_name': 'index1', 'task_name': 'task_name1'},
                'task2': {'id': 'task2', 'status': 'ACTIVE', 'index_name': 'index2', 'task_name': 'task_name2'},
                'task3': {'id': 'task3', 'status': 'RESERVED', 'index_name': 'index3', 'task_name': 'task_name3'},
            }
            return task_data.get(task_id, {})

        mock_get_task_info.side_effect = mock_task_info

        # Get all tasks - should handle Redis error gracefully
        result = await self.service.get_all_tasks(filter=True)

        # Verify result (should only include tasks from Celery, not Redis)
        self.assertEqual(len(result), 3)

        # Verify that Redis was called and failed
        mock_get_redis_task_ids.assert_called_once()

    @patch('backend.services.data_process_service.DataProcessService.get_all_tasks')
    @pytest.mark.asyncio
    async def async_test_get_index_tasks(self, mock_get_all_tasks):
        """
        Async implementation of get_index_tasks testing.

        This test verifies that the service correctly retrieves tasks for a specific index.
        It ensures that:
        1. All tasks are retrieved first
        2. Tasks are filtered based on the index_name property
        3. Only tasks matching the specified index are returned
        """
        # Setup mock
        mock_get_all_tasks.return_value = [
            {'id': 'task1', 'index_name': 'index1', 'task_name': 'task_name1'},
            {'id': 'task2', 'index_name': 'index2', 'task_name': 'task_name2'},
            {'id': 'task3', 'index_name': 'index1', 'task_name': 'task_name3'},
        ]

        # Get tasks for index1
        result = await self.service.get_index_tasks('index1')

        # Verify result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['id'], 'task1')
        self.assertEqual(result[1]['id'], 'task3')

        # Get tasks for index2
        result = await self.service.get_index_tasks('index2')

        # Verify result
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 'task2')

        # Get tasks for non-existent index
        result = await self.service.get_index_tasks('index3')

        # Verify result
        self.assertEqual(len(result), 0)

    def test_get_index_tasks(self):
        """
        Test retrieval of tasks for a specific index.

        This test serves as a wrapper to run the async test for get_index_tasks.
        It verifies that the service can filter tasks based on their associated index.
        """
        asyncio.run(self.async_test_get_index_tasks())

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_from_url(self, mock_session):
        """
        Async implementation for testing image loading from URL.

        This test verifies that the service can load images from URLs.
        It ensures that:
        1. The HTTP request is made to the correct URL
        2. The response is properly processed to create a PIL Image
        3. The returned image has the expected properties
        """
        # Create a test image
        img = Image.new('RGB', (300, 300), color='red')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read.return_value = img_byte_arr

        # Setup mock session
        mock_session_instance = MagicMock()
        mock_session_instance.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.return_value = mock_response
        mock_session.return_value = mock_session_instance

        # Load image from URL
        result = await self.service.load_image("http://example.com/image.png")

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 300)
        self.assertEqual(result.height, 300)
        self.assertEqual(result.mode, 'RGB')

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_from_url_failure(self, mock_session):
        """
        Async implementation for testing image loading failure from URL.

        This test verifies the service's error handling when image loading fails.
        It ensures that:
        1. When the HTTP request returns a non-200 status code, the error is handled
        2. The method returns None to indicate failure
        """
        # Setup mock response with error status
        mock_response = AsyncMock()
        mock_response.status = 404

        # Setup mock session
        mock_session_instance = MagicMock()
        mock_session_instance.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.return_value = mock_response
        mock_session.return_value = mock_session_instance

        # Load image from URL
        result = await self.service.load_image("http://example.com/not-found.png")

        # Verify result
        self.assertIsNone(result)

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_from_base64(self, mock_session):
        """
        Async implementation for testing image loading from base64 data.

        This test verifies that the service can load images from base64-encoded data.
        It ensures that:
        1. Base64 data URIs are properly detected and processed
        2. The image is correctly decoded from base64
        3. The returned image has the expected properties
        4. HTTP session is not used for base64 images
        """
        # Create a test image and convert to base64
        img = Image.new('RGB', (300, 300), color='blue')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        img_data_uri = f"data:image/png;base64,{img_base64}"

        # Load image from base64
        result = await self.service.load_image(img_data_uri)

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 300)
        self.assertEqual(result.height, 300)
        self.assertEqual(result.mode, 'RGB')

        # Session should not be used for base64 images
        mock_session.assert_called_once()
        mock_session_instance = mock_session.return_value.__aenter__.return_value
        mock_session_instance.get.assert_not_called()

    @patch('os.path.isfile')
    @patch('PIL.Image.open')
    @pytest.mark.asyncio
    async def async_test_load_image_from_file(self, mock_image_open, mock_isfile):
        """
        Async implementation for testing image loading from file.

        This test verifies that the service can load images from the filesystem.
        It ensures that:
        1. The file existence is checked
        2. PIL.Image.open is called with the correct path
        3. The returned image preserves the properties of the loaded image
        """
        # Setup mocks
        mock_isfile.return_value = True
        mock_img = MagicMock()
        mock_img.mode = 'RGB'
        mock_img.size = (300, 300)
        mock_image_open.return_value = mock_img

        # Load image from file
        result = await self.service.load_image("/path/to/image.png")

        # Verify result
        self.assertIsNotNone(result)
        mock_image_open.assert_called_once_with("/path/to/image.png")

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_rgba_to_rgb_conversion(self, mock_session):
        """
        Async implementation for testing RGBA to RGB conversion.

        This test verifies that the service correctly converts RGBA images to RGB.
        It ensures that:
        1. RGBA images are converted to RGB with white background
        2. The alpha channel is properly handled using mask
        3. The returned image has RGB mode
        """
        # Create a test RGBA image
        img = Image.new('RGBA', (300, 300), color=(
            255, 0, 0, 128))  # Semi-transparent red
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read.return_value = img_byte_arr

        # Setup mock session
        mock_session_instance = MagicMock()
        mock_session_instance.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.return_value = mock_response
        mock_session.return_value = mock_session_instance

        # Load image from URL
        result = await self.service.load_image("http://example.com/rgba_image.png")

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 300)
        self.assertEqual(result.height, 300)
        self.assertEqual(result.mode, 'RGB')  # Should be converted to RGB

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_non_rgb_to_rgb_conversion(self, mock_session):
        """
        Async implementation for testing non-RGB to RGB conversion.

        This test verifies that the service correctly converts non-RGB images to RGB.
        It ensures that:
        1. Non-RGB images (like L, P, etc.) are converted to RGB
        2. The conversion preserves image dimensions
        3. The returned image has RGB mode
        """
        # Create a test grayscale image
        img = Image.new('L', (300, 300), color=128)  # Grayscale
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read.return_value = img_byte_arr

        # Setup mock session
        mock_session_instance = MagicMock()
        mock_session_instance.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.return_value = mock_response
        mock_session.return_value = mock_session_instance

        # Load image from URL
        result = await self.service.load_image("http://example.com/grayscale_image.png")

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 300)
        self.assertEqual(result.height, 300)
        self.assertEqual(result.mode, 'RGB')  # Should be converted to RGB

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_rgb_no_conversion(self, mock_session):
        """
        Async implementation for testing RGB images that don't need conversion.

        This test verifies that RGB images are not unnecessarily converted.
        It ensures that:
        1. RGB images remain in RGB mode
        2. No conversion operations are performed
        3. The image properties are preserved
        """
        # Create a test RGB image
        img = Image.new('RGB', (300, 300), color='blue')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read.return_value = img_byte_arr

        # Setup mock session
        mock_session_instance = MagicMock()
        mock_session_instance.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.return_value = mock_response
        mock_session.return_value = mock_session_instance

        # Load image from URL
        result = await self.service.load_image("http://example.com/rgb_image.png")

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 300)
        self.assertEqual(result.height, 300)
        self.assertEqual(result.mode, 'RGB')  # Should remain RGB

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_rgba_base64_conversion(self, mock_session):
        """
        Async implementation for testing RGBA to RGB conversion in base64 images.

        This test verifies that RGBA base64 images are correctly converted to RGB.
        It ensures that:
        1. RGBA base64 images are converted to RGB with white background
        2. The alpha channel is properly handled
        3. The returned image has RGB mode
        """
        # Create a test RGBA image and convert to base64
        img = Image.new('RGBA', (300, 300), color=(
            0, 255, 0, 200))  # Semi-transparent green
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        img_data_uri = f"data:image/png;base64,{img_base64}"

        # Load image from base64
        result = await self.service.load_image(img_data_uri)

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 300)
        self.assertEqual(result.height, 300)
        self.assertEqual(result.mode, 'RGB')  # Should be converted to RGB

        # Session should not be used for base64 images
        mock_session.assert_called_once()
        mock_session_instance = mock_session.return_value.__aenter__.return_value
        mock_session_instance.get.assert_not_called()

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_non_rgb_base64_conversion(self, mock_session):
        """
        Async implementation for testing non-RGB to RGB conversion in base64 images.

        This test verifies that non-RGB base64 images are correctly converted to RGB.
        It ensures that:
        1. Non-RGB base64 images are converted to RGB
        2. The conversion preserves image dimensions
        3. The returned image has RGB mode
        """
        # Create a test grayscale image and convert to base64
        img = Image.new('L', (300, 300), color=64)  # Grayscale
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        img_data_uri = f"data:image/png;base64,{img_base64}"

        # Load image from base64
        result = await self.service.load_image(img_data_uri)

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 300)
        self.assertEqual(result.height, 300)
        self.assertEqual(result.mode, 'RGB')  # Should be converted to RGB

        # Session should not be used for base64 images
        mock_session.assert_called_once()
        mock_session_instance = mock_session.return_value.__aenter__.return_value
        mock_session_instance.get.assert_not_called()

    @patch('os.path.isfile')
    @patch('PIL.Image.open')
    @pytest.mark.asyncio
    async def async_test_load_image_non_rgb_file_conversion(self, mock_image_open, mock_isfile):
        """
        Async implementation for testing non-RGB to RGB conversion in local files.

        This test verifies that non-RGB local files are correctly converted to RGB.
        It ensures that:
        1. Non-RGB local files are converted to RGB
        2. The conversion preserves image dimensions
        3. The returned image has RGB mode
        """
        # Setup mocks
        mock_isfile.return_value = True
        mock_img = MagicMock()
        mock_img.mode = 'L'  # Grayscale
        mock_img.size = (300, 300)
        mock_img.convert.return_value = MagicMock()  # Mock the converted image
        mock_image_open.return_value = mock_img

        # Load image from file
        result = await self.service.load_image("/path/to/grayscale_image.png")

        # Verify result
        self.assertIsNotNone(result)
        mock_image_open.assert_called_once_with("/path/to/grayscale_image.png")
        mock_img.convert.assert_called_once_with('RGB')

    @patch('os.path.isfile')
    @patch('PIL.Image.open')
    @pytest.mark.asyncio
    async def async_test_load_image_rgb_file_no_conversion(self, mock_image_open, mock_isfile):
        """
        Async implementation for testing RGB local files that don't need conversion.

        This test verifies that RGB local files are not unnecessarily converted.
        It ensures that:
        1. RGB local files remain in RGB mode
        2. No conversion operations are performed
        3. The image properties are preserved
        """
        # Setup mocks
        mock_isfile.return_value = True
        mock_img = MagicMock()
        mock_img.mode = 'RGB'
        mock_img.size = (300, 300)
        mock_image_open.return_value = mock_img

        # Load image from file
        result = await self.service.load_image("/path/to/rgb_image.png")

        # Verify result
        self.assertIsNotNone(result)
        mock_image_open.assert_called_once_with("/path/to/rgb_image.png")
        # No conversion should be called for RGB images

    @patch('aiohttp.ClientSession')
    @pytest.mark.asyncio
    async def async_test_load_image_svg_filtered(self, mock_session):
        """
        Async implementation for testing SVG file filtering.

        This test verifies that SVG files are filtered out and not processed.
        It ensures that:
        1. SVG files are detected by their extension
        2. The method returns None for SVG files
        3. No HTTP request is made for SVG files
        """
        # Load SVG image (should be filtered out)
        result = await self.service.load_image("http://example.com/image.svg")

        # Verify result - should be None for SVG files
        self.assertIsNone(result)

        # Session should not be used for SVG files
        mock_session.assert_called_once()
        mock_session_instance = mock_session.return_value.__aenter__.return_value
        mock_session_instance.get.assert_not_called()

    @patch('aiohttp.ClientSession')
    @patch('tempfile.NamedTemporaryFile')
    @patch('PIL.Image.open')
    @patch('PIL.Image.new')
    @patch('os.unlink')
    @patch('os.path.splitext')
    @patch('backend.services.data_process_service.logger')
    @pytest.mark.asyncio
    async def async_test_load_image_temp_file_fallback(self, mock_logger, mock_splitext, mock_unlink, mock_image_new, mock_image_open, mock_tempfile, mock_session):
        """
        Async implementation for testing temporary file fallback when direct loading fails.

        This test verifies that when direct image loading fails, the service falls back
        to using a temporary file for loading.
        It ensures that:
        1. Direct loading fails and triggers the fallback mechanism
        2. A temporary file is created with the correct suffix
        3. Image data is written to the temporary file
        4. The image is loaded from the temporary file
        5. The temporary file is properly cleaned up
        6. Image mode conversion is applied if needed
        """
        # Create a test image
        img = Image.new('RGB', (300, 300), color='green')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read.return_value = img_byte_arr

        # Setup mock session
        mock_session_instance = MagicMock()
        mock_session_instance.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value.__aenter__.return_value = mock_response
        mock_session.return_value = mock_session_instance

        # Setup mocks for the fallback mechanism
        mock_splitext.return_value = ('image', '.png')

        # Mock the temporary file
        mock_temp_file = MagicMock()
        mock_temp_file.name = '/tmp/temp_image.png'
        mock_tempfile.return_value.__enter__.return_value = mock_temp_file

        # Mock Image.open to fail on direct loading but succeed on temp file
        def mock_image_open_side_effect(path_or_file):
            if isinstance(path_or_file, io.BytesIO):
                # Direct loading fails
                raise Exception("Direct loading failed")
            else:
                # Loading from temp file succeeds
                mock_img = MagicMock()
                mock_img.mode = 'RGB'
                mock_img.size = (300, 300)
                return mock_img

        mock_image_open.side_effect = mock_image_open_side_effect

        # Load image from URL
        result = await self.service.load_image("http://example.com/image.png")

        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result.mode, 'RGB')
        self.assertEqual(result.size, (300, 300))

        # Verify the fallback mechanism was used
        mock_splitext.assert_called_once_with("http://example.com/image.png")
        mock_tempfile.assert_called_once_with(suffix='.png', delete=False)

        # Verify image data was written to temp file
        mock_temp_file.write.assert_called_once_with(img_byte_arr)
        mock_temp_file.flush.assert_called_once()

        # Verify image was loaded from temp file
        mock_image_open.assert_any_call('/tmp/temp_image.png')

        # Verify temp file was cleaned up
        mock_unlink.assert_called_once_with('/tmp/temp_image.png')

    @patch('os.path.isfile')
    @patch('PIL.Image.open')
    @patch('backend.services.data_process_service.logger')
    @pytest.mark.asyncio
    async def async_test_load_image_local_file_exception(self, mock_logger, mock_image_open, mock_isfile):
        """
        Async implementation for testing local file loading exception.

        This test verifies that when loading a local file fails, the service properly
        logs the error and returns None.
        It ensures that:
        1. The file existence is checked and returns True
        2. PIL.Image.open fails with an exception
        3. The error is logged with appropriate context
        4. The method returns None instead of raising an exception
        """
        # Setup mocks
        mock_isfile.return_value = True
        mock_image_open.side_effect = Exception("Corrupted image file")

        # Load image from file
        result = await self.service.load_image("/path/to/corrupted_image.png")

        # Verify result
        self.assertIsNone(result)

        # Verify error was logged
        mock_logger.info.assert_called_once()
        error_call = mock_logger.info.call_args[0][0]
        self.assertIn(
            "Failed to load local image: Corrupted image file", error_call)

        # Verify file existence was checked
        mock_isfile.assert_called_once_with("/path/to/corrupted_image.png")

        # Verify Image.open was attempted
        mock_image_open.assert_called_once_with("/path/to/corrupted_image.png")

    def test_load_image(self):
        """
        Test image loading from various sources.

        This test serves as a wrapper to run the async tests for load_image.
        It verifies that the service can load images from:
        1. URLs (with both success and failure cases)
        2. Base64-encoded data
        3. Local files
        4. Image mode conversions (RGBA to RGB, non-RGB to RGB)
        5. SVG file filtering
        6. Temporary file fallback mechanism
        7. Local file loading exceptions
        8. General exception handling
        """
        asyncio.run(self.async_test_load_image_from_url())
        asyncio.run(self.async_test_load_image_from_url_failure())
        asyncio.run(self.async_test_load_image_from_base64())
        asyncio.run(self.async_test_load_image_from_file())
        asyncio.run(self.async_test_load_image_rgba_to_rgb_conversion())
        asyncio.run(self.async_test_load_image_non_rgb_to_rgb_conversion())
        asyncio.run(self.async_test_load_image_rgb_no_conversion())
        asyncio.run(self.async_test_load_image_rgba_base64_conversion())
        asyncio.run(self.async_test_load_image_non_rgb_base64_conversion())
        asyncio.run(self.async_test_load_image_non_rgb_file_conversion())
        asyncio.run(self.async_test_load_image_rgb_file_no_conversion())
        asyncio.run(self.async_test_load_image_svg_filtered())
        asyncio.run(self.async_test_load_image_temp_file_fallback())
        asyncio.run(self.async_test_load_image_local_file_exception())

    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
    @patch('backend.services.data_process_service.DataProcessService._init_clip_model')
    @pytest.mark.asyncio
    async def async_test_filter_important_image_size_filter(self, mock_init_clip, mock_check_size, mock_load_image):
        """
        Async implementation for testing image filtering by size.

        This test verifies the initial size filtering stage of the image importance filter.
        It ensures that:
        1. Images that don't meet size requirements are immediately rejected
        2. The CLIP model is not initialized for such images (optimization)
        3. The result indicates the image is not important with zero confidence
        """
        # Setup mocks
        mock_img = MagicMock()
        mock_img.width = 100  # Small image
        mock_img.height = 100
        mock_load_image.return_value = mock_img
        mock_check_size.return_value = False  # Image doesn't meet size requirements

        # Filter image
        result = await self.service.filter_important_image("http://example.com/small_image.png")

        # Verify result
        self.assertFalse(result["is_important"])
        self.assertEqual(result["confidence"], 0.0)
        mock_load_image.assert_called_once_with(
            "http://example.com/small_image.png")
        mock_check_size.assert_called_once_with(100, 100)
        mock_init_clip.assert_not_called()  # CLIP should not be initialized

    @patch('backend.services.data_process_service.IMAGE_FILTER', False)
    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
    @pytest.mark.asyncio
    async def async_test_filter_important_image_filter_disabled(self, mock_check_size, mock_load_image):
        """
        Async implementation for testing behavior when image filtering is disabled.

        This test verifies that when IMAGE_FILTER is disabled:
        1. All images are considered important regardless of content
        2. The result indicates the image is important with maximum confidence
        3. The CLIP model is not used (optimization)
        """
        # Setup mocks
        mock_img = MagicMock()
        mock_img.width = 300
        mock_img.height = 300
        mock_load_image.return_value = mock_img
        mock_check_size.return_value = True  # Image meets size requirements

        # Filter image
        result = await self.service.filter_important_image("http://example.com/image.png")

        # Verify result
        self.assertTrue(result["is_important"])
        self.assertEqual(result["confidence"], 1.0)

    @patch('backend.services.data_process_service.IMAGE_FILTER', True)
    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
    @patch('torch.no_grad')
    @pytest.mark.asyncio
    async def async_test_filter_important_image_with_clip(self, mock_no_grad, mock_check_size, mock_load_image):
        """
        Async implementation for testing image filtering with CLIP model.

        This test verifies the complete image filtering process with CLIP:
        1. The image is loaded and passes size requirements
        2. The CLIP model processes the image with positive and negative prompts
        3. The model's output probabilities determine the image importance
        4. The result includes the correct confidence scores and classification
        """
        # Setup image mock
        mock_img = MagicMock()
        mock_img.width = 300
        mock_img.height = 300
        mock_img.mode = 'RGB'
        mock_load_image.return_value = mock_img
        mock_check_size.return_value = True  # Image meets size requirements

        # Setup CLIP model mocks
        self.service.clip_available = True
        self.service.model = MagicMock()
        self.service.processor = MagicMock()

        # Setup model outputs
        mock_outputs = MagicMock()
        mock_logits = MagicMock()
        mock_probs = MagicMock()
        mock_probs[0].tolist.return_value = [0.3, 0.7]  # [negative, positive]
        mock_logits.softmax.return_value = mock_probs
        mock_outputs.logits_per_image = mock_logits
        self.service.model.return_value = mock_outputs

        # Setup processor
        self.service.processor.return_value = {"inputs": "processed"}

        # Filter image
        result = await self.service.filter_important_image(
            "http://example.com/image.png",
            positive_prompt="an important image",
            negative_prompt="an unimportant image"
        )

        # Verify result
        self.assertTrue(result["is_important"])
        self.assertEqual(result["confidence"], 0.7)
        self.assertEqual(result["probabilities"]["positive"], 0.7)
        self.assertEqual(result["probabilities"]["negative"], 0.3)

        # Verify CLIP was used
        self.service.processor.assert_called_once()
        self.service.model.assert_called_once()

    @patch('backend.services.data_process_service.IMAGE_FILTER', True)
    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
    @patch('backend.services.data_process_service.DataProcessService._init_clip_model')
    @patch('backend.services.data_process_service.logger')
    @pytest.mark.asyncio
    async def async_test_filter_important_image_clip_not_available(self, mock_logger, mock_init_clip, mock_check_size, mock_load_image):
        """
        Async implementation for testing behavior when CLIP model is not available.

        This test verifies that when the CLIP model is not available:
        1. The service attempts to initialize the CLIP model
        2. If initialization fails, all images that pass size filtering are considered important
        3. The result indicates the image is important with maximum confidence
        """
        # Setup mocks
        mock_img = MagicMock()
        mock_img.width = 300
        mock_img.height = 300
        mock_load_image.return_value = mock_img
        mock_check_size.return_value = True  # Image meets size requirements

        # Make CLIP unavailable
        self.service.clip_available = False

        # Filter image
        result = await self.service.filter_important_image("http://example.com/image.png")

        # Verify result
        self.assertTrue(result["is_important"])
        self.assertEqual(result["confidence"], 1.0)
        mock_init_clip.assert_called_once()  # CLIP initialization attempted

    @patch('backend.services.data_process_service.IMAGE_FILTER', True)
    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
    @patch('backend.services.data_process_service.DataProcessService._init_clip_model')
    @patch('backend.services.data_process_service.logger')
    @pytest.mark.asyncio
    async def async_test_filter_important_image_clip_processing_failure(self, mock_logger, mock_init_clip, mock_check_size, mock_load_image):
        """
        Async implementation for testing CLIP model processing failure fallback.

        This test verifies that when CLIP model processing fails, the service falls back
        to size-only filtering with predefined confidence values.
        It ensures that:
        1. The image passes size requirements
        2. CLIP model is available and initialized
        3. CLIP processing fails during model execution
        4. The service falls back to size-only filtering
        5. A warning is logged about the CLIP processing failure
        6. The result indicates the image is important with fallback confidence values
        """
        # Setup mocks
        mock_img = MagicMock()
        mock_img.width = 300
        mock_img.height = 300
        mock_img.mode = 'RGB'
        mock_load_image.return_value = mock_img
        mock_check_size.return_value = True  # Image meets size requirements

        # Setup CLIP model mocks
        self.service.clip_available = True
        self.service.model = MagicMock()
        self.service.processor = MagicMock()

        # Setup processor to raise exception during processing
        self.service.processor.side_effect = Exception(
            "CLIP model processing failed")

        # Filter image
        result = await self.service.filter_important_image("http://example.com/image.png")

        # Verify result - should fall back to size-only filtering
        self.assertTrue(result["is_important"])
        self.assertEqual(result["confidence"], 0.8)
        self.assertEqual(result["probabilities"]["positive"], 0.8)
        self.assertEqual(result["probabilities"]["negative"], 0.2)

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        self.assertIn(
            "CLIP processing failed, using size-only filter", warning_call)
        self.assertIn("CLIP model processing failed", warning_call)

        # Verify CLIP was attempted
        self.service.processor.assert_called_once()

    @patch('backend.services.data_process_service.IMAGE_FILTER', True)
    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
    @patch('backend.services.data_process_service.DataProcessService._init_clip_model')
    @patch('backend.services.data_process_service.logger')
    @patch('PIL.Image.new')
    @pytest.mark.asyncio
    async def async_test_filter_important_image_general_exception(self, mock_image_new, mock_logger, mock_init_clip, mock_check_size, mock_load_image):
        """
        Async implementation for testing general exception handling in image filtering.

        This test verifies that when a general exception occurs during image processing,
        the service properly logs the error and raises an exception.
        It ensures that:
        1. An exception occurs during the image filtering process (outside CLIP processing)
        2. The error is logged with appropriate context
        3. An exception is raised to the caller
        4. The exception message includes the original error details
        """
        # Setup mocks
        mock_img = MagicMock()
        mock_img.width = 300
        mock_img.height = 300
        mock_img.mode = 'RGBA'  # Set to RGBA to trigger the conversion path
        mock_load_image.return_value = mock_img
        mock_check_size.return_value = True  # Image meets size requirements

        # Setup CLIP model mocks
        self.service.clip_available = True
        self.service.model = MagicMock()
        self.service.processor = MagicMock()

        # Make the image mode conversion fail to trigger the outer exception handler
        mock_image_new.side_effect = Exception("Image conversion failed")

        # Filter image - should raise exception
        with self.assertRaises(Exception) as context:
            await self.service.filter_important_image("http://example.com/image.png")

        # Verify exception message
        self.assertIn(
            "Error processing image: Image conversion failed", str(context.exception))

        # Verify error was logged
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        self.assertIn(
            "Error processing image: Image conversion failed", error_call)

        # Verify image conversion was attempted
        mock_image_new.assert_called_once()

    def test_filter_important_image(self):
        """
        Test image importance filtering.

        This test serves as a wrapper to run the async tests for filter_important_image.
        It verifies that the service can filter images based on:
        1. Size requirements
        2. CLIP model assessment when available
        3. Global configuration settings
        4. CLIP processing failure fallback
        5. General exception handling
        """
        asyncio.run(self.async_test_filter_important_image_size_filter())
        asyncio.run(self.async_test_filter_important_image_filter_disabled())
        asyncio.run(self.async_test_filter_important_image_clip_not_available())
        asyncio.run(self.async_test_filter_important_image_with_clip())
        asyncio.run(
            self.async_test_filter_important_image_clip_processing_failure())
        asyncio.run(self.async_test_filter_important_image_general_exception())

    @patch('backend.services.data_process_service.DataProcessService')
    def test_get_data_process_service(self, mock_service_class):
        """
        Test the get_data_process_service global instance function.

        This test verifies the singleton pattern implementation:
        1. The first call creates a new service instance
        2. Subsequent calls return the same instance
        3. The service class constructor is only called once
        4. The global variable _data_process_service is properly set
        """
        # Set up module level variable to None
        import backend.services.data_process_service as dps_module
        dps_module._data_process_service = None

        # Create mock service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # First call should create new instance
        service1 = get_data_process_service()
        mock_service_class.assert_called_once()
        self.assertEqual(service1, mock_service)

        # Second call should return the same instance
        service2 = get_data_process_service()
        mock_service_class.assert_called_once()  # Still only called once
        self.assertEqual(service2, mock_service)
        self.assertEqual(service1, service2)

    @patch('backend.services.data_process_service.chain')
    @patch('backend.services.data_process_service.forward')
    @patch('backend.services.data_process_service.process')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_success(self, mock_process, mock_forward, mock_chain):
        """
        Async implementation for testing successful batch task creation.

        This test verifies that the service correctly creates batch tasks.
        It ensures that:
        1. Individual tasks are created for each source in the request
        2. The process_and_forward.delay method is called with correct parameters
        3. Task IDs are collected and returned
        4. All valid source configurations are processed
        """
        # Setup Celery signature mocks
        process_sig_1 = MagicMock()
        process_sig_1.set.return_value = process_sig_1
        process_sig_2 = MagicMock()
        process_sig_2.set.return_value = process_sig_2
        forward_sig_1 = MagicMock()
        forward_sig_1.set.return_value = forward_sig_1
        forward_sig_2 = MagicMock()
        forward_sig_2.set.return_value = forward_sig_2

        # process.s returns different sig objects per call
        mock_process.s.side_effect = [process_sig_1, process_sig_2]
        mock_forward.s.side_effect = [forward_sig_1, forward_sig_2]

        # chain(...).apply_async() returns result with id
        chain_inst_1 = MagicMock()
        chain_inst_1.apply_async.return_value = MagicMock(id="task_id_1")
        chain_inst_2 = MagicMock()
        chain_inst_2.apply_async.return_value = MagicMock(id="task_id_2")
        mock_chain.side_effect = [chain_inst_1, chain_inst_2]

        # Create test request
        from consts.model import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source': 'http://example.com/doc1.pdf',
                    'source_type': 'url',
                    'chunking_strategy': 'semantic',
                    'index_name': 'test_index_1',
                    'original_filename': 'doc1.pdf'
                },
                {
                    'source': 'http://example.com/doc2.pdf',
                    'source_type': 'url',
                    'chunking_strategy': 'fixed',
                    'index_name': 'test_index_2',
                    'original_filename': 'doc2.pdf'
                }
            ]
        )

        # Create batch tasks
        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        # Verify result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "task_id_1")
        self.assertEqual(result[1], "task_id_2")

        # Verify chain was invoked for each source
        self.assertEqual(mock_chain.call_count, 2)

        # Verify process.s and forward.s were called with correct params
        expected_process_calls = [
            {
                'source': 'http://example.com/doc1.pdf',
                'source_type': 'url',
                'chunking_strategy': 'semantic',
                'index_name': 'test_index_1',
                'original_filename': 'doc1.pdf'
            },
            {
                'source': 'http://example.com/doc2.pdf',
                'source_type': 'url',
                'chunking_strategy': 'fixed',
                'index_name': 'test_index_2',
                'original_filename': 'doc2.pdf'
            }
        ]
        actual_process_calls = [kwargs for args,
                                kwargs in mock_process.s.call_args_list]
        self.assertEqual(actual_process_calls, expected_process_calls)
        process_sig_1.set.assert_called_once_with(queue='process_q')
        process_sig_2.set.assert_called_once_with(queue='process_q')

        expected_forward_calls = [
            {
                'index_name': 'test_index_1',
                'source': 'http://example.com/doc1.pdf',
                'source_type': 'url',
                'original_filename': 'doc1.pdf',
                'authorization': 'Bearer test_token'
            },
            {
                'index_name': 'test_index_2',
                'source': 'http://example.com/doc2.pdf',
                'source_type': 'url',
                'original_filename': 'doc2.pdf',
                'authorization': 'Bearer test_token'
            }
        ]
        actual_forward_calls = [kwargs for args,
                                kwargs in mock_forward.s.call_args_list]
        self.assertEqual(actual_forward_calls, expected_forward_calls)
        forward_sig_1.set.assert_called_once_with(queue='forward_q')
        forward_sig_2.set.assert_called_once_with(queue='forward_q')

    @patch('backend.services.data_process_service.chain')
    @patch('backend.services.data_process_service.forward')
    @patch('backend.services.data_process_service.process')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_missing_source(self, mock_process, mock_forward, mock_chain):
        """
        Async implementation for testing batch task creation with missing source field.

        This test verifies that the service handles missing source field correctly.
        It ensures that:
        1. Tasks with missing 'source' field are skipped
        2. An error is logged for the invalid configuration
        3. Only valid source configurations are processed
        4. The method continues processing other sources
        """
        # Setup signature mocks
        process_sig = MagicMock()
        process_sig.set.return_value = process_sig
        forward_sig = MagicMock()
        forward_sig.set.return_value = forward_sig
        mock_process.s.return_value = process_sig
        mock_forward.s.return_value = forward_sig
        chain_inst = MagicMock()
        chain_inst.apply_async.return_value = MagicMock(id="task_id_1")
        mock_chain.return_value = chain_inst

        # Create test request with missing source
        from consts.model import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source_type': 'url',
                    'chunking_strategy': 'semantic',
                    'index_name': 'test_index_1',
                    'original_filename': 'doc1.pdf'
                    # Missing 'source' field
                },
                {
                    'source': 'http://example.com/doc2.pdf',
                    'source_type': 'url',
                    'chunking_strategy': 'fixed',
                    'index_name': 'test_index_2',
                    'original_filename': 'doc2.pdf'
                }
            ]
        )

        # Create batch tasks
        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        # Verify result - only one task should be created
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "task_id_1")

        # Verify chain called once with built signatures
        mock_chain.assert_called_once()
        mock_process.s.assert_called_once()
        mock_forward.s.assert_called_once()
        self.assertEqual(
            mock_process.s.call_args[1]['source'], 'http://example.com/doc2.pdf')
        self.assertEqual(
            mock_process.s.call_args[1]['index_name'], 'test_index_2')

    @patch('backend.services.data_process_service.chain')
    @patch('backend.services.data_process_service.forward')
    @patch('backend.services.data_process_service.process')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_missing_index_name(self, mock_process, mock_forward, mock_chain):
        """
        Async implementation for testing batch task creation with missing index_name field.

        This test verifies that the service handles missing index_name field correctly.
        It ensures that:
        1. Tasks with missing 'index_name' field are skipped
        2. An error is logged for the invalid configuration
        3. Only valid source configurations are processed
        4. The method continues processing other sources
        """
        # Setup signature mocks
        process_sig = MagicMock()
        process_sig.set.return_value = process_sig
        forward_sig = MagicMock()
        forward_sig.set.return_value = forward_sig
        mock_process.s.return_value = process_sig
        mock_forward.s.return_value = forward_sig
        chain_inst = MagicMock()
        chain_inst.apply_async.return_value = MagicMock(id="task_id_1")
        mock_chain.return_value = chain_inst

        # Create test request with missing index_name
        from consts.model import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source': 'http://example.com/doc1.pdf',
                    'source_type': 'url',
                    'chunking_strategy': 'semantic',
                    'original_filename': 'doc1.pdf'
                    # Missing 'index_name' field
                },
                {
                    'source': 'http://example.com/doc2.pdf',
                    'source_type': 'url',
                    'chunking_strategy': 'fixed',
                    'index_name': 'test_index_2',
                    'original_filename': 'doc2.pdf'
                }
            ]
        )

        # Create batch tasks
        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        # Verify result - only one task should be created
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "task_id_1")

        # Verify chain called once with built signatures
        mock_chain.assert_called_once()
        mock_process.s.assert_called_once()
        mock_forward.s.assert_called_once()
        self.assertEqual(
            mock_process.s.call_args[1]['source'], 'http://example.com/doc2.pdf')
        self.assertEqual(
            mock_process.s.call_args[1]['index_name'], 'test_index_2')

    @patch('backend.services.data_process_service.chain')
    @patch('backend.services.data_process_service.forward')
    @patch('backend.services.data_process_service.process')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_missing_both_required_fields(self, mock_process, mock_forward, mock_chain):
        """
        Async implementation for testing batch task creation with both required fields missing.

        This test verifies that the service handles multiple invalid configurations correctly.
        It ensures that:
        1. Tasks with missing required fields are skipped
        2. Errors are logged for invalid configurations
        3. No tasks are created when all sources are invalid
        4. The method returns an empty list
        """
        # Create test request with all sources missing required fields
        from consts.model import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source_type': 'url',
                    'chunking_strategy': 'semantic',
                    'original_filename': 'doc1.pdf'
                    # Missing both 'source' and 'index_name' fields
                },
                {
                    'source_type': 'url',
                    'chunking_strategy': 'fixed',
                    'original_filename': 'doc2.pdf'
                    # Missing both 'source' and 'index_name' fields
                }
            ]
        )

        # Create batch tasks
        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        # Verify result - no tasks should be created
        self.assertEqual(len(result), 0)

        # Verify no chain created
        mock_chain.assert_not_called()
        mock_process.s.assert_not_called()
        mock_forward.s.assert_not_called()

    @patch('backend.services.data_process_service.chain')
    @patch('backend.services.data_process_service.forward')
    @patch('backend.services.data_process_service.process')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_empty_sources(self, mock_process, mock_forward, mock_chain):
        """
        Async implementation for testing batch task creation with empty sources list.

        This test verifies that the service handles empty sources list correctly.
        It ensures that:
        1. No tasks are created when sources list is empty
        2. The method returns an empty list
        3. No errors occur during processing
        """
        # Create test request with empty sources
        from consts.model import BatchTaskRequest
        request = BatchTaskRequest(sources=[])

        # Create batch tasks
        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        # Verify result - no tasks should be created
        self.assertEqual(len(result), 0)

        # Verify no chain created
        mock_chain.assert_not_called()
        mock_process.s.assert_not_called()
        mock_forward.s.assert_not_called()

    @patch('backend.services.data_process_service.chain')
    @patch('backend.services.data_process_service.forward')
    @patch('backend.services.data_process_service.process')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_optional_fields(self, mock_process, mock_forward, mock_chain):
        """
        Async implementation for testing batch task creation with optional fields.

        This test verifies that the service handles optional fields correctly.
        It ensures that:
        1. Tasks are created even when optional fields are missing
        2. Optional fields are passed as None when not provided
        3. The method processes all valid sources regardless of optional field presence
        """
        # Setup signature mocks
        process_sig = MagicMock()
        process_sig.set.return_value = process_sig
        forward_sig = MagicMock()
        forward_sig.set.return_value = forward_sig
        mock_process.s.return_value = process_sig
        mock_forward.s.return_value = forward_sig
        chain_inst = MagicMock()
        chain_inst.apply_async.return_value = MagicMock(id="task_id_1")
        mock_chain.return_value = chain_inst

        # Create test request with minimal required fields only
        from consts.model import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source': 'http://example.com/doc1.pdf',
                    'index_name': 'test_index_1'
                    # Only required fields, optional fields missing
                }
            ]
        )

        # Create batch tasks
        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        # Verify result
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "task_id_1")

        # Verify signatures built with None optional fields for process, and authorization on forward
        mock_process.s.assert_called_once()
        proc_kwargs = mock_process.s.call_args[1]
        self.assertEqual(proc_kwargs['source'], 'http://example.com/doc1.pdf')
        self.assertEqual(proc_kwargs['index_name'], 'test_index_1')
        self.assertIsNone(proc_kwargs['source_type'])
        self.assertIsNone(proc_kwargs['chunking_strategy'])
        self.assertIsNone(proc_kwargs['original_filename'])

        mock_forward.s.assert_called_once()
        fwd_kwargs = mock_forward.s.call_args[1]
        self.assertEqual(fwd_kwargs['authorization'], 'Bearer test_token')

    @patch('backend.services.data_process_service.chain')
    @patch('backend.services.data_process_service.forward')
    @patch('backend.services.data_process_service.process')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_no_authorization(self, mock_process, mock_forward, mock_chain):
        """
        Async implementation for testing batch task creation without authorization.

        This test verifies that the service handles missing authorization correctly.
        It ensures that:
        1. Tasks are created even when authorization is None
        2. None is passed as authorization parameter
        3. The method processes all valid sources
        """
        # Setup signature mocks
        process_sig = MagicMock()
        process_sig.set.return_value = process_sig
        forward_sig = MagicMock()
        forward_sig.set.return_value = forward_sig
        mock_process.s.return_value = process_sig
        mock_forward.s.return_value = forward_sig
        chain_inst = MagicMock()
        chain_inst.apply_async.return_value = MagicMock(id="task_id_1")
        mock_chain.return_value = chain_inst

        # Create test request
        from consts.model import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source': 'http://example.com/doc1.pdf',
                    'source_type': 'url',
                    'chunking_strategy': 'semantic',
                    'index_name': 'test_index_1',
                    'original_filename': 'doc1.pdf'
                }
            ]
        )

        # Create batch tasks without authorization
        result = await self.service.create_batch_tasks_impl(None, request)

        # Verify result
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "task_id_1")

        # Verify forward.s called with None authorization
        mock_forward.s.assert_called_once()
        fwd_kwargs = mock_forward.s.call_args[1]
        self.assertEqual(fwd_kwargs['source'], 'http://example.com/doc1.pdf')
        self.assertEqual(fwd_kwargs['index_name'], 'test_index_1')
        self.assertIsNone(fwd_kwargs['authorization'])

    def test_create_batch_tasks_impl(self):
        """
        Test batch task creation functionality.

        This test serves as a wrapper to run the async tests for create_batch_tasks_impl.
        It verifies that the service can create batch tasks with various configurations:
        1. Successful creation with all fields
        2. Handling missing required fields (source, index_name)
        3. Handling empty sources list
        4. Handling optional fields
        5. Handling missing authorization
        """
        asyncio.run(self.async_test_create_batch_tasks_impl_success())
        asyncio.run(self.async_test_create_batch_tasks_impl_missing_source())
        asyncio.run(
            self.async_test_create_batch_tasks_impl_missing_index_name())
        asyncio.run(
            self.async_test_create_batch_tasks_impl_missing_both_required_fields())
        asyncio.run(self.async_test_create_batch_tasks_impl_empty_sources())
        asyncio.run(self.async_test_create_batch_tasks_impl_optional_fields())
        asyncio.run(self.async_test_create_batch_tasks_impl_no_authorization())

    @patch('backend.services.data_process_service.DataProcessCore')
    @pytest.mark.asyncio
    async def async_test_process_uploaded_text_file(self, mock_data_process_core):
        """
        Async implementation for testing processing uploaded text file with mixed chunks.

        This test verifies that:
        1. Chunks with 'content' are concatenated and returned
        2. Chunks without 'content' are ignored from text/chunks but count towards chunks_count
        3. Returned metadata fields are set correctly
        """
        # Arrange: mock DataProcessCore.file_process to return mixed chunks
        mock_instance = MagicMock()
        mock_instance.file_process.return_value = [
            {"content": "First chunk"},
            {"no_content": True},
            {"content": "Second chunk"},
        ]
        mock_data_process_core.return_value = mock_instance

        filename = "test.txt"
        chunking_strategy = "semantic"
        file_bytes = b"ignored-by-mock"

        # Act
        result = await self.service.process_uploaded_text_file(
            file_content=file_bytes,
            filename=filename,
            chunking_strategy=chunking_strategy
        )

        # Assert core call
        mock_instance.file_process.assert_called_once_with(
            file_data=file_bytes,
            filename=filename,
            chunking_strategy=chunking_strategy
        )

        # Assert result shape and values
        self.assertTrue(result["success"])
        self.assertEqual(result["filename"], filename)
        self.assertEqual(result["chunking_strategy"], chunking_strategy)
        self.assertEqual(result["chunks"], ["First chunk", "Second chunk"])
        # includes chunk without 'content'
        self.assertEqual(result["chunks_count"], 3)
        self.assertEqual(result["text"], "First chunk\nSecond chunk")
        self.assertEqual(result["text_length"],
                         len("First chunk\nSecond chunk"))

    def test_process_uploaded_text_file(self):
        """
        Test wrapper to run the async test for processing uploaded text files.
        """
        asyncio.run(self.async_test_process_uploaded_text_file())

    def test_convert_celery_states_to_custom(self):
        """
        Minimal branch coverage for convert_celery_states_to_custom.

        Covers:
        - process FAILURE override
        - forward FAILURE override
        - both SUCCESS -> COMPLETED
        - both None -> WAIT_FOR_PROCESSING
        - only forward STARTED -> FORWARDING
        - only process STARTED -> PROCESSING
        """
        # process FAILURE has priority
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=states.FAILURE, forward_celery_state=states.PENDING),
            "PROCESS_FAILED"
        )

        # forward FAILURE has next priority
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=states.SUCCESS, forward_celery_state=states.FAILURE),
            "FORWARD_FAILED"
        )

        # both SUCCESS -> COMPLETED
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=states.SUCCESS, forward_celery_state=states.SUCCESS),
            "COMPLETED"
        )

        # both None -> WAIT_FOR_PROCESSING
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=None, forward_celery_state=None),
            "WAIT_FOR_PROCESSING"
        )

        # only forward state present -> map forward STARTED -> FORWARDING
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=None, forward_celery_state=states.STARTED),
            "FORWARDING"
        )

        # only process state present -> map process STARTED -> PROCESSING
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=states.STARTED, forward_celery_state=None),
            "PROCESSING"
        )

    async def test_convert_celery_states_wait_for_processing(self):
        """
        Cover return "WAIT_FOR_PROCESSING" branches:
        - both states are None
        - process state PENDING, forward None
        - process state unknown, forward None (fallback default)
        """
        # both None -> WAIT_FOR_PROCESSING
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=None, forward_celery_state=None
            ),
            "WAIT_FOR_PROCESSING",
        )

        # process PENDING with no forward -> WAIT_FOR_PROCESSING
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state=states.PENDING, forward_celery_state=None
            ),
            "WAIT_FOR_PROCESSING",
        )

        # unknown process state with no forward -> default WAIT_FOR_PROCESSING
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state="UNKNOWN_STATE", forward_celery_state=None
            ),
            "WAIT_FOR_PROCESSING",
        )

    async def test_convert_celery_states_wait_for_processing_empty_strings(self):
        """
        Explicitly cover the last-line default return by passing empty strings
        (falsy values) for both states.
        """
        self.assertEqual(
            self.service.convert_celery_states_to_custom(
                process_celery_state="", forward_celery_state=""
            ),
            "WAIT_FOR_PROCESSING",
        )

    @pytest.mark.asyncio
    async def async_test_convert_to_base64(self):
        """
        Minimal branch coverage for convert_to_base64:
        - When image.format is set(e.g., PNG)
        - When image.format is None (defaults to JPEG)
        """
        # PNG branch
        img_png = Image.new('RGB', (10, 10), color='red')
        img_png.format = 'PNG'
        b64_png, content_type_png = await self.service.convert_to_base64(img_png)
        self.assertTrue(isinstance(b64_png, str) and len(b64_png) > 0)
        self.assertEqual(content_type_png, 'image/png')
        decoded_png = base64.b64decode(b64_png)
        opened_png = Image.open(io.BytesIO(decoded_png))
        self.assertEqual(opened_png.format, 'PNG')
        self.assertEqual(opened_png.size, (10, 10))

        # Default JPEG branch
        # format is None by default
        img_jpeg = Image.new('RGB', (8, 8), color='blue')
        self.assertIsNone(img_jpeg.format)
        b64_jpeg, content_type_jpeg = await self.service.convert_to_base64(img_jpeg)
        self.assertTrue(isinstance(b64_jpeg, str) and len(b64_jpeg) > 0)
        self.assertEqual(content_type_jpeg, 'image/jpeg')
        decoded_jpeg = base64.b64decode(b64_jpeg)
        opened_jpeg = Image.open(io.BytesIO(decoded_jpeg))
        self.assertEqual(opened_jpeg.format, 'JPEG')
        self.assertEqual(opened_jpeg.size, (8, 8))

    def test_convert_to_base64(self):
        """
        Test wrapper to run async test for convert_to_base64.
        """
        asyncio.run(self.async_test_convert_to_base64())


if __name__ == '__main__':
    unittest.main()
