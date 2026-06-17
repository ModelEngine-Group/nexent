"""
Global test configuration for third-party component environment variables.

This file sets up environment variables for external services used in tests.
"""
import os
import sys
import shutil
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch as _patch

import pytest

# Stub out mem0 and smolagents modules before anything else imports them.
# The sdk imports these at module level, so stubs must be registered first.
_mem0_stubs = {
    "mem0": MagicMock(),
    "mem0.memory": MagicMock(),
    "mem0.memory.main": MagicMock(),
    "mem0.embeddings": MagicMock(),
    "mem0.embeddings.base": MagicMock(),
    "mem0.configs": MagicMock(),
    "mem0.configs.embeddings": MagicMock(),
    "mem0.configs.embeddings.base": MagicMock(),
}

_optional_sdk_stubs = {}

# Add backend and sdk directories to sys.path so that modules can be imported
# as `from backend.xxx import ...` and `from sdk.xxx import ...`
_test_root = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_test_root, "..", "backend"))
_sdk_dir = os.path.abspath(os.path.join(_test_root, "..", "sdk"))

if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _sdk_dir not in sys.path:
    sys.path.insert(0, _sdk_dir)

sys.modules.update({k: v for k, v in _mem0_stubs.items() if k not in sys.modules})
sys.modules.update({k: v for k, v in _optional_sdk_stubs.items() if k not in sys.modules})

_tmp_root = os.path.abspath(os.path.join(_test_root, "..", ".pytest-tmp"))
os.makedirs(_tmp_root, exist_ok=True)
os.environ.setdefault("TMP", _tmp_root)
os.environ.setdefault("TEMP", _tmp_root)
os.environ.setdefault("TMPDIR", _tmp_root)
tempfile.tempdir = _tmp_root

# MinIO Configuration
os.environ.setdefault('MINIO_ENDPOINT', 'http://localhost:9000')
os.environ.setdefault('MINIO_ACCESS_KEY', 'minioadmin')
os.environ.setdefault('MINIO_SECRET_KEY', 'minioadmin')
os.environ.setdefault('MINIO_REGION', 'us-east-1')
os.environ.setdefault('MINIO_DEFAULT_BUCKET', 'test-bucket')

# Elasticsearch Configuration
os.environ.setdefault('ELASTICSEARCH_HOST', 'http://localhost:9200')
os.environ.setdefault('ELASTICSEARCH_API_KEY', 'test-es-key')
os.environ.setdefault('ELASTIC_PASSWORD', 'test-password')

# PostgresSQL Configuration
os.environ.setdefault('POSTGRES_HOST', 'localhost')
os.environ.setdefault('POSTGRES_USER', 'test_user')
os.environ.setdefault('POSTGRES_PASSWORD', 'test_password')
os.environ.setdefault('POSTGRES_DB', 'test_db')
os.environ.setdefault('POSTGRES_PORT', '5432')


class _PatchProxy:
    def __init__(self, owner):
        self._owner = owner

    def __call__(self, target, *args, **kwargs):
        return self._owner._start(_patch(target, *args, **kwargs))

    def object(self, target, attribute, *args, **kwargs):
        return self._owner._start(_patch.object(target, attribute, *args, **kwargs))

    def dict(self, target, *args, **kwargs):
        return self._owner._start(_patch.dict(target, *args, **kwargs))


class _MiniMocker:
    def __init__(self):
        self._patchers = []
        self.patch = _PatchProxy(self)

    def _start(self, patcher):
        value = patcher.start()
        self._patchers.append(patcher)
        return value

    def stopall(self):
        while self._patchers:
            self._patchers.pop().stop()


@pytest.fixture
def mocker():
    helper = _MiniMocker()
    try:
        yield helper
    finally:
        helper.stopall()


@pytest.fixture
def tmp_path():
    """Use a repo-local temp dir instead of pytest's default temp root."""
    path = Path(tempfile.mkdtemp(prefix="tmp-", dir=_tmp_root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def install_supabase_mock():
    """Install a structured supabase package mock into ``sys.modules``.

    ``backend.utils.auth_utils`` imports ``from supabase.lib.client_options
    import SyncClientOptions`` at module load time. Test files that simply
    replace ``sys.modules['supabase']`` with a bare ``MagicMock`` cause that
    import to fail (the mock has no ``.lib.client_options`` attribute),
    which in turn makes every test that transitively imports ``auth_utils``
    (for example anything that imports ``services.user_service``) fail
    during collection.

    This helper installs a package-like mock that exposes the attributes
    used by the production code paths we exercise in unit tests, while
    still letting tests override individual functions via ``monkeypatch``
    or ``patch``.
    """
    supabase_mock = MagicMock()
    supabase_mock.create_client = MagicMock()

    supabase_lib_mock = types.ModuleType("supabase.lib")
    supabase_client_options_mock = types.ModuleType(
        "supabase.lib.client_options"
    )

    class _SyncClientOptions:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    supabase_client_options_mock.SyncClientOptions = _SyncClientOptions
    supabase_lib_mock.client_options = supabase_client_options_mock
    supabase_mock.lib = supabase_lib_mock

    sys.modules['supabase'] = supabase_mock
    sys.modules['supabase.lib'] = supabase_lib_mock
    sys.modules['supabase.lib.client_options'] = supabase_client_options_mock

    return supabase_mock


# Install a sane supabase mock up front so test files that import
# ``backend.utils.auth_utils`` (directly or transitively) succeed during
# collection, even before their own module-level mocks run. Individual
# test files can override ``sys.modules['supabase']`` with their own mock
# and call this helper to re-install the structured attributes.
if 'supabase' not in sys.modules:
    install_supabase_mock()
