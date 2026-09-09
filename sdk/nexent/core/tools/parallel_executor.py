import concurrent.futures
import contextvars
from typing import Any, Dict

from smolagents.tools import Tool


class ParallelExecutorTool(Tool):
    name = "parallel_executor"
    category = None
    tool_sign = None
    description = (
        "Run multiple independent tool or agent calls in parallel. "
        "parallel_executor is already injected into the Python environment: "
        "call it directly and never import it. "
        "Each task must be (available_tool_or_agent, kwargs_dict) or "
        "(available_tool_or_agent, kwargs_dict, result_key); do not mix formats. "
        "Use only tools or agents listed in Available Resources; do not import "
        "or create the callable. "
        "All 2-tuples return a list in input order; all 3-tuples return a dict "
        "keyed by result_key. "
        "Only include independent tasks; dependent calls must be sequential. "
        "Timeouts and failures are returned as error strings; successful results "
        "keep their original type. timeout is per task and max_workers controls "
        "the maximum concurrency."
    )
    description_zh = (
        "并行执行多个互不依赖的工具或助手调用。"
        "parallel_executor 已直接注入当前 Python 环境，必须直接调用，禁止使用 import 获取。"
        "每个任务必须是二元组（可用工具或助手对象，参数字典）或三元组（可用工具或助手对象，参数字典，结果名称）；同一次调用不能混用两种格式。"
        "只能传入“可用资源”中已经列出的工具或助手，不要导入或创建函数。"
        "全部使用二元组时返回按输入顺序排列的列表；全部使用三元组时返回以结果名称为 key 的字典。"
        "任务之间必须互不依赖；有依赖关系时必须串行调用。"
        "单个任务超时（默认120秒）或失败时返回错误字符串；成功结果保留原始类型。"
        "timeout 控制单个任务的超时时间，max_workers 控制最大并发数。"
    )
    inputs = {
        "tasks": {
            "type": "array",
            "description": (
                "A list of tasks. Each task is (available_tool_or_agent, kwargs_dict) "
                "or (available_tool_or_agent, kwargs_dict, result_key). "
                "Use only already available tools or agents; never import "
                "parallel_executor or the task callable. Do not mix the two formats."
            ),
            "description_zh": (
                "任务列表。每个任务是二元组（可用工具或助手对象，参数字典） "
                "或三元组（可用工具或助手对象，参数字典，结果名称）。"
                "只能使用已经注入且列在可用资源中的工具或助手；禁止 import parallel_executor 或任务对象。"
                "同一次调用不能混用两种格式。"
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx: Dict[concurrent.futures.Future, int] = {}
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
                results[idx] = (
                    f"[{label}] Not callable: {type(func).__name__}"
                )
                continue
            task_context = contextvars.copy_context()
            future_to_idx[pool.submit(task_context.run, func, **kwargs)] = idx

        for future, idx in future_to_idx.items():
            label = names[idx] or f"task-{idx}"
            try:
                results[idx] = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
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
