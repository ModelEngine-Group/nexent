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

# Optional SDK stubs (xlrd, supabase, etc.) live below; see the per-section
# comments.  The legacy mem0 stub block has been removed because the SDK
# no longer imports mem0 at module load time.

_optional_sdk_stubs: dict = {}

# Add backend and sdk directories to sys.path so that modules can be imported
# as `from backend.xxx import ...` and `from sdk.xxx import ...`
_test_root = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_test_root, "..", "backend"))
_sdk_dir = os.path.abspath(os.path.join(_test_root, "..", "sdk"))

if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _sdk_dir not in sys.path:
    sys.path.insert(0, _sdk_dir)

# Stub xlrd — only required when tests exercise ``evaluation_set_excel_utils``
# in environments where the optional SDK is not installed.  We register a
# permissive module-like object that exposes ``open_workbook`` so the .xls
# parsing path can be imported without raising.  Individual test files
# (e.g. ``test_evaluation_set_excel_utils.py``) replace this with a richer
# fake that mimics the sheet-level API for the .xls tests.
class _XlrdProxy(types.ModuleType):
    """Permissive xlrd stub.

    Exposes a callable ``open_workbook`` attribute so that ``xlrd.open_workbook(...)``
    works at import time.  Returns a shape that satisfies the bits of the .xls
    parsing path used by ``evaluation_set_excel_utils`` well enough to import
    without crashing; richer behaviour is supplied by per-test-file overrides.
    """

    def __init__(self):
        super().__init__("xlrd")
        self._sentinel = object()

    def open_workbook(self, file_contents=b""):
        # Return a fully-formed stub book that survives ``sheet_by_index``,
        # ``sheet.nrows``, ``sheet.row_values`` and ``sheet.cell_value`` —
        # these are the four accessors used in the .xls branch.
        class _Sheet:
            nrows = 0
            def row_values(self, _rowx):
                return []

            def cell_value(self, _rowx, _colx):
                return None

        class _Book:
            def sheet_by_index(self, _idx):
                return _Sheet()

        return _Book()


if "xlrd" not in sys.modules or not hasattr(sys.modules["xlrd"], "open_workbook"):
    sys.modules["xlrd"] = _XlrdProxy()

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


@pytest.fixture(autouse=True)
def _supabase_mock():
    """Re-install the supabase mock before each test.

    Module-level ``sys.modules['supabase']`` overrides in test files
    (e.g. ``sys.modules['supabase'] = MagicMock()``) strip out the
    structured attributes (``lib``, ``lib.client_options``,
    ``SyncClientOptions``) that ``backend.utils.auth_utils`` resolves at
    import time. The module-level install below covers collection, but
    any test that re-mocks ``supabase`` after collection needs the
    structured attributes re-installed before its test body runs.
    """
    install_supabase_mock()
    yield


# Install a sane supabase mock at collection time so test modules that
# import ``backend.utils.auth_utils`` (directly or transitively) succeed
# during pytest's collection phase, before any test fixture has had a
# chance to run. The ``_supabase_mock`` autouse fixture above re-runs the
# install before each test body in case individual test modules
# overwrote ``sys.modules['supabase']``.
if 'supabase' not in sys.modules:
    install_supabase_mock()
