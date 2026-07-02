"""Unit tests for agent_evaluation_service focusing on the new
delete-only-creator behavior and the failed-cases-only Excel report."""

import sys
import types
import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Pre-stub heavy third-party packages that are imported transitively by the
# SDK / database layers we do not exercise in these unit tests.
sys.modules["boto3"] = MagicMock()
sys.modules["botocore"] = MagicMock()
sys.modules["botocore.client"] = MagicMock()
sys.modules["botocore.exceptions"] = MagicMock()
sys.modules["openjiuwen"] = MagicMock()

# Use a top-level MagicMock for sqlalchemy so any submodule attribute access
# (sqlalchemy.orm, sqlalchemy.sql, etc.) succeeds without error.
_sqlalchemy_root = MagicMock()
sys.modules["sqlalchemy"] = _sqlalchemy_root

# Stub out the ``services`` and ``nexent`` packages so importing
# ``services.agent_evaluation_service`` does not pull in the full dependency
# graph. We pre-register the specific submodules the service module imports
# under ``sys.modules`` so attribute lookups succeed.
def _register_package(name: str) -> types.ModuleType:
    """Register ``name`` as a real package on ``sys.modules``.

    Real ``__path__`` (pointing to the matching backend dir when one applies)
    is used so subsequent ``from X.Y import Z`` resolution can locate
    submodules; this prevents sibling tests from seeing a stubbed package
    with no resolvable submodules.

    If ``sys.modules[name]`` already exposes ``__path__`` (e.g. a stub
    created by a sibling test file) we reuse it so we don't fork the
    package identity mid-session — module-level execution of one test
    file would otherwise orphan the other file's package object, and
    ``from package import X`` would then short-circuit through a stale
    cache that has no entry in ``sys.modules``.
    """
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _BACKEND_DIR / name
    if backend_path.is_dir():
        pkg.__path__ = [str(backend_path)]
    else:
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
# Attach subpackages to their parents so ``nexent.X.Y`` attribute access works
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

# Stub the services package with the real backend path so that
# ``from services.X import Y`` resolves to the actual file under test, while
# letting us pre-stub sibling service modules below without triggering their
# full dependency chains.
_services_pkg = sys.modules.get("services")
if _services_pkg is None or not hasattr(_services_pkg, "__path__"):
    _services_pkg = types.ModuleType("services")
    _services_pkg.__path__ = [str(_BACKEND_DIR / "services")]
    sys.modules["services"] = _services_pkg

_agent_service_module = types.ModuleType("services.agent_service")
_agent_service_module.prepare_agent_run = MagicMock()
sys.modules["services.agent_service"] = _agent_service_module
_services_pkg.agent_service = _agent_service_module

# database package and its submodules touched at import time
_db_pkg = _register_package("database")
_db_pkg.get_db_session = MagicMock()
_db_pkg.as_dict = MagicMock()

_agent_version_db_mock = MagicMock()
_agent_version_db_mock.query_version_list = MagicMock()
sys.modules["database.agent_version_db"] = _agent_version_db_mock
_db_pkg.agent_version_db = _agent_version_db_mock

_evaluation_set_db_mock = MagicMock()
_evaluation_set_db_mock.soft_delete_evaluation_set = MagicMock()
sys.modules["database.evaluation_set_db"] = _evaluation_set_db_mock
_db_pkg.evaluation_set_db = _evaluation_set_db_mock

_agent_evaluation_db_mock = MagicMock()
_agent_evaluation_db_mock.get_agent_evaluation = MagicMock()
_agent_evaluation_db_mock.list_agent_evaluation_cases = MagicMock()
_agent_evaluation_db_mock.soft_delete_agent_evaluation = MagicMock()
sys.modules["database.agent_evaluation_db"] = _agent_evaluation_db_mock
_db_pkg.agent_evaluation_db = _agent_evaluation_db_mock

# database.client / database.db_models are imported by both service modules.
_db_client_module = MagicMock()
_db_client_module.get_db_session = MagicMock()
_db_client_module.as_dict = MagicMock()
sys.modules["database.client"] = _db_client_module
_db_pkg.client = _db_client_module

_db_models_module = MagicMock()
sys.modules["database.db_models"] = _db_models_module
_db_pkg.db_models = _db_models_module

# consts.model referenced by the service
_consts_pkg = _register_package("consts")
_consts_model_module = types.ModuleType("consts.model")
_consts_model_module.AgentRequest = MagicMock()
sys.modules["consts.model"] = _consts_model_module
_consts_pkg.model = _consts_model_module

# adapters (Jiuwen SDK) stubs
_adapters_pkg = _register_package("adapters")
_adapters_exc_module = types.ModuleType("adapters.exception")
_adapters_exc_module.JiuwenSDKError = Exception
_adapters_exc_module.JiuwenSDKUnavailableError = Exception
sys.modules["adapters.exception"] = _adapters_exc_module
_adapters_pkg.exception = _adapters_exc_module

_jiuwen_module = MagicMock()
_jiuwen_module.JiuwenSDKAdapter = None
sys.modules["adapters.jiuwen_sdk_adapter"] = _jiuwen_module
_adapters_pkg.jiuwen_sdk_adapter = _jiuwen_module

# Make sure pre-existing real utils package is in sys.modules so
# the app test (and any sibling tests) can resolve doted paths like
# ``utils.auth_utils`` without hitting a stubbed package.
_existing_utils = sys.modules.get("utils")
if _existing_utils is None or not hasattr(_existing_utils, "__path__"):
    _utils_pkg = _register_package("utils")
else:
    _utils_pkg = _existing_utils
# Pre-stub the thread_utils module the service imports.
_utils_thread_module = MagicMock()
_utils_thread_module.submit = MagicMock()
sys.modules["utils.thread_utils"] = _utils_thread_module
_utils_pkg.thread_utils = _utils_thread_module
# Pre-load the real auth_utils module so it is in sys.modules and set as
# an attribute on the ``utils`` package, so doted ``patch`` resolution in
# sibling tests can find it.
try:
    importlib.import_module("utils.auth_utils")
    _utils_pkg.auth_utils = sys.modules["utils.auth_utils"]
except Exception:  # noqa: BLE001
    pass

# openpyxl stub for the report generator
openpyxl_mock = MagicMock()
openpyxl_styles_mock = MagicMock()
sys.modules["openpyxl"] = openpyxl_mock
sys.modules["openpyxl.styles"] = openpyxl_styles_mock

# Lazy worksheet / workbook recorders so the report tests can introspect rows
_workbook_holder: dict = {}


class _WorksheetRecorder:
    def __init__(self, title):
        self.title = title
        self.column_dimensions = MagicMock()
        self._rows = []

    def append(self, row):
        self._rows.append(list(row))

    def cell(self, row=None, column=None, **_):
        # The report generator calls ``ws.cell(row=..., column=...)`` to
        # adjust alignment on already-appended summary rows. Return a MagicMock
        # cell so attribute access (``.alignment``, ...) succeeds.
        return MagicMock()

    def __getitem__(self, index):
        # openpyxl supports both ``ws[row_index]`` (1-based) for the header
        # row and column access; return a list of MagicMock cells.
        if isinstance(index, int):
            row = self._rows[index - 1] if 1 <= index <= len(self._rows) else []
            return [MagicMock(value=v) for v in row]
        return self

    def iter_rows(self, min_row=None, max_row=None, min_col=None, max_col=None, values_only=False):
        start = (min_row or 1) - 1
        end = max_row if max_row is not None else len(self._rows)
        for row in self._rows[start:end]:
            if values_only:
                yield row
            else:
                yield [MagicMock(value=v) for v in row] 


class _WorkbookRecorder:
    def __init__(self):
        self._sheets: dict = {}

    @property
    def active(self):
        # Production code does ``ws_summary = wb.active`` followed by
        # ``ws_summary.title = "概要"``. The recorder does not observe the
        # rename, so look the worksheet up under both the original default
        # key ("Sheet") and the localised title the tests expect ("概要").
        ws = self._sheets.setdefault("__active__", _WorksheetRecorder("概要"))
        self._sheets.setdefault("概要", ws)
        return ws

    def create_sheet(self, title):
        return self._sheets.setdefault(title, _WorksheetRecorder(title))

    def save(self, buf):
        buf.write(b"stub")

    def __getitem__(self, title):
        return self._sheets[title]


def _workbook_factory():
    wb = _WorkbookRecorder()
    _workbook_holder["wb"] = wb
    return wb


openpyxl_mock.Workbook = _workbook_factory

@pytest.fixture
def service_module(monkeypatch):
    """Import agent_evaluation_service fresh for each test with stubs in place.

    The conftest.py already installs a supabase mock at collection time; we do
    not need to redo that here.
    """
    if "services.agent_evaluation_service" in sys.modules:
        del sys.modules["services.agent_evaluation_service"]
    # Also clear the attribute on the services package so the ``from services``
    # below triggers a fresh import (and therefore repopulates ``sys.modules``).
    # Without this, Python's attribute-on-package lookup returns the previous
    # module object without re-importing it, leaving sys.modules empty and
    # causing sibling tests' patches to target a stale module.
    if hasattr(_services_pkg, "agent_evaluation_service"):
        try:
            delattr(_services_pkg, "agent_evaluation_service")
        except AttributeError:
            pass

    from services import agent_evaluation_service  # noqa: E402
    # Make sure the freshly imported submodule is also visible as an attribute
    # of the ``services`` package, so subsequent ``from services.X import Y``
    # access (and ``getattr(services_pkg, 'X')`` in mocks) does not fall
    # through to a ModuleNotFoundError on the parent package.
    _services_pkg.agent_evaluation_service = agent_evaluation_service
    agent_evaluation_service.openpyxl = openpyxl_mock
    agent_evaluation_service.get_agent_evaluation = _agent_evaluation_db_mock.get_agent_evaluation
    agent_evaluation_service.list_agent_evaluation_cases = _agent_evaluation_db_mock.list_agent_evaluation_cases
    agent_evaluation_service.soft_delete_agent_evaluation = _agent_evaluation_db_mock.soft_delete_agent_evaluation

    _agent_evaluation_db_mock.get_agent_evaluation.reset_mock(side_effect=True)
    _agent_evaluation_db_mock.list_agent_evaluation_cases.reset_mock(side_effect=True)
    _agent_evaluation_db_mock.soft_delete_agent_evaluation.reset_mock(side_effect=True)
    _workbook_holder.clear()

    return agent_evaluation_service


def _make_case(case_id: int, *, status: str, score, pass_status: str | None):
    return {
        "agent_evaluation_case_id": case_id,
        "status": status,
        "score": score,
        "pass_status": pass_status,
        "inputs": {"query": f"q{case_id}", "context": None},
        "label": {"answer": f"expected-{case_id}"},
        "predict": {"answer": f"actual-{case_id}"} if pass_status != "pass" else None,
        "reason": f"reason-{case_id}" if pass_status != "pass" else None,
        "error_message": "boom" if status == "FAILED" else None,
    }


def test_delete_agent_evaluation_run_only_creator_allowed(service_module):
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 1,
        "tenant_id": "t1",
        "created_by": "u1",
    }

    service_module.delete_agent_evaluation_run_impl(1, "t1", "u1")
    service_module.soft_delete_agent_evaluation.assert_called_once_with(1, "t1", "u1")

    service_module.soft_delete_agent_evaluation.reset_mock()
    with pytest.raises(ValueError, match="Only the creator"):
        service_module.delete_agent_evaluation_run_impl(1, "t1", "u2")
    service_module.soft_delete_agent_evaluation.assert_not_called()


def test_generate_report_only_contains_failed_cases(service_module):
    cases = [
        _make_case(1, status="COMPLETED", score=1, pass_status="pass"),
        _make_case(2, status="COMPLETED", score=0, pass_status="fail"),
        _make_case(3, status="FAILED", score=None, pass_status="fail"),
        _make_case(4, status="COMPLETED", score=1, pass_status="pass"),
    ]
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 100,
        "agent_id": 5,
        "agent_version_no": 2,
        "evaluation_set_id": 7,
        "status": "COMPLETED",
        "progress_total": 4,
        "progress_done": 4,
        "score_overall": 0.5,
        "error_message": None,
        "create_time": "2024-01-01",
    }
    service_module.list_agent_evaluation_cases.return_value = cases

    data, fail_count = service_module.generate_agent_evaluation_report_impl(100, "t1")
    assert isinstance(data, (bytes, bytearray))
    assert fail_count == 2

    wb = _workbook_holder["wb"]
    summary_rows = list(wb["概要"].iter_rows(values_only=True))
    assert summary_rows[0] == ["字段", "值"]
    fields = {row[0]: row[1] for row in summary_rows[1:] if row and row[0]}
    assert fields["用例总数"] == 4
    assert fields["通过用例数"] == 2
    assert fields["失败用例数"] == 2
    assert fields["通过率"] == "50.00%"
    assert fields["报告范围"] == "失败用例"

    failed_rows = list(wb["失败用例"].iter_rows(min_row=2, values_only=True))
    assert failed_rows == [
        [2, "q2", "expected-2", "actual-2", "0.0000", "reason-2", "COMPLETED", ""],
        [3, "q3", "expected-3", "actual-3", "-", "reason-3", "FAILED", "boom"],
    ]


def test_generate_report_all_pass_results_in_empty_failed_sheet(service_module):
    cases = [
        _make_case(10, status="COMPLETED", score=1, pass_status="pass"),
        _make_case(11, status="COMPLETED", score=1, pass_status="pass"),
    ]
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 200,
        "agent_id": 5,
        "agent_version_no": 2,
        "evaluation_set_id": 7,
        "status": "COMPLETED",
        "progress_total": 2,
        "progress_done": 2,
        "score_overall": 1.0,
        "error_message": None,
        "create_time": "2024-01-02",
    }
    service_module.list_agent_evaluation_cases.return_value = cases

    data, fail_count = service_module.generate_agent_evaluation_report_impl(200, "t1")
    assert fail_count == 0
    assert isinstance(data, (bytes, bytearray))
    wb = _workbook_holder["wb"]
    failed_rows = list(wb["失败用例"].iter_rows(min_row=2, values_only=True))
    assert failed_rows == []

    summary_rows = list(wb["概要"].iter_rows(values_only=True))
    fields = {row[0]: row[1] for row in summary_rows[1:] if row and row[0]}
    assert fields["失败用例数"] == 0
    assert fields["通过率"] == "100.00%"


# ---------------------------------------------------------------------------
# Extra stubs shared by the additional tests below. ``service_module`` only
# rebinds the three db helpers that the report generator touches, so the
# remaining impls (create / get / list / list-cases) need their own DB helpers
# patched onto the freshly imported module below.
# ---------------------------------------------------------------------------


def _wire_full_db_module(service_module):
    """Bind every agent_evaluation_db / evaluation_set_db helper we use.

    The original ``service_module`` fixture only wires three functions; the
    newly covered impls need ``create_agent_evaluation``,
    ``create_agent_evaluation_cases``, ``list_agent_evaluations_by_agent`` and
    ``update_agent_evaluation_case_result`` too. We do it here so the test
    bodies stay focused on behaviour rather than mocking boilerplate.
    """
    create_mock = MagicMock(return_value={"agent_evaluation_id": 999})
    service_module.create_agent_evaluation = create_mock
    service_module.create_agent_evaluation_cases = MagicMock(return_value=3)
    service_module.list_agent_evaluations_by_agent = MagicMock(return_value=[{"id": 1}])
    service_module.update_agent_evaluation_case_result = MagicMock()
    service_module.update_agent_evaluation_status = MagicMock()
    service_module.get_evaluation_set_cases_all = MagicMock(return_value=[
        {"evaluation_set_case_id": 1, "inputs": {"query": "q1"}, "label": {"answer": "a1"}},
        {"evaluation_set_case_id": 2, "inputs": {"query": "q2"}, "label": {"answer": "a2"}},
        {"evaluation_set_case_id": 3, "inputs": {"query": "q3"}, "label": {"answer": "a3"}},
    ])
    service_module.resolve_latest_published_version_no = MagicMock(return_value=7)
    service_module.prepare_agent_run = MagicMock()
    return create_mock


def test_get_agent_evaluation_run_impl_returns_db_payload(service_module):
    _wire_full_db_module(service_module)
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 7, "status": "RUNNING",
    }

    result = service_module.get_agent_evaluation_run_impl(7, "t1")

    assert result == {"agent_evaluation_id": 7, "status": "RUNNING"}
    service_module.get_agent_evaluation.assert_called_once_with(
        agent_evaluation_id=7, tenant_id="t1",
    )


def test_list_agent_evaluations_by_agent_impl_forwards_pagination(service_module):
    _wire_full_db_module(service_module)
    service_module.list_agent_evaluations_by_agent.return_value = [{"id": 1}, {"id": 2}]

    result = service_module.list_agent_evaluations_by_agent_impl(
        agent_id=11, tenant_id="t1", limit=10, offset=20,
    )

    assert result == [{"id": 1}, {"id": 2}]
    service_module.list_agent_evaluations_by_agent.assert_called_once_with(
        agent_id=11, tenant_id="t1", limit=10, offset=20,
    )


def test_list_agent_evaluation_cases_impl_forwards_pagination(service_module):
    _wire_full_db_module(service_module)
    service_module.list_agent_evaluation_cases.return_value = [{"case_id": 1}]

    result = service_module.list_agent_evaluation_cases_impl(
        agent_evaluation_id=5, tenant_id="t1", limit=25, offset=5,
    )

    assert result == [{"case_id": 1}]
    service_module.list_agent_evaluation_cases.assert_called_once_with(
        agent_evaluation_id=5, tenant_id="t1", limit=25, offset=5,
    )


def test_delete_agent_evaluation_run_not_found_raises(service_module):
    """A missing run bubbles up the ``ValueError`` from the DB layer."""
    _wire_full_db_module(service_module)
    service_module.get_agent_evaluation.side_effect = ValueError("agent evaluation not found")

    with pytest.raises(ValueError, match="agent evaluation not found"):
        service_module.delete_agent_evaluation_run_impl(404, "t1", "u1")
    service_module.soft_delete_agent_evaluation.assert_not_called()


def test_delete_agent_evaluation_run_creator_missing_raises(service_module):
    """``created_by`` is None on the run record — never matches any user."""
    _wire_full_db_module(service_module)
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 1, "tenant_id": "t1", "created_by": None,
    }

    with pytest.raises(ValueError, match="Only the creator"):
        service_module.delete_agent_evaluation_run_impl(1, "t1", "u1")
    service_module.soft_delete_agent_evaluation.assert_not_called()


# ---------------------------------------------------------------------------
# ``_extract_clean_reason_v2`` exercises — the helper is responsible for
# stripping SDK log envelopes off judge ``reason`` text, so several shapes need
# explicit coverage.
# ---------------------------------------------------------------------------


def test_extract_clean_reason_returns_plain_verdict(service_module):
    assert service_module._extract_clean_reason_v2("pass") == "pass"
    assert service_module._extract_clean_reason_v2("fail") == "fail"


def test_extract_clean_reason_returns_free_form_text(service_module):
    assert service_module._extract_clean_reason_v2("looks correct to me") == "looks correct to me"


def test_extract_clean_reason_returns_empty_for_none(service_module):
    assert service_module._extract_clean_reason_v2(None) == ""
    assert service_module._extract_clean_reason_v2("") == ""
    assert service_module._extract_clean_reason_v2("   ") == ""


def test_extract_clean_reason_unwraps_markdown_fence(service_module):
    raw = '[12:00:00 INFO llm] {"response_content": "```json\\n{\\"reason\\": \\"missing steps\\"}\\n```"}'
    assert service_module._extract_clean_reason_v2(raw) == "missing steps"


def test_extract_clean_reason_unwraps_top_level_reason(service_module):
    raw = '[12:00:00 INFO llm] {"reason": "  wrong entity  "}'
    assert service_module._extract_clean_reason_v2(raw) == "wrong entity"


def test_extract_clean_reason_walks_multiple_envelopes(service_module):
    raw = (
        '[12:00:00 INFO llm] {"event_id": "noop"}\n'
        '[12:00:01 INFO llm] {"response_content": "```json\\n{\\"reason\\": \\"second envelope wins\\"}\\n```"}'
    )
    assert service_module._extract_clean_reason_v2(raw) == "second envelope wins"


def test_extract_clean_reason_falls_back_to_stripped_text(service_module):
    """Unparseable noise should return the prefix-stripped raw text, not crash."""
    raw = "[12:00:00 INFO llm] not actually json payload"
    assert service_module._extract_clean_reason_v2(raw) == "not actually json payload"


def test_extract_clean_reason_handles_openai_chatcompletion_repr(service_module):
    """The SDK captures ``repr(ChatCompletion)`` for the request-side log."""
    repr_payload = (
        "ChatCompletion(id='x', choices=[Choice(finish_reason='stop', "
        "message=ChatCompletionMessage(content='```json\\n{\\\"reason\\\": \\\"from repr\\\"}\\n```', "
        "refusal=None))])"
    )
    raw = f'[12:00:00 INFO llm] {{"response": "{repr_payload}"}}'
    assert service_module._extract_clean_reason_v2(raw) == "from repr"


# ---------------------------------------------------------------------------
# ``create_agent_evaluation_run_impl`` — drives the synchronous bootstrap path
# that creates the run row, copies cases into the per-run table, then submits
# the background worker. The background future is captured so we can verify
# the done-callback is attached without actually executing the worker.
# ---------------------------------------------------------------------------


def test_create_agent_evaluation_run_happy_path(service_module):
    """All collaborators behave; the run row, cases and a worker future are produced."""
    create_mock = _wire_full_db_module(service_module)
    pool_mock = MagicMock()
    future = MagicMock()
    pool_mock.submit.return_value = future
    service_module.pool = pool_mock

    run = service_module.create_agent_evaluation_run_impl(
        tenant_id="t1",
        user_id="u1",
        agent_id=42,
        evaluation_set_id=7,
        judge_model_id=99,
    )

    assert run == {"agent_evaluation_id": 999}
    create_mock.assert_called_once_with(
        tenant_id="t1",
        agent_id=42,
        agent_version_no=7,
        evaluation_set_id=7,
        total=3,
        judge_model_id=99,
        created_by="u1",
    )
    service_module.create_agent_evaluation_cases.assert_called_once()
    kwargs = service_module.create_agent_evaluation_cases.call_args.kwargs
    assert kwargs["tenant_id"] == "t1"
    assert kwargs["agent_evaluation_id"] == 999
    assert kwargs["created_by"] == "u1"
    assert len(kwargs["set_cases"]) == 3

    pool_mock.submit.assert_called_once()
    future.add_done_callback.assert_called_once()
    # Done-callback signature should be a callable wrapping the run id + tenant.
    callback = future.add_done_callback.call_args.args[0]
    assert callable(callback)


def test_create_agent_evaluation_run_empty_set_raises(service_module):
    """An evaluation set with no cases is rejected before any DB writes happen."""
    _wire_full_db_module(service_module)
    service_module.get_evaluation_set_cases_all.return_value = []

    with pytest.raises(ValueError, match="evaluation set has no cases"):
        service_module.create_agent_evaluation_run_impl(
            tenant_id="t1", user_id="u1",
            agent_id=1, evaluation_set_id=2, judge_model_id=3,
        )
    service_module.create_agent_evaluation.assert_not_called()
    service_module.create_agent_evaluation_cases.assert_not_called()


def test_create_agent_evaluation_run_uses_resolved_version_no(service_module):
    """The published version number flows from ``resolve_latest_published_version_no``."""
    create_mock = _wire_full_db_module(service_module)
    service_module.resolve_latest_published_version_no.return_value = 13
    service_module.pool = MagicMock()

    service_module.create_agent_evaluation_run_impl(
        tenant_id="t1", user_id="u1",
        agent_id=1, evaluation_set_id=2, judge_model_id=3,
    )

    assert create_mock.call_args.kwargs["agent_version_no"] == 13


# ---------------------------------------------------------------------------
# ``execute_agent_evaluation_run`` — exercises the synchronous background loop.
# We stub the agent invocation + adapter so the loop runs without real I/O.
# ---------------------------------------------------------------------------


def _wire_executor_dependencies(service_module, cases):
    """Wire the collaborators touched by ``execute_agent_evaluation_run``."""
    _wire_full_db_module(service_module)
    service_module.JiuwenSDKAdapter = MagicMock()
    adapter = MagicMock()
    adapter.evaluate_semantic_consistency.return_value = (1, "ok")
    service_module.JiuwenSDKAdapter.return_value = adapter

    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 50,
        "agent_id": 11,
        "agent_version_no": 4,
        "judge_model_id": 99,
    }
    service_module.list_agent_evaluation_cases.return_value = cases

    async def _fake_run_to_final_answer(**_):
        return "agent-said-X"

    service_module._run_agent_to_final_answer = _fake_run_to_final_answer
    return adapter


def _make_exec_case(case_id, query="q", expected="a"):
    return {
        "agent_evaluation_case_id": case_id,
        "inputs": {"query": query},
        "label": {"answer": expected},
    }


def test_execute_agent_evaluation_run_completes_with_overall_score(service_module):
    cases = [_make_exec_case(1), _make_exec_case(2)]
    adapter = _wire_executor_dependencies(service_module, cases)

    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=99)

    # Adapter is constructed with the judge model id we passed in.
    service_module.JiuwenSDKAdapter.assert_called_once_with(model_id=99, tenant_id="t1")
    adapter.evaluate_semantic_consistency.assert_called()

    # Final transition should mark the run COMPLETED with the mean score.
    completed_calls = [
        c for c in service_module.update_agent_evaluation_status.call_args_list
        if c.kwargs.get("status") == "COMPLETED"
    ]
    assert len(completed_calls) == 1
    assert completed_calls[0].kwargs["score_overall"] == 1.0


def test_execute_agent_evaluation_run_case_exception_marks_failed(service_module):
    """A single case exception must not abort the whole run; others keep going."""
    cases = [_make_exec_case(1), _make_exec_case(2)]

    async def _flaky(**_):
        raise RuntimeError("boom")

    _wire_executor_dependencies(service_module, cases)
    service_module._run_agent_to_final_answer = _flaky

    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=99)

    # Final status must still be COMPLETED (the loop swallows per-case errors).
    final = service_module.update_agent_evaluation_status.call_args_list[-1]
    assert final.kwargs["status"] == "COMPLETED"

    # Both cases should have a FAILED update written.
    failed_updates = [
        c for c in service_module.update_agent_evaluation_case_result.call_args_list
        if c.kwargs.get("status") == "FAILED"
    ]
    assert len(failed_updates) == 2


def test_execute_agent_evaluation_run_top_level_error_marks_run_failed(service_module):
    """An exception raised before the loop starts must transition the run FAILED."""
    _wire_full_db_module(service_module)
    service_module.JiuwenSDKAdapter = MagicMock(side_effect=RuntimeError("adapter init boom"))
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 50, "agent_id": 11, "agent_version_no": 4, "judge_model_id": 99,
    }

    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=99)

    failed = [
        c for c in service_module.update_agent_evaluation_status.call_args_list
        if c.kwargs.get("status") == "FAILED"
    ]
    assert failed, "expected the outer except branch to mark the run FAILED"
    assert "adapter init boom" in (failed[0].kwargs.get("error_message") or "")


def test_execute_agent_evaluation_run_falls_back_to_persisted_judge_model(service_module):
    """When the queued judge_model_id is lost the persisted one is reused."""
    cases = [_make_exec_case(1)]
    _wire_executor_dependencies(service_module, cases)

    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=None)

    # The adapter should be constructed with the model id from the run record.
    service_module.JiuwenSDKAdapter.assert_called_once_with(model_id=99, tenant_id="t1")


def test_execute_agent_evaluation_run_missing_judge_model_raises(service_module):
    """Both the argument and persisted judge_model_id are absent — outer except fires."""
    _wire_full_db_module(service_module)
    service_module.JiuwenSDKAdapter = MagicMock()
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 50, "agent_id": 11, "agent_version_no": 4, "judge_model_id": None,
    }

    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=None)

    failed = [
        c for c in service_module.update_agent_evaluation_status.call_args_list
        if c.kwargs.get("status") == "FAILED"
    ]
    assert failed, "outer except branch should mark run FAILED"
