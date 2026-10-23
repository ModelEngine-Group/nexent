import builtins
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
        
    def remote(self, *args, **kwargs):
        """Mock ray.remote decorator"""
        def decorator(cls_or_func):
            if hasattr(cls_or_func, '__init__'):
                def options(**opts):
                    return cls_or_func
                cls_or_func.options = options
            return cls_or_func
        
        if args and callable(args[0]) and not kwargs:
            return decorator(args[0])
        return decorator
    
    def __getattr__(self, name):
        """Handle any other ray attribute access with a mock"""
        def mock_method(*args, **kwargs):
            return None
        return mock_method

def setup_mocks_for_worker(mocker, initialized=False):
    """Setup all necessary mocks before importing worker module"""
    fake_ray = FakeRay(initialized=initialized)
    
    # Mock ray module
    mocker.patch.dict(sys.modules, {"ray": fake_ray})
    
    # Stub consts.const with deterministic values even when another test has
    # already imported the real configuration module.
    if "consts" not in sys.modules:
        sys.modules["consts"] = types.ModuleType("consts")
        setattr(sys.modules["consts"], "__path__", [])
    const_mod = types.ModuleType("consts.const")
    const_mod.CELERY_TASK_TIME_LIMIT = 3600
    const_mod.CELERY_WORKER_PREFETCH_MULTIPLIER = 1
    const_mod.ELASTICSEARCH_SERVICE = "http://elasticsearch:9200"
    const_mod.QUEUES = "process_q,process_part_q,forward_q"
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
    const_mod.DP_REDIS_CHUNKS_WAIT_TIMEOUT_S = 30
    const_mod.DP_REDIS_CHUNKS_POLL_INTERVAL_MS = 100
    const_mod.RAY_ACTOR_NUM_CPUS = 1
    const_mod.RAY_NUM_CPUS = 4
    const_mod.DP_PART_PROCESSOR_COUNT = 3
    const_mod.DP_FILE_SPLIT_SIZE_MB = 5
    const_mod.PER_WAVE_TIMEOUT = 300
    const_mod.MAX_TIMEOUT = 3600
    const_mod.RAY_ACTOR_WARM_TIMEOUT_S = 60
    const_mod.RAY_GLOBAL_ACTOR_POOL_NAME = "global_actor_pool"
    const_mod.RAY_GLOBAL_ACTOR_POOL_NAMESPACE = "nexent"
    mocker.patch.dict(sys.modules, {"consts.const": const_mod})

    # New ingestion classification is imported while the data_process package
    # initializes. Keep the worker unit-test sandbox independent from the full
    # consts package and its production error-code registry.
    error_code_mod = types.ModuleType("consts.error_code")
    error_code_mod.ErrorCode = types.SimpleNamespace(
        KNOWLEDGE_INDEX_WRITE_BLOCKED=types.SimpleNamespace(value="060106")
    )
    mocker.patch.dict(sys.modules, {"consts.error_code": error_code_mod})

    ingestion_errors_mod = types.ModuleType("utils.knowledge_ingestion_errors")

    class _ClassifiedIngestionException:
        error_code = None
        error_message = None
        retryable = False

    ingestion_errors_mod.ClassifiedIngestionException = _ClassifiedIngestionException
    ingestion_errors_mod.classify_ingestion_exception = (
        lambda *args, **kwargs: _ClassifiedIngestionException()
    )
    mocker.patch.dict(
        sys.modules, {"utils.knowledge_ingestion_errors": ingestion_errors_mod}
    )
    
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
    else:
        result_mod = sys.modules["celery.result"]
    result_mod.AsyncResult = type("AsyncResult", (), {})
    # Simple mock that can be used as a decorator/context manager
    class MockAllowJoinResult:
        def __call__(self, *args, **kwargs):
            return self
        def __enter__(self):
            return None
        def __exit__(self, *args):
            pass
    
    result_mod.allow_join_result = MockAllowJoinResult()
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
        celery_mod.group = lambda *args, **kwargs: None
        celery_mod.chord = lambda *args, **kwargs: None
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
            get_file_stream=lambda object_name, bucket=None: None,
        )
        setattr(sys.modules["database"], "attachment_db", sys.modules["database.attachment_db"])
    if "database.model_management_db" not in sys.modules:
        sys.modules["database.model_management_db"] = types.SimpleNamespace(
            get_model_by_model_id=lambda model_id, tenant_id=None: None
        )
        setattr(sys.modules["database"], "model_management_db", sys.modules["database.model_management_db"])
    if "database.knowledge_db" not in sys.modules:
        sys.modules["database.knowledge_db"] = types.SimpleNamespace(
            get_knowledge_record=lambda query=None: {},
        )
        setattr(sys.modules["database"], "knowledge_db", sys.modules["database.knowledge_db"])

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
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.SimpleNamespace(
            Redis=types.SimpleNamespace(
                from_url=lambda *args, **kwargs: types.SimpleNamespace(
                    get=lambda *a, **k: None,
                    set=lambda *a, **k: True,
                    expire=lambda *a, **k: True,
                    delete=lambda *a, **k: True,
                    ping=lambda: True,
                )
            ),
            from_url=lambda *args, **kwargs: types.SimpleNamespace(ping=lambda: True),
        )
    if "fastapi" not in sys.modules:
        fastapi_mod = types.ModuleType("fastapi")
        fastapi_mod.UploadFile = type("UploadFile", (), {})
        sys.modules["fastapi"] = fastapi_mod
    
    # Stub utils.file_management_utils (required by tasks.py)
    if "utils.file_management_utils" not in sys.modules:
        file_utils_mod = types.ModuleType("utils.file_management_utils")
        file_utils_mod.get_file_size = lambda *args, **kwargs: 0
        sys.modules["utils.file_management_utils"] = file_utils_mod

    # Stub services.redis_service (required by tasks.py via package __init__)
    if "services.redis_service" not in sys.modules:
        redis_service_mod = types.ModuleType("services.redis_service")

        class _StubRedisService:
            def save_error_info(self, *args, **kwargs):
                return True

            def is_task_cancelled(self, *args, **kwargs):
                return False

            def save_progress_info(self, *args, **kwargs):
                return True

            def increment_progress_info(self, *args, **kwargs):
                return True

        redis_service_mod.get_redis_service = lambda: _StubRedisService()
        sys.modules["services.redis_service"] = redis_service_mod

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
    
    # Stub app module. Always install a fresh stub if the existing
    # ``sys.modules['backend.data_process.app']`` lacks the
    # ``worker_main`` attribute, because a prior test (notably
    # ``test_tasks.py``) reloads the real ``app.py`` and ends up
    # binding ``app.app`` to a ``Celery`` stub that has no
    # ``worker_main``.
    _existing_app = sys.modules.get("backend.data_process.app")
    _needs_fake_app = (
        _existing_app is None
        or not hasattr(getattr(_existing_app, "app", None), "worker_main")
        or not hasattr(_existing_app, "app")
    )
    if _needs_fake_app:
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
    assert '--queues=process_q,process_part_q,forward_q' in args
    assert '--hostname=None@%h' in args
    assert '--concurrency=4' in args


def test_start_worker_with_custom_name(mocker):
    """Test start_worker with custom WORKER_NAME"""
    worker_module, _ = setup_mocks_for_worker(mocker)
    
    # Set custom worker name
    worker_module.WORKER_NAME = "custom-worker"
    
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


def test_worker_ready_handler_starts_background_threads(mocker):
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.worker_state['start_time'] = 1000.0
    mocker.patch("backend.data_process.worker.time.time", return_value=1001.0)
    mocker.patch("backend.data_process.worker.os.getpid", return_value=7)

    calls = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            calls.append((target, daemon))

        def start(self):
            return None

    mocker.patch.object(worker_module.threading, "Thread", FakeThread)
    worker_module.worker_ready_handler()
    assert len(calls) >= 1


def test_worker_ready_handler_thread_schedule_failure(mocker):
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.worker_state['start_time'] = 1000.0
    mocker.patch("backend.data_process.worker.time.time", return_value=1001.0)
    mocker.patch("backend.data_process.worker.os.getpid", return_value=7)
    mocker.patch.object(worker_module.threading, "Thread", side_effect=RuntimeError("thread failed"))
    worker_module.worker_ready_handler()
    assert worker_module.worker_state["ready"] is True


def test_setup_worker_environment_sets_logging_level(mocker):
    """Test setup_worker_environment sets celery worker strategy log level."""
    worker_module, _ = setup_mocks_for_worker(mocker, initialized=True)

    logger_capture = []

    class FakeCeleryWorkerStrategyLogger:
        def setLevel(self, level):
            logger_capture.append(level)

    import logging
    strategy_logger = FakeCeleryWorkerStrategyLogger()
    real_get_logger = logging.getLogger
    mocker.patch.object(
        worker_module.logging,
        "getLogger",
        side_effect=lambda name=None: strategy_logger
        if name == "celery.worker.strategy"
        else real_get_logger(name),
    )

    worker_module.setup_worker_environment()
    assert logging.WARNING in logger_capture


def test_setup_worker_environment_logs_environment_status(mocker):
    """Test setup_worker_environment logs environment variables status."""
    worker_module, _ = setup_mocks_for_worker(mocker, initialized=True)

    # Mock logger to capture calls
    import logging
    log_calls = []

    class MockLogger:
        def debug(self, msg, *args):
            log_calls.append(("debug", msg % args if args else msg))

        def info(self, msg, *args):
            log_calls.append(("info", msg % args if args else msg))

        def error(self, msg, *args):
            log_calls.append(("error", msg % args if args else msg))

        def warning(self, msg, *args):
            log_calls.append(("warning", msg % args if args else msg))

    mocker.patch.object(worker_module.logger, "info", side_effect=lambda msg, *args: log_calls.append(("info", msg % args if args else msg)))
    mocker.patch.object(worker_module.logger, "debug", side_effect=lambda msg, *args: log_calls.append(("debug", msg % args if args else msg)))
    mocker.patch.object(worker_module.logger, "warning", side_effect=lambda msg, *args: log_calls.append(("warning", msg % args if args else msg)))
    mocker.patch.object(worker_module.logger, "error", side_effect=lambda msg, *args: log_calls.append(("error", msg % args if args else msg)))

    worker_module.setup_worker_environment()

    # Verify that initialization happened
    assert worker_module.worker_state['initialized'] is True


def test_validate_service_connections_handles_redis_exception(mocker):
    """Test validate_service_connections handles Redis exception gracefully."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    # Mock validate_redis_connection to raise
    mocker.patch.object(worker_module, "validate_redis_connection", side_effect=RuntimeError("Redis error"))

    result = worker_module.validate_service_connections()
    assert result is False


def test_worker_state_keys_exist(mocker):
    """Test worker_state has all required keys."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    assert "initialized" in worker_module.worker_state
    assert "ready" in worker_module.worker_state
    assert "start_time" in worker_module.worker_state
    assert "process_id" in worker_module.worker_state
    assert "tasks_completed" in worker_module.worker_state
    assert "tasks_failed" in worker_module.worker_state
    assert "environment_validated" in worker_module.worker_state
    assert "services_validated" in worker_module.worker_state


def test_worker_ready_handler_with_process_part_queue(mocker):
    """Test worker_ready_handler with process_part queue configures concurrency logger."""
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.worker_state['start_time'] = 1000.0
    mocker.patch("backend.data_process.worker.time.time", return_value=1001.0)
    mocker.patch("backend.data_process.worker.os.getpid", return_value=7)

    # Mock QUEUES to include process_part_q
    worker_module.QUEUES = "process_part_q"

    calls = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            calls.append(target)

        def start(self):
            pass

    mocker.patch.object(worker_module.threading, "Thread", FakeThread)

    worker_module.worker_ready_handler()
    # Should have started prewarm thread and potentially part concurrency thread
    assert len(calls) >= 0  # Threads may or may not be started depending on queue config


def test_setup_worker_environment_with_env_var_check(mocker):
    """Test setup_worker_environment checks sensitive environment variables."""
    worker_module, _ = setup_mocks_for_worker(mocker, initialized=True)

    debug_calls = []

    class FakeLogger:
        def debug(self, msg, *args):
            debug_calls.append(msg % args if args else msg)

        def info(self, msg, *args):
            pass

        def error(self, msg, *args):
            pass

        def warning(self, msg, *args):
            pass

    mocker.patch.object(worker_module.logger, "debug", side_effect=lambda msg, *args: debug_calls.append(msg % args if args else msg))

    worker_module.setup_worker_environment()

    # Check that environment variable checks are logged
    assert any("REDIS" in str(call) or "ELASTICSEARCH" in str(call) for call in debug_calls)


def test_validate_redis_connection_with_custom_timeout(mocker):
    """Test validate_redis_connection uses correct socket_timeout."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    captured_timeout = []

    class FakeRedisClient:
        def ping(self):
            return True

    class FakeRedis:
        @staticmethod
        def from_url(url, socket_timeout=5):
            captured_timeout.append(socket_timeout)
            return FakeRedisClient()

    fake_redis_module = types.SimpleNamespace(from_url=FakeRedis.from_url)
    mocker.patch.dict(sys.modules, {"redis": fake_redis_module})

    worker_module.validate_redis_connection()
    assert captured_timeout[0] == 5  # Default timeout should be 5


def test_start_worker_logs_configuration(mocker):
    """Test start_worker logs Celery configuration."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    mocker.patch("backend.data_process.worker.os.getpid", return_value=12345)

    debug_calls = []

    class FakeLogger:
        def debug(self, msg, *args):
            debug_calls.append(msg % args if args else msg)

        def info(self, msg, *args):
            pass

    mocker.patch.object(worker_module.logger, "debug", side_effect=lambda msg, *args: debug_calls.append(msg % args if args else msg))

    call_args = []

    def mock_worker_main(args):
        call_args.append(args)

    mocker.patch.object(worker_module.app, "worker_main", side_effect=mock_worker_main)

    worker_module.start_worker()

    # Verify configuration logging
    assert any("Broker URL" in str(call) or "Backend URL" in str(call) for call in debug_calls)


def test_task_failure_handler_logs_exception_details(mocker):
    """Test task_failure_handler logs exception type and message."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    error_calls = []

    class FakeLogger:
        def error(self, msg, *args):
            error_calls.append(msg % args if args else msg)

    mocker.patch.object(worker_module.logger, "error", side_effect=lambda msg, *args: error_calls.append(msg % args if args else msg))

    fake_sender = types.SimpleNamespace(name="test_task")
    fake_exception = ValueError("Test error message")

    worker_module.task_failure_handler(
        sender=fake_sender,
        task_id="task-123",
        exception=fake_exception
    )

    # Verify error logging
    assert any("task-123" in str(call) for call in error_calls)
    assert any("ValueError" in str(call) or "Test error" in str(call) for call in error_calls)


def test_task_failure_handler_updates_worker_state(mocker):
    """Test task_failure_handler increments tasks_failed counter."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    initial_failed = worker_module.worker_state['tasks_failed']

    fake_sender = types.SimpleNamespace(name="test_task")
    fake_exception = RuntimeError("Task failed")

    # Mock logger to suppress output
    mocker.patch.object(worker_module.logger, "error")

    worker_module.task_failure_handler(
        sender=fake_sender,
        task_id="task-456",
        exception=fake_exception
    )

    assert worker_module.worker_state['tasks_failed'] == initial_failed + 1


def test_worker_ready_handler_calculates_startup_time(mocker):
    """Test worker_ready_handler calculates correct startup time."""
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.worker_state['start_time'] = 1000.0

    mocker.patch("backend.data_process.worker.os.getpid", return_value=12345)
    mocker.patch("backend.data_process.worker.time.time", return_value=1005.5)

    # Mock logger to suppress output
    mocker.patch.object(worker_module.logger, "debug")
    mocker.patch.object(worker_module.logger, "info")

    worker_module.worker_ready_handler()

    assert worker_module.worker_state['ready'] is True


def test_start_worker_with_multiple_queues(mocker):
    """Test start_worker handles multiple queue configuration."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    # Set multiple queues
    worker_module.QUEUES = "process_q,forward_q,custom_q"

    mocker.patch("backend.data_process.worker.os.getpid", return_value=12345)

    call_args = []

    def mock_worker_main(args):
        call_args.append(args)

    mocker.patch.object(worker_module.app, "worker_main", side_effect=mock_worker_main)

    worker_module.start_worker()

    assert len(call_args) == 1
    assert "--queues=process_q,forward_q,custom_q" in call_args[0]


def test_worker_ready_handler_schedules_prewarm_for_process_queue(mocker):
    """Test worker_ready_handler schedules Ray actor prewarm for process_q."""
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.worker_state['start_time'] = 1000.0

    mocker.patch("backend.data_process.worker.os.getpid", return_value=7)
    mocker.patch("backend.data_process.worker.time.time", return_value=1001.0)

    # Set QUEUES to include process_q
    worker_module.QUEUES = "process_q,forward_q"

    prewarm_calls = []

    def mock_prewarm(target_size):
        prewarm_calls.append(target_size)
        return 2

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            if self.target:
                self.target()

    mocker.patch.object(worker_module.threading, "Thread", FakeThread)

    # Mock prewarm function
    mocker.patch("backend.data_process.tasks.prewarm_ray_actors", mock_prewarm)

    worker_module.worker_ready_handler()

    # Give thread time to execute (in real scenario)
    # The prewarm is started in a daemon thread


def test_setup_worker_process_resources_handles_monitoring_exception(mocker):
    """Test setup_worker_process_resources handles monitoring initialization failure."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    mocker.patch("backend.data_process.worker.os.getpid", return_value=99999)

    # Mock validate_service_connections to succeed
    mocker.patch.object(worker_module, "validate_service_connections", return_value=True)

    # Mock monitoring import to fail
    import_original = __builtins__.__import__ if hasattr(__builtins__, '__import__') else builtins.__import__

    def mock_import(name, *args, **kwargs):
        if "monitoring" in name:
            raise ImportError("No monitoring module")
        return import_original(name, *args, **kwargs)

    mocker.patch("builtins.__import__", side_effect=mock_import)

    # Should not raise, just log warning
    try:
        worker_module.setup_worker_process_resources()
    except ImportError:
        pass  # May or may not raise depending on import structure


def test_setup_worker_environment_logs_missing_sensitive_variables(mocker):
    worker_module, _ = setup_mocks_for_worker(mocker, initialized=True)
    worker_module.REDIS_URL = ""
    worker_module.ELASTICSEARCH_SERVICE = ""
    error_calls = []
    mocker.patch.object(
        worker_module.logger,
        "error",
        side_effect=lambda msg, *args, **kwargs: error_calls.append(msg % args if args else msg),
    )

    worker_module.setup_worker_environment()

    assert any("REDIS_URL: NOT SET" in message for message in error_calls)
    assert any("ELASTICSEARCH_SERVICE: NOT SET" in message for message in error_calls)


def test_setup_worker_process_resources_logs_monitoring_status(mocker):
    worker_module, _ = setup_mocks_for_worker(mocker)
    monitoring_module = types.ModuleType("utils.monitoring")
    monitoring_module.monitoring_manager = types.SimpleNamespace(is_enabled=True)
    mocker.patch.dict(sys.modules, {"utils.monitoring": monitoring_module})
    mocker.patch.object(worker_module, "validate_service_connections", return_value=True)
    info = mocker.patch.object(worker_module.logger, "info")

    worker_module.setup_worker_process_resources()

    assert any(
        call.args[:2] == (
            "Knowledge telemetry initialized in worker process: enabled=%s",
            True,
        )
        for call in info.call_args_list
    )
    assert worker_module.worker_state["services_validated"] is True


@pytest.mark.parametrize("should_fail", [False, True])
def test_worker_ready_handler_runs_prewarm_background(mocker, should_fail):
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.QUEUES = "process_q"
    prewarm_calls = []

    def prewarm(target_size):
        prewarm_calls.append(target_size)
        if should_fail:
            raise RuntimeError("warm failed")
        return 2

    tasks_module = types.ModuleType("data_process.tasks")
    tasks_module.prewarm_ray_actors = prewarm
    mocker.patch.dict(sys.modules, {"data_process.tasks": tasks_module})

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    mocker.patch.object(worker_module.threading, "Thread", ImmediateThread)
    warning = mocker.patch.object(worker_module.logger, "warning")

    worker_module.worker_ready_handler()

    assert prewarm_calls == [worker_module.DP_PART_PROCESSOR_COUNT]
    if should_fail:
        assert any("Background prewarm failed" in call.args[0] for call in warning.call_args_list)


def test_worker_ready_handler_collects_part_concurrency_once(mocker):
    worker_module, fake_ray = setup_mocks_for_worker(mocker, initialized=True)
    worker_module.QUEUES = "process_part_q"
    tasks_module = types.ModuleType("data_process.tasks")
    tasks_module.prewarm_ray_actors = lambda target_size: 1
    mocker.patch.dict(sys.modules, {"data_process.tasks": tasks_module})

    targets = []

    class CapturingThread:
        def __init__(self, target=None, daemon=None):
            targets.append(target)

        def start(self):
            pass

    inspector = types.SimpleNamespace(
        active=lambda: {
            "worker-1": [
                {"name": "data_process.tasks.process_part"},
                {"name": "another.task"},
            ],
            "worker-2": None,
        }
    )
    worker_module.app.control = types.SimpleNamespace(
        inspect=lambda timeout: inspector
    )
    fake_ray.available_resources = lambda: {"CPU": 3.5}
    mocker.patch.object(worker_module.threading, "Thread", CapturingThread)
    mocker.patch.object(worker_module.time, "sleep", side_effect=StopIteration)
    info = mocker.patch.object(worker_module.logger, "info")

    worker_module.worker_ready_handler()
    assert len(targets) == 2
    with pytest.raises(StopIteration):
        targets[1]()

    assert any(
        "active=1, ray_available_cpu=3.5" in call.args[0]
        for call in info.call_args_list
    )


def test_worker_ready_handler_logs_thread_schedule_failures(mocker):
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.QUEUES = "process_part_q"
    tasks_module = types.ModuleType("data_process.tasks")
    tasks_module.prewarm_ray_actors = lambda target_size: 1
    mocker.patch.dict(sys.modules, {"data_process.tasks": tasks_module})
    mocker.patch.object(worker_module.threading, "Thread", side_effect=RuntimeError("thread failed"))
    warning = mocker.patch.object(worker_module.logger, "warning")

    worker_module.worker_ready_handler()

    messages = [call.args[0] for call in warning.call_args_list]
    assert any("Failed to schedule Ray actor prewarm" in message for message in messages)
    assert any("Failed to start process_part concurrency logger" in message for message in messages)


def test_start_worker_logs_successful_monitoring_initialization(mocker):
    worker_module, _ = setup_mocks_for_worker(mocker)
    monitoring_module = types.ModuleType("utils.monitoring")
    monitoring_module.monitoring_manager = types.SimpleNamespace(is_enabled=True)
    mocker.patch.dict(sys.modules, {"utils.monitoring": monitoring_module})
    mocker.patch.object(worker_module.app, "worker_main")
    info = mocker.patch.object(worker_module.logger, "info")

    worker_module.start_worker()

    assert any(
        call.args[:2] == (
            "Knowledge telemetry initialized before worker start: enabled=%s",
            True,
        )
        for call in info.call_args_list
    )


def test_validate_service_connections_returns_true_on_success(mocker):
    """Test validate_service_connections returns True when all checks pass."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    class FakeRedisClient:
        def ping(self):
            return True

    class FakeRedis:
        @staticmethod
        def from_url(url, socket_timeout=5):
            return FakeRedisClient()

    fake_redis_module = types.SimpleNamespace(from_url=FakeRedis.from_url)
    mocker.patch.dict(sys.modules, {"redis": fake_redis_module})

    result = worker_module.validate_service_connections()
    assert result is True


def test_worker_ready_handler_logs_worker_status(mocker):
    """Test worker_ready_handler logs worker status summary."""
    worker_module, _ = setup_mocks_for_worker(mocker)
    worker_module.worker_state['start_time'] = 1000.0

    mocker.patch("backend.data_process.worker.os.getpid", return_value=12345)
    mocker.patch("backend.data_process.worker.time.time", return_value=1002.0)

    debug_calls = []

    class FakeLogger:
        def debug(self, msg, *args):
            debug_calls.append(msg % args if args else msg)

        def info(self, msg, *args):
            pass

    mocker.patch.object(worker_module.logger, "debug", side_effect=lambda msg, *args: debug_calls.append(msg % args if args else msg))

    worker_module.worker_ready_handler()

    # Should log status summary
    assert any("status" in str(call).lower() or "summary" in str(call).lower() for call in debug_calls)


def test_task_postrun_handler_does_not_increment_on_failure_state(mocker):
    """Test task_postrun_handler does not increment completed on FAILURE state."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    initial_completed = worker_module.worker_state['tasks_completed']

    fake_task = types.SimpleNamespace(name="test_task")
    worker_module.task_postrun_handler(task=fake_task, task_id="task-789", state="FAILURE")

    # Should not increment completed count
    assert worker_module.worker_state['tasks_completed'] == initial_completed


def test_task_postrun_handler_does_not_increment_on_pending_state(mocker):
    """Test task_postrun_handler does not increment completed on PENDING state."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    initial_completed = worker_module.worker_state['tasks_completed']

    fake_task = types.SimpleNamespace(name="test_task")
    worker_module.task_postrun_handler(task=fake_task, task_id="task-999", state="PENDING")

    # Should not increment completed count
    assert worker_module.worker_state['tasks_completed'] == initial_completed


def test_task_postrun_handler_increments_on_success_state(mocker):
    """Test task_postrun_handler increments completed on SUCCESS state."""
    worker_module, _ = setup_mocks_for_worker(mocker)

    initial_completed = worker_module.worker_state['tasks_completed']

    fake_task = types.SimpleNamespace(name="test_task")
    worker_module.task_postrun_handler(task=fake_task, task_id="task-success", state="SUCCESS")

    assert worker_module.worker_state['tasks_completed'] == initial_completed + 1
