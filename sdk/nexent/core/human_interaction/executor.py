"""Small JSON-only interpreter with stable call slots and no Python eval/exec.

The entire program is validated before dispatch. Imports, attributes, loops,
callbacks, comprehensions, and arbitrary host objects are intentionally absent.
"""

import ast
from types import SimpleNamespace

from .codec import json_copy
from .contracts import StepSteered


class UnsupportedResumableExecution(ValueError):
    pass


class LinearToolExecutor:
    def __init__(self, runtime):
        self.runtime = runtime
        self.state = {}
        self.tools = {}

    def send_variables(self, variables):
        self.state.update(json_copy(variables))

    def send_tools(self, tools):
        self.tools = dict(tools)

    def _validate_expr(self, node, *, call_allowed=False):
        if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool, type(None)):
            return
        if isinstance(node, ast.Name) and not node.id.startswith("_"):
            return
        if isinstance(node, (ast.List, ast.Tuple)):
            for item in node.elts:
                self._validate_expr(item)
            return
        if isinstance(node, ast.Dict) and all(key is not None for key in node.keys):
            for item in [*node.keys, *node.values]:
                self._validate_expr(item)
            return
        if isinstance(node, ast.Subscript):
            self._validate_expr(node.value)
            self._validate_expr(node.slice)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            self._validate_expr(node.operand)
            return
        if call_allowed and isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in {*self.tools, "print"}:
                raise UnsupportedResumableExecution("Call an explicitly registered tool by name")
            for value in [*node.args, *(item.value for item in node.keywords)]:
                self._validate_expr(value)
            if any(item.arg is None for item in node.keywords):
                raise UnsupportedResumableExecution("Expanded keyword arguments are not supported")
            return
        raise UnsupportedResumableExecution(
            "UNSUPPORTED_RESUMABLE_EXECUTION: use linear assignments and registered tool calls with JSON values; "
            "split complex work into separate steps. Imports, attributes and nested calls are unavailable."
        )

    def _value(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return json_copy(self.state[node.id])
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._value(item) for item in node.elts]
        if isinstance(node, ast.Dict):
            result = {self._value(key): self._value(value) for key, value in zip(node.keys, node.values)}
            if any(not isinstance(key, str) for key in result):
                raise ValueError("JSON object keys must be strings")
            return result
        if isinstance(node, ast.Subscript):
            return self._value(node.value)[self._value(node.slice)]
        if isinstance(node, ast.UnaryOp):
            value = self._value(node.operand)
            if type(value) not in (int, float):
                raise ValueError("Unary signs require JSON numbers")
            return -value if isinstance(node.op, ast.USub) else value
        raise UnsupportedResumableExecution("Unsupported expression")

    def __call__(self, code):
        tree = ast.parse(code)
        if len(tree.body) > 64:
            raise UnsupportedResumableExecution("Split the action into at most 64 statements")
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                if (len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name)
                        or statement.targets[0].id.startswith("_")):
                    raise UnsupportedResumableExecution("Only simple variable assignments are supported")
            elif not isinstance(statement, ast.Expr):
                raise UnsupportedResumableExecution("Only linear assignments and tool calls are supported")
            self._validate_expr(statement.value, call_allowed=True)

        logs = []
        output = None
        for index, statement in enumerate(tree.body):
            node = statement.value
            if isinstance(node, ast.Call):
                name = node.func.id
                args = [self._value(item) for item in node.args]
                kwargs = {item.arg: self._value(item.value) for item in node.keywords}
                if name == "print":
                    if kwargs:
                        raise UnsupportedResumableExecution("print supports positional JSON values only")
                    logs.append(" ".join(str(item) for item in args))
                    output = None
                else:
                    if self.runtime.safe_boundary():
                        raise StepSteered()
                    output = self.runtime.call(str(index), name, args, kwargs, self.tools[name])
                    if name == "final_answer":
                        return SimpleNamespace(output=output, logs="\n".join(logs), is_final_answer=True)
            else:
                output = self._value(node)
            if isinstance(statement, ast.Assign):
                self.state[statement.targets[0].id] = json_copy(output)
        self.state["_print_outputs"] = "\n".join(logs)
        return SimpleNamespace(output=output, logs="\n".join(logs), is_final_answer=False)
