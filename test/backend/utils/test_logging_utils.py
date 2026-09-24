"""
Unit tests for backend.utils.logging_utils.

Covers:
  - ColorFormatter: colored vs plain output for each level
  - HybridRotatingFileHandler: rotation triggers (time vs size) and stream-error fallback
  - configure_logging: IS_DEBUG override of LOG_LEVEL, explicit level passthrough, default categories
  - get_uvicorn_logging_config: dictConfig contract, IS_DEBUG override, custom categories
  - model_call routing: whitelisted SDK model-layer loggers write to the dedicated
    model_call file and stop propagating to the service category files
  - configure_elasticsearch_logging: noisy client loggers demoted to WARNING
"""

import logging
import logging.config
from logging.handlers import TimedRotatingFileHandler
from unittest.mock import MagicMock, patch

import pytest

from backend.utils.logging_utils import (
    ColorFormatter,
    HybridRotatingFileHandler,
    MODEL_CALL_LOGGERS,
    configure_elasticsearch_logging,
    configure_logging,
    get_uvicorn_logging_config,
)


# ---------------------------------------------------------------------------
# ColorFormatter
# ---------------------------------------------------------------------------


class TestColorFormatter:
    """ColorFormatter wraps messages with ANSI color codes based on level name."""

    def _format(self, record: logging.LogRecord) -> str:
        return ColorFormatter("%(message)s").format(record)

    def test_warning_is_yellow(self):
        record = logging.LogRecord("x", logging.WARNING, "x", 0, "msg", None, None)
        assert self._format(record) == "\033[33mmsg\033[0m"

    def test_error_is_red(self):
        record = logging.LogRecord("x", logging.ERROR, "x", 0, "boom", None, None)
        assert self._format(record) == "\033[31mboom\033[0m"

    def test_critical_is_red_background(self):
        record = logging.LogRecord("x", logging.CRITICAL, "x", 0, "fatal", None, None)
        assert self._format(record) == "\033[41mfatal\033[0m"

    def test_info_has_no_color(self):
        record = logging.LogRecord("x", logging.INFO, "x", 0, "ordinary", None, None)
        assert self._format(record) == "ordinary"

    def test_debug_has_no_color(self):
        record = logging.LogRecord("x", logging.DEBUG, "x", 0, "chatty", None, None)
        assert self._format(record) == "chatty"

    def test_message_with_format_placeholders_still_renders(self):
        record = logging.LogRecord("x", logging.INFO, "x", 0, "user=%s", None, None)
        record.args = ("alice",)
        assert self._format(record) == "user=alice"


# ---------------------------------------------------------------------------
# HybridRotatingFileHandler
# ---------------------------------------------------------------------------


class TestHybridRotatingFileHandler:
    """Hybrid rollover triggers on either time or size, whichever happens first."""

    def test_initializes_with_max_bytes_attribute(self, tmp_path):
        log_path = tmp_path / "test.log"
        handler = HybridRotatingFileHandler(log_path, maxBytes=100)
        try:
            assert handler._max_bytes == 100
            assert isinstance(handler, TimedRotatingFileHandler)
        finally:
            handler.close()

    def test_max_bytes_zero_disables_size_check(self, tmp_path):
        log_path = tmp_path / "test.log"
        handler = HybridRotatingFileHandler(log_path, maxBytes=0)
        try:
            record = logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)
            # Force a stream tell to return a huge value; should NOT trigger when disabled.
            handler.stream = MagicMock()
            handler.stream.tell.return_value = 10**9
            assert handler.shouldRollover(record) == 0
        finally:
            handler.close()

    def test_size_above_max_bytes_triggers_rollover(self, tmp_path):
        log_path = tmp_path / "test.log"
        handler = HybridRotatingFileHandler(log_path, maxBytes=10)
        try:
            handler.stream = MagicMock()
            handler.stream.tell.return_value = 100
            record = logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)
            assert handler.shouldRollover(record) == 1
        finally:
            handler.close()

    def test_size_below_max_bytes_does_not_trigger_rollover(self, tmp_path):
        log_path = tmp_path / "test.log"
        handler = HybridRotatingFileHandler(log_path, maxBytes=100)
        try:
            handler.stream = MagicMock()
            handler.stream.tell.return_value = 50
            record = logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)
            assert handler.shouldRollover(record) == 0
        finally:
            handler.close()

    def test_time_check_wins_when_time_triggers_first(self, tmp_path):
        """If super().shouldRollover() returns a truthy value, the size check is skipped."""
        log_path = tmp_path / "test.log"
        handler = HybridRotatingFileHandler(log_path, maxBytes=10)
        try:
            handler.stream = MagicMock()
            handler.stream.tell.return_value = 10**9  # would otherwise trigger size rollover
            with patch.object(
                TimedRotatingFileHandler,
                "shouldRollover",
                return_value=1,  # pretend time rollover fired
            ):
                record = logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)
                assert handler.shouldRollover(record) == 1
        finally:
            handler.close()

    def test_stream_tell_exception_returns_zero(self, tmp_path):
        log_path = tmp_path / "test.log"
        handler = HybridRotatingFileHandler(log_path, maxBytes=10)
        try:
            handler.stream = MagicMock()
            handler.stream.tell.side_effect = OSError("disk full")
            record = logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)
            # Exception during tell is swallowed; result should be 0 (no rollover).
            assert handler.shouldRollover(record) == 0
        finally:
            handler.close()

    def test_do_rollover_sets_mode_to_append(self, tmp_path):
        """doRollover switches to append mode so the reopened stream is not truncated."""
        log_path = tmp_path / "test.log"
        handler = HybridRotatingFileHandler(log_path, maxBytes=10)
        try:
            with patch.object(TimedRotatingFileHandler, "doRollover") as super_rollover:
                handler.doRollover()
            assert handler.mode == "a"
            super_rollover.assert_called_once()
        finally:
            handler.close()


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_root_logger():
    """Snapshot and restore root logger state so tests don't pollute each other."""
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)
    root.handlers.clear()
    yield
    root.handlers.clear()
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


class TestConfigureLogging:
    """configure_logging sets up root logger with console + per-category file handlers."""

    def test_default_categories_create_one_file_handler_each(self, reset_root_logger, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        configure_logging()
        root = logging.getLogger()
        # One StreamHandler (console) + one file handler per default category,
        # except model_call: its file handler is bound only to the whitelisted
        # model-layer loggers, never to root.
        default_cats = ["config", "runtime", "northbound", "data_process", "model_call"]
        assert len(root.handlers) == len(default_cats)  # console + 4 category files
        handler_classes = [type(h).__name__ for h in root.handlers]
        assert handler_classes.count("StreamHandler") == 1
        assert handler_classes.count("HybridRotatingFileHandler") == len(default_cats) - 1

    def test_explicit_level_overrides_effective_level(self, reset_root_logger, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        configure_logging(level=logging.WARNING)
        assert logging.getLogger().level == logging.WARNING

    def test_is_debug_true_forces_debug_level(self, reset_root_logger, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        monkeypatch.setattr("backend.utils.logging_utils.IS_DEBUG", True)
        monkeypatch.setattr("backend.utils.logging_utils.LOG_LEVEL", "INFO")
        configure_logging()
        assert logging.getLogger().level == logging.DEBUG

    def test_is_debug_false_uses_log_level(self, reset_root_logger, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        monkeypatch.setattr("backend.utils.logging_utils.IS_DEBUG", False)
        monkeypatch.setattr("backend.utils.logging_utils.LOG_LEVEL", "ERROR")
        configure_logging()
        assert logging.getLogger().level == logging.ERROR

    def test_unknown_log_level_falls_back_to_info(self, reset_root_logger, tmp_path, monkeypatch):
        """Invalid LOG_LEVEL strings should not crash; degrade to INFO."""
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        monkeypatch.setattr("backend.utils.logging_utils.IS_DEBUG", False)
        monkeypatch.setattr("backend.utils.logging_utils.LOG_LEVEL", "NOT_A_LEVEL")
        configure_logging()
        assert logging.getLogger().level == logging.INFO

    def test_handlers_are_cleared_before_setup(self, reset_root_logger, tmp_path, monkeypatch):
        """Calling configure_logging twice should not accumulate handlers."""
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        configure_logging()
        first_count = len(logging.getLogger().handlers)
        configure_logging()
        second_count = len(logging.getLogger().handlers)
        assert first_count == second_count

    def test_custom_categories_create_only_requested_handlers(self, reset_root_logger, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        configure_logging(categories=["only_one"])
        handler_classes = [type(h).__name__ for h in logging.getLogger().handlers]
        assert handler_classes.count("HybridRotatingFileHandler") == 1
        assert handler_classes.count("StreamHandler") == 1


# ---------------------------------------------------------------------------
# get_uvicorn_logging_config
# ---------------------------------------------------------------------------


class TestGetUvicornLoggingConfig:
    """get_uvicorn_logging_config returns a dictConfig-compatible dict."""

    def test_returns_dictconfig_version_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        cfg = get_uvicorn_logging_config()
        assert cfg["version"] == 1
        assert cfg["disable_existing_loggers"] is False

    def test_root_handler_names_list_console_and_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        cfg = get_uvicorn_logging_config(categories=["a", "b"])
        assert cfg["root"]["handlers"] == ["console", "file_a", "file_b"]

    def test_is_debug_true_sets_debug_level(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        monkeypatch.setattr("backend.utils.logging_utils.IS_DEBUG", True)
        monkeypatch.setattr("backend.utils.logging_utils.LOG_LEVEL", "INFO")
        cfg = get_uvicorn_logging_config()
        assert cfg["root"]["level"] == "DEBUG"
        assert cfg["handlers"]["console"]["level"] == "DEBUG"

    def test_is_debug_false_uses_log_level(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        monkeypatch.setattr("backend.utils.logging_utils.IS_DEBUG", False)
        monkeypatch.setattr("backend.utils.logging_utils.LOG_LEVEL", "ERROR")
        cfg = get_uvicorn_logging_config()
        assert cfg["root"]["level"] == "ERROR"
        assert cfg["handlers"]["console"]["level"] == "ERROR"

    def test_levels_remain_strings_for_dictconfig(self, tmp_path, monkeypatch):
        """dictConfig requires handler levels to be string names; verify the contract."""
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        monkeypatch.setattr("backend.utils.logging_utils.IS_DEBUG", True)
        cfg = get_uvicorn_logging_config()
        for handler in cfg["handlers"].values():
            assert isinstance(handler["level"], str)

    def test_formatters_color_and_plain_are_defined(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        cfg = get_uvicorn_logging_config()
        assert "color" in cfg["formatters"]
        assert "plain" in cfg["formatters"]
        assert cfg["formatters"]["color"]["()"].endswith("ColorFormatter")

    def test_file_handler_paths_under_log_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        cfg = get_uvicorn_logging_config(categories=["my_cat"])
        file_h = cfg["handlers"]["file_my_cat"]
        # Accept both POSIX and Windows separators for portability.
        assert file_h["filename"].replace("\\", "/").endswith("my_cat/nexent_my_cat.log")
        assert file_h["encoding"] == "utf-8"
        assert file_h["class"].endswith("HybridRotatingFileHandler")


# ---------------------------------------------------------------------------
# model_call routing
# ---------------------------------------------------------------------------


def _cleanup_routing_state():
    """Close test-created root handlers and unbind model_call loggers.

    The console instance is shared between root and the model_call loggers, so
    handlers attached to the named loggers are removed without closing (they
    were already closed via root). Levels are reset too so the DEBUG pin does
    not leak into unrelated tests.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for name in MODEL_CALL_LOGGERS:
        named = logging.getLogger(name)
        for h in list(named.handlers):
            named.removeHandler(h)
        named.propagate = True
        named.setLevel(logging.NOTSET)


def _read(tmp_path, category: str) -> str:
    return (tmp_path / category / f"nexent_{category}.log").read_text(encoding="utf-8")


def _apply_dictconfig(monkeypatch, tmp_path):
    """Wire logging through the dictConfig path used by the service entrypoints."""
    monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
    logging.config.dictConfig(get_uvicorn_logging_config(categories=["runtime", "model_call"]))


def _apply_configure_logging(monkeypatch, tmp_path):
    """Wire logging through the programmatic configure_logging path."""
    monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
    configure_logging(categories=["runtime", "model_call"])


class TestModelCallRouting:
    """When model_call is among the categories, whitelisted model-layer loggers
    write to the dedicated model_call file and stop propagating."""

    def test_loggers_section_only_when_model_call_included(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        cfg_with = get_uvicorn_logging_config(categories=["runtime", "model_call"])
        assert "loggers" in cfg_with
        # Other services must keep their current behaviour untouched.
        cfg_without = get_uvicorn_logging_config(categories=["config"])
        assert "loggers" not in cfg_without

    def test_named_loggers_bound_to_model_call_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        cfg = get_uvicorn_logging_config(categories=["runtime", "model_call"])
        for name in MODEL_CALL_LOGGERS:
            entry = cfg["loggers"][name]
            assert entry["handlers"] == ["console", "file_model_call"]
            assert entry["propagate"] is False
            # DEBUG pin: model-layer debug records must be emitted even when
            # the root logger stays at INFO.
            assert entry["level"] == "DEBUG"
        # file_model_call must pass DEBUG records through the handler gate;
        # it is bound only to the whitelisted loggers, so nothing can leak in.
        assert cfg["handlers"]["file_model_call"]["level"] == "DEBUG"
        # Console itself stays unfiltered (docker logs behaviour unchanged).
        assert "filters" not in cfg["handlers"]["console"]
        assert "filters" not in cfg["handlers"]["file_runtime"]

    def test_whitelist_covers_sdk_model_loggers(self):
        assert set(MODEL_CALL_LOGGERS) >= {
            "openai_llm",
            "openai_long_context_model",
            "nexent.core.models.openai_vlm",
            "nexent.core.models.ali_stt_model",
            "nexent.core.models.ali_tts_model",
            "volc_stt_model",
            "volc_tts_model",
            "model_call",
            "context_evidence",
        }

    def test_config_is_dictconfig_instantiable(self, reset_root_logger, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        cfg = get_uvicorn_logging_config(categories=["runtime", "model_call"])
        logging.config.dictConfig(cfg)  # must not raise
        _cleanup_routing_state()

    def _log_and_assert_routing(self, tmp_path):
        try:
            logging.getLogger("openai_llm").info("llm event")
            logging.getLogger("context_evidence").info("context evidence event")
            logging.getLogger("runtime_service").info("system event")
            for h in logging.getLogger().handlers:
                h.flush()
            model_log = _read(tmp_path, "model_call")
            runtime_log = _read(tmp_path, "runtime")
            assert "llm event" in model_log
            assert "context evidence event" in model_log
            assert "system event" not in model_log
            assert "system event" in runtime_log
            assert "llm event" not in runtime_log
            assert "context evidence event" not in runtime_log
        finally:
            _cleanup_routing_state()

    @pytest.mark.parametrize(
        "apply_config",
        [_apply_dictconfig, _apply_configure_logging],
        ids=["dictconfig", "configure_logging"],
    )
    def test_routes_model_records_to_dedicated_file(
        self, reset_root_logger, tmp_path, monkeypatch, apply_config
    ):
        apply_config(monkeypatch, tmp_path)
        self._log_and_assert_routing(tmp_path)

    @pytest.mark.parametrize(
        "apply_config",
        [_apply_dictconfig, _apply_configure_logging],
        ids=["dictconfig", "configure_logging"],
    )
    def test_debug_records_reach_model_call_file(
        self, reset_root_logger, tmp_path, monkeypatch, apply_config
    ):
        """Regression: MODEL INPUT PARAMETERS is logged at DEBUG on
        model_call.core_agent; with the whitelist left at NOTSET it inherited
        the root INFO level and was silently dropped before reaching the file.
        """
        apply_config(monkeypatch, tmp_path)
        try:
            assert logging.getLogger("model_call.core_agent").isEnabledFor(logging.DEBUG)
            logging.getLogger("model_call.core_agent").debug("MODEL INPUT PARAMETERS probe")
            logging.getLogger("openai_llm").debug("debug probe from openai_llm")
            for h in logging.getLogger().handlers:
                h.flush()
            model_log = _read(tmp_path, "model_call")
            runtime_log = _read(tmp_path, "runtime")
            assert "MODEL INPUT PARAMETERS probe" in model_log
            assert "debug probe from openai_llm" in model_log
            assert "MODEL INPUT PARAMETERS probe" not in runtime_log
            assert "debug probe from openai_llm" not in runtime_log
        finally:
            _cleanup_routing_state()

    def test_whitelist_pinned_to_debug_level(self, reset_root_logger, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        configure_logging(categories=["runtime", "model_call"])
        try:
            for name in MODEL_CALL_LOGGERS:
                assert logging.getLogger(name).level == logging.DEBUG
        finally:
            _cleanup_routing_state()

    def test_unbind_resets_whitelist_levels(self, reset_root_logger, tmp_path, monkeypatch):
        """Without the model_call category the whitelist returns to its
        pre-branch behaviour: no handlers, propagate on, level inherited."""
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        configure_logging(categories=["runtime", "model_call"])
        configure_logging(categories=["runtime"])
        try:
            for name in MODEL_CALL_LOGGERS:
                named = logging.getLogger(name)
                assert named.level == logging.NOTSET
                assert named.handlers == []
                assert named.propagate is True
        finally:
            _cleanup_routing_state()

    def test_named_loggers_do_not_accumulate_handlers(
        self, reset_root_logger, tmp_path, monkeypatch
    ):
        """Calling configure_logging twice must not stack handlers on named loggers."""
        monkeypatch.setattr("backend.utils.logging_utils.LOG_DIR", str(tmp_path))
        configure_logging(categories=["runtime", "model_call"])
        configure_logging(categories=["runtime", "model_call"])
        try:
            for name in MODEL_CALL_LOGGERS:
                assert len(logging.getLogger(name).handlers) == 2
        finally:
            _cleanup_routing_state()


# ---------------------------------------------------------------------------
# configure_elasticsearch_logging
# ---------------------------------------------------------------------------


class TestConfigureElasticsearchLogging:
    """configure_elasticsearch_logging should quiet noisy HTTP-related loggers."""

    def test_quiet_elasticsearch_transport(self):
        configure_elasticsearch_logging()
        assert logging.getLogger("elastic_transport.transport").level == logging.WARNING

    def test_quiet_elasticsearch_trace(self):
        configure_elasticsearch_logging()
        assert logging.getLogger("elasticsearch.trace").level == logging.WARNING

    def test_quiet_httpx(self):
        configure_elasticsearch_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
