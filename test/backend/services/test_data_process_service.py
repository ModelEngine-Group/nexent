import unittest
import os
import io
import base64
import tempfile
import asyncio
from unittest.mock import patch, MagicMock, Mock, call, AsyncMock
import warnings
from PIL import Image
import torch

# Set required environment variables
os.environ['REDIS_URL'] = 'redis://mock:6379/0'
os.environ['REDIS_BACKEND_URL'] = 'redis://mock:6379/0'

# Mock data_process.app module and consts.const
import sys
from unittest.mock import MagicMock

# Mock celery_app - each test will set the appropriate behavior
sys.modules['data_process.app'] = MagicMock()
sys.modules['data_process.app'].app = MagicMock()

# Mock constants from consts.const
mock_const = MagicMock()
mock_const.CLIP_MODEL_PATH = "mock_clip_path"
mock_const.IMAGE_FILTER = True
sys.modules['consts.const'] = mock_const

# Import the module to be tested
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
        import data_process.app
        data_process.app.app = MagicMock()
        self.mock_celery_app = data_process.app.app

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
            'redis://localhost:6379/0',
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

        # Create a fresh instance to trigger init
        service = DataProcessService()

        # Assert that Redis was not initialized
        mock_pool.assert_not_called()
        self.assertIsNone(service.redis_client)
        self.assertIsNone(service.redis_pool)

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
        self.assertTrue(self.service.check_image_size(150, 150, min_width=100, min_height=100))
        self.assertFalse(self.service.check_image_size(150, 150, min_width=200, min_height=200))

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
        mock_celery_app.control.inspect.side_effect = Exception("Failed to create inspector")

        # Verify exception is raised
        with self.assertRaises(Exception) as context:
            self.service._get_celery_inspector()

        # Verify exception message
        self.assertIn("Failed to create inspector with celery_app", str(context.exception))

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

        mock_celery_app.control.inspect.side_effect = [mock_inspector1, mock_inspector2]

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

    @patch('data_process.utils.get_task_info')
    async def async_test_get_task(self, mock_get_task_info):
        """
        Async implementation of get_task testing.

        This test verifies that the service correctly retrieves task information by ID.
        It ensures that:
        1. The utility function is called with the correct task ID
        2. The task data is returned as-is from the utility function
        """
        # Setup mock
        task_data = {"id": "task1", "status": "SUCCESS"}
        mock_get_task_info.return_value = task_data

        # Get task
        result = await self.service.get_task("task1")

        # Verify result
        self.assertEqual(result, task_data)
        mock_get_task_info.assert_called_once_with("task1")

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
        self.assertEqual(len(result), 4)
        task_ids = [task['id'] for task in result]
        self.assertIn('task1', task_ids)
        self.assertIn('task2', task_ids)
        self.assertIn('task3', task_ids)
        self.assertIn('task4', task_ids)
        self.assertNotIn('task5', task_ids)

        # Get all tasks without filtering
        result = await self.service.get_all_tasks(filter=False)

        # Verify result (should include all tasks)
        self.assertEqual(len(result), 5)
        task_ids = [task['id'] for task in result]
        self.assertIn('task5', task_ids)

    def test_get_all_tasks(self):
        """
        Test retrieval of all tasks.

        This test serves as a wrapper to run the async test for get_all_tasks.
        It verifies that the service can retrieve a comprehensive list of all tasks
        from both Celery (active and reserved) and Redis (completed).
        """
        asyncio.run(self.async_test_get_all_tasks())

    @patch('backend.services.data_process_service.DataProcessService.get_all_tasks')
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

    def test_load_image(self):
        """
        Test image loading from various sources.

        This test serves as a wrapper to run the async tests for load_image.
        It verifies that the service can load images from:
        1. URLs (with both success and failure cases)
        2. Base64-encoded data
        3. Local files
        """
        asyncio.run(self.async_test_load_image_from_url())
        asyncio.run(self.async_test_load_image_from_url_failure())
        asyncio.run(self.async_test_load_image_from_base64())
        asyncio.run(self.async_test_load_image_from_file())

    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
    @patch('backend.services.data_process_service.DataProcessService._init_clip_model')
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
        mock_load_image.assert_called_once_with("http://example.com/small_image.png")
        mock_check_size.assert_called_once_with(100, 100)
        mock_init_clip.assert_not_called()  # CLIP should not be initialized

    @patch('backend.services.data_process_service.IMAGE_FILTER', False)
    @patch('backend.services.data_process_service.DataProcessService.load_image')
    @patch('backend.services.data_process_service.DataProcessService.check_image_size')
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
    @patch('backend.services.data_process_service.DataProcessService._init_clip_model')
    async def async_test_filter_important_image_clip_not_available(self, mock_init_clip, mock_check_size, mock_load_image):
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
    @patch('torch.no_grad')
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

    def test_filter_important_image(self):
        """
        Test image importance filtering.

        This test serves as a wrapper to run the async tests for filter_important_image.
        It verifies that the service can filter images based on:
        1. Size requirements
        2. CLIP model assessment when available
        3. Global configuration settings
        """
        asyncio.run(self.async_test_filter_important_image_size_filter())
        asyncio.run(self.async_test_filter_important_image_filter_disabled())
        asyncio.run(self.async_test_filter_important_image_clip_not_available())
        asyncio.run(self.async_test_filter_important_image_with_clip())

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


if __name__ == '__main__':
    unittest.main()
