# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging

_QUERY_FORMAT_ERR_MSG = "AI returned invalid format for test queries"

logger = logging.getLogger(__name__)

agent_run_manager = None

ALLOWED_BUILTINS = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "len": len,
    "range": range,
    "sorted": sorted,
    "reversed": reversed,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "any": any,
    "all": all,
    "isinstance": isinstance,
    "True": True,
    "False": False,
    "None": None,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
}

_EVALUATOR_FILENAME = "<evaluator>"

_EVENT_LABELS: dict[str, str] = {
    "tool": "runtime_label_tool",
    "kb": "runtime_label_kb",
    "log": "runtime_label_log",
    "artifact": "runtime_label_artifact",
    "file": "runtime_label_file",
    "error": "runtime_label_error",
}

_TRIMMABLE_TYPES: dict[str, str] = {
    "tool": "tool",
    "execution_logs": "log",
    "search_content": "kb",
    "skill_artifact": "artifact",
    "file_created": "file",
    "error": "error",
}

_SKIP_TYPES = frozenset({"step_count", "final_answer", "token_count"})
