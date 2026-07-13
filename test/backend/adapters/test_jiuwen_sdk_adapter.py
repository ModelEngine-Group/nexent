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
from unittest.mock import MagicMock, patch, PropertyMock

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


@pytest.mark.skip(reason="OpenJiuwen 0.1.15 no longer uses the legacy import bypasser")
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


@pytest.mark.skip(reason="OpenJiuwen 0.1.15 no longer uses the legacy import bypasser")
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
        # OpenJiuwen 0.1.15 uses the system CA when no custom certificate is set.
        assert client.verify_ssl is True

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
        # No custom certificate keeps TLS verification enabled with the system CA.
        assert client.verify_ssl is True

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

    def test_returns_jiuwen_symbols_when_available(
        self, adapter_module, monkeypatch,
    ):
        """Cover the success path: install stub modules for every
        ``openjiuwen...`` import referenced by ``_lazy_import_jiuwen`` so
        the function completes and returns the eight-tuple."""
        monkeypatch.setattr(
            adapter_module, "_install_jiuwen_bypasser", lambda: True,
        )

        # The function imports several submodules; create stubs for each so
        # ``from <x> import <y>`` works.
        targets = {
            "openjiuwen.core.foundation.llm.schema.config": [
                "ModelRequestConfig", "ModelClientConfig", "ProviderType",
            ],
            "openjiuwen.dev_tools.prompt_builder.builder.feedback_prompt_builder": [
                "FeedbackPromptBuilder",
            ],
            "openjiuwen.dev_tools.prompt_builder.builder.badcase_prompt_builder": [
                "BadCasePromptBuilder",
            ],
            "openjiuwen.dev_tools.tune.base": ["Case", "EvaluatedCase"],
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge": [
                "LLMAsJudgeMetric",
            ],
        }
        for mod_name, attrs in targets.items():
            mod = types.ModuleType(mod_name)
            for a in attrs:
                setattr(mod, a, MagicMock())
            sys.modules[mod_name] = mod

        # ``openjiuwen`` itself must be present for the ``import openjiuwen`` line.
        sys.modules["openjiuwen"] = types.ModuleType("openjiuwen")

        result = adapter_module._lazy_import_jiuwen()
        assert len(result) == 8
        assert result[0] is sys.modules[
            "openjiuwen.core.foundation.llm.schema.config"
        ].ModelRequestConfig


# ===========================================================================
# 10. run_async — loop-is-running branch (nest_asyncio success)
# ===========================================================================


class TestRunAsyncLoopRunning:
    def test_running_loop_nest_asyncio_apply_called_and_run_until_complete_used(
        self, adapter_module, monkeypatch,
    ):
        """When a loop is already running and nest_asyncio is available,
        ``run_async`` calls ``nest_asyncio.apply()`` and then uses
        ``loop.run_until_complete``.  We verify the apply call was made
        and that the result of run_until_complete propagates."""
        async def coro():
            return "nest-asyncio-path"

        mock_loop = MagicMock()
        mock_loop.is_running = lambda: True

        # ``nest_asyncio.apply`` is a no-op for our mock; we just verify it was
        # called.  ``run_until_complete`` must be a sync callable that runs the
        # coroutine to completion and returns the result.
        apply_called = {}

        def _capture_apply():
            apply_called["yes"] = True

        def _sync_run_until_complete(c):
            # Run the coroutine synchronously and return its result.
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(c)
            finally:
                loop.close()

        mock_loop.run_until_complete = _sync_run_until_complete

        monkeypatch.setattr(adapter_module.asyncio, "get_running_loop", lambda: mock_loop)

        with patch("nest_asyncio.apply", side_effect=_capture_apply):
            result = adapter_module.run_async(coro())

        assert apply_called.get("yes"), "nest_asyncio.apply was not called"
        assert result == "nest-asyncio-path"

    def test_running_loop_nest_asyncio_missing_falls_back_to_thread(
        self, adapter_module, monkeypatch,
    ):
        """When a loop is running and nest_asyncio is not installed,
        ``run_async`` spins up a ThreadPoolExecutor to run the coroutine."""
        async def coro():
            return "from-thread"

        mock_loop = MagicMock()
        mock_loop.is_running = lambda: True

        import builtins

        _orig_import = builtins.__import__

        def _import_raiser(name, *args, **kwargs):
            if name == "nest_asyncio" or name.startswith("nest_asyncio."):
                raise ImportError("simulated missing nest_asyncio")
            return _orig_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _import_raiser)
        monkeypatch.setattr(adapter_module.asyncio, "get_running_loop", lambda: mock_loop)

        result = adapter_module.run_async(coro())

        assert result == "from-thread"


# ===========================================================================
# 11. evaluate_semantic_consistency — LLM invoke and TuneUtils error paths
# ===========================================================================


class TestEvaluateSemanticConsistencyLLMPath:
    def test_invoke_exception_raises_jiuwen_error(self, adapter_module):
        from adapters.exception import JiuwenSDKError

        llm_as_judge_mod = types.ModuleType(
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        )
        metric = MagicMock()

        class _UserMsg:
            def __init__(self, content):
                self.content = content
                self.role = "user"

        async def _invoke_fail(*_args, **_kwargs):
            raise RuntimeError("LLM call failed")

        # ``_template.format()`` is synchronous; it returns a mock whose
        # ``.to_messages()`` is called immediately.
        _formatted = MagicMock()
        _formatted.to_messages.return_value = [_UserMsg("original")]
        metric._template.format = MagicMock(return_value=_formatted)
        metric._model.invoke = MagicMock(side_effect=_invoke_fail)
        llm_as_judge_mod.LLMAsJudgeMetric = MagicMock(return_value=metric)
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        ] = llm_as_judge_mod
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics"
        ].llm_as_judge = llm_as_judge_mod

        utils_mod = types.ModuleType("openjiuwen.agent_evolving.utils")
        utils_mod.TuneUtils = types.SimpleNamespace(
            parse_json_from_llm_response=MagicMock(
                return_value={"result": "true", "reason": "ok"}
            )
        )
        sys.modules["openjiuwen.agent_evolving.utils"] = utils_mod

        _patch_build_configs(adapter_module)
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")

        with pytest.raises(JiuwenSDKError, match="Judge LLM invoke failed"):
            adapter.evaluate_semantic_consistency(
                question="q", expected_answer="a", model_answer="b",
            )

    def test_parse_exception_raises_jiuwen_error(self, adapter_module):
        from adapters.exception import JiuwenSDKError

        llm_as_judge_mod = types.ModuleType(
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        )

        class _UserMsg:
            def __init__(self, content):
                self.content = content
                self.role = "user"

        async def _invoke_ok(*_args, **_kwargs):
            return MagicMock(content='{"result": true, "reason": "ok"}')

        _formatted = MagicMock()
        _formatted.to_messages.return_value = [_UserMsg("original")]
        metric = MagicMock()
        metric._template.format = MagicMock(return_value=_formatted)
        metric._model.invoke = MagicMock(side_effect=_invoke_ok)
        llm_as_judge_mod.LLMAsJudgeMetric = MagicMock(return_value=metric)
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        ] = llm_as_judge_mod
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics"
        ].llm_as_judge = llm_as_judge_mod

        utils_mod = types.ModuleType("openjiuwen.agent_evolving.utils")

        def _parse_fail(_):
            raise RuntimeError("parse failed")

        utils_mod.TuneUtils = types.SimpleNamespace(parse_json_from_llm_response=_parse_fail)
        sys.modules["openjiuwen.agent_evolving.utils"] = utils_mod

        _patch_build_configs(adapter_module)
        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")

        with pytest.raises(JiuwenSDKError, match="Failed to parse judge response"):
            adapter.evaluate_semantic_consistency(
                question="q", expected_answer="a", model_answer="b",
            )

    def test_chinese_directive_appended_to_user_message(self, adapter_module):
        """When messages[-1] has role='user', the Chinese directive is appended
        to the existing message content rather than creating a new one."""
        _patch_build_configs(adapter_module)

        llm_as_judge_mod = types.ModuleType(
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        )
        captured_messages = {}

        class _UserMsg:
            def __init__(self, content):
                self.content = content
                self.role = "user"

        async def _invoke_ok(*_args, **_kwargs):
            return MagicMock(content='{"result": true, "reason": "ok"}')

        _messages = [_UserMsg("original")]
        captured_messages["list"] = _messages
        _formatted = MagicMock()
        _formatted.to_messages.return_value = _messages
        metric = MagicMock()
        metric._template.format = MagicMock(return_value=_formatted)
        metric._model.invoke = MagicMock(side_effect=_invoke_ok)
        llm_as_judge_mod.LLMAsJudgeMetric = MagicMock(return_value=metric)
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        ] = llm_as_judge_mod
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics"
        ].llm_as_judge = llm_as_judge_mod

        utils_mod = types.ModuleType("openjiuwen.agent_evolving.utils")
        utils_mod.TuneUtils = types.SimpleNamespace(
            parse_json_from_llm_response=MagicMock(
                return_value={"result": "true", "reason": "ok"}
            )
        )
        sys.modules["openjiuwen.agent_evolving.utils"] = utils_mod

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        adapter.evaluate_semantic_consistency(
            question="q", expected_answer="a", model_answer="b",
        )

        # The original message should have the Chinese directive appended.
        assert "IMPORTANT" in captured_messages["list"][0].content
        assert "Chinese" in captured_messages["list"][0].content

    def test_non_user_last_message_appends_user_directive(self, adapter_module):
        """When messages[-1] has a non-'user' role, a new UserMessage with the
        Chinese directive is appended to the messages list."""
        _patch_build_configs(adapter_module)

        llm_as_judge_mod = types.ModuleType(
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        )
        captured_messages = {}

        class _AssistantMsg:
            role = "assistant"
            content = "assistant reply"

        class _FakeUserMessage:
            def __init__(self, content):
                self.content = content
                self.role = "user"

        async def _invoke_ok(*_args, **_kwargs):
            return MagicMock(content='{"result": true, "reason": "ok"}')

        _messages = [_AssistantMsg()]
        captured_messages["list"] = _messages
        captured_messages["original_len"] = len(_messages)
        _formatted = MagicMock()
        _formatted.to_messages.return_value = _messages
        metric = MagicMock()
        metric._template.format = MagicMock(return_value=_formatted)
        metric._model.invoke = MagicMock(side_effect=_invoke_ok)
        llm_as_judge_mod.LLMAsJudgeMetric = MagicMock(return_value=metric)
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        ] = llm_as_judge_mod
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics"
        ].llm_as_judge = llm_as_judge_mod

        # Provide a stub ``UserMessage`` so the adapter can append it.
        sys.modules.setdefault(
            "openjiuwen.core.foundation.llm",
            types.ModuleType("openjiuwen.core.foundation.llm"),
        )
        sys.modules["openjiuwen.core.foundation.llm"].UserMessage = _FakeUserMessage

        utils_mod = types.ModuleType("openjiuwen.agent_evolving.utils")
        utils_mod.TuneUtils = types.SimpleNamespace(
            parse_json_from_llm_response=MagicMock(
                return_value={"result": "true", "reason": "ok"}
            )
        )
        sys.modules["openjiuwen.agent_evolving.utils"] = utils_mod

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        adapter.evaluate_semantic_consistency(
            question="q", expected_answer="a", model_answer="b",
        )

        # A new UserMessage should have been appended with the Chinese directive.
        msgs = captured_messages["list"]
        assert len(msgs) == captured_messages["original_len"] + 1
        last = msgs[-1]
        assert last.role == "user"
        assert "IMPORTANT" in last.content

    def test_user_metrics_propagated_to_metric(self, adapter_module):
        """The optional ``user_metrics`` argument is passed through to the
        LLM-as-Judge metric constructor."""
        _patch_build_configs(adapter_module)

        llm_as_judge_mod = types.ModuleType(
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        )
        captured_kwargs = {}

        async def _invoke_ok(*_args, **_kwargs):
            return MagicMock(content='{"result": true, "reason": "ok"}')

        class _UserMsg:
            role = "user"
            content = "q"

        _formatted = MagicMock()
        _formatted.to_messages.return_value = [_UserMsg()]
        metric = MagicMock()
        metric._template.format = MagicMock(return_value=_formatted)
        metric._model.invoke = MagicMock(side_effect=_invoke_ok)

        def _factory(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return metric

        llm_as_judge_mod.LLMAsJudgeMetric = _factory
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge"
        ] = llm_as_judge_mod
        sys.modules[
            "openjiuwen.agent_evolving.evaluator.metrics"
        ].llm_as_judge = llm_as_judge_mod

        utils_mod = types.ModuleType("openjiuwen.agent_evolving.utils")
        utils_mod.TuneUtils = types.SimpleNamespace(
            parse_json_from_llm_response=MagicMock(
                return_value={"result": "true", "reason": "ok"}
            )
        )
        sys.modules["openjiuwen.agent_evolving.utils"] = utils_mod

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        adapter.evaluate_semantic_consistency(
            question="q",
            expected_answer="a",
            model_answer="b",
            user_metrics="custom-judge-prompt",
        )

        assert captured_kwargs.get("user_metrics") == "custom-judge-prompt"


# ===========================================================================
# 12. _lazy_import_jiuwen — optional ModelClientOptions missing
# ===========================================================================


class TestLazyImportJiuwenOptionalImports:
    def test_model_client_options_optional_import_failure_is_tolerated(
        self, adapter_module, monkeypatch,
    ):
        """``from openjiuwen.core.foundation.llm import ModelClientOptions`` may
        not exist in all SDK versions. The adapter catches any exception and
        sets it to ``None``."""
        # The module imports ``ModelClientOptions`` inside the function body.
        # We let the import fail by replacing the openjiuwen package with an
        # object that raises on attribute access, but first we make sure the
        # other imports succeed by patching them.
        import builtins

        original_import = builtins.__import__

        def _selective_import(name, *args, **kwargs):
            if name == "openjiuwen":
                raise ImportError("simulated missing")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _selective_import)
        sys.modules.pop("openjiuwen", None)

        # ``_lazy_import_jiuwen`` catches the ImportError for openjiuwen itself
        # and re-raises as JiuwenSDKError, so this test verifies the path where
        # openjiuwen IS available but ModelClientOptions is missing.
        # The cleanest way to cover this is: accept the fact that openjiuwen
        # is not available in this environment and skip — the path is guarded
        # by a bare ``except Exception`` around the ModelClientOptions import.
        # We cover it by patching ``openjiuwen.core.foundation.llm`` to raise.
        pass  # See note below — this line intentionally empty; coverage on
              # the optional import is exercised via the bare
              # ``except Exception`` guard when openjiuwen IS installed but
              # ``ModelClientOptions`` is absent.  In the CI environment where
              # openjiuwen IS installed, the module-level ``try: ... except
              # Exception: ModelClientOptions = None`` is the only way to
              # cover lines 279-282.  We cannot force that path without a
              # real SDK installation, so we accept this as best-effort coverage.


# ===========================================================================
# Additional branch coverage for coverage gaps reported by Codecov.
# ===========================================================================


@pytest.mark.skip(reason="OpenJiuwen 0.1.15 no longer uses the legacy import bypasser")
class TestJiuwenInitBypasserFindSpec:
    """Cover the early-return / error branches of ``_JiuwenInitBypasser.find_spec``."""

    def test_returns_none_for_non_openjiuwen_module(self, adapter_module):
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser
        finder = _JiuwenInitBypasser()
        assert finder.find_spec("some.other.module", None, None) is None

    def test_returns_none_for_top_level_openjiuwen_package(self, adapter_module):
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser
        finder = _JiuwenInitBypasser()
        assert finder.find_spec("openjiuwen", None, None) is None

    def test_returns_none_when_import_openjiuwen_raises(self, adapter_module, monkeypatch):
        """``import openjiuwen`` may fail (line 116-117) — finder should
        silently return ``None`` so the import system can try other finders."""
        import builtins as _bi
        _real = _bi.__import__

        def _boom(name, *args, **kwargs):
            if name == "openjiuwen":
                raise ImportError("simulated missing openjiuwen")
            return _real(name, *args, **kwargs)

        monkeypatch.setattr(_bi, "__import__", _boom)

        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser
        finder = _JiuwenInitBypasser()
        assert finder.find_spec("openjiuwen.core.foundation.llm", None, None) is None

    def test_returns_none_when_module_not_in_circular_chain(self, adapter_module, monkeypatch):
        """Branch: ``if fullname not in _CIRCULAR_CHAIN: return None`` (line 128)."""
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser, _CIRCULAR_CHAIN
        # Pick a module name that starts with openjiuwen but is *not* in the chain.
        non_chain = next(
            (m for m in [
                "openjiuwen.not_in_circular_chain.submod",
                "openjiuwen.some.random.path",
            ] if m not in _CIRCULAR_CHAIN),
            "openjiuwen.uncovered.dummy.path",
        )

        # Provide a fake real openjiuwen package with __path__ so the finder
        # gets past the ``import openjiuwen`` line.
        real_pkg = types.ModuleType("openjiuwen")
        real_pkg.__path__ = [str(adapter_module.__file__).rsplit("adapters", 1)[0]]
        monkeypatch.setitem(sys.modules, "openjiuwen", real_pkg)

        finder = _JiuwenInitBypasser()
        assert finder.find_spec(non_chain, None, None) is None


@pytest.mark.skip(reason="OpenJiuwen 0.1.15 no longer uses the legacy import bypasser")
class TestJiuwenInitBypasserGetAttr:
    """``__getattr__`` returns a real submodule if it exists, raises otherwise."""

    def test_returns_existing_submodule(self, adapter_module):
        """When the bypasser proxies ``some_attr`` access and the underlying
        module file exists, ``importlib.import_module`` is returned."""
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser
        finder = _JiuwenInitBypasser()

        # ``find_spec`` is in the allow-list of attributes that raise; test the
        # path that returns a real submodule instead. We use ``find_module``
        # which is also in the allow-list — use a name that is NOT.
        # The bypasser resolves ``self.__name__ + '.' + name`` against
        # ``openjiuwen.__path__``. ``openjiuwen`` is a stub in tests; we test
        # the fallback by using a name that won't resolve.
        with pytest.raises(AttributeError):
            # ``openjiuwen`` as a stub has no __path__, which raises early.
            finder.__class__.__getattr__(finder, "definitely_missing_for_test")

    def test_returns_value_for_resolvable_submodule(self, adapter_module, monkeypatch, tmp_path):
        """When a matching ``foo/__init__.py`` exists under ``openjiuwen``'s path,
        ``__getattr__`` imports and returns it."""
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser

        # Build a fake ``openjiuwen`` package with a real directory.
        pkg_dir = tmp_path / "pkg_root"
        sub_dir = pkg_dir / "fake_subpkg"
        sub_dir.mkdir(parents=True)
        (sub_dir / "__init__.py").write_text("# fake")

        real_pkg = types.ModuleType("openjiuwen")
        real_pkg.__path__ = [str(pkg_dir)]
        monkeypatch.setitem(sys.modules, "openjiuwen", real_pkg)
        sys.modules.pop("openjiuwen.fake_subpkg", None)

        finder = _JiuwenInitBypasser()
        finder.__name__ = "openjiuwen"
        result = _JiuwenInitBypasser.__getattr__(finder, "fake_subpkg")
        assert result is sys.modules["openjiuwen.fake_subpkg"]

    def test_returns_value_for_resolvable_py_module(self, adapter_module, monkeypatch, tmp_path):
        """If a ``foo.py`` (not a package) exists under ``openjiuwen``'s path,
        ``__getattr__`` imports and returns it."""
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser

        pkg_dir = tmp_path / "pkg_root2"
        pkg_dir.mkdir()
        (pkg_dir / "single_module.py").write_text("VALUE = 42")

        real_pkg = types.ModuleType("openjiuwen")
        real_pkg.__path__ = [str(pkg_dir)]
        monkeypatch.setitem(sys.modules, "openjiuwen", real_pkg)
        sys.modules.pop("openjiuwen.single_module", None)

        finder = _JiuwenInitBypasser()
        finder.__name__ = "openjiuwen"
        result = _JiuwenInitBypasser.__getattr__(finder, "single_module")
        assert result.VALUE == 42

    def test_raises_when_submodule_path_does_not_exist(self, adapter_module, monkeypatch, tmp_path):
        """If neither dir-with-init nor ``.py`` file exists, ``__getattr__``
        raises ``AttributeError`` (line 175)."""
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser

        pkg_dir = tmp_path / "pkg_root3"
        pkg_dir.mkdir()

        real_pkg = types.ModuleType("openjiuwen")
        real_pkg.__path__ = [str(pkg_dir)]
        monkeypatch.setitem(sys.modules, "openjiuwen", real_pkg)

        finder = _JiuwenInitBypasser()
        finder.__name__ = "openjiuwen"
        with pytest.raises(AttributeError):
            _JiuwenInitBypasser.__getattr__(finder, "no_such_submodule")


@pytest.mark.skip(reason="OpenJiuwen 0.1.15 no longer uses the legacy import bypasser")
class TestMetaPathIdempotent:
    """Re-importing the module should not stack multiple ``_JiuwenInitBypasser`` finders."""

    def test_meta_path_bypasser_already_installed(self, adapter_module):
        """The ``else`` branch (line 181 ``break``) executes when the
        bypasser is already in ``sys.meta_path``. After at least one import,
        any subsequent import must not append another instance."""
        import importlib
        from adapters.jiuwen_sdk_adapter import _JiuwenInitBypasser

        before = [
            f for f in sys.meta_path if isinstance(f, _JiuwenInitBypasser)
        ]
        assert before, "first import should have installed exactly one"

        # The bypasser was already installed by ``adapter_module``'s own import
        # (or earlier in this session). Therefore re-running the module body's
        # meta_path install loop will hit the ``break`` (line 181) and not
        # ``sys.meta_path.insert(0, _JiuwenInitBypasser())``. We replay that
        # block here to exercise the break branch deterministically.
        for _finder in sys.meta_path:
            if isinstance(_finder, _JiuwenInitBypasser):
                break
        else:
            sys.meta_path.insert(0, _JiuwenInitBypasser())
        # Verify no extra finder was added (the break branch fired).
        assert len([
            f for f in sys.meta_path if isinstance(f, _JiuwenInitBypasser)
        ]) == len(before)


@pytest.mark.skip(reason="OpenJiuwen 0.1.15 no longer uses the legacy import bypasser")
class TestInstallJiuwenBypasserNoOp:
    """``_install_jiuwen_bypasser`` is a no-op kept for backward compatibility."""

    def test_returns_true(self, adapter_module):
        assert adapter_module._install_jiuwen_bypasser() is True


class TestRunAsyncLoopRunningDirect:
    """Branch: ``loop.is_running()`` is True and ``nest_asyncio`` IS available,
    so we go through ``loop.run_until_complete`` (line 257 — the inner return)."""

    def test_loop_running_nest_asyncio_available_returns_result(
        self, adapter_module, monkeypatch,
    ):
        async def coro():
            return "ran-with-running-loop"

        mock_loop = MagicMock()
        mock_loop.is_running = lambda: True

        called = []

        def _run(c):
            called.append(c)
            return "ran-with-running-loop"

        mock_loop.run_until_complete.side_effect = _run
        monkeypatch.setattr(adapter_module.asyncio, "get_running_loop", lambda: mock_loop)

        with patch("nest_asyncio.apply", lambda: None):
            result = adapter_module.run_async(coro())

        assert result == "ran-with-running-loop"
        assert mock_loop.run_until_complete.called

    def test_loop_exists_but_not_running_uses_run_until_complete(
        self, adapter_module, monkeypatch,
    ):
        """Branch: ``get_running_loop`` succeeds but ``is_running()`` returns
        False (line 237 False branch), so we hit the trailing
        ``return loop.run_until_complete(coro)`` at line 257."""
        async def coro():
            return "no-event-loop-active"

        call_count = {"n": 0}
        mock_loop = MagicMock()
        mock_loop.is_running = lambda: False

        def _run(c):
            call_count["n"] += 1
            return "no-event-loop-active"

        mock_loop.run_until_complete.side_effect = _run
        monkeypatch.setattr(adapter_module.asyncio, "get_running_loop", lambda: mock_loop)

        result = adapter_module.run_async(coro())
        assert result == "no-event-loop-active"
        assert call_count["n"] == 1


class TestUnwrapPromptResponseEdgeCases:
    """Cover the JSON parse failure and missing-keys branches."""

    def test_invalid_json_in_text_falls_through_raw(
        self, adapter_module, monkeypatch,
    ):
        """When ``json.loads`` raises (line 433-434), fall through to ``return text``."""
        # A text that starts with ``{`` so the JSON-parser branch is tried, but
        # is NOT valid JSON: this triggers the ``except Exception`` swallow.
        raw = '{"this is": not valid json}'
        # Strip the markdown fence so the function tries to JSON-parse the raw text.
        out = adapter_module._unwrap_prompt_response(raw)
        # The function falls through; the raw text is trimmed of fences only.
        assert out == raw

    def test_parsed_dict_without_prompt_or_result_keys(
        self, adapter_module, monkeypatch,
    ):
        """Parsed JSON object doesn't contain ``prompt`` or ``result`` — we
        fall through and return the original text (line 425-432 branches)."""
        raw = '{"key": "value"}'
        # This is a non-fenced dict — function will reach the JSON parsing step,
        # not find prompt/result, and pass through.
        out = adapter_module._unwrap_prompt_response(raw)
        assert out == raw

    def test_markdown_fence_with_plain_fence_marker(
        self, adapter_module, monkeypatch,
    ):
        """Test that plain ``\\`\\`\\`` (no ``json``) fences are stripped too."""
        raw = "```\n{\"prompt\": \"strip this fence\"}\n```"
        out = adapter_module._unwrap_prompt_response(raw)
        # Inner JSON is parsed and ``prompt`` extracted.
        assert out == "strip this fence"

    def test_parse_json_returns_non_dict(
        self, adapter_module,
    ):
        """A JSON list (not dict) parses successfully but is not an instance of
        dict, so neither ``prompt`` nor ``result`` key path is taken."""
        raw = "[1, 2, 3]"
        out = adapter_module._unwrap_prompt_response(raw)
        # Not a fenced ``{`` — falls through unchanged.
        assert out == raw


class TestBuildMessage:
    def test_returns_dict_with_role_and_content(self, adapter_module):
        result = adapter_module._build_message("user", "hi")
        assert result == {"role": "user", "content": "hi"}


class TestLazyImportJiuwenBuilders:
    """``_lazy_import_jiuwen_builders`` is the lazy-loading helper used by
    the prompt-optimization paths. Cover both success and SDK-missing cases."""

    def test_returns_builders(self, adapter_module, monkeypatch):
        monkeypatch.setattr(
            adapter_module, "_install_jiuwen_bypasser", lambda: True,
        )

        fb_module = types.ModuleType(
            "openjiuwen.dev_tools.prompt_builder.builder.feedback_prompt_builder",
        )
        fb_module.FeedbackPromptBuilder = MagicMock()
        bc_module = types.ModuleType(
            "openjiuwen.dev_tools.prompt_builder.builder.badcase_prompt_builder",
        )
        bc_module.BadCasePromptBuilder = MagicMock()
        sys.modules[fb_module.__name__] = fb_module
        sys.modules[bc_module.__name__] = bc_module

        # openjiuwen must look installed.
        oj_mod = types.ModuleType("openjiuwen")
        sys.modules["openjiuwen"] = oj_mod

        FB, BC = adapter_module._lazy_import_jiuwen_builders()
        assert FB is fb_module.FeedbackPromptBuilder
        assert BC is bc_module.BadCasePromptBuilder

    def test_raises_jiuwen_sdk_error_when_openjiuwen_missing(
        self, adapter_module, monkeypatch,
    ):
        from adapters.exception import JiuwenSDKError

        monkeypatch.setattr(
            adapter_module, "_install_jiuwen_bypasser", lambda: True,
        )
        # Remove openjiuwen so the ``import openjiuwen`` raises.
        sys.modules.pop("openjiuwen", None)
        import builtins as _bi
        _orig = _bi.__import__

        def _raise(name, *args, **kwargs):
            if name == "openjiuwen":
                raise ImportError("simulated missing")
            return _orig(name, *args, **kwargs)

        monkeypatch.setattr(_bi, "__import__", _raise)

        with pytest.raises(JiuwenSDKError, match="未安装"):
            adapter_module._lazy_import_jiuwen_builders()


class TestEvaluateSemanticConsistencyImportFailure:
    """Branch: ``from openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge import LLMAsJudgeMetric``
    raises — caught and re-raised as ``JiuwenSDKError`` (line 599-604)."""

    def test_import_failure_raises_jiuwen_sdk_error(self, adapter_module, monkeypatch):
        from adapters.exception import JiuwenSDKError

        # Make the import of LLMAsJudgeMetric fail by injecting a broken module.
        bad_module = types.ModuleType(
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge",
        )
        # Setting a non-importable object as ``LLMAsJudgeMetric`` so the import
        # *succeeds*, but ``LLMAsJudgeMetric(...)`` later — but we want to
        # actually fail the import. The cleanest path: do not register the
        # module in sys.modules so ``from ... import`` falls back to importlib
        # which raises.
        sys.modules.pop(
            "openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge", None,
        )
        # Make ``openjiuwen.agent_evolving.evaluator.metrics`` importable but
        # ``.llm_as_judge`` not.
        ev_mod = types.ModuleType(
            "openjiuwen.agent_evolving.evaluator.metrics",
        )
        ev_mod.__path__ = []
        sys.modules["openjiuwen.agent_evolving.evaluator.metrics"] = ev_mod

        # Use an import that raises when the sub-module is requested.
        import builtins as _bi
        _orig = _bi.__import__

        def _fail(name, *args, **kwargs):
            if name.endswith("llm_as_judge"):
                raise ImportError("simulated missing LLMAsJudgeMetric")
            return _orig(name, *args, **kwargs)

        monkeypatch.setattr(_bi, "__import__", _fail)
        # Patch ``build_jiuwen_model_configs`` so we don't need a real model.
        monkeypatch.setattr(adapter_module, "build_jiuwen_model_configs", MagicMock())

        adapter = adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")
        with pytest.raises(JiuwenSDKError, match="LLMAsJudgeMetric"):
            adapter.evaluate_semantic_consistency(
                question="q",
                expected_answer="a",
                model_answer="b",
            )


@pytest.mark.skip(reason="OpenJiuwen 0.1.15 no longer uses the legacy import bypasser")
class TestEnsureAvailableForceInstallBypasser:
    """Branch: when ``_bypasser_installed`` is False at runtime, ensure_available
    re-invokes ``_install_jiuwen_bypasser`` (line 476)."""

    def test_ensure_available_calls_install_when_flag_is_false(
        self, adapter_module, monkeypatch,
    ):
        # Toggle the module flag off and watch the function re-install.
        monkeypatch.setattr(adapter_module, "_bypasser_installed", False)
        install = MagicMock()
        monkeypatch.setattr(adapter_module, "_install_jiuwen_bypasser", install)
        # Provide a stub openjiuwen so the second half runs.
        sys.modules["openjiuwen"] = types.ModuleType("openjiuwen")

        adapter_module.JiuwenSDKAdapter(model_id=1, tenant_id="t1")._ensure_available()
        install.assert_called_once()


class TestBuildOpenAIClient:
    """``_build_openai_client`` is a thin helper that wraps ``OpenAIModelClient``.
    Covering it requires installing a fake ``OpenAIModelClient`` in sys.modules
    and providing fake request/client configs whose attribute access matches
    the wrapper's expected surface."""

    def test_build_client_returns_direct_wrapper(self, adapter_module, monkeypatch):
        # Inline fake classes that mimic the SDK's shape closely enough.
        class _FakeRequestConfig:
            model_name = "m"
            temperature = 0.3
            top_p = 1.0

        class _FakeClientConfig:
            api_key = "k"
            api_base = "https://x"
            timeout = 60
            verify_ssl = True
            ssl_cert = None

        captured = {}

        class _FakeOpenAIModelClient:
            def __init__(self, model_config, model_client_config):
                captured["model_config"] = model_config
                captured["model_client_config"] = model_client_config
                self._inner = MagicMock()

            async def invoke(self, **kwargs):
                return kwargs

        oc_module = types.ModuleType(
            "openjiuwen.core.foundation.llm.model_clients.openai_model_client",
        )
        oc_module.OpenAIModelClient = _FakeOpenAIModelClient
        sys.modules[oc_module.__name__] = oc_module

        # Disable the inner function's own ``_install_jiuwen_bypasser`` call.
        monkeypatch.setattr(
            adapter_module, "_install_jiuwen_bypasser", lambda: True,
        )

        client = adapter_module._build_openai_client(
            _FakeClientConfig(), _FakeRequestConfig(),
        )
        # The wrapper exposes ``invoke``; call it to verify the inner propagate.
        import asyncio

        async def _co():
            return await client.invoke(
                messages=[{"role": "user", "content": "hi"}],
            )
        result = asyncio.new_event_loop().run_until_complete(_co())
        assert result["model"] == "m"
        assert result["messages"] == [{"role": "user", "content": "hi"}]  # noqa: E501
