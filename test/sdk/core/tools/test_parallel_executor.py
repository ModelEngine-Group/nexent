import time
import pytest

from sdk.nexent.core.tools.parallel_executor import _parallel_executor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _echo(**kwargs):
    """Simple callable that returns its kwargs as a string."""
    return str(kwargs)


def _slow(seconds: float = 0.1, **kwargs):
    """Callable that sleeps before returning."""
    time.sleep(seconds)
    return f"done after {seconds}s"


def _raise(exc_type=ValueError, message="test error"):
    """Callable that raises an exception."""
    raise exc_type(message)


# ---------------------------------------------------------------------------
# Basic 2-tuple mode
# ---------------------------------------------------------------------------

class TestTwoTupleMode:
    def test_empty_tasks_returns_empty_list(self):
        result = _parallel_executor()
        assert result == []

    def test_single_task(self):
        result = _parallel_executor((_echo, {"key": "value"}))
        assert len(result) == 1
        assert "key" in result[0]

    def test_two_independent_tasks_execute_in_parallel(self):
        start = time.perf_counter()
        result = _parallel_executor(
            (_slow, {"seconds": 0.1}),
            (_slow, {"seconds": 0.1}),
            max_workers=2,
        )
        elapsed = time.perf_counter() - start

        assert len(result) == 2
        assert "done after 0.1s" in result[0]
        assert "done after 0.1s" in result[1]
        # With max_workers=2, both should run in parallel: total < 0.2s
        assert elapsed < 0.2

    def test_results_preserve_input_order(self):
        result = _parallel_executor(
            (_echo, {"value": 1}),
            (_echo, {"value": 2}),
            (_echo, {"value": 3}),
        )
        assert len(result) == 3
        for i in range(3):
            assert str(i + 1) in result[i]


# ---------------------------------------------------------------------------
# 3-tuple (named) mode
# ---------------------------------------------------------------------------

class TestThreeTupleMode:
    def test_named_tasks_return_dict(self):
        result = _parallel_executor(
            (_echo, {"v": "a"}, "task_a"),
            (_echo, {"v": "b"}, "task_b"),
        )
        assert isinstance(result, dict)
        assert set(result.keys()) == {"task_a", "task_b"}

    def test_named_results_accessible_by_name(self):
        result = _parallel_executor(
            (_echo, {"msg": "hello"}, "greeting"),
            (_echo, {"msg": "world"}, "subject"),
        )
        assert "hello" in result["greeting"]
        assert "world" in result["subject"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_mixed_two_and_three_tuples_raises_value_error(self):
        with pytest.raises(ValueError, match="same format"):
            _parallel_executor(
                (_echo, {"a": 1}),
                (_echo, {"b": 2}, "named"),
            )

    def test_non_callable_returns_error_string(self):
        result = _parallel_executor(("not_a_function", {"x": 1}))
        assert "Not callable" in result[0]

    def test_non_dict_kwargs_returns_error_string(self):
        result = _parallel_executor((_echo, "not_a_dict"))
        assert "kwargs must be a dict" in result[0]

    def test_exception_in_task_is_captured(self):
        result = _parallel_executor((_raise, {}))
        assert "Failed" in result[0]


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_is_captured_as_error_string(self):
        result = _parallel_executor(
            (_slow, {"seconds": 0.5}),
            timeout=0.1,
        )
        assert "Timed out" in result[0]


# ---------------------------------------------------------------------------
# max_workers
# ---------------------------------------------------------------------------

class TestMaxWorkers:
    def test_max_workers_limits_concurrency(self):
        """With max_workers=1, tasks should run sequentially."""
        start = time.perf_counter()
        result = _parallel_executor(
            (_slow, {"seconds": 0.05}),
            (_slow, {"seconds": 0.05}),
            (_slow, {"seconds": 0.05}),
            max_workers=1,
        )
        elapsed = time.perf_counter() - start

        assert len(result) == 3
        # Sequential: 3 × 0.05 ≈ 0.15s + overhead
        assert elapsed >= 0.15

    def test_default_max_workers_allows_parallelism(self):
        """Default max_workers=4 — two tasks should run in parallel."""
        start = time.perf_counter()
        result = _parallel_executor(
            (_slow, {"seconds": 0.1}),
            (_slow, {"seconds": 0.1}),
        )
        elapsed = time.perf_counter() - start

        assert len(result) == 2
        assert elapsed < 0.2
