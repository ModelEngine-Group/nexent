# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from test.common.contract_stubs import install_shared_contract_stub
from test.common.contract_stubs import install_business_constant_stubs
import asyncio
import os
import sys
import types
import unittest
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery import states

# Set required environment variables
os.environ['REDIS_URL'] = 'redis://mock:6379/0'
os.environ['REDIS_BACKEND_URL'] = 'redis://mock:6379/0'

# Mock modules to prevent actual import chain
sys.modules['data_process.app'] = MagicMock()
sys.modules['data_process.app'].app = MagicMock()
sys.modules['data_process.tasks'] = MagicMock()
sys.modules['management.db.file.attachment'] = MagicMock()
sys.modules['infrastructure.rdb.client'] = MagicMock()
sys.modules["infrastructure.object_storage.client"] = sys.modules["infrastructure.rdb.client"]
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])
sys.modules['infrastructure.rdb.client'].minio_client = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['transformers'].CLIPProcessor = MagicMock()
sys.modules['transformers'].CLIPModel = MagicMock()
sys.modules['nexent'] = types.ModuleType('nexent')
sys.modules['nexent'].__path__ = [str(Path(__file__).resolve().parents[3] / "sdk/nexent")]
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'].ToolConfig = MagicMock()

# Add missing nexent.data_process module mock
sys.modules['nexent.data_process'] = MagicMock()
sys.modules['nexent.data_process.core'] = MagicMock()
sys.modules['nexent.data_process.core'].DataProcessCore = MagicMock()

# Mock constants from contracts.constants.environment
mock_const = MagicMock()
mock_const.CLIP_MODEL_PATH = "mock_clip_path"
mock_const.IMAGE_FILTER = True
mock_const.REDIS_BACKEND_URL = "redis://mock:6379/0"
mock_const.REDIS_URL = "redis://mock:6379/0"
mock_const.MAX_CONCURRENT_CONVERSIONS = 3
sys.modules['contracts.constants.environment'] = mock_const
install_business_constant_stubs(mock_const)

# Stub torch (data_process_service.py imports it unconditionally).
_torch_mod = types.ModuleType('torch')
_torch_mod.Tensor = type('Tensor', (), {})
_torch_mod.float16 = 'float16'
_torch_mod.no_grad = lambda: (_ for _ in ()).throw(StopIteration)  # callable that acts as context manager decorator
sys.modules.setdefault('torch', _torch_mod)

# Stub contracts.agent — data_process_service.py imports BatchTaskRequest from it.
_model_mod = types.ModuleType('contracts.agent')


class _BatchTaskRequest:
    """Lightweight stand-in for contracts.knowledge.BatchTaskRequest.

    Implements just enough to support `request.sources` iteration that
    production code uses inside `create_batch_tasks_impl`.
    """

    def __init__(self, sources=None):
        self.sources = sources or []

_model_mod.BatchTaskRequest = _BatchTaskRequest
sys.modules.setdefault('contracts.agent', _model_mod)

# Stub contracts.errors.exceptions with real exception classes so assertRaises works correctly
_exceptions_mod = types.ModuleType('contracts.errors.exceptions')


class AppException(Exception):
    """Stub AppException carrying the production error-code contract."""

    def __init__(self, error_code=None, message=None):
        self.error_code = error_code
        self.message = message
        super().__init__(message or error_code or "application error")


class OfficeConversionException(Exception):
    """Stub OfficeConversionException used in tests."""


class FileTooLargeException(Exception):
    """Stub file-size validation exception."""


class UnsupportedFileTypeException(Exception):
    """Stub file-type validation exception."""


class QuotaExceededError(Exception):
    """Stub quota exception."""


_exceptions_mod.AppException = AppException
_exceptions_mod.OfficeConversionException = OfficeConversionException
_exceptions_mod.FileTooLargeException = FileTooLargeException
_exceptions_mod.UnsupportedFileTypeException = UnsupportedFileTypeException
_exceptions_mod.QuotaExceededError = QuotaExceededError
install_shared_contract_stub(_exceptions_mod, 'exceptions')

# Stub management.services.file.upload (new import in data_process_service)
if 'management.services.file.upload' not in sys.modules:
    import types as _types
    _utils_mod = _types.ModuleType('management.services.file.upload')
    _utils_mod.convert_office_to_pdf = AsyncMock()
    sys.modules['management.services.file.upload'] = _utils_mod

# Mock data_process.utils as a top-level module so patch('data_process.utils.get_task_info')
# resolves to a real module (otherwise it falls through to `from data_process.utils import ...`
# which would try to import the heavy .tasks chain).
_data_process_pkg = types.ModuleType('data_process')
_data_process_pkg.__path__ = [str(Path(__file__).resolve().parents[3] / "backend/data_process")]
sys.modules.setdefault('data_process', _data_process_pkg)
_data_process_utils = types.ModuleType('data_process.utils')
_data_process_utils.get_task_info = AsyncMock()
_data_process_utils.get_task_details = AsyncMock()
_data_process_utils.get_all_task_ids_from_redis = MagicMock()
sys.modules.setdefault('data_process.utils', _data_process_utils)

# Ensure `backend.services` is in sys.modules as a package so the dotted-path
# patch below resolves. Python's normal import system will resolve the submodule
# from `backend/services/` once the package is registered.
import os as _os

_backend_services_dir = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    '..', '..', '..', 'backend', 'services'
)
_backend_services_dir = _os.path.normpath(_backend_services_dir)
if 'backend.services' not in sys.modules:
    _bs_mod = types.ModuleType('backend.services')
    _bs_mod.__path__ = [_backend_services_dir]
    sys.modules['backend.services'] = _bs_mod

# Import the service module first. By this point the mocks for `data_process.*`,
# `nexent.data_process.core`, `transformers`, `torch`, etc. are already in
# sys.modules so the heavy import chain succeeds. This also installs the module
# under sys.modules, so the subsequent patch(...) call resolves correctly.
import data_process.services.tasks as _dps

del _dps

# from data_process.services.tasks import DataProcessService, get_data_process_service
with patch('data_process.utils.get_task_info') as mock_get_task_info, \
        patch('data_process.services.tasks.get_all_task_ids_from_redis') as mock_get_redis_task_ids:
    from data_process.services.tasks import (
        DataProcessService,
        get_data_process_service,
    )


class TestDataProcessService(unittest.TestCase):

    class _NopSemaphore:
        """Drop-in asyncio.Semaphore that never blocks.

        asyncio.Semaphore is bound to the event loop at creation time; using
        asyncio.run() in tests creates a new loop each time, so the module-level
        semaphore would deadlock. This stub avoids that issue completely.
        """

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    def setUp(self):
        """Set up test environment before each test"""
        # Create a clean instance for each test
        self.service = DataProcessService()
        # Store original environment to restore after tests
        self.original_env = os.environ.copy()
        # Suppress warnings during tests
        warnings.filterwarnings('ignore', category=UserWarning)

        # Replace module-level semaphore with a no-op to avoid asyncio loop issues
        import data_process.services.tasks as _dm
        self._dm = _dm
        self._orig_sem = _dm._conversion_semaphore
        self._nop_sem = TestDataProcessService._NopSemaphore()
        _dm._conversion_semaphore = self._nop_sem

        # Reset mocks for each test to prevent interference
        mock_celery_app = sys.modules['data_process.app'].app
        mock_celery_app.reset_mock()
        self.mock_celery_app = mock_celery_app

    def tearDown(self):
        """Clean up after each test"""
        # Restore the original semaphore
        self._dm._conversion_semaphore = self._orig_sem
        # Restore environment variables
        os.environ.clear()
        os.environ.update(self.original_env)

    @staticmethod
    def _make_stream(data: bytes):
        """Return a BytesIO stream containing *data*."""
        from io import BytesIO
        return BytesIO(data)

    @patch('data_process.services.tasks.redis.ConnectionPool.from_url')
    @patch('data_process.services.tasks.redis.Redis')
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

    @patch('data_process.services.tasks.redis.ConnectionPool.from_url')
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
        import data_process.services.tasks as dps_module
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

    @patch('data_process.services.tasks.redis.ConnectionPool.from_url')
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

    @patch('data_process.services.tasks.celery_app')
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

    @patch('data_process.services.tasks.celery_app')
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

    @patch('data_process.services.tasks.celery_app')
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

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.logger')
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

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.logger')
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

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.logger')
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

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.logger')
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

    @patch('data_process.services.tasks.get_task_info')
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

    @patch('data_process.services.tasks.get_task_details_info')
    @pytest.mark.asyncio
    async def test_get_task_details(self, mock_get_task_details):
        task_details = {"id": "task1", "status": "SUCCESS", "result": {"chunks_count": 1}}
        mock_get_task_details.return_value = task_details

        result = await self.service.get_task_details("task1")

        self.assertEqual(result, task_details)
        mock_get_task_details.assert_awaited_once_with("task1")

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.get_task_info')
    @patch('data_process.services.tasks.get_all_task_ids_from_redis')
    @pytest.mark.asyncio
    async def async_test_get_all_tasks(self, mock_get_redis_task_ids, mock_get_task_info, mock_celery_app):
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
        # Setup mocks — get_all_tasks creates short-timeout inspectors via celery_app
        mock_inspector = MagicMock()
        mock_inspector.active.return_value = {
            'worker1': [{'id': 'task1', 'kwargs': {'file_id': 'fid-runtime'}}, {'id': 'task2'}]
        }
        mock_inspector.reserved.return_value = {
            'worker1': [{'id': 'task3'}]
        }
        mock_celery_app.control.inspect.return_value = mock_inspector
        mock_celery_app.conf.broker_url = "redis://mock:6379/0"
        mock_celery_app.conf.result_backend = "redis://mock:6379/0"

        mock_get_redis_task_ids.return_value = ['task2', 'task4', 'task5']

        # Setup task info mock to return different task data
        async def mock_task_info(task_id):
            task_data = {
                'task1': {'id': 'task1', 'status': 'ACTIVE', 'index_name': 'index1', 'task_name': 'task_name1'},
                'task2': {'id': 'task2', 'status': 'ACTIVE', 'index_name': 'index2', 'task_name': 'task_name2'},
                'task3': {'id': 'task3', 'status': 'RESERVED', 'index_name': 'index3', 'task_name': 'task_name3'},
                'task4': {
                    'id': 'task4',
                    'status': 'SUCCESS',
                    'index_name': 'index4',
                    'task_name': 'task_name4',
                    'file_id': 'fid-result',
                },
                'task5': {'id': 'task5', 'status': 'FAILURE', 'index_name': None, 'task_name': None},
            }
            return task_data.get(task_id, {})

        mock_get_task_info.side_effect = mock_task_info

        # Get all tasks with filtering (excludes task5 which has no index_name and task_name)
        result = await self.service.get_all_tasks(filter=True)

        # task1-task4 have index_name + task_name; task5 is filtered out
        self.assertEqual(len(result), 4)
        self.assertEqual(next(task for task in result if task['id'] == 'task1')['file_id'], 'fid-runtime')
        self.assertEqual(next(task for task in result if task['id'] == 'task4')['file_id'], 'fid-result')

        # Get all tasks without filtering
        result = await self.service.get_all_tasks(filter=False)

        # All unique task IDs from Celery + Redis
        self.assertEqual(len(result), 5)

    def test_get_all_tasks(self):
        """
        Test retrieval of all tasks.

        This test serves as a wrapper to run the async test for get_all_tasks.
        It verifies that the service can retrieve a comprehensive list of all tasks
        from both Celery (active and reserved) and Redis (completed).
        """
        asyncio.run(self.async_test_get_all_tasks())

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.get_task_info')
    @patch('data_process.services.tasks.get_all_task_ids_from_redis')
    @pytest.mark.asyncio
    async def test_get_all_tasks_redis_error(self, mock_get_redis_task_ids, mock_get_task_info, mock_celery_app):
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
        mock_celery_app.control.inspect.return_value = mock_inspector
        mock_celery_app.conf.broker_url = "redis://mock:6379/0"
        mock_celery_app.conf.result_backend = "redis://mock:6379/0"

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

    @patch('data_process.services.tasks.DataProcessService.get_all_tasks')
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


        # No conversion should be called for RGB images


    @patch('data_process.services.tasks.DataProcessService')
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
        import data_process.services.tasks as dps_module
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

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_success(self, mock_submit_chain):
        """
        Async implementation for testing successful batch task creation.

        This test verifies that the service correctly creates batch tasks.
        It ensures that:
        1. Individual tasks are created for each source in the request
        2. submit_process_forward_chain is called with correct parameters
        3. Task IDs are collected and returned
        4. All valid source configurations are processed
        """
        mock_submit_chain.side_effect = ["task_id_1", "task_id_2"]

        from contracts.knowledge import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source': 'http://example.com/doc1.pdf',
                    'source_type': 'url',
                    'chunking_strategy': 'semantic',
                    'index_name': 'test_index_1',
                    'original_filename': 'doc1.pdf',
                    'file_id': 'fid-batch-1',
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

        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        self.assertEqual(result["task_ids"], ["task_id_1", "task_id_2"])
        self.assertEqual(result["status"], "success")
        self.assertEqual([item["status"] for item in result["results"]], ["SUBMITTED", "SUBMITTED"])
        self.assertEqual(mock_submit_chain.call_count, 2)

        expected_calls = [
            {
                'source': 'http://example.com/doc1.pdf',
                'source_type': 'url',
                'chunking_strategy': 'semantic',
                'index_name': 'test_index_1',
                'original_filename': 'doc1.pdf',
                'authorization': 'Bearer test_token',
                'embedding_model_id': None,
                'tenant_id': None,
                'telemetry_context': {},
                'file_id': 'fid-batch-1',
            },
            {
                'source': 'http://example.com/doc2.pdf',
                'source_type': 'url',
                'chunking_strategy': 'fixed',
                'index_name': 'test_index_2',
                'original_filename': 'doc2.pdf',
                'authorization': 'Bearer test_token',
                'embedding_model_id': None,
                'tenant_id': None,
                'telemetry_context': {},
            },
        ]
        actual_calls = [kwargs for args, kwargs in mock_submit_chain.call_args_list]
        self.assertEqual(actual_calls, expected_calls)

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_missing_source(self, mock_submit_chain):
        """
        Async implementation for testing batch task creation with missing source field.

        This test verifies that the service handles missing source field correctly.
        It ensures that:
        1. Tasks with missing 'source' field are skipped
        2. An error is logged for the invalid configuration
        3. Only valid source configurations are processed
        4. The method continues processing other sources
        """
        mock_submit_chain.return_value = "task_id_1"

        from contracts.knowledge import BatchTaskRequest
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

        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        self.assertEqual(result["task_ids"], ["task_id_1"])
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["results"][0]["error_code"], "000103")
        mock_submit_chain.assert_called_once()
        self.assertEqual(
            mock_submit_chain.call_args[1]['source'], 'http://example.com/doc2.pdf')
        self.assertEqual(
            mock_submit_chain.call_args[1]['index_name'], 'test_index_2')

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_missing_index_name(self, mock_submit_chain):
        """
        Async implementation for testing batch task creation with missing index_name field.

        This test verifies that the service handles missing index_name field correctly.
        It ensures that:
        1. Tasks with missing 'index_name' field are skipped
        2. An error is logged for the invalid configuration
        3. Only valid source configurations are processed
        4. The method continues processing other sources
        """
        mock_submit_chain.return_value = "task_id_1"

        from contracts.knowledge import BatchTaskRequest
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

        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        self.assertEqual(result["task_ids"], ["task_id_1"])
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["results"][0]["error_code"], "000103")
        mock_submit_chain.assert_called_once()
        self.assertEqual(
            mock_submit_chain.call_args[1]['source'], 'http://example.com/doc2.pdf')
        self.assertEqual(
            mock_submit_chain.call_args[1]['index_name'], 'test_index_2')

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_missing_both_required_fields(self, mock_submit_chain):
        """
        Async implementation for testing batch task creation with both required fields missing.

        This test verifies that the service handles multiple invalid configurations correctly.
        It ensures that:
        1. Tasks with missing required fields are skipped
        2. Errors are logged for invalid configurations
        3. No tasks are created when all sources are invalid
        4. The method returns an empty list
        """
        from contracts.knowledge import BatchTaskRequest
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

        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        self.assertEqual(result["task_ids"], [])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_count"], 2)
        mock_submit_chain.assert_not_called()

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_empty_sources(self, mock_submit_chain):
        """
        Async implementation for testing batch task creation with empty sources list.

        This test verifies that the service handles empty sources list correctly.
        It ensures that:
        1. No tasks are created when sources list is empty
        2. The method returns an empty list
        3. No errors occur during processing
        """
        from contracts.knowledge import BatchTaskRequest
        request = BatchTaskRequest(sources=[])

        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        self.assertEqual(result["task_ids"], [])
        self.assertEqual(result["results"], [])
        self.assertEqual(result["status"], "success")
        mock_submit_chain.assert_not_called()

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_optional_fields(self, mock_submit_chain):
        """
        Async implementation for testing batch task creation with optional fields.

        This test verifies that the service handles optional fields correctly.
        It ensures that:
        1. Tasks are created even when optional fields are missing
        2. Optional fields are passed as None when not provided
        3. The method processes all valid sources regardless of optional field presence
        """
        mock_submit_chain.return_value = "task_id_1"

        from contracts.knowledge import BatchTaskRequest
        request = BatchTaskRequest(
            sources=[
                {
                    'source': 'http://example.com/doc1.pdf',
                    'index_name': 'test_index_1'
                    # Only required fields, optional fields missing
                }
            ]
        )

        result = await self.service.create_batch_tasks_impl("Bearer test_token", request)

        self.assertEqual(result["task_ids"], ["task_id_1"])
        mock_submit_chain.assert_called_once()
        kwargs = mock_submit_chain.call_args[1]
        self.assertEqual(kwargs['source'], 'http://example.com/doc1.pdf')
        self.assertEqual(kwargs['index_name'], 'test_index_1')
        self.assertIsNone(kwargs['source_type'])
        self.assertIsNone(kwargs['chunking_strategy'])
        self.assertIsNone(kwargs['original_filename'])
        self.assertEqual(kwargs['authorization'], 'Bearer test_token')

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_no_authorization(self, mock_submit_chain):
        """
        Async implementation for testing batch task creation without authorization.

        This test verifies that the service handles missing authorization correctly.
        It ensures that:
        1. Tasks are created even when authorization is None
        2. None is passed as authorization parameter
        3. The method processes all valid sources
        """
        mock_submit_chain.return_value = "task_id_1"

        from contracts.knowledge import BatchTaskRequest
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

        result = await self.service.create_batch_tasks_impl(None, request)

        self.assertEqual(result["task_ids"], ["task_id_1"])
        mock_submit_chain.assert_called_once()
        kwargs = mock_submit_chain.call_args[1]
        self.assertEqual(kwargs['source'], 'http://example.com/doc1.pdf')
        self.assertEqual(kwargs['index_name'], 'test_index_1')
        self.assertIsNone(kwargs['authorization'])

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

    @patch('data_process.services.tasks.submit_process_forward_chain')
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_continues_after_submission_exception(self, mock_submit_chain):
        """A single Celery submission exception must not discard later files."""
        mock_submit_chain.side_effect = [RuntimeError("broker unavailable"), "task_id_2"]

        from contracts.knowledge import BatchTaskRequest
        request = BatchTaskRequest(sources=[
            {"source": "/tmp/a.txt", "source_type": "local", "index_name": "idx", "file_id": "fid-a"},
            {"source": "/tmp/b.txt", "source_type": "local", "index_name": "idx", "file_id": "fid-b"},
        ])

        result = await self.service.create_batch_tasks_impl("Bearer token", request)

        self.assertEqual(result["task_ids"], ["task_id_2"])
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["results"][0]["file_id"], "fid-a")
        self.assertEqual(result["results"][0]["error_code"], "060108")
        self.assertEqual(result["results"][1]["task_id"], "task_id_2")

    def test_create_batch_tasks_impl_submission_exception(self):
        asyncio.run(self.async_test_create_batch_tasks_impl_continues_after_submission_exception())

    @patch('data_process.services.tasks.submit_process_forward_chain', return_value="")
    @pytest.mark.asyncio
    async def async_test_create_batch_tasks_impl_empty_task_id(self, mock_submit_chain):
        """An empty task id is reported as a durable per-file submission failure."""
        from contracts.knowledge import BatchTaskRequest
        request = BatchTaskRequest(sources=[{
            "source": "/tmp/a.txt",
            "source_type": "local",
            "index_name": "idx",
            "original_filename": "a.txt",
            "file_id": "fid-a",
        }])

        result = await self.service.create_batch_tasks_impl("Bearer token", request)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["results"][0]["file_id"], "fid-a")
        mock_submit_chain.assert_called_once()

    def test_create_batch_tasks_impl_empty_task_id(self):
        asyncio.run(self.async_test_create_batch_tasks_impl_empty_task_id())


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


    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_size_from_minio')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_success(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_get_size, mock_upload, mock_convert
    ):
        """Happy path: full pipeline completes and temp dir is cleaned up."""
        mock_get_stream.side_effect = [
            self._make_stream(b'DOC data'),      # Step 1: original file
            self._make_stream(b'%PDF-1.4 ok'),   # Step 4: header check
        ]
        mock_get_size.return_value = 208
        mock_upload.return_value = {'success': True}
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'

        with patch('builtins.open', MagicMock()):
            asyncio.run(
                self.service.convert_office_to_pdf_impl(
                    'uploads/doc.docx', 'converted/doc.pdf'
                )
            )

        mock_convert.assert_called_once()
        mock_rmtree.assert_called_once_with('/tmp/test_cv')

    @patch('data_process.services.tasks.get_file_stream',
           return_value=None)
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_source_not_found(
        self, _exists, _mkdtemp, mock_rmtree, _get_stream
    ):
        """Source file missing → OfficeConversionException."""
        # Prevent cleanup path from calling real delete_file
        sys.modules['management.db.file.attachment'].file_exists = MagicMock(
            return_value=False
        )
        with self.assertRaises(OfficeConversionException) as ctx:
            asyncio.run(
                self.service.convert_office_to_pdf_impl(
                    'uploads/missing.docx', 'converted/missing.pdf'
                )
            )
        self.assertIn('Source file not found', str(ctx.exception))

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_libreoffice_failure(
        self, _exists, _mkdtemp, mock_rmtree, mock_get_stream, mock_convert
    ):
        """LibreOffice error → OfficeConversionException."""
        mock_get_stream.return_value = self._make_stream(b'DOC data')
        mock_convert.side_effect = RuntimeError('soffice not found')
        sys.modules['management.db.file.attachment'].file_exists = MagicMock(
            return_value=False
        )
        with patch('builtins.open', MagicMock()):
            with self.assertRaises(OfficeConversionException) as ctx:
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        self.assertIn('LibreOffice conversion failed', str(ctx.exception))

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_upload_failure(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_upload, mock_convert
    ):
        """Upload failure → OfficeConversionException with error detail."""
        mock_get_stream.return_value = self._make_stream(b'DOC data')
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'
        mock_upload.return_value = {'success': False, 'error': 'quota exceeded'}
        sys.modules['management.db.file.attachment'].file_exists = MagicMock(
            return_value=False
        )
        with patch('builtins.open', MagicMock()):
            with self.assertRaises(OfficeConversionException) as ctx:
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        self.assertIn('Failed to upload PDF', str(ctx.exception))

    @patch('data_process.services.tasks.delete_file')
    @patch('data_process.services.tasks.file_exists', return_value=True)
    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_size_from_minio')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_invalid_pdf_header(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_get_size, mock_upload, mock_convert,
        mock_file_exists, mock_delete_file
    ):
        """Invalid PDF header → OfficeConversionException; remote file deleted."""
        mock_get_stream.side_effect = [
            self._make_stream(b'DOC data'),      # Step 1: original file
            self._make_stream(b'NOT-PDF'),       # Step 4: header check
        ]
        mock_get_size.return_value = 208
        mock_upload.return_value = {'success': True}
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'

        with patch('builtins.open', MagicMock()):
            with self.assertRaises(OfficeConversionException) as ctx:
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        self.assertIn('invalid PDF header', str(ctx.exception))
        mock_delete_file.assert_called_once_with('converted/doc.pdf')

    @patch('data_process.services.tasks.file_exists', return_value=False)
    @patch('data_process.services.tasks.get_file_stream', return_value=None)
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_no_remote_cleanup_when_not_exists(
        self, _exists, _mkdtemp, mock_rmtree, _get_stream, mock_file_exists
    ):
        """OfficeConversionException raised and file_exists=False → delete_file never called."""
        with patch('data_process.services.tasks.delete_file') as mock_del:
            with self.assertRaises(OfficeConversionException):
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        mock_del.assert_not_called()

    @patch('data_process.services.tasks.get_file_stream', return_value=None)
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', side_effect=OSError('no space left on device'))
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_mkdtemp_failure(
        self, _exists, mock_mkdtemp, mock_rmtree, _get_stream
    ):
        """tempfile.mkdtemp raises → temp_dir stays None → finally skips cleanup."""
        with self.assertRaises(OfficeConversionException) as ctx:
            asyncio.run(
                self.service.convert_office_to_pdf_impl(
                    'uploads/doc.docx', 'converted/doc.pdf'
                )
            )
        self.assertIn('Unexpected error', str(ctx.exception))
        mock_rmtree.assert_not_called()

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_size_from_minio')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_size_zero(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_get_size, mock_upload, mock_convert
    ):
        """remote_size == 0 → OfficeConversionException: cannot read remote file size."""
        mock_get_stream.return_value = self._make_stream(b'DOC data')
        mock_get_size.return_value = 0
        mock_upload.return_value = {'success': True}
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'
        sys.modules['management.db.file.attachment'].file_exists = MagicMock(return_value=False)
        with patch('builtins.open', MagicMock()):
            with self.assertRaises(OfficeConversionException) as ctx:
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        self.assertIn('cannot read remote file size', str(ctx.exception))

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_size_from_minio')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_size_too_small(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_get_size, mock_upload, mock_convert
    ):
        """remote_size < 100 (but > 0) → OfficeConversionException: file too small."""
        mock_get_stream.return_value = self._make_stream(b'DOC data')
        mock_get_size.return_value = 50
        mock_upload.return_value = {'success': True}
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'
        sys.modules['management.db.file.attachment'].file_exists = MagicMock(return_value=False)
        with patch('builtins.open', MagicMock()):
            with self.assertRaises(OfficeConversionException) as ctx:
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        self.assertIn('file too small', str(ctx.exception))

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_size_from_minio')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_stream_none(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_get_size, mock_upload, mock_convert
    ):
        """get_file_stream returns None for header check → OfficeConversionException."""
        mock_get_stream.side_effect = [
            self._make_stream(b'DOC data'),  # Step 1: original file
            None,                            # Step 4: header check stream
        ]
        mock_get_size.return_value = 208
        mock_upload.return_value = {'success': True}
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'
        sys.modules['management.db.file.attachment'].file_exists = MagicMock(return_value=False)
        with patch('builtins.open', MagicMock()):
            with self.assertRaises(OfficeConversionException) as ctx:
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        self.assertIn('cannot read uploaded file', str(ctx.exception))

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_size_from_minio')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_close_raises(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_get_size, mock_upload, mock_convert
    ):
        """stream.close() raises during header check → exception swallowed, pipeline succeeds."""
        header_stream = MagicMock()
        header_stream.read.return_value = b'%PDF-1.4'
        header_stream.close.side_effect = OSError('close failed')
        mock_get_stream.side_effect = [
            self._make_stream(b'DOC data'),  # Step 1: original file
            header_stream,                   # Step 4: header check
        ]
        mock_get_size.return_value = 208
        mock_upload.return_value = {'success': True}
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'
        with patch('builtins.open', MagicMock()):
            asyncio.run(
                self.service.convert_office_to_pdf_impl(
                    'uploads/doc.docx', 'converted/doc.pdf'
                )
            )
        mock_convert.assert_called_once()

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_unexpected_exception(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_upload, mock_convert
    ):
        """Non-OfficeConversionException from upload_file → wrapped as OfficeConversionException."""
        mock_get_stream.return_value = self._make_stream(b'DOC data')
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'
        mock_upload.side_effect = ConnectionError('storage unreachable')
        with patch('builtins.open', MagicMock()):
            with self.assertRaises(OfficeConversionException) as ctx:
                asyncio.run(
                    self.service.convert_office_to_pdf_impl(
                        'uploads/doc.docx', 'converted/doc.pdf'
                    )
                )
        self.assertIn('Unexpected error', str(ctx.exception))

    @patch('data_process.services.tasks.convert_office_to_pdf',
           new_callable=AsyncMock)
    @patch('data_process.services.tasks.upload_file')
    @patch('data_process.services.tasks.get_file_size_from_minio')
    @patch('data_process.services.tasks.get_file_stream')
    @patch('shutil.rmtree')
    @patch('tempfile.mkdtemp', return_value='/tmp/test_cv')
    @patch('os.path.exists', return_value=True)
    def test_convert_office_to_pdf_impl_cleanup_failure(
        self, _exists, _mkdtemp, mock_rmtree,
        mock_get_stream, mock_get_size, mock_upload, mock_convert
    ):
        """shutil.rmtree raises during cleanup → error is logged, not re-raised."""
        mock_get_stream.side_effect = [
            self._make_stream(b'DOC data'),     # Step 1: original file
            self._make_stream(b'%PDF-1.4 ok'),  # Step 4: header check
        ]
        mock_get_size.return_value = 208
        mock_upload.return_value = {'success': True}
        mock_convert.return_value = '/tmp/test_cv/doc.pdf'
        mock_rmtree.side_effect = OSError('permission denied')
        with patch('builtins.open', MagicMock()):
            # Cleanup error must not propagate
            asyncio.run(
                self.service.convert_office_to_pdf_impl(
                    'uploads/doc.docx', 'converted/doc.pdf'
                )
            )

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.get_all_task_ids_from_redis', return_value=[])
    @patch('data_process.services.tasks.get_task_info')
    def test_get_all_tasks_handles_string_kwargs_and_bad_json(
        self, mock_get_task_info, _mock_ids, mock_celery_app
    ):
        """Cover runtime kwargs normalization fallback branches."""
        mock_inspector = MagicMock()
        mock_inspector.active.return_value = {
            "w1": [{
                "id": "task-1",
                "name": "data_process.tasks.process",
                "kwargs": "{bad-json"
            }]
        }
        mock_inspector.reserved.return_value = {
            "w1": [{
                "id": "task-2",
                "name": "data_process.tasks.forward",
                "kwargs": ["not-a-dict"],
            }]
        }
        mock_celery_app.control.inspect.return_value = mock_inspector
        mock_celery_app.conf.broker_url = "redis://mock:6379/0"
        mock_celery_app.conf.result_backend = "redis://mock:6379/0"

        async def _run():
            async def _task_info(task_id):
                return {
                    "id": task_id,
                    "task_name": "",
                    "index_name": "",
                    "path_or_url": "",
                    "original_filename": "",
                }

            mock_get_task_info.side_effect = _task_info
            rows = await self.service.get_all_tasks(filter=False)
            self.assertEqual(len(rows), 2)
            by_id = {row["id"]: row for row in rows}
            self.assertEqual(by_id["task-1"]["task_name"], "process")
            self.assertEqual(by_id["task-2"]["task_name"], "forward")

        asyncio.run(_run())


    # ---- Additional coverage tests ----

    def test_init_redis_client_no_url(self):
        """If REDIS_BACKEND_URL is empty, the warning branch fires."""
        with patch('data_process.services.tasks.REDIS_BACKEND_URL', ''):
            service = DataProcessService()
        self.assertIsNone(service.redis_pool)
        self.assertIsNone(service.redis_client)

    def test_init_redis_client_raises(self):
        """If redis.Redis raises, the except branch logs and leaves pool/client None."""
        from data_process.services import tasks as _dps
        original = _dps.redis
        fake_redis = MagicMock()
        fake_redis.ConnectionPool.from_url.side_effect = RuntimeError('boom')
        _dps.redis = fake_redis
        try:
            service = DataProcessService()
            self.assertIsNone(service.redis_pool)
            self.assertIsNone(service.redis_client)
        finally:
            _dps.redis = original

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.get_task_info')
    @patch('data_process.services.tasks.get_all_task_ids_from_redis')
    def test_get_all_tasks_inspector_raises(self, mock_get_redis_task_ids, mock_get_task_info, mock_celery_app):
        """If inspector raises, get_all_tasks returns empty tasks (with logged warning)."""
        mock_celery_app.conf.broker_url = "redis://mock:6379/0"
        mock_celery_app.conf.result_backend = "redis://mock:6379/0"
        mock_celery_app.control.inspect.return_value = MagicMock(
            active=MagicMock(side_effect=RuntimeError('inspect failed'))
        )

        async def _run():
            rows = await self.service.get_all_tasks(filter=False)
            self.assertEqual(rows, [])

        asyncio.run(_run())

    @patch('data_process.services.tasks.celery_app')
    @patch('data_process.services.tasks.get_task_info')
    @patch('data_process.services.tasks.get_all_task_ids_from_redis', return_value=[])
    def test_get_all_tasks_outer_exception(self, _mock_ids, mock_get_task_info, mock_celery_app):
        """If get_all_tasks raises during processing, empty list is returned."""
        mock_celery_app.conf.broker_url = "redis://mock:6379/0"
        mock_celery_app.conf.result_backend = "redis://mock:6379/0"

        # Make asyncio.gather raise by making get_task_info raise uncaught
        async def _raise(task_id):
            raise ValueError('simulated downstream failure')

        mock_get_task_info.side_effect = _raise

        mock_inspector = MagicMock()
        mock_inspector.active.return_value = {'w1': [{'id': 't1', 'name': 'process', 'kwargs': {}}]}
        mock_inspector.reserved.return_value = {}
        mock_celery_app.control.inspect.return_value = mock_inspector

        async def _run():
            # asyncio.gather with return_exceptions=True swallows per-task errors,
            # so we need to trigger the outer except instead.
            with patch('asyncio.gather', side_effect=RuntimeError('gather failed')):
                rows = await self.service.get_all_tasks(filter=False)
                self.assertEqual(rows, [])

        asyncio.run(_run())


if __name__ == '__main__':
    unittest.main()
