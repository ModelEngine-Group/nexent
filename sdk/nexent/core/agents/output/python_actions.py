# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Restricted Python call grammar shared by code-action execution protocols."""

import ast


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
