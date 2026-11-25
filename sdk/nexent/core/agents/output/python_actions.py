# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Restricted Python call grammar shared by code-action execution protocols."""

import ast


_PARALLEL_EXECUTOR = "parallel_executor"


def _authorized_parallel_call(call, names):
    parameters = ("tasks", "timeout", "max_workers")
    if len(call.args) > len(parameters):
        return False
    arguments = dict(zip(parameters, call.args))
    for keyword in call.keywords:
        if keyword.arg not in parameters or keyword.arg in arguments:
            return False
        arguments[keyword.arg] = keyword.value
    tasks = arguments.pop("tasks", None)
    if not isinstance(tasks, (ast.List, ast.Tuple)) or not tasks.elts:
        return False
    if any(not isinstance(value, ast.Constant) for value in arguments.values()):
        return False
    widths = set()
    for task in tasks.elts:
        if not isinstance(task, (ast.List, ast.Tuple)) or len(task.elts) not in (2, 3):
            return False
        widths.add(len(task.elts))
        target, kwargs, *label = task.elts
        if not isinstance(target, ast.Name) or target.id not in names or not isinstance(kwargs, ast.Dict):
            return False
        try:
            literal_kwargs = ast.literal_eval(kwargs)
        except (ValueError, TypeError, SyntaxError):
            return False
        if any(not isinstance(key, str) for key in literal_kwargs):
            return False
        if label and (not isinstance(label[0], ast.Constant) or not isinstance(label[0].value, str)):
            return False
    return len(widths) == 1


def is_delegation_action(code, names, *, allow_parallel=False):
    """Accept authorized collaborator calls and optional result assignment or printing."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, KeyError, TypeError):
        return False
    # Imports, attributes and indirect calls are outside the delegation action.
    dispatchers = names | {_PARALLEL_EXECUTOR} if allow_parallel else names
    allowed = (
        ast.Module,
        ast.Expr,
        ast.Assign,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Store,
        ast.keyword,
        ast.Constant,
        ast.Dict,
        ast.List,
        ast.Tuple,
    )
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
    variables = set()
    for assignment in assignments:
        if (
            not isinstance(assignment.value, ast.Call)
            or not isinstance(assignment.value.func, ast.Name)
            or assignment.value.func.id not in dispatchers
            or any(
                not isinstance(target, ast.Name) or target.id in dispatchers | {"print"}
                for target in assignment.targets
            )
        ):
            return False
        variables.update(target.id for target in assignment.targets)
    worker_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return False
        if isinstance(node, ast.Name) and node.id not in dispatchers | {"print"} | variables:
            return False
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in dispatchers | {"print"}:
                return False
            if allow_parallel and node.func.id == _PARALLEL_EXECUTOR:
                if not _authorized_parallel_call(node, names):
                    return False
                worker_calls += 1
            else:
                worker_calls += node.func.id in names
            if any(keyword.arg is None for keyword in node.keywords):
                return False
        if isinstance(node, ast.Assign) and any(not isinstance(target, ast.Name) for target in node.targets):
            return False
    return worker_calls > 0
