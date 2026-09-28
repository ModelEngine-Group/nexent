from concurrent.futures import TimeoutError as FutureTimeoutError
import threading
from typing import Any, Dict

from smolagents.tools import Tool

from ..concurrency import ManagedTaskSpec, get_current_thread_manager


class ParallelExecutorTool(Tool):
    name = "parallel_executor"
    category = None
    tool_sign = None
    description = (
        "Run independent available tools or sub-agents in parallel. "
        "Dependent calls must run sequentially. Example:\n"
        "<code>\n"
        "# Search KB-A and KB-B concurrently\n"
        'parallel_executor(tasks=[(knowledge_base_search, {"query": "test", "index_names": ["KB-A"]}, "kb_a"), '
        '(knowledge_base_search, {"query": "test", "index_names": ["KB-B"]}, "kb_b")])\n'
        "</code>"
    )
    description_zh = (
        "并行执行多个互不依赖的可用工具或子智能体调用。有依赖的调用须串行执行。示例：\n"
        "<code>\n"
        "# 并发调用知识库工具检索知识库 KB-A 与 KB-B\n"
        'parallel_executor(tasks=[(knowledge_base_search, {"query": "test", "index_names": ["KB-A"]}, "kb_a"), '
        '(knowledge_base_search, {"query": "test", "index_names": ["KB-B"]}, "kb_b")])\n'
        "</code>"
    )
    inputs = {
        "tasks": {
            "type": "array",
            "description": (
                "Each task is (available_tool_or_agent, kwargs_dict) or "
                "(available_tool_or_agent, kwargs_dict, result_key). "
                "Use only listed resources and do not mix formats. "
                "Two-tuples return a list in input order; three-tuples return a dict keyed by result_key. "
                "Failures return error strings; successes retain their original types."
            ),
            "description_zh": (
                "每个任务是二元组（可用工具或子智能体对象，参数字典）或三元组"
                "（可用工具或子智能体对象，参数字典，结果名称）。仅使用已列出的资源，"
                "同次调用不得混用格式。二元组返回按输入顺序排列的列表，三元组返回"
                "以结果名称为键的字典；失败返回错误字符串，成功结果保留原始类型。"
            ),
        },
        "timeout": {
            "type": "integer",
            "description": "Per-task timeout in seconds (default 120)",
            "description_zh": "单个任务超时秒数（默认120）",
            "default": 120,
            "nullable": True,
        },
        "max_workers": {
            "type": "integer",
            "description": (
                "Maximum number of threads for parallel execution (default 4).  "
                "Set higher when you have many independent tasks."
            ),
            "description_zh": "并行执行的最大线程数（默认4）。任务较多时可调高。",
            "default": 4,
            "nullable": True,
        },
    }
    output_type = "any"

    def forward(self, tasks, timeout: int = 120, max_workers: int = 4):
        """Execute the tasks in parallel.

        ``tasks`` is a list where each element is a 2-tuple
        ``(tool_or_agent, kwargs)`` or 3-tuple
        ``(tool_or_agent, kwargs, \"result_key\")``.

        Returns a list (all 2-tuples) or dict (all 3-tuples).
        """
        return _parallel_executor(tasks, timeout=timeout, max_workers=max_workers)


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------

def _validate_tasks(tasks):
    """Validate task format and return (names, has_names)."""
    if not tasks:
        return [], False

    n = len(tasks)
    has_names = any(len(t) == 3 for t in tasks)

    if has_names:
        if not all(len(t) == 3 for t in tasks):
            raise ValueError(
                "parallel_executor: all tasks must use the same format "
                "(2-tuple or 3-tuple). Mixed formats are not allowed."
            )
        names = [t[2] for t in tasks]
    else:
        if not all(len(t) == 2 for t in tasks):
            raise ValueError(
                "parallel_executor: each task must be a 2-tuple "
                "(tool_or_agent, kwargs_dict) or 3-tuple "
                "(tool_or_agent, kwargs_dict, result_key)."
            )
        names = [None] * n

    return names, has_names


def _execute_tasks(tasks, names, timeout, max_workers):
    """Submit tasks to a thread pool and collect results."""
    n = len(tasks)
    results = [None] * n

    manager = get_current_thread_manager()
    if manager is None:
        from ..agents.run_agent import _get_default_agent_thread_manager

        manager = _get_default_agent_thread_manager()
    requested_limit = max(1, int(max_workers))
    admission = threading.BoundedSemaphore(requested_limit)
    executions: Dict[str, tuple[Any, int]] = {}

    def run_admitted(func, kwargs):
        with admission:
            return func(**kwargs)

    for idx, t in enumerate(tasks):
        func, kwargs = t[0], t[1]
        label = names[idx] or f"task-{idx}"
        if not isinstance(kwargs, dict):
            results[idx] = (
                f"[{label}] Invalid: "
                f"kwargs must be a dict, got {type(kwargs).__name__}"
            )
            continue
        if not callable(func):
            results[idx] = f"[{label}] Not callable: {type(func).__name__}"
            continue
        execution = manager.submit(
            "model-tool-io",
            ManagedTaskSpec(
                task_name="parallel-tool-call",
                owner="sdk-agent",
            ),
            run_admitted,
            func,
            kwargs,
        )
        executions[execution.execution_id] = (execution, idx)

    for execution, idx in executions.values():
        label = names[idx] or f"task-{idx}"
        try:
            results[idx] = execution.future.result(timeout=timeout)
        except FutureTimeoutError:
            manager.cancel(
                execution.execution_id,
                reason="parallel tool deadline exceeded",
                wait_timeout=0,
            )
            results[idx] = f"[{label}] Timed out after {timeout}s."
        except Exception:
            import traceback as _tb
            results[idx] = f"[{label}] Failed: {_tb.format_exc(limit=1)}"

    return results


def _parallel_executor(tasks, timeout: int = 120, max_workers: int = 4):
    names, has_names = _validate_tasks(tasks)
    if not tasks:
        return []
    results = _execute_tasks(tasks, names, timeout, max_workers)
    if has_names:
        return {names[idx]: results[idx] for idx in range(len(tasks))}
    return results
