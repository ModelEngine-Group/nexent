"""Unit tests for evaluation_set_service focusing on the new
delete-with-reference-count behavior."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Pre-stub heavy third-party packages that are imported transitively.
sys.modules["boto3"] = MagicMock()
sys.modules["botocore"] = MagicMock()
sys.modules["botocore.client"] = MagicMock()
sys.modules["botocore.exceptions"] = MagicMock()


def _register_package(name: str) -> types.ModuleType:
    """Register ``name`` as a real package on ``sys.modules``.

    Reuses an existing entry that already exposes ``__path__`` (e.g. a stub
    created by a sibling test file) so we don't fork the package identity
    mid-session — module-level execution of one test file would otherwise
    orphan the other file's package object, and ``from package import X``
    would then short-circuit through a stale cache that has no entry in
    ``sys.modules``.
    """
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    sys.modules[name] = pkg
    return pkg


_nexent_pkg = _register_package("nexent")
_nexent_core = _register_package("nexent.core")
_nexent_core_agents = _register_package("nexent.core.agents")
_nexent_core_utils = _register_package("nexent.core.utils")
_nexent_memory = _register_package("nexent.memory")
_nexent_monitor = _register_package("nexent.monitor")
_nexent_storage = _register_package("nexent.storage")
_nexent_pkg.core = _nexent_core
_nexent_pkg.memory = _nexent_memory
_nexent_pkg.monitor = _nexent_monitor
_nexent_pkg.storage = _nexent_storage
_nexent_core.agents = _nexent_core_agents
_nexent_core.utils = _nexent_core_utils

_agent_model_mock = MagicMock()


class _MockAgentVerificationConfig:
    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self, **kwargs):
        return dict(self.__dict__)


class _MockToolConfig:
    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self, **kwargs):
        return dict(self.__dict__)


_agent_model_mock.AgentVerificationConfig = _MockAgentVerificationConfig
_agent_model_mock.ToolConfig = _MockToolConfig
sys.modules["nexent.core.agents.agent_model"] = _agent_model_mock
sys.modules["nexent.core.agents.agent_context"] = MagicMock()
sys.modules["nexent.core.agents.run_agent"] = MagicMock()
sys.modules["nexent.core.utils.observer"] = MagicMock()
sys.modules["nexent.core.utils.common"] = MagicMock()
sys.modules["nexent.memory.memory_service"] = MagicMock()
sys.modules["nexent.monitor.monitoring"] = MagicMock()
sys.modules["nexent.storage.storage_client_factory"] = MagicMock()
sys.modules["nexent.storage.minio_config"] = MagicMock()

# Services package with the real backend path so the service under test loads.
_services_pkg = _register_package("services")
_services_pkg.__path__ = [str(_BACKEND_DIR / "services")]

_consts_pkg = _register_package("consts")
_consts_model_module = types.ModuleType("consts.model")
_consts_model_module.AgentRequest = MagicMock()
sys.modules["consts.model"] = _consts_model_module
_consts_pkg.model = _consts_model_module

_db_pkg = _register_package("database")
_db_client_module = MagicMock()
sys.modules["database.client"] = _db_client_module
_db_pkg.client = _db_client_module

_db_models_module = MagicMock()
sys.modules["database.db_models"] = _db_models_module
_db_pkg.db_models = _db_models_module

_agent_version_db_mock = MagicMock()
_agent_version_db_mock.query_version_list = MagicMock()
sys.modules["database.agent_version_db"] = _agent_version_db_mock
_db_pkg.agent_version_db = _agent_version_db_mock

_evaluation_set_db_mock = MagicMock()
_evaluation_set_db_mock.soft_delete_evaluation_set = MagicMock()
sys.modules["database.evaluation_set_db"] = _evaluation_set_db_mock
_db_pkg.evaluation_set_db = _evaluation_set_db_mock


@pytest.fixture
def service_module(monkeypatch):
    if "services.evaluation_set_service" in sys.modules:
        del sys.modules["services.evaluation_set_service"]
    # Clear the package attribute so the ``from services`` below triggers a
    # fresh import (and therefore repopulates ``sys.modules``). Without this,
    # Python's attribute-on-package lookup returns the previous module object
    # without re-importing, leaving sys.modules empty for sibling tests.
    if hasattr(_services_pkg, "evaluation_set_service"):
        try:
            delattr(_services_pkg, "evaluation_set_service")
        except AttributeError:
            pass

    session_holder = {"count": 0}

    class _SessionCtx:
        def __enter__(self_inner):
            session = MagicMock()
            session.query.return_value.filter.return_value.count.return_value = session_holder["count"]
            return session

        def __exit__(self_inner, exc_type, exc, tb):
            return False

    # Wire the context manager onto the get_db_session symbol that the
    # service module reads at call time.
    db_client_mock = MagicMock()
    db_client_mock.get_db_session = MagicMock(return_value=_SessionCtx())
    sys.modules["database.client"] = db_client_mock
    _db_pkg.client = db_client_mock

    from services import evaluation_set_service  # noqa: E402

    # Patch the names bound at module load time so the test exercises the
    # mocked implementations.
    evaluation_set_service.get_db_session = MagicMock(return_value=_SessionCtx())
    evaluation_set_service.soft_delete_evaluation_set = _evaluation_set_db_mock.soft_delete_evaluation_set

    _evaluation_set_db_mock.soft_delete_evaluation_set.reset_mock()
    return evaluation_set_service, session_holder


def test_delete_blocked_when_referenced(service_module):
    service, holder = service_module
    holder["count"] = 3

    with pytest.raises(ValueError, match="referenced by 3"):
        service.delete_evaluation_set_impl(1, "t1", "u1")
    service.soft_delete_evaluation_set.assert_not_called()


def test_delete_allowed_when_no_references(service_module):
    service, holder = service_module
    holder["count"] = 0

    service.delete_evaluation_set_impl(1, "t1", "u1")
    service.soft_delete_evaluation_set.assert_called_once_with(1, "t1", "u1")


def test_count_active_runs_using_set(service_module):
    service, holder = service_module
    holder["count"] = 7

    assert service.count_active_runs_using_set(2, "t1") == 7
