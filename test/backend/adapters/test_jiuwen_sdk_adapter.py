"""Unit tests for ``backend.adapters.jiuwen_sdk_adapter``.

The adapter module has heavy module-level side effects (installing a
``sys.meta_path`` finder, stubbing missing optional dependencies, then doing
``from openjiuwen.dev_tools.tune.base import Case, EvaluatedCase``).  We
pre-stub the ``openjiuwen`` package tree so the module body executes
successfully even when the real SDK is missing; the actual SDK surface used
at runtime is mocked per test through ``mocker``.
"""

import asyncio
import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# openjiuwen stub tree — must exist before the adapter module body runs.
# The module imports ``from openjiuwen.dev_tools.tune.base import Case,
# EvaluatedCase`` at module load, so we register a real package with a fake
# ``__path__`` and a populated ``base`` submodule.  The fake path is not on
# disk: it only needs to satisfy attribute lookups inside the module.
# ---------------------------------------------------------------------------
_FAKE_OJ_ROOT = os.path.join(str(_BACKEND_DIR), "_fake_openjiuwen_root")


def _ensure_openjiuwen_stub(force: bool = False):
    """Install a structurally-valid ``openjiuwen`` stub into ``sys.modules``.

    The adapter's top-level import is ``from openjiuwen.dev_tools.tune.base
    import Case as _Case, EvaluatedCase as _EvaluatedCase``.  We register
    each level of that path as a real package whose ``__path__`` points at
    a non-existent directory — the directory never needs to exist because we
    only ever resolve ``base`` by name, not by file lookup.  Additional
    submodules the adapter references at runtime (LLM helpers, metrics, etc.)
    are registered lazily by tests.

    ``force=True`` rebuilds the stub tree even if it already exists, which
    the fixture uses to undo monkey-patches installed by individual tests.
    """
    if not force:
        existing = sys.modules.get("openjiuwen")
        if existing is not None and getattr(existing, "__path__", None):
            return

    oj = types.ModuleType("openjiuwen")
    oj.__path__ = [_FAKE_OJ_ROOT]
    sys.modules["openjiuwen"] = oj

    for pkg in (
        "openjiuwen.core",
        "openjiuwen.core.foundation",
        "openjiuwen.core.foundation.llm",
        "openjiuwen.core.foundation.llm.schema",
        "openjiuwen.core.foundation.llm.model_clients",
        "openjiuwen.dev_tools",
        "openjiuwen.dev_tools.tune",
        "openjiuwen.dev_tools.prompt_builder",
        "openjiuwen.dev_tools.prompt_builder.builder",
        "openjiuwen.agent_evolving",
        "openjiuwen.agent_evolving.evaluator",
        "openjiuwen.agent_evolving.evaluator.metrics",
        "openjiuwen.agent_evolving.utils",
    ):
        mod = types.ModuleType(pkg)
        mod.__path__ = [_FAKE_OJ_ROOT]
        sys.modules[pkg] = mod
        # Mirror onto the parent so ``openjiuwen.core.foundation`` attribute
        # lookups (the bypasser's ``__getattr__`` path) succeed.
        parent_name, _, child = pkg.rpartition(".")
        parent = sys.modules[parent_name]
        setattr(parent, child, mod)

    base = types.ModuleType("openjiuwen.dev_tools.tune.base")

    class _StubCase:
        def __init__(self, inputs=None, label=None):
            self.inputs = inputs
            self.label = label

    class _StubEvaluatedCase:
        def __init__(self, case=None, answer=None, score=0.0, reason=""):
            self.case = case
            self.answer = answer
            self.score = score
            self.reason = reason

    base.Case = _StubCase
    base.EvaluatedCase = _StubEvaluatedCase
    sys.modules["openjiuwen.dev_tools.tune.base"] = base
    sys.modules["openjiuwen.dev_tools.tune"].base = base


_ensure_openjiuwen_stub()


# ---------------------------------------------------------------------------
# Adapter import.  Force a fresh load so the module's module-level side
# effects run against our stubs.  Reload via importlib so the test can run
# multiple times inside the same pytest session without leaking state.
# ---------------------------------------------------------------------------
@pytest.fixture
def adapter_module(monkeypatch):
    """Import ``adapters.jiuwen_sdk_adapter`` fresh for each test.

    The module installs a meta-path finder and writes module-level stubs on
    first import.  Reloading between tests ensures we exercise the import-
    time code paths (which is exactly what Codecov should cover) and isolates
    patches per test.  The fixture also restores the openjiuwen stub tree
    after the test so deletions done by ``TestJiuwenSDKAdapterEnsure`` /
    ``TestLazyImportJiuwen`` don't leak into siblings.
    """
    # Snapshot of the stub-tree entries we manage.  We re-register them
    # before every test, even if the test deleted them.
    _ensure_openjiuwen_stub()

    sys.modules.pop("adapters.jiuwen_sdk_adapter", None)
    import adapters.jiuwen_sdk_adapter as mod  # noqa: E402,WPS433

    yield mod

    sys.modules.pop("adapters.jiuwen_sdk_adapter", None)
    # Restore the openjiuwen stub tree so a previous test that monkey-
    # patched ``__import__`` to raise ImportError does not leave the package
    # missing for the next test.
    _ensure_openjiuwen_stub(force=True)


# ===========================================================================
# 1. Module-level / import-time behaviour
# ===========================================================================


class TestModuleImport:
    """Verify the module's top-level side effects landed correctly."""

    def test_bypasser_installed_flag_is_true(self, adapter_module):
        # The module marks the bypasser as installed at import time.
        assert adapter_module._bypasser_installed is True

    def test_install_jiuwen_bypasser_is_now_a_noop(self, adapter_module):
        # After the import-time install, calling the helper is a no-op that
        # returns True.  This guards the backwards-compat shim.
        assert adapter_module._install_jiuwen_bypasser() is True

    def test_circular_chain_contains_known_packages(self, adapter_module):
        # Spot-check the chain list — these are the packages whose
        # ``__init__.py`` the bypasser blocks to break the import cycle.
        assert "openjiuwen.core" in adapter_module._CIRCULAR_CHAIN
        assert "openjiuwen.dev_tools.tune" in adapter_module._CIRCULAR_CHAIN
        assert (
            "openjiuwen.agent_evolving.trainer.trainer"
            in adapter_module._CIRCULAR_CHAIN
        )

    def test_meta_path_finder_is_registered(self, adapter_module):
        # The bypasser must be the first finder so it wins the race.
        assert any(
            isinstance(f, adapter_module._JiuwenInitBypasser)
            for f in sys.meta_path
        )

    def test_case_and_evaluated_case_aliases_loaded(self, adapter_module):
        # The module re-exports Case / EvaluatedCase under a private name so
        # the rest of the file can use them without paying the import cost.
        assert adapter_module._Case is sys.modules["openjiuwen.dev_tools.tune.base"].Case
        assert (
            adapter_module._EvaluatedCase
            is sys.modules["openjiuwen.dev_tools.tune.base"].EvaluatedCase
        )

    def test_optional_dep_stubs_are_idempotent(self, adapter_module):
        # pymilvus / dashscope / pdfplumber get stubbed if missing; on
        # subsequent imports the helper should leave them alone.  We can't
        # easily assert "no overwrite" without leaking state, but we can at
        # least check they remain in sys.modules.
        for name in ("pymilvus", "dashscope", "pdfplumber"):
            assert name in sys.modules


# ===========================================================================
# 2. Meta-path finder
# ===========================================================================


class TestJiuwenInitBypasser:
    """Cover ``_JiuwenInitBypasser.find_spec`` and the loader hooks."""

    def _setup_fake_pkg(self, tmp_path, subpkg_name):
        """Create ``tmp_path/openjiuwen/<subpkg_name>/__init__.py`` and wire it up.

        The bypasser reads ``openjiuwen.__path__[0]`` and joins each part of
        the dotted name onto it, so we need the on-disk layout to match the
        dotted name: ``<root>/<part1>/<part2>/...``.  We then repoint the
        stubbed ``openjiuwen`` package at that root.
        """
        pkg_root = tmp_path / "openjiuwen"
        pkg = pkg_root / subpkg_name
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("# blocked init")
        sys.modules["openjiuwen"].__path__ = [str(pkg_root)]
        return pkg_root, pkg

    def test_find_spec_returns_none_for_non_openjiuwen_name(self, tmp_path, adapter_module):
        sys.modules["openjiuwen"].__path__ = [str(tmp_path / "openjiuwen")]
        finder = adapter_module._JiuwenInitBypasser()
        assert finder.find_spec("some.other.module", None) is None
        # ``openjiuwen`` itself (without a child) is not a candidate either.
        assert finder.find_spec("openjiuwen", None) is None

    def test_find_spec_returns_none_when_package_dir_missing(self, tmp_path, adapter_module):
        sys.modules["openjiuwen"].__path__ = [str(tmp_path / "openjiuwen")]
        finder = adapter_module._JiuwenInitBypasser()
        # The package directory does not exist on disk.
        assert finder.find_spec("openjiuwen.does_not_exist", None) is None

    def test_find_spec_returns_none_when_init_missing(self, tmp_path, adapter_module):
        sys.modules["openjiuwen"].__path__ = [str(tmp_path / "openjiuwen")]
        finder = adapter_module._JiuwenInitBypasser()
        pkg = tmp_path / "openjiuwen" / "no_init"
        pkg.mkdir(parents=True)
        # No ``__init__.py`` — the bypasser ignores it.
        assert finder.find_spec("openjiuwen.no_init", None) is None

    def test_find_spec_returns_none_when_package_not_in_chain(self, tmp_path, adapter_module):
        sys.modules["openjiuwen"].__path__ = [str(tmp_path / "openjiuwen")]
        finder = adapter_module._JiuwenInitBypasser()
        pkg = tmp_path / "openjiuwen" / "unrelated"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        # Not in ``_CIRCULAR_CHAIN`` so the bypasser should let the regular
        # finder handle it.
        assert finder.find_spec("openjiuwen.unrelated", None) is None

    def test_find_spec_returns_spec_for_circular_package(self, tmp_path, adapter_module):
        _, pkg = self._setup_fake_pkg(tmp_path, "core")
        finder = adapter_module._JiuwenInitBypasser()
        spec = finder.find_spec("openjiuwen.core", None)
        assert spec is not None
        assert spec.origin == "<init bypassed>"
        assert spec.submodule_search_locations == [str(pkg)]

    def test_create_and_exec_module_set_path(self, tmp_path, adapter_module):
        _, pkg = self._setup_fake_pkg(tmp_path, "core")
        finder = adapter_module._JiuwenInitBypasser()

        module = types.ModuleType("openjiuwen.core")
        # ``create_module`` returns ``None`` per the importlib contract,
        # meaning the loader is opting out of the default behaviour that
        # would have set ``__file__`` on the new module.  The contract is
        # therefore: no ``__file__`` set by the finder.
        module.__file__ = "sentinel-from-default-loader"
        finder.create_module(module)
        assert module.__file__ == "sentinel-from-default-loader"

        finder.exec_module(module)
        assert module.__path__ == [str(pkg)]
        assert module.__file__ == str(pkg / "__init__.py")

    def test_getattr_blocks_internal_attribute_recursion(self, tmp_path, adapter_module):
        sys.modules["openjiuwen"].__path__ = [str(tmp_path / "openjiuwen")]
        finder = adapter_module._JiuwenInitBypasser()
        # ``__path__`` etc. must raise AttributeError to break the recursive
        # attribute lookup that Python's import machinery does on finders.
        for name in (
            "find_distributions",
            "find_module",
            "__path__",
            "__name__",
            "__file__",
            "__loader__",
            "__package__",
            "__spec__",
        ):
            with pytest.raises(AttributeError):
                finder.__getattr__(name)

    def test_getattr_raises_for_unknown_attribute(self, tmp_path, adapter_module):
        sys.modules["openjiuwen"].__path__ = [str(tmp_path / "openjiuwen")]
        finder = adapter_module._JiuwenInitBypasser()
        with pytest.raises(AttributeError):
            finder.__getattr__("definitely_not_a_module")


# ===========================================================================
# 3. Pure helper functions
# ===========================================================================


class TestNormalizeLanguage:
    def test_known_languages_map_to_canonical(self, adapter_module):
        assert adapter_module.normalize_language("zh") == "zh-CN"
        assert adapter_module.normalize_language("en") == "en-US"

    def test_unknown_language_falls_back_to_chinese(self, adapter_module):
        # Anything we don't recognise is treated as Chinese, which is the
        # module's documented default.
        assert adapter_module.normalize_language("ja") == "zh-CN"
        assert adapter_module.normalize_language("") == "zh-CN"


class TestUnwrapPromptResponse:
    def test_plain_text_is_returned_verbatim(self, adapter_module):
        assert adapter_module._unwrap_prompt_response("hello world") == "hello world"

    def test_json_wrapper_with_prompt_key(self, adapter_module):
        text = '{"prompt": "  improved prompt  "}'
        assert adapter_module._unwrap_prompt_response(text) == "improved prompt"

    def test_json_wrapper_with_result_key(self, adapter_module):
        text = '{"result": "  rewritten  "}'
        assert adapter_module._unwrap_prompt_response(text) == "rewritten"

    def test_invalid_json_returns_stripped_text(self, adapter_module):
        text = "  not json at all  "
        assert adapter_module._unwrap_prompt_response(text) == "not json at all"

    def test_markdown_fence_with_json_lang_is_stripped(self, adapter_module):
        text = "```json\n{\"prompt\": \"cleaned\"}\n```"
        assert adapter_module._unwrap_prompt_response(text) == "cleaned"

    def test_markdown_fence_with_no_lang_is_stripped(self, adapter_module):
        text = "```\n{\"prompt\": \"cleaned\"}\n```"
        assert adapter_module._unwrap_prompt_response(text) == "cleaned"

    def test_markdown_fence_without_trailing_newline(self, adapter_module):
        # Some model outputs close the fence with `` ``` `` (no preceding
        # newline).  The stripper should still find the ``prompt`` payload.
        text = "```json\n{\"prompt\": \"cleaned\"}```"
        assert adapter_module._unwrap_prompt_response(text) == "cleaned"

    def test_json_with_unrelated_keys_falls_through_to_text(self, adapter_module):
        # No ``prompt`` and no ``result`` — return the parsed raw value.
        text = '{"other_key": 1}'
        assert adapter_module._unwrap_prompt_response(text) == '{"other_key": 1}'


class TestExtractScoreReason:
    def test_normal_payload(self, adapter_module):
        evaluated = MagicMock(score=1, reason="good")
        score, reason = adapter_module._extract_score_reason(evaluated)
        assert score == 1.0
        assert reason == "good"

    def test_none_score_falls_back_to_zero(self, adapter_module):
        # ``or 0.0`` is the spec; ``0.0 or 0.0`` evaluates to 0.0.
        evaluated = MagicMock(score=None, reason=None)
        score, reason = adapter_module._extract_score_reason(evaluated)
        assert score == 0.0
        assert reason == ""

    def test_invalid_score_string_falls_back_to_zero(self, adapter_module):
        evaluated = MagicMock(score="not-a-number", reason="x")
        score, reason = adapter_module._extract_score_reason(evaluated)
        assert score == 0.0
        assert reason == "x"

    def test_missing_reason_falls_back_to_empty(self, adapter_module):
        # ``getattr(... "reason", "") or ""`` collapses None to "".
        evaluated = MagicMock(spec=["score"])
        evaluated.score = 1
        score, reason = adapter_module._extract_score_reason(evaluated)
        assert score == 1.0
        assert reason == ""


# ===========================================================================
# 4. run_async — event-loop handling for sync callers
# ===========================================================================


class TestRunAsync:
    def test_no_running_loop_uses_asyncio_run(self, adapter_module, monkeypatch):
        # ``asyncio.get_running_loop`` raises ``RuntimeError`` when there is
        # no loop, so ``run_async`` falls through to ``asyncio.run``.
        async def coro():
            return "done"

        captured = {}

        def fake_run(c):
            captured["called_with"] = c
            return "ran"

        monkeypatch.setattr(adapter_module.asyncio, "run", fake_run)
        result = adapter_module.run_async(coro())
        assert result == "ran"
        assert captured["called_with"] is not None


# ===========================================================================
# 5. build_jiuwen_model_configs — DB lookup + SSL/timeout fallback
# ===========================================================================


class TestBuildJiuwenModelConfigs:
    @pytest.fixture
    def fake_jiuwen_module(self, adapter_module, monkeypatch):
        """Replace ``_lazy_import_jiuwen`` with a stub that returns real classes.

        The helper is exercised via ``build_jiuwen_model_configs``, so we do
        not need a real openjiuwen schema implementation — just attribute
        access on the returned objects.  We use real classes with
        ``__init__`` so keyword arguments land on the instance and the test
        can assert on them.
        """
        class ModelRequestConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class ModelClientConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class ProviderType:
            OpenAI = "openai"

        def _lazy():
            return (
                ModelRequestConfig,
                ModelClientConfig,
                ProviderType,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )

        monkeypatch.setattr(adapter_module, "_lazy_import_jiuwen", _lazy)
        return ModelRequestConfig, ModelClientConfig

    def test_missing_model_raises_jiuwen_error(self, adapter_module, fake_jiuwen_module):
        from adapters.exception import JiuwenSDKError

        # Give the ``database`` stub a ``__path__`` so that subsequent
        # ``from X import Y`` inside the stub's ``__init__`` resolves through
        # ``sys.modules`` rather than falling back to the filesystem and
        # pulling in the real module tree (which depends on boto3, etc.).
        _db_pkg = sys.modules.get("database")
        if _db_pkg is None:
            _db_pkg = types.ModuleType("database")
            sys.modules["database"] = _db_pkg
        _db_pkg.__path__ = [str(_BACKEND_DIR / "database")]

        stub = types.ModuleType("database.model_management_db")
        stub.__path__ = [str(_BACKEND_DIR / "database")]
        sys.modules["database.model_management_db"] = stub
        stub.get_model_by_model_id = lambda *a, **kw: None

        # ``from utils.config_utils import get_model_name_from_config`` is
        # imported inside ``build_jiuwen_model_configs``.  Pre-register it so
        # the real module (and its database chain) is never touched.
        utils_stub = types.ModuleType("utils.config_utils")
        utils_stub.get_model_name_from_config = lambda cfg: "m"
        sys.modules["utils.config_utils"] = utils_stub

        with pytest.raises(JiuwenSDKError, match="not found"):
            adapter_module.build_jiuwen_model_configs(1, "t1")

    def test_default_api_base_and_timeout_when_missing(self, adapter_module, fake_jiuwen_module):
        sys.modules.setdefault(
            "database.model_management_db",
            types.ModuleType("database.model_management_db"),
        )
        sys.modules["database.model_management_db"].get_model_by_model_id = lambda *a, **kw: {
            "api_key": "k",
            "base_url": "  ",  # blank -> default
            "model_name": "m",
            "model_type": "chat",
            # no timeout_seconds -> default
            "ssl_verify": True,
            # No ssl_cert -> the adapter forces verify_ssl off because it
            # has nothing to verify against.
        }
        sys.modules.setdefault(
            "utils.config_utils",
            types.ModuleType("utils.config_utils"),
        )
        sys.modules["utils.config_utils"].get_model_name_from_config = lambda cfg: "m"

        request, client = adapter_module.build_jiuwen_model_configs(1, "t1")
        # Default OpenAI base URL when base_url is blank.
        assert client.api_base == "https://api.openai.com/v1"
        # Default 120s timeout when not configured.
        assert client.timeout == 120.0
        # No cert means we cannot verify, so the adapter disables verification
        # even when the user asked for it.
        assert client.verify_ssl is False

    def test_ssl_verify_disabled_when_cert_missing(self, adapter_module, fake_jiuwen_module):
        sys.modules.setdefault(
            "database.model_management_db",
            types.ModuleType("database.model_management_db"),
        )
        sys.modules["database.model_management_db"].get_model_by_model_id = lambda *a, **kw: {
            "api_key": "k",
            "base_url": "https://x",
            "model_name": "m",
            "model_type": "chat",
            "timeout_seconds": 30,
            "ssl_verify": True,
            "ssl_cert": None,
        }
        sys.modules.setdefault(
            "utils.config_utils",
            types.ModuleType("utils.config_utils"),
        )
        sys.modules["utils.config_utils"].get_model_name_from_config = lambda cfg: "m"

        _, client = adapter_module.build_jiuwen_model_configs(1, "t1")
        # No cert -> verify_ssl gets turned off, even though the user asked
        # for verification.
        assert client.verify_ssl is False

    def test_custom_timeout_and_ssl_cert_propagate(self, adapter_module, fake_jiuwen_module):
        sys.modules.setdefault(
            "database.model_management_db",
            types.ModuleType("database.model_management_db"),
        )
        sys.modules["database.model_management_db"].get_model_by_model_id = lambda *a, **kw: {
            "api_key": "k",
            "base_url": "https://x",
            "model_name": "m",
            "model_type": "chat",
            "timeout_seconds": 15,
            "ssl_verify": True,
            "ssl_cert": "/etc/ssl/cert.pem",
        }
        sys.modules.setdefault(
            "utils.config_utils",
            types.ModuleType("utils.config_utils"),
        )
        sys.modules["utils.config_utils"].get_model_name_from_config = lambda cfg: "m"

        request, client = adapter_module.build_jiuwen_model_configs(1, "t1")
        assert client.timeout == 15.0
        assert client.ssl_cert == "/etc/ssl/cert.pem"
        assert client.verify_ssl is True


# ===========================================================================
# 6. JiuwenSDKAdapter — public methods
# ===========================================================================


class TestJiuwenSDKAdapterEnsure:
    def test_ensure_available_imports_openjiuwen(self, adapter_module, monkeypatch):
        from adapters.exception import JiuwenSDKError

        # The simplest way to simulate ``openjiuwen`` being uninstalled is
        # to delete the cached module so the ``import openjiuwen`` statement
        # inside ``_ensure_available`` re-runs and finds nothing.  We then
        # override ``__import__`` to make sure the rebuilt module entry
        # raises ImportError too.
        sys.modules.pop("openjiuwen", None)

        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "openjiuwen" or name.startswith("openjiuwen."):
                raise ImportError("simulated missing")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="Jiuwen SDK 未安装"):
            adapter._ensure_available()


class TestJiuwenSDKAdapterGenerate:
    def test_generate_raises_not_implemented(self, adapter_module):
        # ``generate`` is a stub: it should always raise ``JiuwenSDKError``
        # with a "not implemented" message.
        from adapters.exception import JiuwenSDKError

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="尚未实现"):
            adapter.generate()


class TestToJiuwenEvaluatedCase:
    def test_translates_bad_case_fields(self, adapter_module, monkeypatch):
        # Build a stand-in for the lazy import.
        Case = MagicMock()
        EvaluatedCase = MagicMock()
        monkeypatch.setattr(
            adapter_module,
            "_lazy_import_jiuwen",
            lambda: (None, None, None, None, None, Case, EvaluatedCase, None),
        )

        bad_case = MagicMock()
        bad_case.question = "Q?"
        bad_case.label = "expected"
        bad_case.answer = "actual"
        bad_case.reason = "r"

        result = adapter_module.to_jiuwen_evaluated_case(bad_case)
        # ``Case`` was constructed with the question / expected answer
        # pulled out of the nexent ``BadCase`` shape.
        Case.assert_called_once_with(
            inputs={"question": "Q?"},
            label={"answer": "expected"},
        )
        EvaluatedCase.assert_called_once_with(
            case=Case.return_value,
            answer={"content": "actual"},
            score=0.0,
            reason="r",
        )
        assert result is EvaluatedCase.return_value

    def test_label_and_reason_defaults_when_missing(self, adapter_module, monkeypatch):
        Case = MagicMock()
        EvaluatedCase = MagicMock()
        monkeypatch.setattr(
            adapter_module,
            "_lazy_import_jiuwen",
            lambda: (None, None, None, None, None, Case, EvaluatedCase, None),
        )

        bad_case = MagicMock()
        bad_case.question = "Q?"
        bad_case.label = None
        bad_case.answer = "actual"
        bad_case.reason = None

        adapter_module.to_jiuwen_evaluated_case(bad_case)
        Case.assert_called_once_with(
            inputs={"question": "Q?"},
            label={"answer": ""},
        )
        EvaluatedCase.assert_called_once_with(
            case=Case.return_value,
            answer={"content": "actual"},
            score=0.0,
            reason="",
        )


class TestCaseFromInputsLabel:
    def test_passes_through_inputs_and_label(self, adapter_module):
        case = adapter_module._case_from_inputs_label(
            {"question": "q"}, {"answer": "a"},
        )
        assert case.inputs == {"question": "q"}
        assert case.label == {"answer": "a"}


# ===========================================================================
# 7. evaluate_semantic_consistency — covers the LLM-as-judge happy paths
#    and a handful of error / edge cases without going near the real SDK.
# ===========================================================================


def _build_metric_mock(
    adapter_module,
    *,
    invoke_response_content,
    judge_payload,
    template_format_result=None,
):
    """Build a mocked LLM-as-judge metric that returns the given JSON.

    The adapter calls ``metric._template.format({...}).to_messages()`` and
    then ``metric._model.invoke(messages)``.  We register a stub
    ``llm_as_judge`` module on the openjiuwen stub tree, monkey-patch the
    adapter's import probe, and let the caller drive the result of
    ``parse_json_from_llm_response``.
    """
    llm_as_judge_mod = types.ModuleType(
        "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
    )
    metric_holder = {}

    def _factory(*_args, **kwargs):
        m = MagicMock()
        m._template.format.return_value.to_messages.return_value = (
            template_format_result if template_format_result is not None
            else [MagicMock(role="user", content="Q")]
        )
        invoke_result = MagicMock()
        invoke_result.content = invoke_response_content
        async def _invoke(*_args, **_kwargs):
            return invoke_result

        m._model.invoke = MagicMock(side_effect=_invoke)
        metric_holder["metric"] = m
        return m

    llm_as_judge_mod.LLMAsJudgeMetric = _factory
    sys.modules[
        "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
    ] = llm_as_judge_mod
    sys.modules[
        "openjiuwen.agent_evolving.evaluator.metrics"
    ].llm_as_judge = llm_as_judge_mod

    # ``from openjiuwen.agent_evolving.utils import TuneUtils`` is imported
    # inside the function; pre-register a stub ``utils`` module with the
    # helper.
    utils_mod = sys.modules.setdefault(
        "openjiuwen.agent_evolving.utils",
        types.ModuleType("openjiuwen.agent_evolving.utils"),
    )

    def _parse(_response):
        return judge_payload

    utils_mod.TuneUtils = types.SimpleNamespace(parse_json_from_llm_response=_parse)
    return metric_holder.get("metric")


def _patch_build_configs(adapter_module):
    """Replace ``build_jiuwen_model_configs`` so no DB calls fire."""
    rc = MagicMock()
    cc = MagicMock()
    adapter_module.build_jiuwen_model_configs = MagicMock(return_value=(rc, cc))
    return rc, cc


class TestEvaluateSemanticConsistency:
    def test_result_true_string_returns_score_one(self, adapter_module):
        # LLM says result="true" → score 1.0.
        _patch_build_configs(adapter_module)
        _build_metric_mock(
            adapter_module,
            invoke_response_content="```json\n{\"result\": \"true\", \"reason\": \"对\"}\n```",
            judge_payload={"result": "true", "reason": "对"},
        )
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        score, reason = adapter.evaluate_semantic_consistency(
            question="q", expected_answer="a", model_answer="b",
        )
        assert score == 1.0
        assert reason == "对"

    def test_result_false_returns_score_zero_with_reason(self, adapter_module):
        _patch_build_configs(adapter_module)
        _build_metric_mock(
            adapter_module,
            invoke_response_content="raw",
            judge_payload={"result": "false", "reason": "答错了"},
        )
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        score, reason = adapter.evaluate_semantic_consistency(
            question="q", expected_answer="a", model_answer="b",
        )
        assert score == 0.0
        assert reason == "答错了"

    def test_result_missing_reason_falls_back_to_default_label(self, adapter_module):
        # No reason field -> the helper substitutes "通过" / "失败".
        _patch_build_configs(adapter_module)
        _build_metric_mock(
            adapter_module,
            invoke_response_content="raw",
            judge_payload={"result": "true"},
        )
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        score, reason = adapter.evaluate_semantic_consistency(
            question="q", expected_answer="a", model_answer="b",
        )
        assert score == 1.0
        assert reason == "通过"

        # And the failing path falls back to "失败".
        _build_metric_mock(
            adapter_module,
            invoke_response_content="raw",
            judge_payload={"result": "false"},
        )
        score, reason = adapter.evaluate_semantic_consistency(
            question="q", expected_answer="a", model_answer="b",
        )
        assert score == 0.0
        assert reason == "失败"

    def test_non_dict_payload_raises(self, adapter_module):
        from adapters.exception import JiuwenSDKError

        _patch_build_configs(adapter_module)
        _build_metric_mock(
            adapter_module,
            invoke_response_content="raw",
            judge_payload=["not", "a", "dict"],
        )
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="not a JSON object"):
            adapter.evaluate_semantic_consistency(
                question="q", expected_answer="a", model_answer="b",
            )

    def test_dict_reason_is_unwrapped(self, adapter_module):
        # The SDK sometimes returns ``reason`` as a dict; we want the inner
        # ``reason`` field, otherwise fall back to empty.
        _patch_build_configs(adapter_module)
        _build_metric_mock(
            adapter_module,
            invoke_response_content="raw",
            judge_payload={"result": "false", "reason": {"reason": "嵌套"}},
        )
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        _, reason = adapter.evaluate_semantic_consistency(
            question="q", expected_answer="a", model_answer="b",
        )
        assert reason == "嵌套"


# ===========================================================================
# 8. optimize / optimize_badcase — exercise the prompt-builder happy path
#    and the failure translation.
# ===========================================================================


def _patch_ensure_available(adapter_module):
    """Skip the openjiuwen import probe inside ``_ensure_available``."""
    adapter_module._ensure_available = lambda self: None


def _patch_lazy_builders(adapter_module, FeedbackPromptBuilder, BadCasePromptBuilder):
    def _lazy():
        return FeedbackPromptBuilder, BadCasePromptBuilder
    adapter_module._lazy_import_jiuwen_builders = _lazy


class TestOptimize:
    def test_returns_unwrapped_prompt_on_success(self, adapter_module):
        # ``run_async`` is also patched so the test stays synchronous.
        _patch_ensure_available(adapter_module)
        FeedbackPromptBuilder = MagicMock()
        _patch_lazy_builders(adapter_module, FeedbackPromptBuilder, MagicMock())
        _patch_build_configs(adapter_module)
        adapter_module.run_async = MagicMock(return_value='{"prompt": "new prompt"}')

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        result = adapter.optimize(prompt="p", feedback="f", language="zh")
        assert result == "new prompt"

    def test_none_result_raises(self, adapter_module):
        from adapters.exception import JiuwenSDKError

        _patch_ensure_available(adapter_module)
        _patch_lazy_builders(adapter_module, MagicMock(), MagicMock())
        _patch_build_configs(adapter_module)
        adapter_module.run_async = MagicMock(return_value=None)

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="返回为空"):
            adapter.optimize(prompt="p", feedback="f")

    def test_exception_is_wrapped_as_jiuwen_sdk_error(self, adapter_module):
        from adapters.exception import JiuwenSDKError

        _patch_ensure_available(adapter_module)
        _patch_lazy_builders(adapter_module, MagicMock(), MagicMock())
        _patch_build_configs(adapter_module)
        adapter_module.run_async = MagicMock(side_effect=RuntimeError("boom"))

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="优化调用失败"):
            adapter.optimize(prompt="p", feedback="f")


class TestOptimizeBadcase:
    def test_returns_unwrapped_prompt_on_success(self, adapter_module):
        _patch_ensure_available(adapter_module)
        BadCasePromptBuilder = MagicMock()
        _patch_lazy_builders(adapter_module, MagicMock(), BadCasePromptBuilder)
        _patch_build_configs(adapter_module)
        adapter_module.to_jiuwen_evaluated_case = MagicMock(
            side_effect=lambda bc: f"case({bc.question})",
        )
        adapter_module.run_async = MagicMock(return_value='{"result": "ok"}')

        bad_case = MagicMock(question="q1", label="l1", answer="a1", reason="r1")
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        result = adapter.optimize_badcase(prompt="p", bad_cases=[bad_case])
        assert result == "ok"
        # The builder received our translated case object, not the raw one.
        BadCasePromptBuilder.assert_called_once()
        kwargs = BadCasePromptBuilder.return_value.build.call_args.kwargs
        assert kwargs["prompt"] == "p"
        assert kwargs["cases"] == ["case(q1)"]
        assert kwargs["language"] == "zh-CN"

    def test_none_result_raises(self, adapter_module):
        from adapters.exception import JiuwenSDKError

        _patch_ensure_available(adapter_module)
        _patch_lazy_builders(adapter_module, MagicMock(), MagicMock())
        _patch_build_configs(adapter_module)
        adapter_module.to_jiuwen_evaluated_case = MagicMock(return_value="c")
        adapter_module.run_async = MagicMock(return_value=None)

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="返回为空"):
            adapter.optimize_badcase(prompt="p", bad_cases=[MagicMock()])

    def test_exception_is_wrapped_as_jiuwen_sdk_error(self, adapter_module):
        from adapters.exception import JiuwenSDKError

        _patch_ensure_available(adapter_module)
        _patch_lazy_builders(adapter_module, MagicMock(), MagicMock())
        _patch_build_configs(adapter_module)
        adapter_module.to_jiuwen_evaluated_case = MagicMock(return_value="c")
        adapter_module.run_async = MagicMock(side_effect=RuntimeError("boom"))

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="BadCasePromptBuilder 调用失败"):
            adapter.optimize_badcase(prompt="p", bad_cases=[MagicMock()])


# ===========================================================================
# 9. Lazy import helper
# ===========================================================================


class TestLazyImportJiuwen:
    def test_missing_openjiuwen_raises_jiuwen_error(self, adapter_module, monkeypatch):
        from adapters.exception import JiuwenSDKError

        # Force the import statement inside ``_lazy_import_jiuwen`` to raise
        # by overriding ``__import__`` for the duration of the call.  We
        # allow everything else through so unrelated side effects still
        # resolve.
        sys.modules.pop("openjiuwen", None)
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "openjiuwen" or name.startswith("openjiuwen."):
                raise ImportError("simulated missing")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(JiuwenSDKError, match="Jiuwen SDK 未安装"):
            adapter_module._lazy_import_jiuwen()
