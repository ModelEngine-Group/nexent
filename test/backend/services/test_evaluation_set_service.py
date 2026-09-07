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

# ── consts.error_code stub with all enumerators referenced by service ──
_consts_error_code_module = types.ModuleType("consts.error_code")


class _ErrorCode:
    COMMON_VALIDATION_ERROR = "COMMON_VALIDATION_ERROR"
    COMMON_RESOURCE_NOT_FOUND = "COMMON_RESOURCE_NOT_FOUND"
    AGENT_EVALUATION_GENERATION_BAD_FORMAT = "AGENT_EVALUATION_GENERATION_BAD_FORMAT"
    AGENT_EVALUATION_AGENT_NOT_FOUND = "AGENT_EVALUATION_AGENT_NOT_FOUND"
    AGENT_EVALUATION_SET_IN_USE = "AGENT_EVALUATION_SET_IN_USE"
    AGENT_EVALUATION_TURN_ORDER_MISMATCH = "AGENT_EVALUATION_TURN_ORDER_MISMATCH"
    AGENT_EVALUATION_TURN_DELETE_NOT_LAST = "AGENT_EVALUATION_TURN_DELETE_NOT_LAST"
    AGENT_EVALUATION_TURN_DELETE_NOT_CONTIGUOUS = (
        "AGENT_EVALUATION_TURN_DELETE_NOT_CONTIGUOUS"
    )
    AGENT_EVALUATION_CASE_GENERATION_FORMAT = "AGENT_EVALUATION_CASE_GENERATION_FORMAT"
    AGENT_EVALUATION_CASE_GENERATION_EMPTY = "AGENT_EVALUATION_CASE_GENERATION_EMPTY"


_consts_error_code_module.ErrorCode = _ErrorCode
sys.modules["consts.error_code"] = _consts_error_code_module
_consts_pkg.error_code = _consts_error_code_module

# ── consts.evaluation_limits stub ──
_consts_limits_module = types.ModuleType("consts.evaluation_limits")
_consts_limits_module.MAX_CASES_PER_SET = 10000
sys.modules["consts.evaluation_limits"] = _consts_limits_module
_consts_pkg.evaluation_limits = _consts_limits_module

# ── consts.evaluation_status stub ──
_consts_status_module = types.ModuleType("consts.evaluation_status")


class _EvalRunStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_consts_status_module.EvalRunStatus = _EvalRunStatus
sys.modules["consts.evaluation_status"] = _consts_status_module
_consts_pkg.evaluation_status = _consts_status_module

# ── consts.exceptions stub (real Exception subclass so try/except works) ──
_consts_exceptions_module = types.ModuleType("consts.exceptions")


class _AppException(Exception):
    def __init__(self, error_code=None, message=None, details=None, *args, **kwargs):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)


_consts_exceptions_module.AppException = _AppException
sys.modules["consts.exceptions"] = _consts_exceptions_module
_consts_pkg.exceptions = _consts_exceptions_module

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
_evaluation_set_db_mock.hard_delete_evaluation_set = MagicMock()
sys.modules["database.evaluation_set_db"] = _evaluation_set_db_mock
_db_pkg.evaluation_set_db = _evaluation_set_db_mock

# ── database.knowledge_db stub ──
_knowledge_db_mock = MagicMock()
_knowledge_db_mock.get_index_name_by_knowledge_name = MagicMock()
sys.modules["database.knowledge_db"] = _knowledge_db_mock
_db_pkg.knowledge_db = _knowledge_db_mock

# ── utils package + sub-module stubs referenced by evaluation_set_service ──
_utils_pkg = _register_package("utils")

_utils_llm_mock = MagicMock()
sys.modules["utils.llm_utils"] = _utils_llm_mock
_utils_pkg.llm_utils = _utils_llm_mock

_utils_prompt_mock = MagicMock()
sys.modules["utils.prompt_template_utils"] = _utils_prompt_mock
_utils_pkg.prompt_template_utils = _utils_prompt_mock

# Function-body imports used by the KB / LLM / export helpers.
sys.modules["utils.evaluation_set_excel_utils"] = MagicMock()
sys.modules["management.services.knowledge_base.service"] = MagicMock()
sys.modules["utils.agent_profile_utils"] = MagicMock()


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
            session.query.return_value.filter.return_value.count.return_value = (
                session_holder["count"]
            )
            return session

        def __exit__(self_inner, exc_type, exc, tb):
            return False

    # Wire the context manager onto the get_db_session symbol that the
    # service module reads at call time.
    db_client_mock = MagicMock()
    db_client_mock.get_db_session = MagicMock(return_value=_SessionCtx())
    sys.modules["database.client"] = db_client_mock
    _db_pkg.client = db_client_mock

    from services import evaluation_set_service

    # Patch the names bound at module load time so the test exercises the
    # mocked implementations.
    evaluation_set_service.get_db_session = MagicMock(return_value=_SessionCtx())
    evaluation_set_service.hard_delete_evaluation_set = MagicMock()
    _evaluation_set_db_mock.soft_delete_evaluation_set.reset_mock()
    _evaluation_set_db_mock.hard_delete_evaluation_set.reset_mock()
    return evaluation_set_service, session_holder


def test_delete_blocked_when_referenced(service_module):
    service, holder = service_module
    holder["count"] = 3

    with pytest.raises(_AppException, match="referenced by 3"):
        service.delete_evaluation_set_impl(1, "t1", "u1")
    service.hard_delete_evaluation_set.assert_not_called()


def test_delete_allowed_when_no_references(service_module):
    service, holder = service_module
    holder["count"] = 0

    service.delete_evaluation_set_impl(1, "t1", "u1")
    service.hard_delete_evaluation_set.assert_called_once_with(1, "t1")


def test_count_active_runs_using_set(service_module):
    service, holder = service_module
    holder["count"] = 7

    assert service.count_active_runs_using_set(2, "t1") == 7


# ---------------------------------------------------------------------------
# create_evaluation_set_from_cases
# ---------------------------------------------------------------------------


class TestCreateEvaluationSetFromCases:
    def test_creates_and_inserts_with_case_count(self, service_module, monkeypatch):
        service, _ = service_module

        # Wire mocks on the freshly imported module reference.
        monkeypatch.setattr(
            service,
            "create_evaluation_set",
            MagicMock(return_value={"evaluation_set_id": 42}),
        )
        monkeypatch.setattr(
            service,
            "insert_evaluation_set_cases",
            MagicMock(return_value=3),
        )
        update_mock = MagicMock()
        monkeypatch.setattr(service, "update_evaluation_set_case_count", update_mock)

        cases = [
            {"inputs": {"query": "q1"}, "label": {"answer": "a1"}},
            {"inputs": {"query": "q2"}, "label": {"answer": "a2"}},
            {"inputs": {"query": "q3"}, "label": {"answer": "a3"}},
        ]
        meta = service.create_evaluation_set_from_cases(
            tenant_id="t1",
            name="n",
            description="d",
            source_filename="src",
            cases=cases,
            created_by="u1",
        )

        assert meta == {"evaluation_set_id": 42, "case_count": 3}
        update_mock.assert_called_once_with(42, 3, updated_by="u1")

    def test_rejects_empty_cases(self, service_module):
        service, _ = service_module
        with pytest.raises(_AppException, match="cases is empty"):
            service.create_evaluation_set_from_cases(
                tenant_id="t1",
                name="n",
                description=None,
                source_filename=None,
                cases=[],
                created_by="u1",
            )


# ---------------------------------------------------------------------------
# create_empty_evaluation_set
# ---------------------------------------------------------------------------


class TestCreateEmptyEvaluationSet:
    def test_creates_set_with_zero_case_count(self, service_module, monkeypatch):
        """create_empty_evaluation_set should call the underlying
        ``create_evaluation_set`` and report ``case_count = 0``."""
        service, _ = service_module
        underlying = MagicMock(return_value={"evaluation_set_id": 42})
        monkeypatch.setattr(service, "create_evaluation_set", underlying)

        result = service.create_empty_evaluation_set(
            tenant_id="t1",
            name="n",
            description="d",
            source_filename="src",
            created_by="u1",
        )
        underlying.assert_called_once_with(
            tenant_id="t1",
            name="n",
            description="d",
            source_filename="src",
            created_by="u1",
        )
        assert result == {"evaluation_set_id": 42, "case_count": 0}

    def test_does_not_insert_any_cases(self, service_module, monkeypatch):
        """Empty-set creation must NOT call ``insert_evaluation_set_cases``
        nor ``update_evaluation_set_case_count``."""
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "create_evaluation_set",
            MagicMock(return_value={"evaluation_set_id": 1}),
        )
        insert_mock = MagicMock(return_value=999)
        update_mock = MagicMock()
        monkeypatch.setattr(service, "insert_evaluation_set_cases", insert_mock)
        monkeypatch.setattr(service, "update_evaluation_set_case_count", update_mock)

        service.create_empty_evaluation_set(
            tenant_id="t1",
            name="n",
            description=None,
            source_filename=None,
            created_by="u1",
        )
        insert_mock.assert_not_called()
        update_mock.assert_not_called()


# ---------------------------------------------------------------------------
# list / get / list_cases impls — thin pass-through wrappers.
# ---------------------------------------------------------------------------


class TestListImpls:
    def test_list_evaluation_sets_impl(self, service_module, monkeypatch):
        service, _ = service_module
        underlying = MagicMock(return_value=[{"id": 1}])
        monkeypatch.setattr(service, "list_evaluation_sets", underlying)

        result = service.list_evaluation_sets_impl(
            tenant_id="t1",
            limit=10,
            offset=20,
        )
        underlying.assert_called_once_with(tenant_id="t1", limit=10, offset=20)
        assert result == [{"id": 1}]

    def test_get_evaluation_set_impl(self, service_module, monkeypatch):
        service, _ = service_module
        underlying = MagicMock(return_value={"id": 1})
        monkeypatch.setattr(service, "get_evaluation_set", underlying)

        result = service.get_evaluation_set_impl(1, "t1")
        underlying.assert_called_once_with(evaluation_set_id=1, tenant_id="t1")
        assert result == {"id": 1}

    def test_list_evaluation_set_cases_impl(self, service_module, monkeypatch):
        service, _ = service_module
        underlying = MagicMock(return_value=[{"case_id": 1}])
        monkeypatch.setattr(service, "list_evaluation_set_cases", underlying)
        count_mock = MagicMock(return_value=1)
        monkeypatch.setattr(service, "count_evaluation_set_cases", count_mock)

        result = service.list_evaluation_set_cases_impl(
            evaluation_set_id=1,
            tenant_id="t1",
            limit=5,
            offset=10,
        )
        underlying.assert_called_once_with(
            evaluation_set_id=1,
            tenant_id="t1",
            limit=5,
            offset=10,
            query=None,
        )
        count_mock.assert_called_once_with(1, "t1", query=None)
        assert result == {"data": [{"case_id": 1}], "total": 1}


# ---------------------------------------------------------------------------
# resolve_latest_published_version_no
# ---------------------------------------------------------------------------


class TestResolveLatestVersion:
    def test_returns_latest_version(self, service_module, monkeypatch):
        service, _ = service_module
        # query_version_list returns latest-first by existing convention.
        monkeypatch.setattr(
            service,
            "query_version_list",
            MagicMock(return_value=[{"version_no": 7}, {"version_no": 3}]),
        )
        assert service.resolve_latest_published_version_no(1, "t1") == 7

    def test_returns_coerced_int(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "query_version_list",
            MagicMock(return_value=[{"version_no": "9"}]),
        )
        assert service.resolve_latest_published_version_no(1, "t1") == 9

    def test_raises_when_no_versions(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "query_version_list",
            MagicMock(return_value=[]),
        )
        with pytest.raises(_AppException, match="no published versions"):
            service.resolve_latest_published_version_no(1, "t1")


# ---------------------------------------------------------------------------
# delete_evaluation_set_case_impl — hard delete
# ---------------------------------------------------------------------------


class TestDeleteEvaluationSetCaseImpl:
    def test_hard_deletes_case(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(
                return_value=[
                    {"evaluation_set_id": 7, "session_id": None, "turn_order": None}
                ]
            ),
        )
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        batch_mock = MagicMock(return_value=1)
        monkeypatch.setattr(service, "batch_delete_evaluation_set_cases", batch_mock)
        recount_mock = MagicMock()
        monkeypatch.setattr(service, "_recount_set_cases", recount_mock)

        ok = service.delete_evaluation_set_case_impl(case_id=11, tenant_id="t1")

        assert ok is True
        batch_mock.assert_called_once_with([11], "t1", 7)
        recount_mock.assert_called_once_with(7)

    def test_returns_false_when_case_missing(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "get_cases_by_ids", MagicMock(return_value=[]))
        batch_mock = MagicMock()
        monkeypatch.setattr(service, "batch_delete_evaluation_set_cases", batch_mock)

        ok = service.delete_evaluation_set_case_impl(case_id=999, tenant_id="t1")

        assert ok is False
        batch_mock.assert_not_called()

    def test_returns_false_when_hard_delete_removes_nothing(
        self, service_module, monkeypatch
    ):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(
                return_value=[
                    {"evaluation_set_id": 7, "session_id": None, "turn_order": None}
                ]
            ),
        )
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        batch_mock = MagicMock(return_value=0)
        monkeypatch.setattr(service, "batch_delete_evaluation_set_cases", batch_mock)
        recount_mock = MagicMock()
        monkeypatch.setattr(service, "_recount_set_cases", recount_mock)

        ok = service.delete_evaluation_set_case_impl(case_id=11, tenant_id="t1")

        assert ok is False
        recount_mock.assert_not_called()

    def test_blocks_non_tail_turn_deletion(self, service_module, monkeypatch):
        """Deleting a middle turn of a multi-turn session is rejected."""
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(
                return_value=[
                    {"evaluation_set_id": 7, "session_id": "s1", "turn_order": 1}
                ]
            ),
        )
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service,
            "list_case_turn_orders_by_session",
            MagicMock(return_value=[1, 2]),
        )

        with pytest.raises(_AppException, match="must delete from the last turn"):
            service.delete_evaluation_set_case_impl(case_id=11, tenant_id="t1")

    def test_raises_when_version_no_missing(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "query_version_list",
            MagicMock(return_value=[{"name": "no_version_field"}]),
        )
        with pytest.raises(
            _AppException, match="Failed to resolve latest published version"
        ):
            service.resolve_latest_published_version_no(1, "t1")


# ---------------------------------------------------------------------------
# create_evaluation_set_from_cases — validation branches
# ---------------------------------------------------------------------------


class TestCreateFromCasesValidation:
    def test_rejects_too_many_cases(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "create_evaluation_set", MagicMock())
        monkeypatch.setattr(service, "insert_evaluation_set_cases", MagicMock())

        with pytest.raises(_AppException, match="exceeds limit"):
            service.create_evaluation_set_from_cases(
                tenant_id="t1", name="n", description=None,
                source_filename=None, cases=[{}] * 10001, created_by="u1",
            )

    def test_rejects_session_with_too_many_turns(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "create_evaluation_set", MagicMock())
        monkeypatch.setattr(service, "insert_evaluation_set_cases", MagicMock())

        cases = [
            {"inputs": {"query": "q"}, "label": {"answer": "a"},
             "session_id": "s1", "turn_order": i}
            for i in range(101)
        ]
        with pytest.raises(_AppException, match="turns, max 100"):
            service.create_evaluation_set_from_cases(
                tenant_id="t1", name="n", description=None,
                source_filename=None, cases=cases, created_by="u1",
            )

    def test_rejects_non_consecutive_turns(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "create_evaluation_set", MagicMock())
        monkeypatch.setattr(service, "insert_evaluation_set_cases", MagicMock())

        cases = [
            {"inputs": {"query": "q"}, "label": {"answer": "a"},
             "session_id": "s1", "turn_order": 1},
            {"inputs": {"query": "q2"}, "label": {"answer": "a2"},
             "session_id": "s1", "turn_order": 3},
        ]
        with pytest.raises(_AppException, match="not consecutive"):
            service.create_evaluation_set_from_cases(
                tenant_id="t1", name="n", description=None,
                source_filename=None, cases=cases, created_by="u1",
            )

    def test_unparseable_turn_falls_back_to_zero(self, service_module, monkeypatch):
        """A non-numeric turn_order is parsed to 0 without crashing."""
        service, _ = service_module
        monkeypatch.setattr(
            service, "create_evaluation_set",
            MagicMock(return_value={"evaluation_set_id": 1}),
        )
        insert_mock = MagicMock(return_value=1)
        monkeypatch.setattr(service, "insert_evaluation_set_cases", insert_mock)
        update_mock = MagicMock()
        monkeypatch.setattr(service, "update_evaluation_set_case_count", update_mock)

        cases = [
            {"inputs": {"query": "q"}, "label": {"answer": "a"},
             "session_id": "s1", "turn_order": "abc"},
        ]
        meta = service.create_evaluation_set_from_cases(
            tenant_id="t1", name="n", description=None,
            source_filename=None, cases=cases, created_by="u1",
        )
        assert meta["case_count"] == 1
        update_mock.assert_called_once()


# ---------------------------------------------------------------------------
# get_evaluation_set_impl — not-found branch / export
# ---------------------------------------------------------------------------


class TestGetEvaluationSetImplNotFound:
    def test_raises_when_underlying_returns_none(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "get_evaluation_set", MagicMock(return_value=None))
        with pytest.raises(_AppException, match="Evaluation set not found"):
            service.get_evaluation_set_impl(1, "t1")


class TestExportEvaluationSet:
    def test_returns_filename_and_bytes(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_evaluation_set_impl",
            MagicMock(return_value={"name": "my set"}),
        )
        monkeypatch.setattr(service, "get_evaluation_set_cases_all", MagicMock(return_value=[]))
        excel_mock = sys.modules["utils.evaluation_set_excel_utils"]
        excel_mock.build_evaluation_set_export_bytes = MagicMock(return_value=b"xlsx")

        filename, payload = service.export_evaluation_set_impl(1, "t1")
        assert filename == "my set.xlsx"
        assert payload == b"xlsx"


# ---------------------------------------------------------------------------
# add_evaluation_set_case_impl
# ---------------------------------------------------------------------------


class TestAddEvaluationSetCase:
    def test_adds_single_turn_case(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        insert_mock = MagicMock(return_value=1)
        monkeypatch.setattr(service, "insert_evaluation_set_cases", insert_mock)
        recount = MagicMock()
        monkeypatch.setattr(service, "_recount_set_cases", recount)

        n = service.add_evaluation_set_case_impl(
            evaluation_set_id=1, tenant_id="t1", inputs={"query": "q"},
            label={"answer": "a"}, created_by="u1",
        )
        assert n == 1
        recount.assert_called_once()
        case = insert_mock.call_args.kwargs["cases"][0]
        assert case["turn_order"] == 0
        assert case["session_id"] is None

    def test_auto_turn_order_continues_session(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service, "list_case_turn_orders_by_session", MagicMock(return_value=[1, 2]),
        )
        insert_mock = MagicMock(return_value=1)
        monkeypatch.setattr(service, "insert_evaluation_set_cases", insert_mock)

        service.add_evaluation_set_case_impl(
            evaluation_set_id=1, tenant_id="t1", inputs={}, label={},
            created_by="u1", session_id="s1", turn_order=None,
        )
        case = insert_mock.call_args.kwargs["cases"][0]
        assert case["turn_order"] == 3

    def test_turn_mismatch_raises(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service, "list_case_turn_orders_by_session", MagicMock(return_value=[1]),
        )
        with pytest.raises(_AppException, match="expected turn_order 2"):
            service.add_evaluation_set_case_impl(
                evaluation_set_id=1, tenant_id="t1", inputs={}, label={},
                created_by="u1", session_id="s1", turn_order=9,
            )

    def test_no_recount_when_nothing_inserted(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(service, "insert_evaluation_set_cases", MagicMock(return_value=0))
        recount = MagicMock()
        monkeypatch.setattr(service, "_recount_set_cases", recount)

        service.add_evaluation_set_case_impl(
            evaluation_set_id=1, tenant_id="t1", inputs={}, label={}, created_by="u1",
        )
        recount.assert_not_called()


# ---------------------------------------------------------------------------
# _validate_turn_continuity / update_evaluation_set_case_impl
# ---------------------------------------------------------------------------


class TestValidateTurnContinuity:
    def test_skips_when_no_session(self, service_module, monkeypatch):
        service, _ = service_module
        turns = MagicMock()
        monkeypatch.setattr(service, "list_case_turn_orders_by_session", turns)
        service._validate_turn_continuity(1, 2, None, 5, True, True)
        turns.assert_not_called()

    def test_skips_when_unchanged(self, service_module, monkeypatch):
        service, _ = service_module
        turns = MagicMock()
        monkeypatch.setattr(service, "list_case_turn_orders_by_session", turns)
        service._validate_turn_continuity(1, 2, "s1", 1, False, False)
        turns.assert_not_called()

    def test_raises_on_mismatch(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "list_case_turn_orders_by_session", MagicMock(return_value=[1]),
        )
        with pytest.raises(_AppException, match="expected turn_order 2"):
            service._validate_turn_continuity(1, 2, "s1", 5, True, True)

    def test_passes_when_expected(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "list_case_turn_orders_by_session", MagicMock(return_value=[1]),
        )
        # expected = 2, new_turn_order = 2 → no raise
        service._validate_turn_continuity(1, 2, "s1", 2, True, True)


class TestUpdateEvaluationSetCase:
    def test_content_only_edit(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(return_value=[{"session_id": None, "turn_order": None}]),
        )
        rec = MagicMock()
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = rec
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))

        ok = service.update_evaluation_set_case_impl(
            evaluation_set_id=1, case_id=10, tenant_id="t1",
            inputs={"query": "new"}, label={"answer": "new"},
        )
        assert ok is True
        assert rec.inputs == {"query": "new"}
        session.commit.assert_called_once()

    def test_returns_false_when_case_missing(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(service, "get_cases_by_ids", MagicMock(return_value=[]))
        ok = service.update_evaluation_set_case_impl(
            evaluation_set_id=1, case_id=10, tenant_id="t1",
            inputs={}, label={},
        )
        assert ok is False

    def test_updates_session_and_turn(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(return_value=[{"session_id": "s1", "turn_order": 1}]),
        )
        monkeypatch.setattr(
            service, "list_case_turn_orders_by_session",
            MagicMock(return_value=[1, 2]),
        )
        rec = MagicMock()
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = rec
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))

        ok = service.update_evaluation_set_case_impl(
            evaluation_set_id=1, case_id=10, tenant_id="t1",
            inputs={}, label={}, session_id="s1", turn_order=3,
        )
        assert ok is True
        assert rec.session_id == "s1"
        assert rec.turn_order == 3


def _ctx(session):
    """Return a context manager yielding *session* (for get_db_session mocks)."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# _recount_set_cases / batch_delete_evaluation_set_cases_impl
# ---------------------------------------------------------------------------


class TestRecountSetCases:
    def test_updates_count(self, service_module, monkeypatch):
        service, _ = service_module
        session = MagicMock()
        q = session.query.return_value.filter.return_value
        q.count.return_value = 5
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))

        service._recount_set_cases(1)
        session.query.return_value.filter.return_value.update.assert_called()
        session.commit.assert_called_once()


class TestBatchDeleteCasesImpl:
    def test_deletes_and_recounts(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(return_value=[{"evaluation_set_case_id": 1, "session_id": "s1"}]),
        )
        monkeypatch.setattr(
            service, "list_case_turn_orders_by_session", MagicMock(return_value=[]),
        )
        batch = MagicMock(return_value=2)
        monkeypatch.setattr(service, "batch_delete_evaluation_set_cases", batch)
        recount = MagicMock()
        monkeypatch.setattr(service, "_recount_set_cases", recount)

        n = service.batch_delete_evaluation_set_cases_impl(1, [1, 2], "t1")
        assert n == 2
        recount.assert_called_once()

    def test_raises_when_remaining_not_contiguous(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(return_value=[{"evaluation_set_case_id": 1, "session_id": "s1"}]),
        )
        monkeypatch.setattr(
            service, "list_case_turn_orders_by_session", MagicMock(return_value=[1, 3]),
        )
        with pytest.raises(_AppException, match="would not be contiguous"):
            service.batch_delete_evaluation_set_cases_impl(1, [1], "t1")

    def test_single_turn_cases_skip_validation(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_check_set_not_in_use", MagicMock())
        monkeypatch.setattr(
            service,
            "get_cases_by_ids",
            MagicMock(return_value=[{"evaluation_set_case_id": 1, "session_id": None}]),
        )
        batch = MagicMock(return_value=1)
        monkeypatch.setattr(service, "batch_delete_evaluation_set_cases", batch)
        recount = MagicMock()
        monkeypatch.setattr(service, "_recount_set_cases", recount)

        assert service.batch_delete_evaluation_set_cases_impl(1, [1], "t1") == 1
        recount.assert_called_once()


# ---------------------------------------------------------------------------
# count_evaluation_sets_impl / _check_set_not_in_use (raise branch)
# ---------------------------------------------------------------------------


class TestCountImpl:
    def test_counts_sets(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "count_evaluation_sets", MagicMock(return_value=9))
        assert service.count_evaluation_sets_impl("t1") == 9


class TestCheckSetNotInUse:
    def test_raises_when_referenced(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "count_active_runs_using_set", MagicMock(return_value=2)
        )
        with pytest.raises(_AppException, match="referenced by 2"):
            service._check_set_not_in_use(1, "t1")


# ---------------------------------------------------------------------------
# KB-aware helpers
# ---------------------------------------------------------------------------


class TestResolveKbInfo:
    def test_resolves_and_skips_missing(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_index_name_by_knowledge_name",
            MagicMock(side_effect=["idx1", None]),
        )
        resolved = service._resolve_kb_info(["kb1", "kb2"], "t1")
        assert resolved == [{"display_name": "kb1", "index_name": "idx1"}]


class TestBuildKbDescriptions:
    def _session_with_first(self, rec):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = rec
        return session

    def test_builds_lines_with_and_without_desc(self, service_module, monkeypatch):
        service, _ = service_module
        kb_info = [
            {"display_name": "kb1", "index_name": "i1"},
            {"display_name": "kb2", "index_name": "i2"},
        ]
        session = self._session_with_first(("  nice desc  ",))
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))
        text = service._build_kb_descriptions(kb_info, "t1")
        assert "- kb1 - nice desc" in text
        assert "kb2" in text

    def test_no_records_uses_no_description_note(self, service_module, monkeypatch):
        service, _ = service_module
        session = self._session_with_first(None)
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))
        text = service._build_kb_descriptions(
            [{"display_name": "kb1", "index_name": "i1"}], "t1"
        )
        assert text == "- kb1 (no description)"

    def test_empty_kb_info_returns_empty(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(MagicMock()))
        assert service._build_kb_descriptions([], "t1") == ""


class TestPlanSearchQueries:
    def test_returns_empty_without_descriptions(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_build_kb_descriptions", MagicMock(return_value=""))
        assert service._plan_search_queries([{"display_name": "kb1"}], "d", "m", "t1") == []

    def test_plans_from_llm(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_build_kb_descriptions", MagicMock(return_value="block")
        )
        monkeypatch.setattr(
            service,
            "get_prompt_template",
            MagicMock(return_value={"SYSTEM_PROMPT": "sp"}),
        )
        monkeypatch.setattr(
            service,
            "call_llm_for_system_prompt",
            MagicMock(return_value='{"queries": ["q1", "q2"]}'),
        )
        queries = service._plan_search_queries([{"display_name": "kb1"}], "d", "m", "t1")
        assert queries == ["q1", "q2"]

    def test_falls_back_when_llm_fails(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_build_kb_descriptions", MagicMock(return_value="block")
        )
        monkeypatch.setattr(
            service, "get_prompt_template", MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        )
        monkeypatch.setattr(
            service, "call_llm_for_system_prompt", MagicMock(side_effect=ValueError("x"))
        )
        queries = service._plan_search_queries(
            [{"display_name": "kb1", "index_name": "i1"}], "d", "m", "t1"
        )
        assert queries == ["kb1", "overview", "policy", "process", "rule"]


class TestExecuteKbSearches:
    def test_returns_empty_when_nothing_to_search(self, service_module, monkeypatch):
        service, _ = service_module
        assert service._execute_kb_searches([], ["q"], "t1") == ""
        assert service._execute_kb_searches([{"display_name": "kb1"}], [], "t1") == ""

    def test_searches_all_kbs(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            sys.modules["management.services.knowledge_base.service"],
            "get_vector_db_core",
            MagicMock(return_value="es_core"),
        )
        monkeypatch.setattr(
            service, "_get_kb_embedding_model", MagicMock(return_value="model")
        )
        monkeypatch.setattr(
            service, "_search_kb_for_query", MagicMock(return_value=["- hit"])
        )
        text = service._execute_kb_searches(
            [{"display_name": "kb1", "index_name": "i1"}], ["q1"], "t1", top_k=2
        )
        assert "### kb1" in text
        assert "- hit" in text

    def test_skips_kb_without_embedding_model(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            sys.modules["management.services.knowledge_base.service"],
            "get_vector_db_core",
            MagicMock(return_value="es_core"),
        )
        monkeypatch.setattr(service, "_get_kb_embedding_model", MagicMock(return_value=None))
        text = service._execute_kb_searches(
            [{"display_name": "kb1", "index_name": "i1"}], ["q1"], "t1"
        )
        assert text == ""


class TestGetKbEmbeddingModel:
    def test_returns_model(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            sys.modules["management.services.knowledge_base.service"],
            "get_embedding_model_by_index_name",
            MagicMock(return_value=("m", None, None)),
        )
        assert service._get_kb_embedding_model("t1", {"index_name": "i1"}) == "m"

    def test_returns_none_when_model_missing(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            sys.modules["management.services.knowledge_base.service"],
            "get_embedding_model_by_index_name",
            MagicMock(return_value=(None, None, None)),
        )
        assert service._get_kb_embedding_model("t1", {"index_name": "i1"}) is None

    def test_returns_none_on_error(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            sys.modules["management.services.knowledge_base.service"],
            "get_embedding_model_by_index_name",
            MagicMock(side_effect=RuntimeError("x")),
        )
        assert service._get_kb_embedding_model("t1", {"index_name": "i1"}) is None


class TestSearchKbForQuery:
    def _hit(self, content, score=0.0):
        return {"_source": {"content": content}, "_score": score}

    def test_formats_hits(self, service_module):
        service, _ = service_module
        es_core = MagicMock()
        es_core.search.return_value = {"hits": {"hits": [self._hit("hello world", 0.5)]}}
        embedding_model = MagicMock()
        embedding_model.get_embeddings.return_value = [[0.1, 0.2]]
        hits = service._search_kb_for_query(
            es_core, {"display_name": "kb1", "index_name": "i1"}, "q", embedding_model, 3
        )
        assert len(hits) == 1
        assert "[q]" in hits[0]
        assert "hello world" in hits[0]

    def test_returns_empty_on_error(self, service_module):
        service, _ = service_module
        es_core = MagicMock()
        es_core.search.side_effect = RuntimeError("boom")
        embedding_model = MagicMock()
        embedding_model.get_embeddings.return_value = [[0.1]]
        hits = service._search_kb_for_query(
            es_core, {"display_name": "kb1", "index_name": "i1"}, "q", embedding_model, 3
        )
        assert hits == []


class TestFormatKbHit:
    def test_formats_content(self, service_module):
        service, _ = service_module
        line = service._format_kb_hit(
            {"_source": {"content": "  some content  "}, "_score": 1.0}, "q"
        )
        assert line.startswith("- [q] (score=1.00)")
        assert "some content" in line

    def test_returns_empty_when_no_content(self, service_module):
        service, _ = service_module
        assert service._format_kb_hit({"_source": {}}, "q") == ""

    def test_parses_str_source_and_clamps_score(self, service_module):
        service, _ = service_module
        line = service._format_kb_hit(
            {"_source": '{"content": "abc", "x": 1}', "_score": -3.0}, "q"
        )
        assert line.endswith("abc")

    def test_unparsable_str_source_returns_empty(self, service_module):
        service, _ = service_module
        assert service._format_kb_hit({"_source": "not-json"}, "q") == ""


class TestUpdateGenerationStatus:
    def test_updates_and_commits(self, service_module, monkeypatch):
        service, _ = service_module
        session = MagicMock()
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))
        service._update_generation_status(1, "t1", "GENERATING", 25)
        session.query.return_value.filter.return_value.update.assert_called_once()
        session.commit.assert_called_once()

    def test_swallows_errors(self, service_module, monkeypatch):
        service, _ = service_module
        session = MagicMock()
        session.query.return_value.filter.return_value.update.side_effect = RuntimeError("x")
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))
        service._update_generation_status(1, "t1", "FAILED", 0)  # must not raise


class TestDoKbSearch:
    def test_returns_empty_when_no_names(self, service_module, monkeypatch):
        service, _ = service_module
        assert service._do_kb_search(None, "d", "m", "t1") == ""

    def test_returns_empty_when_no_kb_resolved(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_resolve_kb_info", MagicMock(return_value=[]))
        assert service._do_kb_search(["kb1"], "d", "m", "t1") == ""

    def test_returns_empty_when_no_queries(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_resolve_kb_info", MagicMock(return_value=[{"display_name": "kb1"}])
        )
        monkeypatch.setattr(service, "_plan_search_queries", MagicMock(return_value=[]))
        assert service._do_kb_search(["kb1"], "d", "m", "t1") == ""

    def test_returns_kb_context(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_resolve_kb_info", MagicMock(return_value=[{"display_name": "kb1"}])
        )
        monkeypatch.setattr(
            service, "_plan_search_queries", MagicMock(return_value=["q1"])
        )
        monkeypatch.setattr(
            service, "_execute_kb_searches", MagicMock(return_value="ctx")
        )
        assert service._do_kb_search(["kb1"], "d", "m", "t1") == "ctx"

    def test_logs_warning_when_no_results(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_resolve_kb_info", MagicMock(return_value=[{"display_name": "kb1"}])
        )
        monkeypatch.setattr(
            service, "_plan_search_queries", MagicMock(return_value=["q1"])
        )
        monkeypatch.setattr(service, "_execute_kb_searches", MagicMock(return_value=""))
        assert service._do_kb_search(["kb1"], "d", "m", "t1") == ""


class TestBuildAgentContextBlock:
    def test_returns_empty_without_agent(self, service_module, monkeypatch):
        service, _ = service_module
        assert service._build_agent_context_block(None, "t1") == ""

    def test_returns_formatted_profile(self, service_module, monkeypatch):
        service, _ = service_module
        profile_mock = sys.modules["utils.agent_profile_utils"]
        profile_mock.fetch_agent_profile = MagicMock(return_value="profile")
        profile_mock.format_agent_profile_context = MagicMock(return_value="agent ctx")
        assert service._build_agent_context_block(7, "t1") == "agent ctx"

    def test_returns_empty_when_profile_context_empty(self, service_module, monkeypatch):
        service, _ = service_module
        profile_mock = sys.modules["utils.agent_profile_utils"]
        profile_mock.fetch_agent_profile = MagicMock(return_value="profile")
        profile_mock.format_agent_profile_context = MagicMock(return_value="")
        assert service._build_agent_context_block(7, "t1") == ""

    def test_returns_empty_on_error(self, service_module, monkeypatch):
        service, _ = service_module
        profile_mock = sys.modules["utils.agent_profile_utils"]
        profile_mock.fetch_agent_profile = MagicMock(side_effect=RuntimeError("x"))
        assert service._build_agent_context_block(7, "t1") == ""


class TestFormatKbName:
    def test_with_description(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "_resolve_kb_info",
            MagicMock(return_value=[{"display_name": "kb1", "description": "d" * 200}]),
        )
        name = service._format_kb_name("kb1", "t1")
        assert name.startswith("kb1（")
        assert name.endswith("）")
        assert len(name) <= len("kb1（" + "d" * 150 + "）")

    def test_without_description(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_resolve_kb_info", MagicMock(return_value=[]))
        assert service._format_kb_name("kb1", "t1") == "kb1"


class TestBuildKbContextBlock:
    def test_uses_search_results(self, service_module, monkeypatch):
        service, _ = service_module
        block = service._build_kb_context_block("search text", ["kb1"], "t1")
        assert "## 知识库检索到的真实内容" in block
        assert "search text" in block

    def test_returns_empty_without_names(self, service_module, monkeypatch):
        service, _ = service_module
        assert service._build_kb_context_block("", None, "t1") == ""

    def test_falls_back_to_name_list(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_format_kb_name", MagicMock(return_value="kb1(desc)"))
        block = service._build_kb_context_block("", ["kb1"], "t1")
        assert "kb1(desc)" in block
        assert "未检索到内容" in block


class TestBuildCaseGenContextBlocks:
    def test_assembles_all_blocks(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_build_agent_context_block", MagicMock(return_value="agent")
        )
        monkeypatch.setattr(
            service, "_build_kb_context_block", MagicMock(return_value="kb")
        )
        blocks = service._build_case_gen_context_blocks(
            1, "t1", "scene", "kbctx", ["kb1"], "file content", "doc.pdf"
        )
        assert blocks == ["agent", "## 场景描述\nscene", "kb", "## 上传文档: doc.pdf\nfile content"]

    def test_minimal_blocks(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_build_agent_context_block", MagicMock(return_value="")
        )
        monkeypatch.setattr(
            service, "_build_kb_context_block", MagicMock(return_value="")
        )
        blocks = service._build_case_gen_context_blocks(
            None, "t1", "scene", "", None, None, None
        )
        assert blocks == ["## 场景描述\nscene"]


class TestBuildCaseGenUserPrompt:
    def test_appends_instruction_with_sources(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_prompt_template",
            MagicMock(
                return_value={
                    "USER_PROMPT_INSTRUCTION": "use {{sources}} count {{count}} max {{max_turns}}"
                }
            ),
        )
        prompt = service._build_case_gen_user_prompt(
            ["ctx1", "ctx2"], 5, "kbctx", 7, "file"
        )
        assert prompt.startswith("ctx1\n\nctx2")
        assert "use 场景描述、知识库检索内容、Agent 配置（含工具、技能、子智能体）、上传的参考文档" in prompt
        assert "count 5" in prompt
        assert "max 100" in prompt

    def test_returns_context_when_no_instruction(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "get_prompt_template", MagicMock(return_value={})
        )
        prompt = service._build_case_gen_user_prompt(["ctx1"], 1, "", None, None)
        assert prompt == "ctx1"


class TestParseLlmCasesResponse:
    def test_parses_json_string(self, service_module):
        service, _ = service_module
        assert service._parse_llm_cases_response('[{"a": 1}]') == [{"a": 1}]

    def test_parses_markdown_fence(self, service_module):
        service, _ = service_module
        resp = '```json\n[{"a": 2}]\n```'
        assert service._parse_llm_cases_response(resp) == [{"a": 2}]

    def test_raises_on_unparsable(self, service_module):
        service, _ = service_module
        with pytest.raises(_AppException) as excinfo:
            service._parse_llm_cases_response("not json at all")
        assert (
            excinfo.value.error_code
            == service.ErrorCode.AGENT_EVALUATION_CASE_GENERATION_FORMAT
        )

    def test_raises_when_not_list(self, service_module):
        service, _ = service_module
        with pytest.raises(_AppException) as excinfo:
            service._parse_llm_cases_response('{"queries": []}')
        assert (
            excinfo.value.error_code
            == service.ErrorCode.AGENT_EVALUATION_CASE_GENERATION_FORMAT
        )


class TestNormalizeOneGeneratedCase:
    def test_normalizes_valid_case(self, service_module):
        service, _ = service_module
        case = service._normalize_one_generated_case(
            {
                "inputs": {"query": "  q  "},
                "label": {"answer": "  a  "},
                "session_id": "s1",
                "turn_order": "3",
            }
        )
        assert case == {
            "inputs": {"query": "q"},
            "label": {"answer": "a"},
            "session_id": "s1",
            "turn_order": 3,
        }

    def test_returns_none_when_missing_fields(self, service_module):
        service, _ = service_module
        assert service._normalize_one_generated_case({"inputs": {}}) is None
        assert service._normalize_one_generated_case("x") is None

    def test_ignores_invalid_turn_order(self, service_module):
        service, _ = service_module
        case = service._normalize_one_generated_case(
            {
                "inputs": {"query": "q"},
                "label": {"answer": "a"},
                "session_id": 3,
                "turn_order": "abc",
            }
        )
        assert case == {"inputs": {"query": "q"}, "label": {"answer": "a"}}


class TestCallLlmAndExtractCases:
    def test_extracts_valid_cases(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_prompt_template",
            MagicMock(return_value={"SYSTEM_PROMPT": "sp {{max_turns}}"}),
        )
        monkeypatch.setattr(
            service,
            "call_llm_for_system_prompt",
            MagicMock(
                return_value='[{"inputs": {"query": "q1"}, "label": {"answer": "a1"}}, '
                '{"inputs": {"query": "q2"}, "label": {"answer": "a2"}}]'
            ),
        )
        cases = service._call_llm_and_extract_cases("m", "prompt", "t1")
        assert len(cases) == 2
        assert cases[0]["inputs"]["query"] == "q1"

    def test_raises_when_no_valid_cases(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "get_prompt_template",
            MagicMock(return_value={"SYSTEM_PROMPT": "sp"}),
        )
        monkeypatch.setattr(
            service, "call_llm_for_system_prompt", MagicMock(return_value="[]")
        )
        with pytest.raises(_AppException) as excinfo:
            service._call_llm_and_extract_cases("m", "prompt", "t1")
        assert (
            excinfo.value.error_code
            == service.ErrorCode.AGENT_EVALUATION_CASE_GENERATION_EMPTY
        )


class TestGenerateCasesByLlmImpl:
    def _default_mocks(self, service, monkeypatch, cases):
        monkeypatch.setattr(service, "_do_kb_search", MagicMock(return_value="kbctx"))
        monkeypatch.setattr(
            service,
            "_build_case_gen_context_blocks",
            MagicMock(return_value=["block"]),
        )
        monkeypatch.setattr(
            service, "_build_case_gen_user_prompt", MagicMock(return_value="prompt")
        )
        monkeypatch.setattr(
            service, "_call_llm_and_extract_cases", MagicMock(return_value=cases)
        )

    def test_generates_and_truncates(self, service_module, monkeypatch):
        service, _ = service_module
        cases = [
            {"inputs": {"query": "q1"}, "label": {"answer": "a1"}},
            {"inputs": {"query": "q2"}, "label": {"answer": "a2"}},
            {"inputs": {"query": "q3"}, "label": {"answer": "a3"}},
        ]
        self._default_mocks(service, monkeypatch, cases)
        result = service.generate_cases_by_llm_impl(
            description="d", count=2, tenant_id="t1", model_id="m"
        )
        assert result == cases[:2]

    def test_passes_through_app_exception(self, service_module, monkeypatch):
        service, _ = service_module
        self._default_mocks(service, monkeypatch, [])
        err = _AppException(service.ErrorCode.AGENT_EVALUATION_CASE_GENERATION_EMPTY)
        monkeypatch.setattr(
            service, "_call_llm_and_extract_cases", MagicMock(side_effect=err)
        )
        with pytest.raises(_AppException) as excinfo:
            service.generate_cases_by_llm_impl(
                description="d", count=1, tenant_id="t1", model_id="m"
            )
        assert excinfo.value is err

    def test_wraps_generic_exception(self, service_module, monkeypatch):
        service, _ = service_module
        self._default_mocks(service, monkeypatch, [])
        monkeypatch.setattr(
            service,
            "_call_llm_and_extract_cases",
            MagicMock(side_effect=ValueError("boom")),
        )
        with pytest.raises(_AppException) as excinfo:
            service.generate_cases_by_llm_impl(
                description="d", count=1, tenant_id="t1", model_id="m"
            )
        assert excinfo.value.error_code == service.ErrorCode.COMMON_VALIDATION_ERROR
        assert "boom" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Async generation orchestration
# ---------------------------------------------------------------------------


class TestReportProgress:
    def test_forwards_to_status_update(self, service_module, monkeypatch):
        service, _ = service_module
        upd = MagicMock()
        monkeypatch.setattr(service, "_update_generation_status", upd)
        service._report_progress(1, "t1", 50)
        upd.assert_called_once_with(1, "t1", "GENERATING", 50)


class TestInsertGeneratedCases:
    def test_inserts_valid_and_reports_progress(self, service_module, monkeypatch):
        service, _ = service_module
        insert = MagicMock()
        monkeypatch.setattr(service, "insert_evaluation_set_cases", insert)
        progress = MagicMock()
        monkeypatch.setattr(service, "_report_progress", progress)
        cases = [
            {"inputs": {"query": "q1"}, "label": {"answer": "a1"}, "session_id": "s1", "turn_order": 1},
            {"inputs": {"query": "q2"}, "label": {"answer": "a2"}},
            {"not": "a case"},
        ]
        written = service._insert_generated_cases(cases, 1, "t1", "u1")
        assert written == 2
        assert insert.call_count == 2
        first = insert.call_args_list[0].kwargs["cases"][0]
        assert first["order_no"] == 1
        assert first["session_id"] == "s1"
        assert first["turn_order"] == 1
        assert progress.call_count == 3
        assert progress.call_args_list[-1].args[2] == 99


class TestFinalizeGeneration:
    def test_recounts_and_marks_done(self, service_module, monkeypatch):
        service, _ = service_module
        recount = MagicMock()
        monkeypatch.setattr(service, "_recount_set_cases", recount)
        upd = MagicMock()
        monkeypatch.setattr(service, "_update_generation_status", upd)
        service._finalize_generation(1, "t1", "u1")
        recount.assert_called_once_with(1)
        upd.assert_called_once_with(1, "t1", "DONE", 100)


class TestHandleGenerationFailure:
    def test_new_set_deletes_it(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "_update_generation_status", MagicMock(side_effect=RuntimeError("x"))
        )
        hard = MagicMock()
        monkeypatch.setattr(service, "hard_delete_evaluation_set", hard)
        service._handle_generation_failure(1, "t1", "u1", True, None)
        hard.assert_called_once_with(1, "t1")

    def test_new_set_swallows_delete_error(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service,
            "hard_delete_evaluation_set",
            MagicMock(side_effect=RuntimeError("x")),
        )
        service._handle_generation_failure(1, "t1", "u1", True, None)  # must not raise

    def test_existing_set_rolls_back_cases(self, service_module, monkeypatch):
        service, _ = service_module

        class _CreateTime:
            def __ge__(self, other):
                return True

        sys.modules["database.db_models"].EvaluationSetCase.create_time = _CreateTime()
        monkeypatch.setattr(service, "_update_generation_status", MagicMock())
        session = MagicMock()
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))
        service._handle_generation_failure(1, "t1", "u1", False, None)
        session.query.return_value.filter.return_value.delete.assert_called_once()
        session.commit.assert_called_once()

    def test_swallows_cleanup_errors(self, service_module, monkeypatch):
        service, _ = service_module

        class _CreateTime:
            def __ge__(self, other):
                return True

        sys.modules["database.db_models"].EvaluationSetCase.create_time = _CreateTime()
        monkeypatch.setattr(service, "_update_generation_status", MagicMock())
        session = MagicMock()
        session.query.return_value.filter.return_value.delete.side_effect = RuntimeError("x")
        monkeypatch.setattr(service, "get_db_session", lambda: _ctx(session))
        service._handle_generation_failure(1, "t1", "u1", False, None)  # must not raise


class TestGenerateCasesAsync:
    def test_orchestrates_success(self, service_module, monkeypatch):
        service, _ = service_module
        progress = MagicMock()
        monkeypatch.setattr(service, "_report_progress", progress)
        monkeypatch.setattr(service, "_do_kb_search", MagicMock(return_value="kbctx"))
        monkeypatch.setattr(
            service,
            "_build_case_gen_context_blocks",
            MagicMock(return_value=["block"]),
        )
        monkeypatch.setattr(
            service, "_build_case_gen_user_prompt", MagicMock(return_value="prompt")
        )
        cases = [
            {"inputs": {"query": "q1"}, "label": {"answer": "a1"}},
            {"inputs": {"query": "q2"}, "label": {"answer": "a2"}},
            {"inputs": {"query": "q3"}, "label": {"answer": "a3"}},
        ]
        monkeypatch.setattr(
            service, "_call_llm_and_extract_cases", MagicMock(return_value=cases)
        )
        insert = MagicMock()
        monkeypatch.setattr(service, "_insert_generated_cases", insert)
        finalize = MagicMock()
        monkeypatch.setattr(service, "_finalize_generation", finalize)

        service._generate_cases_async(
            set_id=1, tenant_id="t1", user_id="u1", description="d", count=2,
            model_id="m", file_content=None, file_name=None, agent_id=None,
            is_new_set=True, knowledge_base_names=["kb1"],
        )
        assert progress.call_args_list[0].args == (1, "t1", 0)
        assert progress.call_args_list[1].args == (1, "t1", 8)
        assert progress.call_args_list[2].args == (1, "t1", 10)
        assert progress.call_args_list[3].args == (1, "t1", 50)
        insert.assert_called_once_with(cases[:2], 1, "t1", "u1")
        finalize.assert_called_once_with(1, "t1", "u1")

    def test_handles_failure(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(service, "_report_progress", MagicMock())
        monkeypatch.setattr(service, "_do_kb_search", MagicMock(return_value="kbctx"))
        monkeypatch.setattr(
            service,
            "_build_case_gen_context_blocks",
            MagicMock(return_value=["block"]),
        )
        monkeypatch.setattr(
            service, "_build_case_gen_user_prompt", MagicMock(return_value="prompt")
        )
        monkeypatch.setattr(
            service,
            "_call_llm_and_extract_cases",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        fail = MagicMock()
        monkeypatch.setattr(service, "_handle_generation_failure", fail)

        service._generate_cases_async(
            set_id=1, tenant_id="t1", user_id="u1", description="d", count=1,
            model_id="m", file_content=None, file_name=None, agent_id=None,
            is_new_set=False, knowledge_base_names=None,
        )
        assert fail.call_count == 1
        assert fail.call_args[0][3] is False
