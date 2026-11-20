# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Restricted Python call grammar shared by code-action execution protocols."""

import ast


def is_parent_preparation_action(code, collaborator_names):
    """Recognize one Python action without delegate or final-answer calls."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, TypeError):
        return False
    reserved_names = collaborator_names | {"parallel_executor", "final_answer"}
    return bool(tree.body) and not any(
        isinstance(node, ast.Name) and node.id in reserved_names for node in ast.walk(tree)
    )


def is_delegation_action(code, names):
    """Accept direct collaborator calls and optional result assignment/printing only."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, KeyError, TypeError):
        return False
    # Before delegation, a text block is only a direct worker call, optional
    # assignment and print. Imports, attributes and indirect calls cannot act.
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
            or assignment.value.func.id not in names
            or any(
                not isinstance(target, ast.Name) or target.id in names | {"print"}
                for target in assignment.targets
            )
        ):
            return False
        variables.update(target.id for target in assignment.targets)
    worker_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return False
        if isinstance(node, ast.Name) and node.id not in names | {"print"} | variables:
            return False
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in names | {"print"}:
                return False
            worker_calls += node.func.id in names
            if any(keyword.arg is None for keyword in node.keywords):
                return False
        if isinstance(node, ast.Assign) and any(not isinstance(target, ast.Name) for target in node.targets):
            return False
    return worker_calls > 0


def parallel_delegation_targets(code, collaborator_names):
    """Read one literal parallel batch followed only by optional result printing."""
    try:
        body = ast.parse(code).body
    except (SyntaxError, ValueError, TypeError):
        return ()
    if not body:
        return ()

    result = None
    match body[0]:
        case ast.Assign(targets=[ast.Name(id=result)], value=ast.Call() as call):
            if result in collaborator_names | {"parallel_executor", "print", "final_answer"}:
                return ()
        case ast.Expr(value=ast.Call() as call):
            pass
        case _:
            return ()
    if not isinstance(call.func, ast.Name) or call.func.id != "parallel_executor":
        return ()

    arguments = dict(zip(("tasks", "timeout", "max_workers"), call.args))
    if len(call.args) > 3:
        return ()
    for keyword in call.keywords:
        if keyword.arg not in {"tasks", "timeout", "max_workers"} or keyword.arg in arguments:
            return ()
        arguments[keyword.arg] = keyword.value
    tasks = arguments.pop("tasks", None)
    if not isinstance(tasks, (ast.List, ast.Tuple)) or not tasks.elts:
        return ()
    for name, option in arguments.items():
        if not isinstance(option, ast.Constant):
            return ()
        value = option.value
        if name == "max_workers" and (type(value) is not int or value < min(2, len(tasks.elts))):
            return ()
        if name == "timeout" and value is not None and (
            type(value) not in (int, float) or not 0 < value < float("inf")
        ):
            return ()

    targets = []
    keys = set()
    for task in tasks.elts:
        match task:
            case ast.Tuple(elts=[ast.Name(id=name), ast.Dict() as kwargs, *key]):
                if name not in collaborator_names or len(key) > 1:
                    return ()
            case _:
                return ()
        try:
            if any(not isinstance(param, str) for param in ast.literal_eval(kwargs)):
                return ()
        except (ValueError, TypeError):
            return ()
        if key:
            if not isinstance(key[0], ast.Constant) or not isinstance(key[0].value, str) or not key[0].value:
                return ()
            keys.add(key[0].value)
        targets.append(name)
    if len(set(targets)) != len(targets) or (keys and len(keys) != len(targets)):
        return ()

    for statement in body[1:]:
        match statement:
            case ast.Expr(value=ast.Call(func=ast.Name(id="print"), args=values, keywords=[])):
                if not all(_is_parallel_result_value(value, result) for value in values):
                    return ()
            case _:
                return ()
    return tuple(targets)


def _is_parallel_result_value(value, result):
    if isinstance(value, ast.Constant):
        return True
    match value:
        case ast.Name(id=name) | ast.Subscript(value=ast.Name(id=name), slice=ast.Constant()):
            return name == result
    return False
