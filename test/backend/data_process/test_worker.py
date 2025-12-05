import sys
import types
import importlib
import pytest
import os


class FakeRay:
    def __init__(self, initialized=False):
        self._initialized = initialized
        self.inits = []

    def is_initialized(self):
        return self._initialized

    def init(self, **kwargs):
        self._initialized = True
        self.inits.append(kwargs)


def setup_mocks_for_worker(mocker, initialized=False):
    """Setup all necessary mocks before importing worker module"""
    fake_ray = FakeRay(initialized=initialized)
    
    # Mock ray module
    mocker.patch.dict(sys.modules, {"ray": fake_ray})
    
    # Stub consts.const module
    if "consts" not in sys.modules:
        sys.modules["consts"] = types.ModuleType("consts")
        setattr(sys.modules["consts"], "__path__", [])
    if "consts.const" not in sys.modules:
        const_mod = types.ModuleType("consts.const")
        const_mod.CELERY_TASK_TIME_LIMIT = 3600
        const_mod.CELERY_WORKER_PREFETCH_MULTIPLIER = 1
        const_mod.ELASTICSEARCH_SERVICE = "http://elasticsearch:9200"
        const_mod.QUEUES = "process_q,forward_q"
        const_mod.RAY_ADDRESS = "auto"
        const_mod.RAY_preallocate_plasma = False
        const_mod.REDIS_URL = "redis://localhost:6379"
        const_mod.REDIS_BACKEND_URL = "redis://localhost:6379"
        const_mod.WORKER_CONCURRENCY = 4
        const_mod.WORKER_NAME = None
        const_mod.FORWARD_REDIS_RETRY_DELAY_S = 0
        const_mod.FORWARD_REDIS_RETRY_MAX = 1
        const_mod.DISABLE_RAY_DASHBOARD = False
        const_mod.DATA_PROCESS_SERVICE = "http://data-process"
        const_mod.ROOT_DIR = "/mock/root"
        sys.modules["consts.const"] = const_mod
    
    # Stub celery module and submodules (required by tasks.py imported via __init__.py)
    if "celery.backends.base" not in sys.modules:
        backends_base_mod = types.ModuleType("celery.backends.base")
        backends_base_mod.DisabledBackend = type("DisabledBackend", (), {})
        sys.modules["celery.backends.base"] = backends_base_mod
    
    if "celery.exceptions" not in sys.modules:
        exceptions_mod = types.ModuleType("celery.exceptions")
        exceptions_mod.Retry = type("Retry", (Exception,), {})
        sys.modules["celery.exceptions"] = exceptions_mod
    
    if "celery.result" not in sys.modules:
        result_mod = types.ModuleType("celery.result")
        result_mod.AsyncResult = type("AsyncResult", (), {})
        sys.modules["celery.result"] = result_mod
    
    if "celery.signals" not in sys.modules:
        signals_mod = types.ModuleType("celery.signals")
        
        # Create fake signal objects with connect method
        class FakeSignal:
            def connect(self, func):
                return func
        
        signals_mod.worker_init = FakeSignal()
        signals_mod.worker_process_init = FakeSignal()
        signals_mod.worker_ready = FakeSignal()
        signals_mod.worker_shutting_down = FakeSignal()
        signals_mod.task_prerun = FakeSignal()
        signals_mod.task_postrun = FakeSignal()
        signals_mod.task_failure = FakeSignal()
        
        sys.modules["celery.signals"] = signals_mod
    
    if "celery" not in sys.modules:
        celery_mod = types.ModuleType("celery")
        # Create a Celery class that accepts any arguments and has required attributes
        class FakeBackend:
            pass
        
        class FakeCelery:
            def __init__(self, *args, **kwargs):
                # Set backend to a non-DisabledBackend instance
                self.backend = FakeBackend()
                # Create a conf object with update method
                self.conf = types.SimpleNamespace(update=lambda **kwargs: None)
            
            def task(self, *args, **kwargs):
                # Return a decorator that returns the function unchanged
                def decorator(func):
                    return func
                return decorator
        
        # Stub classes and functions needed by tasks.py
        celery_mod.Celery = FakeCelery
        celery_mod.Task = type("Task", (), {})
        celery_mod.chain = lambda *args: None
        celery_mod.states = types.SimpleNamespace(
            PENDING="PENDING",
            STARTED="STARTED",
            SUCCESS="SUCCESS",
            FAILURE="FAILURE",
            RETRY="RETRY",
            REVOKED="REVOKED"
        )
        sys.modules["celery"] = celery_mod
    
    # Stub consts.model (required by utils.file_management_utils)
    if "consts.model" not in sys.modules:
        model_mod = types.ModuleType("consts.model")
        class ProcessParams:
            def __init__(self, chunking_strategy: str, source_type: str, index_name: str, authorization: str | None):
                self.chunking_strategy = chunking_strategy
                self.source_type = source_type
                self.index_name = index_name
                self.authorization = authorization
        model_mod.ProcessParams = ProcessParams
        sys.modules["consts.model"] = model_mod
    
    # Stub database modules (required by utils.file_management_utils and ray_actors)
    if "database" not in sys.modules:
        db_pkg = types.ModuleType("database")
        setattr(db_pkg, "__path__", [])
        sys.modules["database"] = db_pkg
    if "database.attachment_db" not in sys.modules:
        sys.modules["database.attachment_db"] = types.SimpleNamespace(
            get_file_size_from_minio=lambda object_name, bucket=None: 0,
        )
        setattr(sys.modules["database"], "attachment_db", sys.modules["database.attachment_db"])
    if "database.model_management_db" not in sys.modules:
        sys.modules["database.model_management_db"] = types.SimpleNamespace(
            get_model_by_model_id=lambda model_id, tenant_id=None: None
        )
        setattr(sys.modules["database"], "model_management_db", sys.modules["database.model_management_db"])
    
    # Stub utils modules (required by utils.file_management_utils)
    if "utils.auth_utils" not in sys.modules:
        sys.modules["utils.auth_utils"] = types.SimpleNamespace(
            get_current_user_id=lambda authorization: ("user-test", "tenant-test")
        )
    if "utils.config_utils" not in sys.modules:
        cfg_mod = types.ModuleType("utils.config_utils")
        cfg_mod.tenant_config_manager = types.SimpleNamespace(
            load_config=lambda tenant_id: {}
        )
        sys.modules["utils.config_utils"] = cfg_mod
    
    # Stub external dependencies (required by utils.file_management_utils)
    if "aiofiles" not in sys.modules:
        sys.modules["aiofiles"] = types.SimpleNamespace(
            open=lambda *args, **kwargs: types.SimpleNamespace(
                __aenter__=lambda: types.SimpleNamespace(
                    write=lambda content: None,
                    __aexit__=lambda *args: None
                ),
                __aexit__=lambda *args: None
            )
        )
    if "httpx" not in sys.modules:
        sys.modules["httpx"] = types.SimpleNamespace()
    if "requests" not in sys.modules:
        sys.modules["requests"] = types.SimpleNamespace()
    if "fastapi" not in sys.modules:
        fastapi_mod = types.ModuleType("fastapi")
        fastapi_mod.UploadFile = type("UploadFile", (), {})
        sys.modules["fastapi"] = fastapi_mod
    
    # Stub utils.file_management_utils (required by tasks.py)
    if "utils.file_management_utils" not in sys.modules:
        file_utils_mod = types.ModuleType("utils.file_management_utils")
        file_utils_mod.get_file_size = lambda *args, **kwargs: 0
        sys.modules["utils.file_management_utils"] = file_utils_mod
    
    # Stub ray_actors (required by tasks.py)
    if "backend.data_process.ray_actors" not in sys.modules:
        ray_actors_mod = types.ModuleType("backend.data_process.ray_actors")
        ray_actors_mod.DataProcessorRayActor = type("DataProcessorRayActor", (), {})
        sys.modules["backend.data_process.ray_actors"] = ray_actors_mod
    
    # Stub aiohttp (required by tasks.py)
    if "aiohttp" not in sys.modules:
        sys.modules["aiohttp"] = types.SimpleNamespace()
    
    # Stub nexent.data_process (required by tasks.py)
    if "nexent.data_process" not in sys.modules:
        sys.modules["nexent.data_process"] = types.SimpleNamespace(
            DataProcessCore=type("_Core", (), {"__init__": lambda self: None, "file_process": lambda *a, **k: []})
        )
    
    # Stub app module
    if "backend.data_process.app" not in sys.modules:
        app_mod = types.ModuleType("backend.data_process.app")
        
        class FakeApp:
            def __init__(self):
                self.conf = types.SimpleNamespace(
                    broker_url="redis://localhost:6379/0",
                    result_backend="redis://localhost:6379/0",
                    task_routes={}
                )
            
            def worker_main(self, args):
                # Mock worker_main to avoid actually starting a worker
                pass
            
            def task(self, *args, **kwargs):
                # Return a decorator that returns the function unchanged
                def decorator(func):
                    return func
                return decorator
        
        app_mod.app = FakeApp()
        sys.modules["backend.data_process.app"] = app_mod
    
    # Stub ray_config module
    if "backend.data_process.ray_config" not in sys.modules:
        ray_config_mod = types.ModuleType("backend.data_process.ray_config")
        
        class FakeRayConfig:
            @classmethod
            def init_ray_for_worker(cls, address):
                return True
        
        ray_config_mod.RayConfig = FakeRayConfig
        sys.modules["backend.data_process.ray_config"] = ray_config_mod
    
    # Import and reload the module after mocks are in place
    import backend.data_process.worker as worker_module
    importlib.reload(worker_module)
    
    return worker_module, fake_ray


def test_validate_redis_connection_success(mocker):
    """Test successful Redis connection validation"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    class FakeRedisClient:
        def ping(self):
            return True
    
    class FakeRedis:
        @staticmethod
        def from_url(url, socket_timeout=5):
            return FakeRedisClient()

    # Patch redis module used inside validate_redis_connection
    fake_redis_module = types.SimpleNamespace(from_url=FakeRedis.from_url)
    mocker.patch.dict(sys.modules, {"redis": fake_redis_module})
    
    result = worker_module.validate_redis_connection()
    assert result is True


def test_validate_redis_connection_failure(mocker):
    """Test Redis connection validation failure"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    class FakeRedisClient:
        def ping(self):
            raise ConnectionError("Cannot connect to Redis")
    
    class FakeRedis:
        @staticmethod
        def from_url(url, socket_timeout=5):
            return FakeRedisClient()

    # Patch redis module so from_url returns a client that fails on ping
    fake_redis_module = types.SimpleNamespace(from_url=FakeRedis.from_url)
    mocker.patch.dict(sys.modules, {"redis": fake_redis_module})
    
    with pytest.raises(ConnectionError):
        worker_module.validate_redis_connection()


def test_validate_redis_connection_import_error(mocker):
    """Test Redis connection validation when redis module is not available"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    # Make redis import fail regardless of environment
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "redis":
            raise ImportError("No module named 'redis'")
        return real_import(name, *args, **kwargs)

    mocker.patch("builtins.__import__", side_effect=fake_import)
    
    result = worker_module.validate_redis_connection()
    assert result is False


def test_validate_service_connections_success(mocker):
    """Test successful service connections validation"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    class FakeRedisClient:
        def ping(self):
            return True
    
    class FakeRedis:
        @staticmethod
        def from_url(url, socket_timeout=5):
            return FakeRedisClient()

    # Patch redis module used by validate_service_connections -> validate_redis_connection
    fake_redis_module = types.SimpleNamespace(from_url=FakeRedis.from_url)
    mocker.patch.dict(sys.modules, {"redis": fake_redis_module})
    
    result = worker_module.validate_service_connections()
    assert result is True


def test_validate_service_connections_failure(mocker):
    """Test service connections validation failure"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    class FakeRedisClient:
        def ping(self):
            raise ConnectionError("Cannot connect")
    
    class FakeRedis:
        @staticmethod
        def from_url(url, socket_timeout=5):
            return FakeRedisClient()

    # Patch redis module so from_url returns a client that fails on ping
    fake_redis_module = types.SimpleNamespace(from_url=FakeRedis.from_url)
    mocker.patch.dict(sys.modules, {"redis": fake_redis_module})
    
    # Should return False, not raise
    result = worker_module.validate_service_connections()
    assert result is False


def test_start_worker_with_defaults(mocker):
    """Test start_worker with default configuration"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    # Mock os.getpid to return a fixed value
    mocker.patch("backend.data_process.worker.os.getpid", return_value=12345)
    
    # Mock app.worker_main to avoid actually starting a worker
    call_args = []
    
    def mock_worker_main(args):
        call_args.append(args)
    
    mocker.patch.object(worker_module.app, "worker_main", side_effect=mock_worker_main)
    
    # Call start_worker - it should not raise
    worker_module.start_worker()
    
    assert len(call_args) == 1
    args = call_args[0]
    assert 'worker' in args
    assert '--queues=process_q,forward_q' in args
    assert '--hostname=worker-12345@%h' in args
    assert '--concurrency=4' in args


def test_start_worker_with_custom_name(mocker):
    """Test start_worker with custom WORKER_NAME"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    # Set custom worker name
    if "consts.const" in sys.modules:
        sys.modules["consts.const"].WORKER_NAME = "custom-worker"
    
    # Reload to pick up new constant value
    importlib.reload(worker_module)
    
    call_args = []
    
    def mock_worker_main(args):
        call_args.append(args)
    
    mocker.patch.object(worker_module.app, "worker_main", side_effect=mock_worker_main)
    
    worker_module.start_worker()
    
    assert len(call_args) == 1
    args = call_args[0]
    assert '--hostname=custom-worker@%h' in args


def test_start_worker_keyboard_interrupt(mocker):
    """Test start_worker handling KeyboardInterrupt"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    def mock_worker_main(args):
        raise KeyboardInterrupt()
    
    mocker.patch.object(worker_module.app, "worker_main", side_effect=mock_worker_main)
    
    # Should handle KeyboardInterrupt gracefully
    with pytest.raises(SystemExit) as exc_info:
        worker_module.start_worker()
    assert exc_info.value.code == 0


def test_start_worker_exception(mocker):
    """Test start_worker handling general exceptions"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    def mock_worker_main(args):
        raise RuntimeError("Worker failed")
    
    mocker.patch.object(worker_module.app, "worker_main", side_effect=mock_worker_main)
    
    # Should exit with code 1 on error
    with pytest.raises(SystemExit) as exc_info:
        worker_module.start_worker()
    assert exc_info.value.code == 1


def test_worker_state_initialization(mocker):
    """Test that worker_state is properly initialized"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    assert 'initialized' in worker_module.worker_state
    assert 'ready' in worker_module.worker_state
    assert 'start_time' in worker_module.worker_state
    assert 'process_id' in worker_module.worker_state
    assert 'tasks_completed' in worker_module.worker_state
    assert 'tasks_failed' in worker_module.worker_state


def test_setup_worker_environment_ray_already_initialized(mocker):
    """Test setup_worker_environment when Ray is already initialized"""
    worker_module, fake_ray = setup_mocks_for_worker(mocker, initialized=True)
    
    fake_ray._initialized = True
    
    # Mock RayConfig.init_ray_for_worker
    init_called = []
    
    class FakeRayConfig:
        @classmethod
        def init_ray_for_worker(cls, address):
            init_called.append(address)
            return True
    
    mocker.patch.object(worker_module, "RayConfig", FakeRayConfig)
    
    # Call setup_worker_environment
    worker_module.setup_worker_environment()
    
    # Should not call init_ray_for_worker when Ray is already initialized
    assert len(init_called) == 0
    assert worker_module.worker_state['initialized'] is True


def test_setup_worker_environment_ray_init_success(mocker):
    """Test setup_worker_environment with successful Ray initialization"""
    worker_module, fake_ray = setup_mocks_for_worker(mocker, initialized=False)
    
    fake_ray._initialized = False
    
    init_called = []
    
    class FakeRayConfig:
        @classmethod
        def init_ray_for_worker(cls, address):
            init_called.append(address)
            return True
    
    mocker.patch.object(worker_module, "RayConfig", FakeRayConfig)
    
    worker_module.setup_worker_environment()
    
    assert len(init_called) == 1
    assert init_called[0] == "auto"
    assert worker_module.worker_state['initialized'] is True


def test_setup_worker_environment_sets_ray_preallocate_env(mocker):
    """Ensure setup_worker_environment sets RAY_preallocate_plasma env var"""
    worker_module, _ = setup_mocks_for_worker(mocker, initialized=False)

    # Force init success to avoid fallback path exceptions
    class FakeRayConfig:
        @classmethod
        def init_ray_for_worker(cls, address):
            return True

    mocker.patch.object(worker_module, "RayConfig", FakeRayConfig)

    worker_module.setup_worker_environment()

    assert os.environ.get("RAY_preallocate_plasma") == str(worker_module.RAY_preallocate_plasma).lower()


def test_setup_worker_environment_ray_init_fallback(mocker):
    """Test setup_worker_environment with Ray init fallback"""
    worker_module, fake_ray = setup_mocks_for_worker(mocker, initialized=False)
    
    fake_ray._initialized = False
    
    init_called = []
    
    class FakeRayConfig:
        @classmethod
        def init_ray_for_worker(cls, address):
            init_called.append(address)
            return False  # Return False to trigger fallback
    
    mocker.patch.object(worker_module, "RayConfig", FakeRayConfig)
    
    worker_module.setup_worker_environment()
    
    # Should call init_ray_for_worker, then fallback to direct ray.init
    assert len(init_called) == 1
    assert len(fake_ray.inits) == 1
    assert fake_ray.inits[0]["address"] == "auto"
    assert worker_module.worker_state['initialized'] is True


def test_setup_worker_environment_ray_init_failure(mocker):
    """Test setup_worker_environment with Ray initialization failure"""
    worker_module, fake_ray = setup_mocks_for_worker(mocker, initialized=False)
    
    fake_ray._initialized = False
    
    class FakeRayConfig:
        @classmethod
        def init_ray_for_worker(cls, address):
            raise ConnectionError("Cannot connect to Ray")
    
    mocker.patch.object(worker_module, "RayConfig", FakeRayConfig)
    
    # Should raise ConnectionError
    with pytest.raises(ConnectionError):
        worker_module.setup_worker_environment()


def test_setup_worker_process_resources_success(mocker):
    """Test setup_worker_process_resources success"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    class FakeRedisClient:
        def ping(self):
            return True
    
    class FakeRedis:
        @staticmethod
        def from_url(url, socket_timeout=5):
            return FakeRedisClient()

    # Patch redis module so validate_service_connections succeeds
    fake_redis_module = types.SimpleNamespace(from_url=FakeRedis.from_url)
    mocker.patch.dict(sys.modules, {"redis": fake_redis_module})
    mocker.patch("backend.data_process.worker.os.getpid", return_value=99999)
    
    # Should not raise
    worker_module.setup_worker_process_resources()
    
    assert worker_module.worker_state['services_validated'] is True


def test_setup_worker_process_resources_failure(mocker):
    """Test setup_worker_process_resources failure"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    # Force validate_service_connections to raise to exercise error handling path
    mocker.patch.object(
        worker_module,
        "validate_service_connections",
        side_effect=Exception("Service validation failed"),
    )
    
    # Should raise exception
    with pytest.raises(Exception):
        worker_module.setup_worker_process_resources()


def test_worker_ready_handler(mocker):
    """Test worker_ready_handler"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    worker_module.worker_state['start_time'] = 1000.0
    mocker.patch("backend.data_process.worker.os.getpid", return_value=12345)
    
    # Mock time.time to return a fixed value
    mocker.patch("backend.data_process.worker.time.time", return_value=1005.0)
    
    worker_module.worker_ready_handler()
    
    assert worker_module.worker_state['ready'] is True


def test_worker_shutdown_handler(mocker):
    """Test worker_shutdown_handler"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    worker_module.worker_state['process_id'] = 12345
    worker_module.worker_state['start_time'] = 1000.0
    worker_module.worker_state['tasks_completed'] = 10
    worker_module.worker_state['tasks_failed'] = 2
    
    mocker.patch("backend.data_process.worker.time.time", return_value=1005.0)
    
    # Should not raise
    worker_module.worker_shutdown_handler()


def test_task_prerun_handler(mocker):
    """Test task_prerun_handler"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    fake_task = types.SimpleNamespace(name="test_task")
    
    # Should not raise
    worker_module.task_prerun_handler(task=fake_task, task_id="task-123")


def test_task_postrun_handler_success(mocker):
    """Test task_postrun_handler with SUCCESS state"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    initial_completed = worker_module.worker_state['tasks_completed']
    
    fake_task = types.SimpleNamespace(name="test_task")
    worker_module.task_postrun_handler(task=fake_task, task_id="task-123", state="SUCCESS")
    
    assert worker_module.worker_state['tasks_completed'] == initial_completed + 1


def test_task_postrun_handler_other_state(mocker):
    """Test task_postrun_handler with non-SUCCESS state"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    initial_completed = worker_module.worker_state['tasks_completed']
    
    fake_task = types.SimpleNamespace(name="test_task")
    worker_module.task_postrun_handler(task=fake_task, task_id="task-123", state="FAILURE")
    
    # Should not increment completed count
    assert worker_module.worker_state['tasks_completed'] == initial_completed


def test_task_failure_handler(mocker):
    """Test task_failure_handler"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    initial_failed = worker_module.worker_state['tasks_failed']
    
    fake_sender = types.SimpleNamespace(name="test_task")
    fake_exception = ValueError("Test error")
    
    worker_module.task_failure_handler(
        sender=fake_sender,
        task_id="task-123",
        exception=fake_exception
    )
    
    assert worker_module.worker_state['tasks_failed'] == initial_failed + 1
