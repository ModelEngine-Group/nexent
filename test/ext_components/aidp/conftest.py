"""Restore aidp_permission_service.require_permission after each test.

A handful of legacy mgmt_app tests assign directly to the module attribute.
When this fixture is active, any such assignment is reverted at teardown
so that subsequent test modules (notably test_aidp_permission_service) can
exercise the real ``require_permission`` implementation.
"""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Stub nexent SDK and storage modules so the conftest does not require boto3
# or other heavy optional deps at collection time.
if "nexent" not in sys.modules:
    _nexent = ModuleType("nexent")
    _nexent.__path__ = []
    sys.modules["nexent"] = _nexent
    _nexent_utils = ModuleType("nexent.utils")
    _nexent_utils.__path__ = []
    sys.modules["nexent.utils"] = _nexent_utils
    _http_mgr = ModuleType("nexent.utils.http_client_manager")
    _http_mgr.http_client_manager = MagicMock()
    sys.modules["nexent.utils.http_client_manager"] = _http_mgr
    _nexent_storage = ModuleType("nexent.storage")
    _nexent_storage.__path__ = []
    sys.modules["nexent.storage"] = _nexent_storage
    _storage_factory = ModuleType("nexent.storage.storage_client_factory")
    _storage_factory.create_storage_client_from_config = MagicMock()

    class _MinIOStorageConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    _storage_factory.MinIOStorageConfig = _MinIOStorageConfig
    sys.modules["nexent.storage.storage_client_factory"] = _storage_factory

# Ensure env vars are set so consts.const can load without .env
for var in (
    "POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD",
    "POSTGRES_DB", "POSTGRES_PORT", "NEXENT_POSTGRES_PASSWORD",
    "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY",
    "MINIO_REGION", "MINIO_DEFAULT_BUCKET",
):
    os.environ.setdefault(var, "test")

import pytest  # noqa: E402


_REQUIRE_ATTRS = (
    "require_permission",
    "_get_user_role",
    "_get_user_groups",
)


@pytest.fixture(autouse=True)
def _preserve_aidp_permission_service(monkeypatch):
    """Snapshot selected attributes and restore them after each test.

    Lazy-import to avoid loading ``aidp_permission_service`` at collection
    time, which would cause coverage to miss the module (the
    ``module-not-measured`` warning).
    """
    from backend.ext_components.aidp.services import aidp_permission_service
    originals = {attr: getattr(aidp_permission_service, attr) for attr in _REQUIRE_ATTRS}
    yield
    from backend.ext_components.aidp.services import aidp_permission_service as _svc
    for attr, value in originals.items():
        setattr(_svc, attr, value)