"""Unit tests for agent_evaluation_service focusing on the new
delete-only-creator behavior and the failed-cases-only Excel report."""

import sys
import types
import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


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

_nexent_core_agents_sandbox_module = types.ModuleType("nexent.core.agents.sandbox")
_nexent_core_agents_sandbox_module._scan_shell_calls = MagicMock(return_value=[])
sys.modules["nexent.core.agents.sandbox"] = _nexent_core_agents_sandbox_module
_nexent_core_agents.sandbox = _nexent_core_agents_sandbox_module

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

_agent_service_module = types.ModuleType("management.services.agent.service")
_agent_service_module.prepare_agent_run = MagicMock()
sys.modules["management.services.agent.service"] = _agent_service_module
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
# ---- 补齐 agent_evaluation_service.py import 的所有函数（L56-L61）----
_evaluation_set_db_mock.create_evaluation_set = MagicMock(return_value={"evaluation_set_id": 1})
_evaluation_set_db_mock.get_evaluation_set_cases_all = MagicMock(return_value=[])
_evaluation_set_db_mock.materialize_virtual_evaluation_set_for_run = MagicMock(
    return_value=1
)
_evaluation_set_db_mock.insert_evaluation_set_cases = MagicMock(return_value=0)
_evaluation_set_db_mock.update_evaluation_set_case_count = MagicMock()
_evaluation_set_db_mock.hard_delete_evaluation_set = MagicMock()
sys.modules["database.evaluation_set_db"] = _evaluation_set_db_mock
_db_pkg.evaluation_set_db = _evaluation_set_db_mock

_agent_evaluation_db_mock = MagicMock()
_agent_evaluation_db_mock.get_agent_evaluation = MagicMock()
_agent_evaluation_db_mock.list_agent_evaluation_cases = MagicMock()
_agent_evaluation_db_mock.soft_delete_agent_evaluation = MagicMock()
# ---- 补齐 agent_evaluation_service.py import 的所有函数（L40-L53）----
_agent_evaluation_db_mock.count_active_runs = MagicMock(return_value=0)
_agent_evaluation_db_mock.count_total_runs = MagicMock(return_value=0)
_agent_evaluation_db_mock.create_agent_evaluation = MagicMock(return_value={"agent_evaluation_id": 1})
_agent_evaluation_db_mock.create_agent_evaluation_cases = MagicMock(return_value=0)
_agent_evaluation_db_mock.get_evaluation_case_scores = MagicMock(return_value=[])
_agent_evaluation_db_mock.hard_delete_agent_evaluation = MagicMock(return_value=1)
_agent_evaluation_db_mock.list_agent_evaluations_by_agent = MagicMock(return_value=[])
_agent_evaluation_db_mock.update_agent_evaluation_analysis_report = MagicMock()
_agent_evaluation_db_mock.update_agent_evaluation_case_result = MagicMock()
_agent_evaluation_db_mock.update_agent_evaluation_status = MagicMock()
sys.modules["database.agent_evaluation_db"] = _agent_evaluation_db_mock
_db_pkg.agent_evaluation_db = _agent_evaluation_db_mock

_knowledge_db_mock = MagicMock()
_knowledge_db_mock.search_knowledge_records = MagicMock(return_value=[])
_knowledge_db_mock.get_knowledge_name_by_id = MagicMock()
_knowledge_db_mock.get_index_name_by_knowledge_name = MagicMock()
sys.modules["database.knowledge_db"] = _knowledge_db_mock
_db_pkg.knowledge_db = _knowledge_db_mock

# ---- 补齐 evaluator_db（service L62：from database.evaluator_db import get_evaluator）----
_evaluator_db_mock = MagicMock()
_evaluator_db_mock.get_evaluator = MagicMock(return_value={"evaluator_id": 1, "pass_threshold": 0.8, "version_no": 1})
sys.modules["database.evaluator_db"] = _evaluator_db_mock
_db_pkg.evaluator_db = _evaluator_db_mock

# database.client / database.db_models are imported by both service modules.
_db_client_module = MagicMock()
_db_client_module.get_db_session = MagicMock()
_db_client_module.as_dict = MagicMock()
sys.modules["database.client"] = _db_client_module
_db_pkg.client = _db_client_module

_db_models_module = MagicMock()
_db_models_module.AgentEvaluation = MagicMock()
_db_models_module.ModelRecord = MagicMock()
sys.modules["database.db_models"] = _db_models_module
_db_pkg.db_models = _db_models_module

# consts.model referenced by the service
_consts_pkg = _register_package("consts")
_consts_model_module = types.ModuleType("consts.model")
_consts_model_module.AgentRequest = MagicMock()
sys.modules["consts.model"] = _consts_model_module
_consts_pkg.model = _consts_model_module

_consts_error_code_module = types.ModuleType("consts.error_code")


class _ErrorCode:
    COMMON_VALIDATION_ERROR = "COMMON_VALIDATION_ERROR"
    COMMON_RESOURCE_NOT_FOUND = "COMMON_RESOURCE_NOT_FOUND"
    COMMON_RATE_LIMIT_EXCEEDED = "COMMON_RATE_LIMIT_EXCEEDED"
    AGENT_EVALUATION_SET_IN_USE = "AGENT_EVALUATION_SET_IN_USE"
    AGENT_EVALUATION_NOT_FOUND = "AGENT_EVALUATION_NOT_FOUND"
    AGENT_EVALUATION_DELETE_NOT_ALLOWED = "AGENT_EVALUATION_DELETE_NOT_ALLOWED"
    AGENT_EVALUATION_NOT_COMPLETED = "AGENT_EVALUATION_NOT_COMPLETED"
    AGENT_EVALUATION_CASE_NOT_FOUND = "AGENT_EVALUATION_CASE_NOT_FOUND"
    AGENT_EVALUATION_ONLY_CREATOR_CAN_DELETE = "AGENT_EVALUATION_ONLY_CREATOR_CAN_DELETE"
    AGENT_EVALUATION_SET_EMPTY = "AGENT_EVALUATION_SET_EMPTY"
    AGENT_EVALUATION_ANALYSIS_FAILED = "AGENT_EVALUATION_ANALYSIS_FAILED"
    AGENT_EVALUATION_ANALYSIS_NOT_READY = "AGENT_EVALUATION_ANALYSIS_NOT_READY"
    AGENT_EVALUATION_EVALUATOR_COUNT = "AGENT_EVALUATION_EVALUATOR_COUNT"
    AGENT_EVALUATION_EVALUATOR_NOT_FOUND = "AGENT_EVALUATION_EVALUATOR_NOT_FOUND"
    AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED = "AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED"
    AGENT_EVALUATION_QUERY_COUNT_RANGE = "AGENT_EVALUATION_QUERY_COUNT_RANGE"
    AGENT_EVALUATION_QUERY_GENERATION_FORMAT = "AGENT_EVALUATION_QUERY_GENERATION_FORMAT"
    AGENT_EVALUATION_QUERY_GENERATION_FAILED = "AGENT_EVALUATION_QUERY_GENERATION_FAILED"
    AGENT_EVALUATION_QUERY_GENERATION_EMPTY = "AGENT_EVALUATION_QUERY_GENERATION_EMPTY"
    AGENT_EVALUATION_AGENT_NOT_FOUND = "AGENT_EVALUATION_AGENT_NOT_FOUND"
    AGENT_EVALUATION_JUDGE_MODEL_REQUIRED = "AGENT_EVALUATION_JUDGE_MODEL_REQUIRED"
    EVALUATION_NOT_FOUND = "EVALUATION_NOT_FOUND"
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    KNOWLEDGE_NOT_FOUND = "KNOWLEDGE_NOT_FOUND"


_consts_error_code_module.ErrorCode = _ErrorCode
sys.modules["consts.error_code"] = _consts_error_code_module
_consts_pkg.error_code = _consts_error_code_module

_consts_limits_module = types.ModuleType("consts.evaluation_limits")
_consts_limits_module.DEFAULT_PASS_THRESHOLD = 0.8
_consts_limits_module.MAX_CONCURRENT_RUNS = 10
_consts_limits_module.MAX_EVALUATORS_PER_RUN = 3
_consts_limits_module.MAX_TOTAL_RUNS = 100
_consts_limits_module.MAX_TURNS_PER_SESSION = 20
_consts_limits_module.MAX_CASES_PER_SET = 10000
sys.modules["consts.evaluation_limits"] = _consts_limits_module
_consts_pkg.evaluation_limits = _consts_limits_module

_consts_status_module = types.ModuleType("consts.evaluation_status")
_consts_status_module.MAX_FAILURE_EXAMPLES = 5
_consts_status_module.EvalCaseStatus = type(
    "EvalCaseStatus",
    (),
    {
        "PENDING": "PENDING",
        "RUNNING": "RUNNING",
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    },
)
_consts_status_module.EvalPassStatus = type(
    "EvalPassStatus", (), {"PASS": "pass", "FAIL": "fail", "PARTIAL": "partial"}
)
_consts_status_module.EvalRunStatus = type(
    "EvalRunStatus",
    (),
    {
        "PENDING": "PENDING",
        "RUNNING": "RUNNING",
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    },
)
sys.modules["consts.evaluation_status"] = _consts_status_module
_consts_pkg.evaluation_status = _consts_status_module

_consts_exceptions_module = types.ModuleType("consts.exceptions")


class _AppException(Exception):
    def __init__(self, error_code=None, message=None, *args, **kwargs):
        self.error_code = error_code
        self.message = message or ""
        super().__init__(self.message)


_consts_exceptions_module.AppException = _AppException
_consts_exceptions_module.NotFoundException = Exception
_consts_exceptions_module.ValidationError = Exception
_consts_exceptions_module.ForbiddenError = Exception
_consts_exceptions_module.NoInviteCodeException = Exception
_consts_exceptions_module.MCPConnectionError = Exception
_consts_exceptions_module.ToolExecutionException = Exception
_consts_exceptions_module.VoiceServiceException = Exception
sys.modules["consts.exceptions"] = _consts_exceptions_module
_consts_pkg.exceptions = _consts_exceptions_module

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

_utils_agent_module = MagicMock()
_utils_agent_module.prepare_request_args = MagicMock()
_utils_agent_module.build_agent_request = MagicMock()
_utils_agent_module.build_output_schema = MagicMock()
_utils_agent_module.verify_agent_runnable = MagicMock()
_utils_agent_module.run_model_provider_health_check = MagicMock()
sys.modules["utils.agent_utils"] = _utils_agent_module
_utils_pkg.agent_utils = _utils_agent_module

_utils_eval_module = MagicMock()
_utils_eval_module.calculate_pass_status = MagicMock(return_value="pass")
_utils_eval_module.format_case_output = MagicMock()
_utils_eval_module.build_score_summary = MagicMock()
_utils_eval_module.build_analysis_report_sections = MagicMock()
sys.modules["utils.evaluation_utils"] = _utils_eval_module
_utils_pkg.evaluation_utils = _utils_eval_module

_utils_eval_run_module = MagicMock()
_utils_eval_run_module.dispatch_background_run = MagicMock()
_utils_eval_run_module.refresh_evaluation_case_predict = MagicMock()
_utils_eval_run_module.refresh_evaluation_case_reason = MagicMock()
sys.modules["utils.evaluation_run"] = _utils_eval_run_module
_utils_pkg.evaluation_run = _utils_eval_run_module

_utils_llm_module = MagicMock()
_utils_llm_module.call_llm_for_system_prompt = MagicMock()
sys.modules["utils.llm_utils"] = _utils_llm_module
_utils_pkg.llm_utils = _utils_llm_module

# utils.agent_profile_utils is imported lazily inside _generate_test_queries.
sys.modules["utils.agent_profile_utils"] = MagicMock()
_utils_pkg.agent_profile_utils = sys.modules["utils.agent_profile_utils"]

_utils_prompt_template_module = MagicMock()
_utils_prompt_template_module.get_prompt_template = MagicMock()
sys.modules["utils.prompt_template_utils"] = _utils_prompt_template_module
_utils_pkg.prompt_template_utils = _utils_prompt_template_module

_nexent_core_models_module = types.ModuleType("nexent.core.models")
_nexent_core_models_module.OpenAIModel = MagicMock()
sys.modules["nexent.core.models"] = _nexent_core_models_module
_nexent_core.models = _nexent_core_models_module

_eval_prompt_service_module = types.ModuleType("services.evaluation_prompt_service")
_eval_prompt_service_module.build_prompts_for_evaluation_cases = MagicMock(
    return_value=[]
)
sys.modules["services.evaluation_prompt_service"] = _eval_prompt_service_module
_services_pkg.evaluation_prompt_service = _eval_prompt_service_module

# ---- 补齐 services.evaluation_set_service（agent_evaluation_service.py L64）----
_eval_set_service_module = types.ModuleType("services.evaluation_set_service")
_eval_set_service_module.resolve_latest_published_version_no = MagicMock(return_value=1)
sys.modules["services.evaluation_set_service"] = _eval_set_service_module
_services_pkg.evaluation_set_service = _eval_set_service_module

_agent_service_module.list_model_providers_impl = MagicMock(return_value=[])
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

    def iter_rows(
        self, min_row=None, max_row=None, min_col=None, max_col=None, values_only=False
    ):
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
    # ``services.agent_evaluation_service`` may or may not do
    # ``from openpyxl import Workbook`` at module load depending on the
    # current code shape; either way we install a patch under the module
    # attribute so the workbook recorder picks it up when used.
    _saved_workbook = getattr(agent_evaluation_service, "Workbook", None)
    agent_evaluation_service.Workbook = _workbook_factory
    monkeypatch.setattr(
        agent_evaluation_service, "Workbook", _workbook_factory, raising=False
    )

    agent_evaluation_service.get_agent_evaluation = (
        _agent_evaluation_db_mock.get_agent_evaluation
    )
    agent_evaluation_service.list_agent_evaluation_cases = (
        _agent_evaluation_db_mock.list_agent_evaluation_cases
    )
    agent_evaluation_service.soft_delete_agent_evaluation = (
        _agent_evaluation_db_mock.soft_delete_agent_evaluation
    )

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
    from consts.exceptions import AppException
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 1,
        "tenant_id": "t1",
        "created_by": "u1",
    }

    service_module.delete_agent_evaluation_run_impl(1, "t1", "u1")
    service_module.hard_delete_agent_evaluation.assert_called_once_with(agent_evaluation_id=1, tenant_id="t1")

    service_module.hard_delete_agent_evaluation.reset_mock()
    with pytest.raises(AppException):
        service_module.delete_agent_evaluation_run_impl(1, "t1", "u2")
    service_module.soft_delete_agent_evaluation.assert_not_called()


@pytest.mark.skip(reason="generate_analysis_report_impl returns Dict (LLM analysis), not (bytes, fail_count) tuple; old Excel report test is obsolete")
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

    data, fail_count = service_module.generate_analysis_report_impl(100, "t1")
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


@pytest.mark.skip(reason="generate_analysis_report_impl returns Dict (LLM analysis), not (bytes, fail_count) tuple; old Excel report test is obsolete")
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

    data, fail_count = service_module.generate_analysis_report_impl(200, "t1")
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
    service_module.get_evaluation_set_cases_all = MagicMock(
        return_value=[
            {
                "evaluation_set_case_id": 1,
                "inputs": {"query": "q1"},
                "label": {"answer": "a1"},
            },
            {
                "evaluation_set_case_id": 2,
                "inputs": {"query": "q2"},
                "label": {"answer": "a2"},
            },
            {
                "evaluation_set_case_id": 3,
                "inputs": {"query": "q3"},
                "label": {"answer": "a3"},
            },
        ]
    )
    service_module.resolve_latest_published_version_no = MagicMock(return_value=7)
    service_module.prepare_agent_run = MagicMock()
    return create_mock


def test_get_agent_evaluation_run_impl_returns_db_payload(service_module):
    _wire_full_db_module(service_module)
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 7,
        "status": "RUNNING",
    }

    result = service_module.get_agent_evaluation_run_impl(7, "t1")

    assert result == {"agent_evaluation_id": 7, "status": "RUNNING"}
    service_module.get_agent_evaluation.assert_called_once_with(
        agent_evaluation_id=7,
        tenant_id="t1",
    )


def test_list_agent_evaluations_by_agent_impl_forwards_pagination(service_module):
    _wire_full_db_module(service_module)
    service_module.list_agent_evaluations_by_agent.return_value = [{"id": 1}, {"id": 2}]

    result = service_module.list_agent_evaluations_by_agent_impl(
        agent_id=11,
        tenant_id="t1",
        limit=10,
        offset=20,
    )

    assert result == [{"id": 1}, {"id": 2}]
    service_module.list_agent_evaluations_by_agent.assert_called_once_with(
        agent_id=11,
        tenant_id="t1",
        limit=10,
        offset=20,
    )


def test_list_agent_evaluation_cases_impl_forwards_pagination(service_module):
    _wire_full_db_module(service_module)
    service_module.list_agent_evaluation_cases.return_value = [{"case_id": 1}]

    result = service_module.list_agent_evaluation_cases_impl(
        agent_evaluation_id=5,
        tenant_id="t1",
        limit=25,
        offset=5,
    )

    assert result == [{"case_id": 1}]
    service_module.list_agent_evaluation_cases.assert_called_once_with(
        agent_evaluation_id=5,
        tenant_id="t1",
        limit=25,
        offset=5,
        sort_by=None,
        sort_order="asc",
        pass_filter=None,
        anno_schema_ids=None,
        anno_values=None,
        session_id=None,
    )


def test_delete_agent_evaluation_run_not_found_raises(service_module):
    """A missing run bubbles up the ``AppException`` from the DB layer."""
    from consts.exceptions import AppException
    _wire_full_db_module(service_module)
    service_module.get_agent_evaluation.side_effect = AppException(
        error_code="AGENT_EVALUATION_NOT_FOUND",
        message="agent evaluation not found"
    )

    with pytest.raises(AppException, match="agent evaluation not found"):
        service_module.delete_agent_evaluation_run_impl(404, "t1", "u1")
    service_module.soft_delete_agent_evaluation.assert_not_called()


def test_delete_agent_evaluation_run_creator_missing_raises(service_module):
    """``created_by`` is None on the run record — never matches any user."""
    from consts.exceptions import AppException
    _wire_full_db_module(service_module)
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 1,
        "tenant_id": "t1",
        "created_by": None,
    }

    with pytest.raises(AppException):
        service_module.delete_agent_evaluation_run_impl(1, "t1", "u1")
    service_module.soft_delete_agent_evaluation.assert_not_called()


# ---------------------------------------------------------------------------
# ``create_agent_evaluation_run_impl`` — drives the synchronous bootstrap path
# that creates the run row, copies cases into the per-run table, then submits
# the background worker. The background future is captured so we can verify
# the done-callback is attached without actually executing the worker.
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="_build_case_for_jiuwen helper removed/refactored in service layer; skip until replaced")
def test_build_case_for_jiuwen_normalizes_inputs_and_label(service_module):
    """The helper pulls ``query`` and ``answer`` out of inputs/label dicts,
    defaulting missing fields to empty strings."""
    case = service_module._build_case_for_jiuwen(
        inputs={"query": "Q?", "extras": "ignored"},
        label={"answer": "A!", "extra": "ignored"},
    )
    assert case == {
        "inputs": {"query": "Q?"},
        "label": {"answer": "A!"},
    }


@pytest.mark.skip(reason="_build_case_for_jiuwen helper removed/refactored in service layer; skip until replaced")
def test_build_case_for_jiuwen_handles_missing_fields(service_module):
    case = service_module._build_case_for_jiuwen(inputs={}, label={})
    assert case == {"inputs": {"query": ""}, "label": {"answer": ""}}


def test_run_agent_to_final_answer_extracts_final_answer_chunks(service_module):
    """The async runner streams JSON ``final_answer`` chunks and joins them."""
    import asyncio

    service_module.AgentRequest = MagicMock()
    service_module.prepare_agent_run = AsyncMock(
        return_value=(MagicMock(name="run_info"), MagicMock(name="memory_ctx"))
    )

    final_answer_parts = [
        json.dumps({"type": "final_answer", "content": "hello "}),
        json.dumps({"type": "final_answer", "content": "world"}),
    ]

    async def _fake_agent_run(_run_info):
        for chunk in final_answer_parts:
            yield chunk

    service_module.agent_run = _fake_agent_run

    result = asyncio.run(
        service_module._run_agent_to_final_answer(
            agent_id=1,
            tenant_id="t1",
            user_id="u1",
            query="q",
            version_no=1,
        )
    )
    assert result[0] == "hello world"


def test_evaluation_conversation_ids_are_isolated_and_stable(service_module):
    first = service_module._evaluation_conversation_id(10, 20)
    second = service_module._evaluation_conversation_id(10, 21)

    assert first < 0
    assert first == service_module._evaluation_conversation_id(10, 20)
    assert first != second


def test_dispatch_agent_evaluation_run_uses_runtime_proxy(service_module, monkeypatch):
    runtime_proxy = types.ModuleType("services.runtime_proxy_service")
    dispatch = MagicMock(return_value={"accepted": True})
    runtime_proxy.dispatch_agent_evaluation_run = dispatch
    monkeypatch.setitem(sys.modules, "services.runtime_proxy_service", runtime_proxy)

    result = service_module._dispatch_agent_evaluation_run(7, "u1", "t1")

    assert result == {"accepted": True}
    dispatch.assert_called_once_with(
        agent_evaluation_id=7,
        user_id="u1",
        tenant_id="t1",
    )


def test_run_agent_to_final_answer_releases_registered_run_on_error(service_module):
    import asyncio

    service_module.AgentRequest = MagicMock()
    run_info = MagicMock(name="run_info")
    service_module.prepare_agent_run = AsyncMock(
        return_value=(run_info, MagicMock(name="memory_ctx"))
    )

    async def _failing_agent_run(_run_info):
        raise RuntimeError("agent failed")
        yield  # pragma: no cover

    service_module.agent_run = _failing_agent_run
    unregister = MagicMock()
    service_module.agent_run_manager = MagicMock()
    service_module.agent_run_manager.unregister_agent_run = unregister

    async def invoke_failing_run():
        return await service_module._run_agent_to_final_answer(
            agent_id=1,
            tenant_id="t1",
            user_id="u1",
            query="q",
            version_no=1,
            conversation_id=-123,
        )

    with pytest.raises(RuntimeError, match="agent failed"):
        asyncio.run(invoke_failing_run())

    unregister.assert_called_once_with(
        -123,
        "u1",
        status="failed",
        agent_run_info=run_info,
    )


def test_run_agent_to_final_answer_skips_non_final_answer_chunks(service_module):
    """Chunks whose ``type`` is not ``final_answer`` are ignored."""
    import asyncio

    service_module.AgentRequest = MagicMock()
    service_module.prepare_agent_run = AsyncMock(
        return_value=(MagicMock(name="run_info"), MagicMock(name="memory_ctx"))
    )

    chunks = [
        json.dumps({"type": "thought", "content": "thinking..."}),
        json.dumps({"type": "final_answer", "content": "only this"}),
        json.dumps({"type": "tool_call", "content": "calling tool"}),
    ]

    async def _fake_agent_run(_run_info):
        for chunk in chunks:
            yield chunk

    service_module.agent_run = _fake_agent_run

    result = asyncio.run(
        service_module._run_agent_to_final_answer(
            agent_id=1,
            tenant_id="t1",
            user_id="u1",
            query="q",
            version_no=1,
        )
    )
    assert result[0] == "only this"


def test_run_agent_to_final_answer_skips_non_string_and_invalid_json_chunks(
    service_module,
):
    """Non-string chunks and unparseable JSON are silently dropped."""
    import asyncio

    service_module.AgentRequest = MagicMock()
    service_module.prepare_agent_run = AsyncMock(
        return_value=(MagicMock(name="run_info"), MagicMock(name="memory_ctx"))
    )

    chunks = [
        "not json",
        json.dumps({"type": "final_answer", "content": "kept"}),
        '{"unterminated":',
    ]

    async def _fake_agent_run(_run_info):
        for chunk in chunks:
            yield chunk

    service_module.agent_run = _fake_agent_run

    result = asyncio.run(
        service_module._run_agent_to_final_answer(
            agent_id=1,
            tenant_id="t1",
            user_id="u1",
            query="q",
            version_no=1,
        )
    )
    assert result[0] == "kept"


def test_run_agent_to_final_answer_handles_no_final_answer_chunks(service_module):
    """When no chunk is a ``final_answer``, the result is the empty string."""
    import asyncio

    service_module.AgentRequest = MagicMock()
    service_module.prepare_agent_run = AsyncMock(
        return_value=(MagicMock(name="run_info"), MagicMock(name="memory_ctx"))
    )

    async def _fake_agent_run(_run_info):
        yield json.dumps({"type": "thought"})

    service_module.agent_run = _fake_agent_run

    result = asyncio.run(
        service_module._run_agent_to_final_answer(
            agent_id=1,
            tenant_id="t1",
            user_id="u1",
            query="q",
            version_no=1,
        )
    )
    assert result[0] == ""


def test_make_background_done_callback_failure_marks_run_failed(service_module):
    """When the future raised, the callback should mark the run FAILED."""
    captured = {}

    def _fake_update(**kwargs):
        captured.update(kwargs)

    service_module.update_agent_evaluation_status = _fake_update

    callback = service_module._make_background_done_callback(
        tenant_id="t1",
        user_id="u1",
        agent_evaluation_id=99,
    )
    future = MagicMock()
    future.exception.return_value = RuntimeError("worker crashed")

    callback(future)

    assert captured["agent_evaluation_id"] == 99
    assert captured["tenant_id"] == "t1"
    assert captured["status"] == "FAILED"
    assert captured["updated_by"] == "u1"
    assert "error_message" in captured


def test_make_background_done_callback_no_exception_is_noop(service_module):
    """When the future completed cleanly, the callback is a no-op."""
    captured = {}

    def _fake_update(**kwargs):
        captured.update(kwargs)

    service_module.update_agent_evaluation_status = _fake_update

    callback = service_module._make_background_done_callback(
        tenant_id="t1",
        user_id="u1",
        agent_evaluation_id=100,
    )
    future = MagicMock()
    future.exception.return_value = None

    callback(future)

    # Status update must not have been called.
    assert captured == {}


def test_make_background_done_callback_update_failure_is_logged(service_module):
    """If the DB update itself fails, the exception must be swallowed and logged."""

    def _failing_update(**_kwargs):
        raise RuntimeError("db unavailable")

    service_module.update_agent_evaluation_status = _failing_update

    callback = service_module._make_background_done_callback(
        tenant_id="t1",
        user_id="u1",
        agent_evaluation_id=101,
    )
    future = MagicMock()
    future.exception.return_value = RuntimeError("worker crashed")

    # Should not raise even though the inner update fails.
    callback(future)


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
        evaluator_config=None,
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
    from consts.exceptions import AppException
    _wire_full_db_module(service_module)
    service_module.get_evaluation_set_cases_all.return_value = []

    with pytest.raises(AppException, match="Evaluation set has no cases"):
        service_module.create_agent_evaluation_run_impl(
            tenant_id="t1",
            user_id="u1",
            agent_id=1,
            evaluation_set_id=2,
            judge_model_id=3,
        )
    service_module.create_agent_evaluation.assert_not_called()
    service_module.create_agent_evaluation_cases.assert_not_called()


def test_create_agent_evaluation_run_uses_resolved_version_no(service_module):
    """The published version number flows from ``resolve_latest_published_version_no``."""
    create_mock = _wire_full_db_module(service_module)
    service_module.resolve_latest_published_version_no.return_value = 13
    service_module.pool = MagicMock()

    service_module.create_agent_evaluation_run_impl(
        tenant_id="t1",
        user_id="u1",
        agent_id=1,
        evaluation_set_id=2,
        judge_model_id=3,
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
    # Use side_effect so the pagination loop gets cases on first call, then
    # an empty list on the second call to break out of the while-True loop.
    service_module.list_agent_evaluation_cases.side_effect = [cases, []]

    async def _fake_run_to_final_answer(**_):
        # Must return a tuple (answer_text, runtime_events) to match the
        # real signature -> Tuple[str, List[dict]].
        return "agent-said-X", []

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
        c
        for c in service_module.update_agent_evaluation_status.call_args_list
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
        c
        for c in service_module.update_agent_evaluation_case_result.call_args_list
        if c.kwargs.get("status") == "FAILED"
    ]
    assert len(failed_updates) == 2


def test_execute_agent_evaluation_run_top_level_error_marks_run_failed(service_module):
    """An exception raised before the loop starts must transition the run FAILED."""
    _wire_full_db_module(service_module)
    service_module.JiuwenSDKAdapter = MagicMock(
        side_effect=RuntimeError("adapter init boom")
    )
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 50,
        "agent_id": 11,
        "agent_version_no": 4,
        "judge_model_id": 99,
    }

    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=99)

    failed = [
        c
        for c in service_module.update_agent_evaluation_status.call_args_list
        if c.kwargs.get("status") == "FAILED"
    ]
    assert failed, "expected the outer except branch to mark the run FAILED"
    assert "adapter init boom" in (failed[0].kwargs.get("error_message") or "")


def test_execute_agent_evaluation_run_falls_back_to_persisted_judge_model(
    service_module,
):
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
        "agent_evaluation_id": 50,
        "agent_id": 11,
        "agent_version_no": 4,
        "judge_model_id": None,
    }

    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=None)

    failed = [
        c
        for c in service_module.update_agent_evaluation_status.call_args_list
        if c.kwargs.get("status") == "FAILED"
    ]
    assert failed, "outer except branch should mark run FAILED"


# ---------------------------------------------------------------------------
# ``_is_llm_related_error`` and ``_generate_friendly_error_message``
# ---------------------------------------------------------------------------


class TestIsLlmRelatedError:
    def test_returns_true_for_known_keywords(self, service_module):
        assert service_module._is_llm_related_error(RuntimeError("openai timeout"))
        assert service_module._is_llm_related_error(Exception("jiuwen sdk error"))
        assert service_module._is_llm_related_error(Exception("model not responding"))
        assert service_module._is_llm_related_error(Exception("rate limit exceeded"))
        assert service_module._is_llm_related_error(Exception("schedule new futures"))

    def test_returns_false_for_unrelated_error(self, service_module):
        assert not service_module._is_llm_related_error(ValueError("bad input"))
        assert not service_module._is_llm_related_error(KeyError("missing"))

    def test_case_insensitive(self, service_module):
        assert service_module._is_llm_related_error(RuntimeError("OPENAI failure"))


class TestGenerateFriendlyErrorMessage:
    def test_returns_default_for_unrelated_error(self, service_module):
        result = service_module._generate_friendly_error_message(
            ValueError("not an LLM error"),
            "fallback message",
        )
        assert result == "fallback message"

    def test_returns_default_when_openai_call_fails(self, service_module, monkeypatch):
        """LLM call failure inside the helper must not bubble — we return default."""
        import builtins as _bi

        real_import = _bi.__import__

        def _failing_import(name, *args, **kwargs):
            if name == "openai" or name.startswith("openai."):
                raise ImportError("openai not available")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(_bi, "__import__", _failing_import)
        # Even with an LLM-related error, the openai import failure is caught
        # inside the helper and we get the default message back.
        result = service_module._generate_friendly_error_message(
            RuntimeError("openai API timed out"),
            "default",
        )
        assert result == "default"

    def test_returns_llm_response_when_openai_succeeds(
        self, service_module, monkeypatch
    ):
        """When call_llm_for_system_prompt returns content, return it."""

        # The service calls call_llm_for_system_prompt (not openai directly).
        # Mock it to return a non-empty string so the helper returns it.
        service_module.call_llm_for_system_prompt = MagicMock(
            return_value="Friendly error from LLM"
        )
        service_module.get_prompt_template = MagicMock(
            return_value={"USER_PROMPT": "test", "SYSTEM_PROMPT": "test"}
        )

        result = service_module._generate_friendly_error_message(
            RuntimeError("openai timeout"),
            "default",
            model_id=99,
            tenant_id="t1",
        )
        assert result == "Friendly error from LLM"


# ---------------------------------------------------------------------------
# ``_extract_clean_reason_v2`` — additional edge cases on top of what is
# already covered.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ``_call_one_llm_evaluator`` — defensive parsing of judge LLM responses.
# Empty / invalid JSON / non-object / bad score must yield a 0-score result
# instead of letting json.loads blow up the whole case run.
# ---------------------------------------------------------------------------


def _call_evaluator(service_module, response):
    service_module.call_llm_for_system_prompt = MagicMock(return_value=response)
    service_module._build_evaluator_prompt = MagicMock(return_value="prompt")
    return service_module._call_one_llm_evaluator(
        eid=1,
        ev={"name": "judge-a"},
        judge_system_prompt="sys",
        tenant_id="t1",
        query="q",
        expected="e",
        actual="a",
        judge_model_id=99,
        runtime_events=[],
        context_window=8000,
        conversation_history=None,
    )


def test_call_one_llm_evaluator_happy_path(service_module):
    result = _call_evaluator(service_module, '{"score": 0.8, "reason": "ok"}')
    assert result == (1, "judge-a", 0.8, "ok")


def test_call_one_llm_evaluator_empty_response_returns_zero(service_module):
    for response in (None, "", "   "):
        result = _call_evaluator(service_module, response)
        assert result[:3] == (1, "judge-a", 0.0)
        assert "empty response" in result[3]


def test_call_one_llm_evaluator_invalid_json_returns_zero(service_module):
    result = _call_evaluator(service_module, "not json")
    assert result[:3] == (1, "judge-a", 0.0)
    assert "invalid JSON" in result[3]


def test_call_one_llm_evaluator_non_object_returns_zero(service_module):
    result = _call_evaluator(service_module, "[1, 2]")
    assert result[:3] == (1, "judge-a", 0.0)
    assert "not a JSON object" in result[3]


def test_call_one_llm_evaluator_non_numeric_score_returns_zero(service_module):
    for payload in ('{"score": "high"}', '{"score": null}'):
        result = _call_evaluator(service_module, payload)
        assert result == (1, "judge-a", 0.0, "")


# ---------------------------------------------------------------------------
# validate_code_evaluator — every failure stage + success paths
# ---------------------------------------------------------------------------


def _valid_evaluator_code(**kwargs):
    params = ", ".join(["query", "expected", "actual", "runtime_events"])
    if kwargs.get("var_keyword"):
        params += ", **kwargs"
    elif kwargs.get("missing"):
        params = "query"
    return f"def evaluate({params}):\n    return {{'score': 1, 'reason': 'ok'}}"


class TestValidateCodeEvaluator:
    def test_success_path(self, service_module):
        service_module.validate_code_evaluator(_valid_evaluator_code())

    def test_success_with_var_keyword(self, service_module):
        service_module.validate_code_evaluator(_valid_evaluator_code(var_keyword=True))

    def test_syntax_error_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException, match="Code syntax error"):
            service_module.validate_code_evaluator("def :")

    def test_forbidden_operations_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        monkeypatch.setattr(
            service_module, "_scan_shell_calls", MagicMock(return_value=["open"])
        )
        with pytest.raises(AppException, match="forbidden operations"):
            service_module.validate_code_evaluator("x = 1")

    def test_dunder_globals_escape_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException, match="forbidden operations"):
            service_module.validate_code_evaluator(
                "esc = json.JSONDecoder.__init__.__globals__['__builtins__']"
            )

    def test_dunder_class_chain_escape_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException, match="forbidden operations"):
            service_module.validate_code_evaluator(
                "esc = ().__class__.__base__.__subclasses__()"
            )

    def test_plain_helpers_without_dunders_pass(self, service_module):
        code = (
            "def _safe(x):\n"
            "    return {'score': 1, 'reason': 'ok'}\n"
            "def evaluate(query, expected, actual, runtime_events):\n"
            "    return _safe(query)\n"
        )
        service_module.validate_code_evaluator(code)

    def test_undefined_name_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException, match="forbidden or undefined name"):
            service_module.validate_code_evaluator("undefined_name()")

    def test_exec_error_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException, match="Code execution failed"):
            service_module.validate_code_evaluator("1 / 0")

    def test_missing_evaluate_callable_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException, match="must define"):
            service_module.validate_code_evaluator("x = 1")

    def test_missing_required_params_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException, match="missing required parameters"):
            service_module.validate_code_evaluator(
                "def evaluate(query):\n    return {'score': 1}"
            )

    def test_signature_introspection_failure_skips_check(self, service_module, monkeypatch):
        import inspect as _real_inspect

        class _FakeInspect:
            Parameter = _real_inspect.Parameter
            signature = MagicMock(side_effect=TypeError("no introspection"))

        monkeypatch.setitem(sys.modules, "inspect", _FakeInspect())
        # Must not raise even though the signature cannot be introspected.
        service_module.validate_code_evaluator(_valid_evaluator_code())


# ---------------------------------------------------------------------------
# _run_agent_to_final_answer — straggler cached-message parsing branches
# ---------------------------------------------------------------------------


def test_run_agent_to_final_answer_parses_straggler_messages(service_module):
    import asyncio

    service_module.AgentRequest = MagicMock()
    run_info = MagicMock()
    run_info.observer.get_cached_message.return_value = [
        "not json",
        json.dumps({"type": "step_count"}),
    ]
    service_module.prepare_agent_run = AsyncMock(return_value=(run_info, None))

    async def _fake_agent_run(_ri):
        yield json.dumps({"type": "final_answer", "content": "done"})

    service_module.agent_run = _fake_agent_run

    result = asyncio.run(
        service_module._run_agent_to_final_answer(
            agent_id=1, tenant_id="t1", user_id="u1", query="q", version_no=1
        )
    )
    assert result[0] == "done"
    assert result[1][-1]["type"] == "step_count"


# ---------------------------------------------------------------------------
# _is_all_pass
# ---------------------------------------------------------------------------


class TestIsAllPass:
    def test_empty_scores_returns_false(self, service_module):
        assert service_module._is_all_pass({}) is False

    def test_all_numeric_pass(self, service_module):
        assert service_module._is_all_pass({"a": 0.9, "b": 1.0}) is True

    def test_low_evaluator_fails(self, service_module):
        assert service_module._is_all_pass({"a": 0.3}, {"a": 0.5}) is False

    def test_uses_fallback_threshold(self, service_module):
        assert service_module._is_all_pass({"a": 0.7}) is False  # below DEFAULT 0.8
        assert service_module._is_all_pass({"a": 0.9}) is True

    def test_non_numeric_values_skipped(self, service_module):
        assert service_module._is_all_pass({"a": "rich", "b": 1.0}) is True
        assert service_module._is_all_pass({"a": "rich"}) is False

    def test_nan_score_skipped(self, service_module):
        assert service_module._is_all_pass({"a": float("nan")}) is False


# ---------------------------------------------------------------------------
# Runtime-context formatting helpers
# ---------------------------------------------------------------------------


class TestRuntimeContextHelpers:
    def test_format_runtime_context_no_events(self, service_module):
        text = service_module._format_runtime_context([], "actual")
        assert "No execution data" in text

    def test_format_runtime_context_with_steps(self, service_module):
        events = [
            {"type": "step_count"},
            {
                "type": "tool",
                "tool_name": "search",
                "tool_arguments": {"q": "x"},
                "content": "tool result",
            },
            {"type": "log", "content": "info line"},
            {"type": "error", "content": "boom"},
            {"type": "token_count", "content": {"total_output_tokens": 42}},
            {"type": "final_answer", "content": "final"},
        ]
        text = service_module._format_runtime_context(events, "actual answer")
        assert "## Agent Execution Log" in text
        assert "Step 1:" in text
        assert "─ Final Answer ─" in text
        assert "actual answer" in text
        assert "─ Stats ─" in text
        assert "Output tokens: 42" in text

    def test_format_runtime_context_zero_budget_breaks(self, service_module):
        events = [{"type": "step_count"}, {"type": "log", "content": "line"}]
        text = service_module._format_runtime_context(events, "actual", max_tokens=200)
        assert "Step 1:" not in text

    def test_group_events_by_step(self, service_module):
        events = [
            {"type": "a"},
            {"type": "step_count"},
            {"type": "b"},
        ]
        steps = service_module._group_events_by_step(events)
        assert steps == [[{"type": "a"}], [{"type": "step_count"}, {"type": "b"}]]

    def test_truncate_actual_answer(self, service_module):
        short = service_module._truncate_actual_answer("abc")
        assert short == "abc"
        long_text = "x" * 500
        truncated = service_module._truncate_actual_answer(long_text)
        assert "…" in truncated
        assert len(truncated) < 500

    def test_classify_step_event(self, service_module):
        assert service_module._classify_step_event({"type": "step_count"}) is None
        assert service_module._classify_step_event({"type": "final_answer"}) is None
        assert service_module._classify_step_event({"type": "token_count"}) is None

        cat, content, fixed = service_module._classify_step_event(
            {"type": "tool", "tool_name": "t", "tool_arguments": {"a": 1}, "content": "c"}
        )
        assert cat == "tool"
        assert content == "c"
        assert fixed == "  → t(a=1)"

        cat, content, fixed = service_module._classify_step_event(
            {"type": "execution_logs", "content": "hi"}
        )
        assert cat == "log"
        assert content == "hi"
        assert fixed == ""

        # trimmable with empty content -> category empty
        cat, content, fixed = service_module._classify_step_event(
            {"type": "execution_logs", "content": ""}
        )
        assert cat == "" and content == "" and fixed == ""

        # fallback event type with content
        cat, content, fixed = service_module._classify_step_event(
            {"type": "unknown", "content": "raw"}
        )
        assert cat == "" and content == "raw" and fixed == ""

        # fallback with empty content
        cat, content, fixed = service_module._classify_step_event({"type": "unknown"})
        assert cat == "" and content == "" and fixed == ""

    def test_trim_content(self, service_module):
        assert service_module._trim_content("short", 100) == "short"
        raw = "a" * 500
        trimmed = service_module._trim_content(raw, 100)
        assert "…" in trimmed and len(trimmed) < 500
        assert service_module._trim_content("abc", 5) == "abc"

    def test_distribute_budget_and_trim(self, service_module):
        assert service_module._distribute_budget_and_trim([], 100) == []
        events = [("tool", {"content": "a" * 300}), ("log", {"content": "b" * 300})]
        lines = service_module._distribute_budget_and_trim(events, 100)
        assert len(lines) == 2
        assert lines[0].startswith("  → ")
        assert lines[1].startswith("    ")

    def test_format_step_text(self, service_module):
        events = [
            {"type": "tool", "tool_name": "t", "tool_arguments": {}, "content": "x" * 200},
            {"type": "log", "content": "y" * 200},
        ]
        text = service_module._format_step_text(events, 100)
        assert "→ t()" in text

    def test_format_stats_summary(self, service_module):
        stats = {
            "steps": 2,
            "tool_calls": 3,
            "output_tokens": 4,
            "errors": 1,
            "max_steps_reached": True,
            "has_final_answer": False,
        }
        text = service_module._format_stats_summary(stats)
        assert "Steps: 2" in text and "Errors: 1" in text

    def test_extract_token_count(self, service_module):
        assert service_module._extract_token_count({"content": {"total_output_tokens": 5}}) == 5
        assert service_module._extract_token_count({"content": '{"total_output_tokens": 7}'}) == 7
        assert service_module._extract_token_count({"content": "not-json"}) is None
        assert service_module._extract_token_count({"content": {"x": 1}}) is None
        assert service_module._extract_token_count({"content": 3}) is None

    def test_extract_runtime_stats(self, service_module):
        events = [
            {"type": "step_count"},
            {"type": "error"},
            {"type": "tool"},
            {"type": "max_steps_reached"},
            {"type": "final_answer"},
            {"type": "token_count", "content": {"total_output_tokens": 11}},
            {"type": "token_count", "content": {"total_output_tokens": 9}},
        ]
        stats = service_module._extract_runtime_stats(events)
        assert stats["steps"] == 1
        assert stats["errors"] == 1
        assert stats["tool_calls"] == 1
        assert stats["max_steps_reached"] is True
        assert stats["has_final_answer"] is True
        assert stats["output_tokens"] == 11

    def test_format_conversation_history(self, service_module):
        assert service_module._format_conversation_history(None) == ""
        assert service_module._format_conversation_history([]) == ""
        text = service_module._format_conversation_history(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "system", "content": "ignored"},
            ]
        )
        assert "User: hi" in text
        assert "Agent: hello" in text
        assert "ignored" not in text
        assert text.endswith("\n\n")


class TestBuildEvaluatorPrompt:
    def test_uses_single_prompt_field_verbatim(self, service_module):
        # Single-field prompt design: no language switching, the prompt is
        # used as-is (builtin prompts carry their own language instruction).
        ev = {"prompt": "ZH"}
        prompt = service_module._build_evaluator_prompt(
            ev, "q", "e", "a", None, 4096, None
        )
        assert prompt == "ZH"

    def test_prepends_history_and_substitutes(self, service_module):
        ev = {"prompt": "q={{query}} e={{expected}} a={{actual}}"}
        prompt = service_module._build_evaluator_prompt(
            ev,
            "Q",
            "E",
            "A",
            None,
            4096,
            [{"role": "user", "content": "prev"}],
        )
        assert prompt.startswith("## Previous Conversation Turns")
        assert "q=Q" in prompt
        assert "e=E" in prompt
        assert "a=A" in prompt

    def test_injects_runtime_stats_when_placeholder_present(self, service_module, monkeypatch):
        ev = {"prompt": "ctx={{runtime_stats}}"}
        monkeypatch.setattr(
            service_module,
            "_format_runtime_context",
            MagicMock(return_value="RUNTIME"),
        )
        prompt = service_module._build_evaluator_prompt(
            ev, "q", "e", "a", [{"type": "step_count"}], 4096, None
        )
        assert "ctx=RUNTIME" in prompt

    def test_does_not_inject_when_no_placeholder(self, service_module):
        ev = {"prompt": "no placeholder"}
        prompt = service_module._build_evaluator_prompt(
            ev, "q", "e", "a", [{"type": "step_count"}], 4096, None
        )
        assert prompt == "no placeholder"


# ---------------------------------------------------------------------------
# Code / LLM evaluator execution + scoring
# ---------------------------------------------------------------------------


class TestRunCodeEvaluators:
    def test_success_and_error(self, service_module):
        code_evals = {
            1: {
                "name": "c1",
                "code": "def evaluate(query, expected, actual, runtime_events, **kw):\n    return {'score': 0.7, 'reason': 'ok'}",
            },
            2: {
                "name": "c2",
                "code": "def evaluate(query, expected, actual, runtime_events):\n    raise ValueError('bad')",
            },
        }
        scores, reasons = service_module._run_code_evaluators(
            code_evals, "q", "e", "a", []
        )
        assert scores == {"c1": 0.7, "c2": 0.0}
        assert "Code evaluator error" in reasons["c2"]


class TestCollectLlmResults:
    def test_success_and_failure(self, service_module, monkeypatch):
        f1, f2 = MagicMock(), MagicMock()
        f1.result.return_value = (1, "n1", 0.8, "r1")
        f2.result.side_effect = RuntimeError("boom")
        monkeypatch.setattr(service_module, "as_completed", lambda fut: [f1, f2])
        llm_evals = {1: {"name": "n1"}, 2: {"name": "n2"}}
        scores, reasons = service_module._collect_llm_results({f1: 1, f2: 2}, llm_evals)
        assert scores == {"n1": 0.8, "n2": 0.0}
        assert "LLM evaluator error" in reasons["n2"]


class TestScoreWithEvaluators:
    def test_code_only_no_llm_executor(self, service_module, monkeypatch):
        evaluators = {
            1: {
                "evaluator_type": "code",
                "name": "c1",
                "code": "def evaluate(query, expected, actual, runtime_events, **kw):\n    return {'score': 1.0, 'reason': ''}",
            }
        }
        scores, reasons = service_module._score_with_evaluators(
            evaluators, "sys", "t1", "q", "e", "a", 99
        )
        assert scores == {"c1": 1.0}

    def test_with_llm_evaluators_submits_to_executor(self, service_module, monkeypatch):
        executor = MagicMock()
        future = MagicMock()
        executor.submit.return_value = future
        monkeypatch.setattr(service_module, "_LLM_EVAL_EXECUTOR", executor)
        monkeypatch.setattr(
            service_module,
            "_collect_llm_results",
            MagicMock(return_value=({"n1": 0.9}, {"n1": "r"})),
        )
        evaluators = {
            1: {"evaluator_type": "llm", "name": "n1"},
            2: {"evaluator_type": "code", "name": "c1", "code": "x=1\ndef evaluate(query, expected, actual, runtime_events, **kw):\n    return {'score': 1, 'reason': ''}"},
        }
        scores, reasons = service_module._score_with_evaluators(
            evaluators, "sys", "t1", "q", "e", "a", 99
        )
        assert scores == {"n1": 0.9, "c1": 1.0}
        executor.submit.assert_called_once()


# ---------------------------------------------------------------------------
# Run limits / evaluator freeze / no-set mode
# ---------------------------------------------------------------------------


class TestCheckRunLimits:
    def test_active_limit_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        monkeypatch.setattr(service_module, "count_active_runs", MagicMock(return_value=10))
        monkeypatch.setattr(service_module, "count_total_runs", MagicMock(return_value=0))
        with pytest.raises(AppException) as excinfo:
            service_module._check_run_limits("t1")
        assert excinfo.value.error_code == service_module.ErrorCode.COMMON_RATE_LIMIT_EXCEEDED

    def test_total_limit_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        monkeypatch.setattr(service_module, "count_active_runs", MagicMock(return_value=0))
        monkeypatch.setattr(service_module, "count_total_runs", MagicMock(return_value=100))
        with pytest.raises(AppException):
            service_module._check_run_limits("t1")

    def test_ok(self, service_module, monkeypatch):
        monkeypatch.setattr(service_module, "count_active_runs", MagicMock(return_value=0))
        monkeypatch.setattr(service_module, "count_total_runs", MagicMock(return_value=0))
        service_module._check_run_limits("t1")


class TestValidateAndFreezeEvaluators:
    def _evaluator(self, status="PUBLISHED", name="e1"):
        return {"evaluator_id": 1, "name": name, "status": status, "pass_threshold": 0.8}

    def test_none_when_no_ids(self, service_module, monkeypatch):
        assert service_module._validate_and_freeze_evaluators(None, "t1", None, "zh") is None

    def test_too_many_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        with pytest.raises(AppException):
            service_module._validate_and_freeze_evaluators([1, 2, 3, 4], "t1", None, "zh")

    def test_not_found_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        monkeypatch.setattr(service_module, "get_evaluator", MagicMock(return_value=None))
        with pytest.raises(AppException):
            service_module._validate_and_freeze_evaluators([1], "t1", None, "zh")

    def test_not_published_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        monkeypatch.setattr(
            service_module, "get_evaluator", MagicMock(return_value=self._evaluator("DRAFT"))
        )
        with pytest.raises(AppException):
            service_module._validate_and_freeze_evaluators([1], "t1", None, "zh")

    def test_returns_snapshot(self, service_module, monkeypatch):
        monkeypatch.setattr(
            service_module, "get_evaluator", MagicMock(return_value=self._evaluator())
        )
        snapshot = service_module._validate_and_freeze_evaluators(
            [1], "t1", {"m": "x"}, "en"
        )
        assert snapshot == {
            "evaluator_ids": [1],
            "field_mappings": {"m": "x"},
            "language": "en",
        }


class TestCreateNoSetModeRun:
    def test_query_count_out_of_range_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        with pytest.raises(AppException):
            service_module._create_no_set_mode_run(
                "t1", "u1", 1, 1, 99, None, None, 0, "zh", None
            )
        with pytest.raises(AppException):
            service_module._create_no_set_mode_run(
                "t1", "u1", 1, 1, 99, None, None, 51, "zh", None
            )

    def test_creates_run_and_submits(self, service_module, monkeypatch):
        create = MagicMock(return_value={"agent_evaluation_id": 5})
        monkeypatch.setattr(service_module, "create_agent_evaluation", create)
        run_bg = MagicMock()
        monkeypatch.setattr(service_module, "_run_in_background", run_bg)

        run = service_module._create_no_set_mode_run(
            "t1", "u1", 7, 3, 99, [1], {"m": "x"}, 10, "zh", {"old": 1}
        )
        assert run == {"agent_evaluation_id": 5}
        assert create.call_args.kwargs["evaluation_set_id"] == 0
        assert create.call_args.kwargs["evaluator_config"]["no_set_mode"] is True
        assert create.call_args.kwargs["evaluator_config"]["old"] == 1
        run_bg.assert_called_once()


class TestCreateNoSetModeBranch:
    def test_forwards_to_no_set_mode_when_no_set_id(self, service_module, monkeypatch):
        monkeypatch.setattr(service_module, "_check_run_limits", MagicMock())
        monkeypatch.setattr(
            service_module, "_validate_and_freeze_evaluators", MagicMock(return_value=None)
        )
        monkeypatch.setattr(
            service_module, "resolve_latest_published_version_no", MagicMock(return_value=3)
        )
        no_set = MagicMock(return_value={"agent_evaluation_id": 1})
        monkeypatch.setattr(service_module, "_create_no_set_mode_run", no_set)

        run = service_module.create_agent_evaluation_run_impl(
            tenant_id="t1", user_id="u1", agent_id=7, judge_model_id=99
        )
        assert run == {"agent_evaluation_id": 1}
        assert no_set.call_args[0][3] == 3  # resolved version_no


# ---------------------------------------------------------------------------
# Query generation helpers
# ---------------------------------------------------------------------------


class TestBuildAgentProfileParts:
    def test_includes_populated_fields(self, service_module):
        profile = {
            "name": "A",
            "description": "d",
            "duty_prompt": "dp",
            "constraint_prompt": "cp",
            "business_description": "bd",
        }
        parts = service_module._build_agent_profile_parts(profile)
        assert "- Name: A" in parts[0]
        assert len(parts) == 5

    def test_skips_empty_fields(self, service_module):
        profile = {
            "name": "A",
            "description": "",
            "duty_prompt": None,
            "constraint_prompt": "",
            "business_description": None,
        }
        parts = service_module._build_agent_profile_parts(profile)
        assert len(parts) == 1


class TestExtractCasesFromMarkdownFence:
    def test_parses_fence(self, service_module):
        cases = service_module._extract_cases_from_markdown_fence(
            '```json\n[{"inputs": {"query": "q"}}]\n```'
        )
        assert cases == [{"inputs": {"query": "q"}}]

    def test_no_fence_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException) as excinfo:
            service_module._extract_cases_from_markdown_fence("no fence here")
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT
        )

    def test_bad_json_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException):
            service_module._extract_cases_from_markdown_fence("```json\n[oops]\n```")


class TestParseCasesFromLlmResponse:
    def test_list_passthrough(self, service_module):
        assert service_module._parse_cases_from_llm_response([{"a": 1}]) == [{"a": 1}]

    def test_json_string(self, service_module):
        assert service_module._parse_cases_from_llm_response('[{"a": 1}]') == [{"a": 1}]

    def test_markdown_fence_fallback(self, service_module):
        cases = service_module._parse_cases_from_llm_response(
            '```json\n[{"a": 1}]\n```'
        )
        assert cases == [{"a": 1}]

    def test_empty_list_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException):
            service_module._parse_cases_from_llm_response("[]")

    def test_non_list_raises(self, service_module):
        from consts.exceptions import AppException
        with pytest.raises(AppException):
            service_module._parse_cases_from_llm_response('{"a": 1}')


class TestGenerateTestQueries:
    def _profile(self):
        return {
            "name": "A",
            "description": "d",
            "duty_prompt": "",
            "constraint_prompt": "",
            "business_description": "",
        }

    def test_profile_missing_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        profile_utils = sys.modules["utils.agent_profile_utils"]
        monkeypatch.setattr(profile_utils, "fetch_agent_profile", MagicMock(return_value=None))
        with pytest.raises(AppException) as excinfo:
            service_module._generate_test_queries(1, "t1", 99)
        assert excinfo.value.error_code == service_module.ErrorCode.AGENT_EVALUATION_AGENT_NOT_FOUND

    def test_llm_failure_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        profile_utils = sys.modules["utils.agent_profile_utils"]
        monkeypatch.setattr(profile_utils, "fetch_agent_profile", MagicMock(return_value=self._profile()))
        monkeypatch.setattr(
            service_module, "get_prompt_template", MagicMock(return_value={"SYSTEM_PROMPT": "s"})
        )
        monkeypatch.setattr(
            service_module,
            "call_llm_for_system_prompt",
            MagicMock(side_effect=RuntimeError("llm down")),
        )
        with pytest.raises(AppException) as excinfo:
            service_module._generate_test_queries(1, "t1", 99)
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FAILED
        )

    def test_no_valid_queries_raises(self, service_module, monkeypatch):
        from consts.exceptions import AppException
        profile_utils = sys.modules["utils.agent_profile_utils"]
        monkeypatch.setattr(profile_utils, "fetch_agent_profile", MagicMock(return_value=self._profile()))
        monkeypatch.setattr(
            service_module, "get_prompt_template", MagicMock(return_value={"SYSTEM_PROMPT": "s"})
        )
        # Non-empty list whose queries are all blank -> filtered to nothing -> EMPTY.
        monkeypatch.setattr(
            service_module,
            "call_llm_for_system_prompt",
            MagicMock(
                return_value=json.dumps(
                    [{"inputs": {"query": "   "}, "label": {"answer": "a"}}]
                )
            ),
        )
        with pytest.raises(AppException) as excinfo:
            service_module._generate_test_queries(1, "t1", 99)
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_EMPTY
        )

    def test_generates_queries(self, service_module, monkeypatch):
        profile_utils = sys.modules["utils.agent_profile_utils"]
        monkeypatch.setattr(profile_utils, "fetch_agent_profile", MagicMock(return_value=self._profile()))
        monkeypatch.setattr(
            service_module, "get_prompt_template", MagicMock(return_value={"SYSTEM_PROMPT": "s"})
        )
        response = json.dumps(
            [
                {"inputs": {"query": "q1"}, "label": {"answer": "a1"}},
                {"inputs": {"query": "  "}, "label": {"answer": "a2"}},
                {"inputs": {"query": "q3"}, "label": {"answer": "a3"}},
                "not-a-dict",
            ]
        )
        monkeypatch.setattr(
            service_module, "call_llm_for_system_prompt", MagicMock(return_value=response)
        )
        queries = service_module._generate_test_queries(1, "t1", 99, query_count=2)
        assert queries == ["q1", "q3"]


# ---------------------------------------------------------------------------
# _evaluate_query / pass-status helpers
# ---------------------------------------------------------------------------


class TestEvaluateQuery:
    def test_with_evaluators(self, service_module, monkeypatch):
        import asyncio

        monkeypatch.setattr(
            service_module, "_run_agent_to_final_answer",
            AsyncMock(return_value=("answer", [{"type": "step_count"}])),
        )
        monkeypatch.setattr(
            service_module,
            "_score_with_evaluators",
            MagicMock(return_value=({"n1": 0.9}, {"n1": "r"})),
        )
        answer, events, score, reason = asyncio.run(
            service_module._evaluate_query(
                tenant_id="t1", user_id="u1", agent_id=1, agent_version_no=1,
                query="q", judge_model_id=99, adapter=None,
                evaluators={1: {"name": "n1"}}, judge_system_prompt="sys",
            )
        )
        assert answer == "answer"
        assert score == {"n1": 0.9}
        service_module._score_with_evaluators.assert_called_once()

    def test_without_evaluators_uses_adapter(self, service_module, monkeypatch):
        import asyncio

        monkeypatch.setattr(
            service_module, "_run_agent_to_final_answer",
            AsyncMock(return_value=("answer", [])),
        )
        adapter = MagicMock()
        adapter.evaluate_semantic_consistency.return_value = (1, "consistent")
        answer, events, score, reason = asyncio.run(
            service_module._evaluate_query(
                tenant_id="t1", user_id="u1", agent_id=1, agent_version_no=1,
                query="q", judge_model_id=99, adapter=adapter,
                evaluators={}, judge_system_prompt="sys",
            )
        )
        assert score == {"semantic_consistency": 1}
        assert reason == {"semantic_consistency": "consistent"}


class TestCasePassStatusHelpers:
    def test_determine_case_pass_status(self, service_module):
        assert (
            service_module._determine_case_pass_status(1, {})
            == service_module.EvalPassStatus.PASS
        )
        assert (
            service_module._determine_case_pass_status(0, {})
            == service_module.EvalPassStatus.FAIL
        )
        assert (
            service_module._determine_case_pass_status({"a": 0.9}, {})
            == service_module.EvalPassStatus.PASS
        )
        assert (
            service_module._determine_case_pass_status({"a": 0.1}, {})
            == service_module.EvalPassStatus.FAIL
        )

    def test_compute_case_average_score(self, service_module):
        assert (
            service_module._compute_case_average_score({"a": 0.8, "b": 0.4})
            == pytest.approx(0.6)
        )
        assert service_module._compute_case_average_score({"a": "x"}) == 0.0
        assert service_module._compute_case_average_score(0.75) == 0.75

    def test_build_evaluator_thresholds(self, service_module):
        evaluators = {
            1: {"name": "a", "pass_threshold": 0.7},
            2: {"name": "b"},
            3: {},
        }
        thresholds = service_module._build_evaluator_thresholds(evaluators)
        assert thresholds == {"a": 0.7, "b": service_module.DEFAULT_PASS_THRESHOLD}


# ---------------------------------------------------------------------------
# ``_generate_friendly_error_message`` — LLM call exception path.
# ---------------------------------------------------------------------------


def test_generate_friendly_error_message_llm_exception_returns_default(service_module):
    service_module.get_prompt_template = MagicMock(
        return_value={"USER_PROMPT": "u {{error_message}}", "SYSTEM_PROMPT": "s"}
    )
    service_module.call_llm_for_system_prompt = MagicMock(
        side_effect=RuntimeError("boom")
    )
    result = service_module._generate_friendly_error_message(
        RuntimeError("openai timeout"), "default", model_id=99, tenant_id="t1"
    )
    assert result == "default"


# ---------------------------------------------------------------------------
# ``_format_step_text`` — tool event with no trimmable content (fixed line only).
# ---------------------------------------------------------------------------


def test_format_step_text_fixed_lines_only(service_module):
    events = [
        {
            "type": "tool",
            "tool_name": "search",
            "tool_arguments": {"q": "x"},
            "content": "",
        }
    ]
    text = service_module._format_step_text(events, 100)
    assert text == "  → search(q=x)"


# ---------------------------------------------------------------------------
# ``_setup_no_set_and_execute`` — background no-set run orchestration.
# ---------------------------------------------------------------------------


class _FakeEvalQuery:
    def __init__(self, owner):
        self._owner = owner

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._owner.models

    def first(self):
        return self._owner.models[0] if self._owner.models else None

    def update(self, *a, **k):
        self._owner.updates.append((a, k))
        return 1

    def commit(self):
        return None


class _FakeEvalSession:
    """Fake ``get_db_session`` context manager for no-set / stats tests."""

    def __init__(self, models=None):
        self.models = models or []
        self.updates = []

    def query(self, *a, **k):
        return _FakeEvalQuery(self)

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _make_eval_model(mid, mtype, window=4096):
    m = MagicMock()
    m.model_id = mid
    m.model_type = mtype
    m.context_window_tokens = window
    return m


class TestSetupNoSetAndExecute:
    def _wire(self, service_module, models):
        sessions = []

        def _gs():
            s = _FakeEvalSession(models=models)
            sessions.append(s)
            return s

        service_module.get_db_session = _gs
        service_module._generate_test_queries = MagicMock(return_value=["q1", "q2"])
        service_module.materialize_virtual_evaluation_set_for_run = MagicMock(
            return_value=7
        )
        service_module.get_evaluation_set_cases_all = MagicMock(
            return_value=[{"evaluation_set_case_id": 1}]
        )
        service_module.create_agent_evaluation_cases = MagicMock()
        service_module._dispatch_agent_evaluation_run = MagicMock()
        return sessions

    def test_success_judge_is_llm(self, service_module):
        sessions = self._wire(
            service_module,
            models=[_make_eval_model(99, "llm"), _make_eval_model(2, "embedding")],
        )
        service_module._setup_no_set_and_execute("t1", "u1", 1, 2, 99, [1], {}, 5, "zh", 10)
        # Judge model is itself an LLM -> used as-is for generation.
        assert service_module._generate_test_queries.call_args.kwargs["model_id"] == 99
        assert service_module._generate_test_queries.call_args.kwargs["query_count"] == 5
        service_module.materialize_virtual_evaluation_set_for_run.assert_called_once()
        service_module._dispatch_agent_evaluation_run.assert_called_once_with(
            agent_evaluation_id=10,
            user_id="u1",
            tenant_id="t1",
        )
        # The virtual set and run link are now committed in one DB transaction.
        assert len(sessions) == 1
        materialize_kw = (
            service_module.materialize_virtual_evaluation_set_for_run.call_args.kwargs
        )
        assert materialize_kw["agent_evaluation_id"] == 10
        assert len(materialize_kw["cases"]) == 2

    def test_judge_not_llm_falls_back_to_newest_llm(self, service_module):
        models = [
            _make_eval_model(99, "embedding"),
            _make_eval_model(5, "llm"),
            _make_eval_model(3, "llm"),
        ]
        self._wire(service_module, models=models)
        service_module._setup_no_set_and_execute("t1", "u1", 1, 2, 99, [1], {}, 5, "zh", 10)
        # Sorted desc by model_id -> 5 is the newest LLM.
        assert service_module._generate_test_queries.call_args.kwargs["model_id"] == 5

    def test_judge_not_llm_no_llm_models_keeps_judge(self, service_module):
        self._wire(service_module, models=[_make_eval_model(99, "embedding")])
        service_module._setup_no_set_and_execute("t1", "u1", 1, 2, 99, [1], {}, 5, "zh", 10)
        assert service_module._generate_test_queries.call_args.kwargs["model_id"] == 99

    def test_model_query_failure_keeps_judge_and_continues(self, service_module):
        sessions = []

        def _flaky_gs():
            if not sessions:
                raise RuntimeError("db down")
            s = _FakeEvalSession()
            sessions.append(s)
            return s

        service_module.get_db_session = _flaky_gs
        service_module._generate_test_queries = MagicMock(return_value=["q1"])
        service_module.materialize_virtual_evaluation_set_for_run = MagicMock(
            return_value=1
        )
        service_module.get_evaluation_set_cases_all = MagicMock(return_value=[])
        service_module.create_agent_evaluation_cases = MagicMock()
        service_module._dispatch_agent_evaluation_run = MagicMock()
        service_module._setup_no_set_and_execute("t1", "u1", 1, 2, 99, [1], {}, 5, "zh", 10)
        assert service_module._generate_test_queries.call_args.kwargs["model_id"] == 99

    def test_failure_marks_run_failed(self, service_module, monkeypatch):
        service_module.get_db_session = MagicMock(side_effect=RuntimeError("db down"))
        service_module._generate_test_queries = MagicMock(
            side_effect=RuntimeError("llm down")
        )
        service_module.update_agent_evaluation_status = MagicMock()
        service_module._setup_no_set_and_execute("t1", "u1", 1, 2, 99, [1], {}, 5, "zh", 10)
        kw = service_module.update_agent_evaluation_status.call_args.kwargs
        assert kw["status"] == service_module.EvalRunStatus.FAILED
        assert kw["error_message"] == "Failed to generate test queries"


class TestPreloadEvaluatorsForRun:
    def test_empty_for_bad_config(self, service_module):
        assert service_module._preload_evaluators_for_run({"evaluator_config": "x"}, "t1") == {}
        assert service_module._preload_evaluators_for_run({"evaluator_config": None}, "t1") == {}
        assert (
            service_module._preload_evaluators_for_run(
                {"evaluator_config": {"evaluator_ids": None}}, "t1"
            )
            == {}
        )

    def test_filters_non_published(self, service_module):
        service_module.get_evaluator = MagicMock(
            side_effect=[
                {"status": "PUBLISHED", "name": "a"},
                {"status": "DRAFT", "name": "b"},
                None,
            ]
        )
        evs = service_module._preload_evaluators_for_run(
            {"evaluator_config": {"evaluator_ids": [1, 2, 3]}}, "t1"
        )
        assert list(evs.keys()) == [1]


class TestResolveJudgeContextWindow:
    def _run(self, service_module, model_row):
        service_module.get_db_session = lambda: _FakeEvalSession(
            models=[model_row] if model_row else []
        )
        return service_module._resolve_judge_context_window(99, "t1")

    def test_uses_model_window(self, service_module):
        m = _make_eval_model(99, "llm", window=8192)
        assert self._run(service_module, m) == 8192

    def test_defaults_when_no_window(self, service_module):
        m = _make_eval_model(99, "llm", window=None)
        assert self._run(service_module, m) == 4096

    def test_defaults_when_no_model(self, service_module):
        assert self._run(service_module, None) == 4096


class TestLoadAllEvaluationCases:
    def test_paginated_dict_response(self, service_module):
        service_module.list_agent_evaluation_cases = MagicMock(
            side_effect=[
                {"items": [{"agent_evaluation_case_id": 1}, {"agent_evaluation_case_id": 2}]},
                {"items": []},
            ]
        )
        cases = service_module._load_all_evaluation_cases(1, "t1")
        assert len(cases) == 2

    def test_list_response_advances_offset(self, service_module):
        service_module.list_agent_evaluation_cases = MagicMock(
            side_effect=[[{"agent_evaluation_case_id": 1}], []]
        )
        cases = service_module._load_all_evaluation_cases(1, "t1")
        assert len(cases) == 1
        assert service_module.list_agent_evaluation_cases.call_args_list[1].kwargs["offset"] == 1

    def test_group_cases_by_session(self, service_module):
        cases = [
            {"agent_evaluation_case_id": 1, "session_id": "s1"},
            {"agent_evaluation_case_id": 2, "session_id": "s1"},
            {"agent_evaluation_case_id": 3},
            {"agent_evaluation_case_id": 4, "session_id": "s2"},
        ]
        groups = service_module._group_cases_by_session(cases)
        assert set(groups) == {"s1", "s2", "__single__3"}
        assert len(groups["s1"]) == 2


# ---------------------------------------------------------------------------
# ``execute_agent_evaluation_run`` — SDK-unavailable + overlong-session edges.
# ---------------------------------------------------------------------------


def test_execute_run_sdk_unavailable_marks_failed(service_module):
    _wire_full_db_module(service_module)
    service_module.JiuwenSDKAdapter = None
    service_module.get_agent_evaluation.return_value = {
        "agent_evaluation_id": 50,
        "agent_id": 11,
        "agent_version_no": 4,
        "judge_model_id": 99,
    }
    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=99)
    last = service_module.update_agent_evaluation_status.call_args_list[-1]
    assert last.kwargs["status"] == service_module.EvalRunStatus.FAILED


def test_execute_run_truncates_overlong_session(service_module):
    limit = service_module.MAX_TURNS_PER_SESSION
    cases = [
        {
            **_make_exec_case(i),
            "session_id": "s1",
            "turn_order": i,
        }
        for i in range(limit + 5)
    ]
    _wire_executor_dependencies(service_module, cases)
    service_module.execute_agent_evaluation_run("t1", "u1", 50, judge_model_id=99)
    completed = [
        c
        for c in service_module.update_agent_evaluation_case_result.call_args_list
        if c.kwargs.get("status") == service_module.EvalCaseStatus.COMPLETED
    ]
    assert len(completed) == limit


# ---------------------------------------------------------------------------
# Analysis report helpers + ``generate_analysis_report_impl``.
# ---------------------------------------------------------------------------


class TestAnalysisHelpers:
    def test_normalize_cases_response(self, service_module):
        assert service_module._normalize_cases_response({"items": [1, 2]}) == [1, 2]
        assert service_module._normalize_cases_response([1]) == [1]
        assert service_module._normalize_cases_response(None) == []

    def test_load_evaluator_thresholds_from_config(self, service_module):
        service_module.get_evaluator = MagicMock(
            return_value={"name": "judge-a", "pass_threshold": 0.7}
        )
        assert service_module._load_evaluator_thresholds_from_config(
            {"evaluator_ids": [1]}, "t1"
        ) == {"judge-a": 0.7}
        assert service_module._load_evaluator_thresholds_from_config("nope", "t1") == {}
        assert (
            service_module._load_evaluator_thresholds_from_config(
                {"evaluator_ids": None}, "t1"
            )
            == {}
        )

    def test_load_evaluator_thresholds_skips_bad_ids(self, service_module):
        service_module.get_evaluator = MagicMock(side_effect=ValueError("bad id"))
        assert (
            service_module._load_evaluator_thresholds_from_config(
                {"evaluator_ids": ["x"]}, "t1"
            )
            == {}
        )

    def test_load_evaluator_thresholds_default_and_skips(self, service_module):
        service_module.get_evaluator = MagicMock(
            side_effect=[
                {"name": "a"},  # no threshold -> default
                {"name": ""},   # no name -> skipped
                None,           # not a dict -> skipped
            ]
        )
        thresholds = service_module._load_evaluator_thresholds_from_config(
            {"evaluator_ids": [1, 2, 3]}, "t1"
        )
        assert thresholds == {"a": service_module.DEFAULT_PASS_THRESHOLD}

    def test_parse_case_reason(self, service_module):
        assert service_module._parse_case_reason("") == {}
        assert service_module._parse_case_reason('{"a": 1}') == {"a": 1}
        assert service_module._parse_case_reason("[1, 2]") == {"reason": "[1, 2]"}
        assert service_module._parse_case_reason("not-json") == {"reason": "not-json"}

    def test_extract_nested_str(self, service_module):
        c = {"predict": {"answer": "ans"}, "inputs": {"query": "q"}}
        assert service_module._extract_nested_str(c, "predict", "answer") == "ans"
        assert service_module._extract_nested_str(c, "inputs", "query") == "q"
        assert service_module._extract_nested_str(c, "missing", "x") == ""
        assert service_module._extract_nested_str({"predict": "str"}, "predict", "answer") == ""

    def test_build_analysis_failure_example_single(self, service_module):
        c = {
            "agent_evaluation_case_id": 1,
            "inputs": {"query": "q1"},
            "predict": {"answer": "a1"},
            "score": {"judge-a": 0.4},
            "reason": '{"judge-a": "too short"}',
        }
        ex = service_module._build_analysis_failure_example(c)
        assert ex["score"] == 0.4  # single evaluator compacted to scalar
        assert ex["reason"] == "judge-a: too short"
        assert ex["answer"] == "a1"
        assert ex["query"] == "q1"
        assert ex["case_id"] == 1

    def test_build_analysis_failure_example_multi_and_clamp(self, service_module):
        c = {
            "agent_evaluation_case_id": 2,
            "inputs": {"query": "q" * 5000},
            "predict": {"answer": "a" * 5000},
            "score": {"judge-a": 0.2, "judge-b": 0.9},
            "reason": "raw",
        }
        ex = service_module._build_analysis_failure_example(c)
        assert ex["score"] == {"judge-a": 0.2, "judge-b": 0.9}
        assert len(ex["answer"]) == 4000
        assert len(ex["query"]) == 5000  # query is NOT clamped
        assert ex["reason"] == "reason: raw"

    def test_build_analysis_failure_example_empty_reason(self, service_module):
        c = {
            "agent_evaluation_case_id": 3,
            "inputs": {"query": "q"},
            "predict": {"answer": "a"},
            "score": {"judge-a": 0.2, "judge-b": 0.9},
            "reason": "",
        }
        ex = service_module._build_analysis_failure_example(c)
        assert ex["reason"] == ""

    def test_render_analysis_stats_block(self, service_module):
        block = service_module._render_analysis_stats_block(10, 7, {})
        assert "Total cases: 10" in block
        assert "Passed: 7" in block
        block2 = service_module._render_analysis_stats_block(10, 7, {"judge-a": 0.8})
        assert "judge-a" in block2

    def test_render_analysis_failures_block(self, service_module):
        assert service_module._render_analysis_failures_block([]) == "\nNo failed cases."
        exs = [
            {
                "query": "q\nwith\nnewlines",
                "score": {"judge-a": 0.1},
                "reason": "r1",
                "answer": "a1",
            },
            {"query": "q2", "score": 0.2, "reason": "", "answer": ""},
        ]
        block = service_module._render_analysis_failures_block(exs)
        assert "Case 1: Q=q with newlines" in block
        assert block.count("Reason:") == 1
        assert block.count("Answer:") == 1
        assert "Case 2" in block

    def test_render_analysis_failures_block_clamps(self, service_module):
        exs = [
            {"query": f"q{i}", "score": 0.1, "reason": "", "answer": ""}
            for i in range(service_module.MAX_FAILURE_EXAMPLES + 2)
        ]
        block = service_module._render_analysis_failures_block(exs)
        assert block.count("Case ") == service_module.MAX_FAILURE_EXAMPLES

    def test_call_analysis_llm_and_parse(self, service_module):
        service_module.get_prompt_template = MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        service_module.call_llm_for_system_prompt = MagicMock(return_value='{"summary": "x"}')
        assert service_module._call_analysis_llm_and_parse(
            {"judge_model_id": 99}, "zh", "up", "t1"
        ) == {"summary": "x"}
        service_module.call_llm_for_system_prompt = MagicMock(return_value={"summary": "y"})
        assert service_module._call_analysis_llm_and_parse(
            {"judge_model_id": 99}, "zh", "up", "t1"
        ) == {"summary": "y"}

    def test_call_analysis_llm_and_parse_non_dict_raises(self, service_module):
        from consts.exceptions import AppException
        service_module.get_prompt_template = MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        service_module.call_llm_for_system_prompt = MagicMock(return_value="[1, 2]")
        with pytest.raises(AppException) as excinfo:
            service_module._call_analysis_llm_and_parse({"judge_model_id": 99}, "zh", "up", "t1")
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED
        )


class TestGenerateAnalysisReportImpl:
    def _run(self, service_module, **overrides):
        run = {
            "agent_evaluation_id": 1,
            "tenant_id": "t1",
            "status": "COMPLETED",
            "judge_model_id": 99,
            "evaluator_config": {"evaluator_ids": [1]},
            "analysis_report": None,
        }
        run.update(overrides)
        service_module.get_agent_evaluation.return_value = run
        return run

    def test_run_not_found_raises(self, service_module):
        from consts.exceptions import AppException
        service_module.get_agent_evaluation.return_value = None
        with pytest.raises(AppException) as excinfo:
            service_module.generate_analysis_report_impl(1, "t1")
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.COMMON_RESOURCE_NOT_FOUND
        )

    def test_cached_returned_without_force(self, service_module):
        cached = {"summary": "cached"}
        self._run(service_module, analysis_report=cached)
        assert service_module.generate_analysis_report_impl(1, "t1") == cached

    def test_not_ready_raises(self, service_module):
        from consts.exceptions import AppException
        self._run(service_module, status="RUNNING")
        with pytest.raises(AppException) as excinfo:
            service_module.generate_analysis_report_impl(1, "t1")
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.AGENT_EVALUATION_ANALYSIS_NOT_READY
        )

    def test_success_path(self, service_module):
        self._run(service_module)
        service_module.update_agent_evaluation_analysis_report.reset_mock()
        service_module.list_agent_evaluation_cases = MagicMock(
            return_value={
                "items": [
                    {
                        "agent_evaluation_case_id": 1,
                        "pass_status": "pass",
                        "score": {"judge-a": 0.9},
                        "reason": "{}",
                        "inputs": {"query": "q1"},
                        "predict": {"answer": "a1"},
                    },
                    {
                        "agent_evaluation_case_id": 2,
                        "pass_status": "fail",
                        "score": {"judge-a": 0.3},
                        "reason": '{"judge-a": "bad"}',
                        "inputs": {"query": "q2"},
                        "predict": {"answer": "a2"},
                    },
                ]
            }
        )
        service_module.get_evaluator = MagicMock(
            return_value={"name": "judge-a", "pass_threshold": 0.8}
        )
        service_module.get_prompt_template = MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        service_module.call_llm_for_system_prompt = MagicMock(
            return_value='{"summary": "ok", "failures": []}'
        )
        result = service_module.generate_analysis_report_impl(1, "t1")
        assert result["summary"] == "ok"
        service_module.update_agent_evaluation_analysis_report.assert_called_once_with(
            1, "t1", {"summary": "ok", "failures": []}
        )

    def test_llm_failure_raises(self, service_module):
        from consts.exceptions import AppException
        self._run(service_module)
        service_module.list_agent_evaluation_cases = MagicMock(return_value=[])
        service_module.get_evaluator = MagicMock(return_value=None)
        service_module.get_prompt_template = MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        service_module.call_llm_for_system_prompt = MagicMock(
            side_effect=RuntimeError("llm down")
        )
        with pytest.raises(AppException) as excinfo:
            service_module.generate_analysis_report_impl(1, "t1")
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED
        )

    def test_non_dict_llm_response_raises(self, service_module):
        from consts.exceptions import AppException
        self._run(service_module)
        service_module.list_agent_evaluation_cases = MagicMock(return_value=[])
        service_module.get_evaluator = MagicMock(return_value=None)
        service_module.get_prompt_template = MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        service_module.call_llm_for_system_prompt = MagicMock(return_value="[1, 2]")
        with pytest.raises(AppException) as excinfo:
            service_module.generate_analysis_report_impl(1, "t1")
        assert (
            excinfo.value.error_code
            == service_module.ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED
        )


# ---------------------------------------------------------------------------
# ``get_evaluation_stats_impl`` — chart aggregates.
# ---------------------------------------------------------------------------


class TestGetEvaluationStatsImpl:
    def test_empty(self, service_module):
        service_module.get_evaluation_case_scores = MagicMock(return_value=[])
        assert service_module.get_evaluation_stats_impl(1, "t1") == {
            "per_evaluator": [],
            "histogram": [],
            "pass_count": 0,
            "fail_count": 0,
            "total": 0,
        }

    def test_aggregates(self, service_module):
        scores = [
            {
                "pass_status": "pass",
                "score": {"judge-a": 1.0, "judge-b": 0.5, "judge-c": "bad"},
            },
            {
                "pass_status": "fail",
                "score": {"judge-a": 0.1, "judge-b": 0.2, "judge-c": 0.9},
            },
            {"pass_status": "pass", "score": None},
        ]
        service_module.get_evaluation_case_scores = MagicMock(return_value=scores)
        stats = service_module.get_evaluation_stats_impl(1, "t1")
        assert stats["pass_count"] == 2
        assert stats["fail_count"] == 1
        assert stats["total"] == 3
        by_name = {p["name"]: p for p in stats["per_evaluator"]}
        assert by_name["judge-a"]["avg"] == pytest.approx(0.55)
        assert by_name["judge-a"]["count"] == 2
        assert by_name["judge-a"]["min"] == 0.1
        assert by_name["judge-a"]["max"] == 1.0
        # 1.0 -> bucket 4 (clamped), 0.5 -> 2, 0.1 -> 0, 0.2 -> 1, 0.9 -> 4
        h = {b["name"]: b["count"] for b in stats["histogram"]}
        assert h == {"0.0-0.2": 1, "0.2-0.4": 1, "0.4-0.6": 1, "0.6-0.8": 0, "0.8-1.0": 2}

    def test_non_finite_skipped(self, service_module):
        scores = [{"pass_status": "pass", "score": {"judge-a": float("inf")}}]
        service_module.get_evaluation_case_scores = MagicMock(return_value=scores)
        stats = service_module.get_evaluation_stats_impl(1, "t1")
        assert stats["per_evaluator"] == []
        assert stats["histogram"][4]["count"] == 0


# ---------------------------------------------------------------------------
# ``delete_agent_evaluation_run_impl`` — no_set_mode virtual-set cleanup.
# ---------------------------------------------------------------------------


class TestDeleteRunNoSetBranch:
    def test_no_set_mode_deletes_virtual_set(self, service_module):
        service_module.hard_delete_agent_evaluation.reset_mock()
        service_module.get_agent_evaluation.return_value = {
            "agent_evaluation_id": 1,
            "created_by": "u1",
            "evaluator_config": {"no_set_mode": True},
            "evaluation_set_id": 7,
        }
        service_module.delete_agent_evaluation_run_impl(1, "t1", "u1")
        from database import evaluation_set_db
        evaluation_set_db.hard_delete_evaluation_set.assert_called_once_with(7, "t1")
        service_module.hard_delete_agent_evaluation.assert_called_once_with(
            agent_evaluation_id=1, tenant_id="t1"
        )
        evaluation_set_db.hard_delete_evaluation_set.reset_mock()

    def test_no_set_cleanup_failure_logs_and_continues(self, service_module):
        service_module.hard_delete_agent_evaluation.reset_mock()
        service_module.get_agent_evaluation.return_value = {
            "agent_evaluation_id": 1,
            "created_by": "u1",
            "evaluator_config": {"no_set_mode": True},
            "evaluation_set_id": 7,
        }
        from database import evaluation_set_db
        evaluation_set_db.hard_delete_evaluation_set.side_effect = RuntimeError("boom")
        service_module.delete_agent_evaluation_run_impl(1, "t1", "u1")
        service_module.hard_delete_agent_evaluation.assert_called_once_with(
            agent_evaluation_id=1, tenant_id="t1"
        )
        evaluation_set_db.hard_delete_evaluation_set.side_effect = None


# ---------------------------------------------------------------------------
# ``trial_run_evaluator_impl`` — async trial run for a single query.
# ---------------------------------------------------------------------------


class TestTrialRunEvaluatorImpl:
    def test_success(self, service_module):
        import asyncio
        service_module.get_evaluator = MagicMock(
            side_effect=[
                {"status": "PUBLISHED", "name": "a"},
                {"status": "DRAFT", "name": "b"},
            ]
        )
        service_module.get_prompt_template = MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        service_module.JiuwenSDKAdapter = MagicMock()

        async def _fake_eval(**kwargs):
            return "ans", [], {"judge-a": 0.9}, {"judge-a": "ok"}

        service_module._evaluate_query = _fake_eval
        result = asyncio.run(
            service_module.trial_run_evaluator_impl("t1", "u1", 1, 2, "query", 99, [1, 2])
        )
        assert result == {
            "query": "query",
            "answer": "ans",
            "scores": {"judge-a": 0.9},
            "reasons": {"judge-a": "ok"},
        }

    def test_sdk_unavailable_raises(self, service_module):
        import asyncio
        service_module.get_prompt_template = MagicMock(return_value={"SYSTEM_PROMPT": "sp"})
        service_module.JiuwenSDKAdapter = None
        with pytest.raises(service_module.JiuwenSDKUnavailableError):
            asyncio.run(
                service_module.trial_run_evaluator_impl("t1", "u1", 1, 2, "q", 99)
            )
