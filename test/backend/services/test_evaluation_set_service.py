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


# ---------------------------------------------------------------------------
# _validate_single_turn_case — drives the parser's per-case validation.
# ---------------------------------------------------------------------------

class TestValidateSingleTurnCase:
    def test_accepts_minimal_case(self, service_module):
        service, _ = service_module
        result = service._validate_single_turn_case(
            {"inputs": {"query": "hi"}, "label": {"answer": "hello"}},
        )
        assert result == {
            "case_id": None,
            "inputs": {"query": "hi"},
            "label": {"answer": "hello"},
        }

    def test_includes_context_when_provided(self, service_module):
        service, _ = service_module
        result = service._validate_single_turn_case({
            "inputs": {"query": "q", "context": "ctx"},
            "label": {"answer": "a"},
        })
        assert result["inputs"]["context"] == "ctx"

    def test_includes_case_id_when_provided(self, service_module):
        service, _ = service_module
        result = service._validate_single_turn_case({
            "case_id": "c1",
            "inputs": {"query": "q"},
            "label": {"answer": "a"},
        })
        assert result["case_id"] == "c1"

    def test_rejects_non_dict(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="case must be an object"):
            service._validate_single_turn_case(["not a dict"])

    def test_rejects_missing_inputs(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="inputs must be an object"):
            service._validate_single_turn_case({"label": {"answer": "a"}})

    def test_rejects_missing_label(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="label must be an object"):
            service._validate_single_turn_case({"inputs": {"query": "q"}})

    def test_rejects_empty_query(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="inputs.query must be a non-empty string"):
            service._validate_single_turn_case(
                {"inputs": {"query": "   "}, "label": {"answer": "a"}},
            )

    def test_rejects_non_string_query(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="inputs.query must be a non-empty string"):
            service._validate_single_turn_case(
                {"inputs": {"query": 123}, "label": {"answer": "a"}},
            )

    def test_rejects_non_string_context(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="inputs.context must be a string"):
            service._validate_single_turn_case({
                "inputs": {"query": "q", "context": 123},
                "label": {"answer": "a"},
            })

    def test_rejects_empty_answer(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="label.answer must be a non-empty string"):
            service._validate_single_turn_case(
                {"inputs": {"query": "q"}, "label": {"answer": ""}},
            )

    def test_rejects_non_string_answer(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="label.answer must be a non-empty string"):
            service._validate_single_turn_case(
                {"inputs": {"query": "q"}, "label": {"answer": None}},
            )

    def test_rejects_non_string_case_id(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="case_id must be a string"):
            service._validate_single_turn_case({
                "case_id": 123,
                "inputs": {"query": "q"},
                "label": {"answer": "a"},
            })


# ---------------------------------------------------------------------------
# parse_jsonl_cases — exercises the JSONL parser and its error branches.
# ---------------------------------------------------------------------------

class TestParseJsonlCases:
    def test_parses_single_case(self, service_module):
        service, _ = service_module
        cases = service.parse_jsonl_cases(
            '{"inputs": {"query": "q"}, "label": {"answer": "a"}}',
        )
        assert len(cases) == 1
        assert cases[0]["inputs"]["query"] == "q"
        assert cases[0]["order_no"] == 0

    def test_parses_multiple_cases_with_order_no(self, service_module):
        service, _ = service_module
        jsonl = (
            '{"inputs": {"query": "q1"}, "label": {"answer": "a1"}}\n'
            '{"inputs": {"query": "q2"}, "label": {"answer": "a2"}}\n'
            '{"inputs": {"query": "q3"}, "label": {"answer": "a3"}}\n'
        )
        cases = service.parse_jsonl_cases(jsonl)
        assert len(cases) == 3
        assert [c["order_no"] for c in cases] == [0, 1, 2]

    def test_skips_blank_lines(self, service_module):
        service, _ = service_module
        jsonl = (
            '\n'
            '{"inputs": {"query": "q"}, "label": {"answer": "a"}}\n'
            '\n\n'
        )
        cases = service.parse_jsonl_cases(jsonl)
        assert len(cases) == 1

    def test_rejects_invalid_json(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="Invalid JSON at line 1"):
            service.parse_jsonl_cases('{not valid json')

    def test_rejects_invalid_json_on_second_line(self, service_module):
        service, _ = service_module
        jsonl = (
            '{"inputs": {"query": "q"}, "label": {"answer": "a"}}\n'
            '{garbage\n'
        )
        with pytest.raises(ValueError, match="Invalid JSON at line 2"):
            service.parse_jsonl_cases(jsonl)

    def test_rejects_empty_jsonl(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="JSONL contains no cases"):
            service.parse_jsonl_cases("")

    def test_rejects_only_blank_lines(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="JSONL contains no cases"):
            service.parse_jsonl_cases("\n\n   \n")

    def test_propagates_validation_errors_with_line_numbers(self, service_module):
        service, _ = service_module
        jsonl = (
            '{"inputs": {"query": "q"}, "label": {"answer": "a"}}\n'
            '{"inputs": {"query": ""}, "label": {"answer": "a"}}\n'
        )
        with pytest.raises(ValueError, match="inputs.query must be a non-empty string"):
            service.parse_jsonl_cases(jsonl)


# ---------------------------------------------------------------------------
# create_evaluation_set_from_cases
# ---------------------------------------------------------------------------

class TestCreateEvaluationSetFromCases:
    def test_creates_and_inserts_with_case_count(self, service_module, monkeypatch):
        service, _ = service_module

        # Wire mocks on the freshly imported module reference.
        monkeypatch.setattr(
            service, "create_evaluation_set",
            MagicMock(return_value={"evaluation_set_id": 42}),
        )
        monkeypatch.setattr(
            service, "insert_evaluation_set_cases",
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
            tenant_id="t1", name="n", description="d",
            source_filename="src", cases=cases, created_by="u1",
        )

        assert meta == {"evaluation_set_id": 42, "case_count": 3}
        update_mock.assert_called_once_with(42, 3, updated_by="u1")

    def test_rejects_empty_cases(self, service_module):
        service, _ = service_module
        with pytest.raises(ValueError, match="cases is empty"):
            service.create_evaluation_set_from_cases(
                tenant_id="t1", name="n", description=None,
                source_filename=None, cases=[], created_by="u1",
            )


# ---------------------------------------------------------------------------
# create_evaluation_set_from_jsonl
# ---------------------------------------------------------------------------

class TestCreateEvaluationSetFromJsonl:
    def test_parses_and_delegates(self, service_module, monkeypatch):
        service, _ = service_module
        delegator = MagicMock(return_value={"evaluation_set_id": 1})
        monkeypatch.setattr(service, "create_evaluation_set_from_cases", delegator)
        monkeypatch.setattr(
            service, "parse_jsonl_cases",
            MagicMock(return_value=[{"inputs": {"query": "q"}, "label": {"answer": "a"}}]),
        )

        result = service.create_evaluation_set_from_jsonl(
            tenant_id="t1", name="n", description="d",
            source_filename="src", jsonl_text="ignored", created_by="u1",
        )
        assert result == {"evaluation_set_id": 1}
        delegator.assert_called_once()


# ---------------------------------------------------------------------------
# list / get / list_cases impls — thin pass-through wrappers.
# ---------------------------------------------------------------------------

class TestListImpls:
    def test_list_evaluation_sets_impl(self, service_module, monkeypatch):
        service, _ = service_module
        underlying = MagicMock(return_value=[{"id": 1}])
        monkeypatch.setattr(service, "list_evaluation_sets", underlying)

        result = service.list_evaluation_sets_impl(
            tenant_id="t1", limit=10, offset=20,
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

        result = service.list_evaluation_set_cases_impl(
            evaluation_set_id=1, tenant_id="t1", limit=5, offset=10,
        )
        underlying.assert_called_once_with(
            evaluation_set_id=1, tenant_id="t1", limit=5, offset=10,
        )
        assert result == [{"case_id": 1}]


# ---------------------------------------------------------------------------
# resolve_latest_published_version_no
# ---------------------------------------------------------------------------

class TestResolveLatestVersion:
    def test_returns_latest_version(self, service_module, monkeypatch):
        service, _ = service_module
        # query_version_list returns latest-first by existing convention.
        monkeypatch.setattr(
            service, "query_version_list",
            MagicMock(return_value=[{"version_no": 7}, {"version_no": 3}]),
        )
        assert service.resolve_latest_published_version_no(1, "t1") == 7

    def test_returns_coerced_int(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "query_version_list",
            MagicMock(return_value=[{"version_no": "9"}]),
        )
        assert service.resolve_latest_published_version_no(1, "t1") == 9

    def test_raises_when_no_versions(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "query_version_list", MagicMock(return_value=[]),
        )
        with pytest.raises(ValueError, match="no published versions"):
            service.resolve_latest_published_version_no(1, "t1")

    def test_raises_when_version_no_missing(self, service_module, monkeypatch):
        service, _ = service_module
        monkeypatch.setattr(
            service, "query_version_list",
            MagicMock(return_value=[{"name": "no_version_field"}]),
        )
        with pytest.raises(ValueError, match="failed to resolve"):
            service.resolve_latest_published_version_no(1, "t1")
