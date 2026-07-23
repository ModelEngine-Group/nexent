import concurrent.futures
from typing import Any, Dict

from smolagents.tools import Tool


class ParallelExecutorTool(Tool):
    name = "parallel_executor"
    category = None
    tool_sign = None
    description = (
        "Execute multiple independent agent/tool calls in parallel. "
        "Each task is a 2-tuple (callable, kwargs_dict) or a 3-tuple "
        "(callable, kwargs_dict, \"name\").  "
        "All 2-tuples → returns a list (results in input order).  "
        "All 3-tuples → returns a dict keyed by name.  "
        "Only put calls that are independent of each other into one call; "
        "if one task needs the output of another, call them serially.  "
        "Timeout (default 120 s) and failures are captured as error strings.  "
        "max_workers (default 4) limits the max number of threads used in "
        "parallel; set higher when you have many independent tasks and want "
        "to finish faster.  "
        "kwargs values can be any Python object (strings, numbers, PIL Images, "
        "file handles, audio, etc.) — just reference the variable name; no "
        "serialization is needed.  "
        "All results — whether from tools, assistants, timeouts, or errors — "
        "are returned as plain strings.  Use print() to read them."
    )
    description_zh = (
        "并行执行多个互不依赖的助手或工具调用。"
        "每个任务是一个二元组 (函数名, {\"参数\": 值}) 或三元组 (函数名, {\"参数\": 值}, \"名称\")。"
        "全部用二元组 → 返回列表，按传入顺序排列。"
        "全部用三元组 → 返回字典，key 是名称字符串。"
        "只有互不依赖的调用才能放入同一个 parallel_executor；"
        "如果后一个任务需要前一个任务的结果，必须分开串行调用。"
        "单个任务超时（默认120秒）或失败不会影响其他任务，会以错误字符串形式返回。"
        "max_workers（默认4）限制并行时使用的最大线程数；当有大量互不依赖的任务时可以提高该值以加快完成速度。"
        "kwargs 值可以是任意 Python 对象（字符串、数字、PIL图片、文件句柄、音频等），"
        "直接引用变量名即可，无需序列化。"
        "所有返回结果——无论来自工具、助手、超时还是异常——均为纯字符串。"
        "用 print() 读取即可。"
    )
    inputs = {
        "tasks": {
            "type": "array",
            "description": (
                "Variable number of (callable, kwargs_dict) or "
                "(callable, kwargs_dict, name) tuples.  "
                "kwargs values can be any Python object — just reference "
                "the variable name, no serialization needed."
            ),
            "description_zh": (
                "可变数量的 (函数名, 参数字典) 或 (函数名, 参数字典, \"名称\") 元组。"
                "kwargs 值可以是任意 Python 对象，直接引用变量名即可，无需序列化。"
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

    def forward(self, *tasks, timeout: int = 120, max_workers: int = 4):
        """Execute the tasks in parallel.

        Each positional argument is a 2-tuple ``(func, kwargs)`` or
        3-tuple ``(func, kwargs, \"name\")``.

        Returns a list (all 2-tuples) or dict (all 3-tuples).
        """
        return _parallel_executor(*tasks, timeout=timeout, max_workers=max_workers)


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------

def _parallel_executor(*tasks, timeout: int = 120, max_workers: int = 4):
    if not tasks:
        return []

    n = len(tasks)

    # ----- detect output mode -----
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
                "(callable, kwargs_dict) or 3-tuple (callable, kwargs_dict, name)."
            )
        names = [None] * n

    results = [None] * n

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx: Dict[concurrent.futures.Future, int] = {}
        for idx, t in enumerate(tasks):
            func, kwargs = t[0], t[1]
            if not isinstance(kwargs, dict):
                results[idx] = (
                    f"[{names[idx] or f'task-{idx}'}] Invalid: "
                    f"kwargs must be a dict, got {type(kwargs).__name__}"
                )
                continue
            if not callable(func):
                results[idx] = (
                    f"[{names[idx] or f'task-{idx}'}] Not callable: "
                    f"{type(func).__name__}"
                )
                continue
            future_to_idx[pool.submit(func, **kwargs)] = idx

        # Iterate directly over futures so that per-task timeout is effective.
        # as_completed would wait for each future to finish before yielding,
        # which makes future.result(timeout=…) a no-op.
        for future, idx in future_to_idx.items():
            label = names[idx] or f"task-{idx}"
            try:
                results[idx] = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                results[idx] = f"[{label}] Timed out after {timeout}s."
            except Exception:
                import traceback as _tb
                results[idx] = f"[{label}] Failed: {_tb.format_exc(limit=1)}"

    if has_names:
        return {names[idx]: results[idx] for idx in range(n)}
    return results
