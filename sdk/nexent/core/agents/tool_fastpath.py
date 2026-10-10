"""Restricted official-tool actions with deferred ordinary executor creation."""

from __future__ import annotations

import ast
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from types import ModuleType
from typing import Any

from smolagents.default_tools import FinalAnswerTool
from smolagents.local_python_executor import LocalPythonExecutor


OFFICIAL_FASTPATH_TOOL_CLASSES = (
    "KnowledgeBaseSearchTool",
    "ReadSkillMdTool",
    "ReadSkillConfigTool",
    "AidpSearchTool",
)
_INTERNAL_VARIABLES = frozenset({"__name__", "_operations_count", "_print_outputs"})
_JSON_FUNCTIONS = {"loads": json.loads, "dumps": json.dumps}


def _json_import_target(value: Any) -> str | None:
    """Identify real JSON functions and the interpreter's safe module copy."""
    if type(value) is ModuleType:
        members = vars(value)
        module_name = members.get("__name__")
        if type(module_name) is str and module_name == "json" and all(
            members.get(name) is function for name, function in _JSON_FUNCTIONS.items()
        ):
            return "json"
    for name, function in _JSON_FUNCTIONS.items():
        if value is function:
            return f"json.{name}"
    return None


def _json_import_bindings(statement: ast.AST) -> dict[str, str]:
    """Describe only the explicitly admitted JSON import forms."""
    if isinstance(statement, ast.Import) and all(alias.name == "json" for alias in statement.names):
        return {alias.asname or alias.name: "json" for alias in statement.names}
    if (
        isinstance(statement, ast.ImportFrom) and statement.module == "json" and statement.level == 0
        and all(alias.name in _JSON_FUNCTIONS for alias in statement.names)
    ):
        return {alias.asname or alias.name: f"json.{alias.name}" for alias in statement.names}
    return {}


def official_fastpath_tools(
    configurations: Sequence[Any], tools: Sequence[Any], allowed_classes: Sequence[str],
) -> dict[str, Any]:
    """Bind exact official implementations created through trusted factory sources."""
    from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool
    from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
    from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
    from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool

    implementations = {
        cls.__name__: cls for cls in (KnowledgeBaseSearchTool, ReadSkillMdTool, ReadSkillConfigTool, AidpSearchTool)
    }
    unknown = set(allowed_classes) - implementations.keys()
    if unknown:
        raise ValueError(f"Unknown official fast-path tool classes: {', '.join(sorted(unknown))}")
    return {
        tool.name: tool
        for config, tool in zip(configurations, tools, strict=True)
        if config.source in {"local", "builtin"}
        and config.class_name in allowed_classes
        and type(tool) is implementations[config.class_name]
    }


def is_simple_whitelisted_action(
    code: str, allowed_tool_names: set[str], variables: Mapping[str, Any],
    imports: Mapping[str, str] | None = None,
) -> bool:
    """Admit a complete positive grammar before executing any part of an action."""
    if not isinstance(code, str) or len(code.encode("utf-8")) > 65536:
        return False
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return False
    if not tree.body or len(tree.body) > 64 or sum(1 for _ in ast.walk(tree)) > 1000:
        return False
    available = set(variables) - _INTERNAL_VARIABLES
    assigned: set[str] = set()
    reserved = allowed_tool_names | {"print", "final_answer"} | _INTERNAL_VARIABLES
    bindings = {
        name: target for name, target in (imports or {}).items()
        if _json_import_target(variables.get(name)) == target
    }

    def json_call(node: ast.Call) -> bool:
        function = node.func
        if isinstance(function, ast.Name):
            return bindings.get(function.id) in {"json.loads", "json.dumps"}
        return (
            isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name)
            and bindings.get(function.value.id) == "json" and function.attr in _JSON_FUNCTIONS
        )

    def basic(value: Any, seen: set[int], depth: int = 0) -> bool:
        if depth > 32:
            return False
        if type(value) in {str, int, float, bool, bytes, type(None)}:
            return True
        if type(value) not in {list, tuple, dict} or id(value) in seen:
            return False
        seen = seen | {id(value)}
        children = (*value.keys(), *value.values()) if type(value) is dict else value
        return all(basic(item, seen, depth + 1) for item in children)

    def data(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return basic(node.value, set())
        if isinstance(node, ast.Name):
            return (
                node.id not in reserved and node.id not in bindings and not node.id.startswith("__")
                and node.id in available
                and (node.id in assigned or basic(variables[node.id], set()))
            )
        if isinstance(node, (ast.List, ast.Tuple)):
            return all(data(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            return all(
                isinstance(key, ast.Constant) and basic(key.value, set()) and data(value)
                for key, value in zip(node.keys, node.values)
            )
        if isinstance(node, ast.UnaryOp):
            return (
                isinstance(node.op, (ast.UAdd, ast.USub))
                and isinstance(node.operand, ast.Constant)
                and type(node.operand.value) in {int, float}
            )
        if isinstance(node, ast.Call):
            return json_call(node) and call(node, False)
        return False

    def call(node: ast.Call, terminal: bool) -> bool:
        if not json_call(node):
            if not isinstance(node.func, ast.Name):
                return False
            name = node.func.id
            if name not in allowed_tool_names | {"print", "final_answer"}:
                return False
            if name in variables:
                return False
            if name == "final_answer" and not terminal:
                return False
        return all(data(arg) for arg in node.args) and all(
            keyword.arg is not None and data(keyword.value) for keyword in node.keywords
        )

    for index, statement in enumerate(tree.body):
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            imported = _json_import_bindings(statement)
            if len(imported) != len(statement.names) or any(
                name in reserved or name == "super" or name.startswith("__") for name in imported
            ):
                return False
            if any(
                name in variables and name not in bindings and not basic(variables[name], set())
                for name in imported
            ):
                return False
            bindings.update(imported)
            available.difference_update(imported)
            assigned.difference_update(imported)
        elif isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                return False
            name = statement.targets[0].id
            if name in reserved or name in bindings or name.startswith("__"):
                return False
            value = statement.value
            if not (call(value, False) if isinstance(value, ast.Call) else data(value)):
                return False
            available.add(name)
            assigned.add(name)
        elif isinstance(statement, ast.Expr):
            value = statement.value
            if not isinstance(value, ast.Call) or not call(value, index == len(tree.body) - 1):
                return False
        else:
            return False
    return True


class DeferredToolExecutor:
    """Reuse local interpreter state until the first ordinary action is needed."""

    def __init__(
        self,
        create_executor: Callable[[], Any],
        release_executor: Callable[[Any], None],
        allowed_tools: Mapping[str, Any],
        stop_event: threading.Event | None = None,
    ) -> None:
        self.local = LocalPythonExecutor(additional_authorized_imports=["json"])
        self.remote: Any = None
        self._create_executor = create_executor
        self._release_executor = release_executor
        self._allowed_tools = dict(allowed_tools)
        self._tools: dict[str, Any] = {}
        self._variable_names: set[str] = set()
        self._imports: dict[str, str] = {}
        self._stop_event = stop_event
        self._lock = threading.RLock()
        self._closed = False

    @property
    def container(self) -> Any:
        """Expose an acquired container without triggering initialization."""
        return getattr(self.remote, "container", None)

    @property
    def _nexent_backend(self) -> str:
        """Report the backend actually executing the current action."""
        return "local" if self.remote is None else getattr(self.remote, "_nexent_backend", "unknown")

    @property
    def state(self) -> dict[str, Any]:
        """Expose interpreter diagnostics without retrieving remote user state."""
        return self.local.state if self.remote is None else getattr(self.remote, "state", {})

    def _check_active(self) -> None:
        if self._closed:
            raise RuntimeError("Deferred tool executor is closed")
        if self._stop_event is not None and self._stop_event.is_set():
            raise RuntimeError("Agent execution cancelled")

    def send_tools(self, tools: dict[str, Any]) -> None:
        with self._lock:
            self._check_active()
            self._tools = dict(tools)
            admitted = {
                name: tool for name, tool in tools.items()
                if self._allowed_tools.get(name) is tool
            }
            final_answer = tools.get("final_answer")
            if type(final_answer) is FinalAnswerTool:
                admitted["final_answer"] = final_answer
            self.local.send_tools(admitted)
            if self.remote is not None:
                self.remote.send_tools(tools)

    def send_variables(self, variables: dict[str, Any]) -> None:
        with self._lock:
            self._check_active()
            self._variable_names.update(set(variables) - _INTERNAL_VARIABLES)
            self.local.send_variables(variables)
            if self.remote is not None:
                self.remote.send_variables(variables)

    def export_user_variables(self) -> dict[str, Any]:
        """Keep aliases while omitting tool objects and interpreter-owned buffers."""
        imports = self._active_imports()
        return {
            name: self.local.state[name]
            for name in self._variable_names
            if name in self.local.state
            and name not in imports
            and all(self.local.state[name] is not tool for tool in self._tools.values())
        }

    def _active_imports(self) -> dict[str, str]:
        """Drop bindings replaced by subsequently supplied run variables."""
        return {
            name: target for name, target in self._imports.items()
            if _json_import_target(self.local.state.get(name)) == target
        }

    def __call__(self, code: str) -> Any:
        from .sandbox import _execute_with_tool_context

        with self._lock:
            self._check_active()
            if self.remote is None:
                allowed = {
                    name for name, tool in self._allowed_tools.items()
                    if self._tools.get(name) is tool
                }
                # final_answer is a framework primitive only when its real tool is bound.
                admitted = is_simple_whitelisted_action(code, allowed, self.local.state, self._active_imports())
                if admitted and any(
                    isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "final_answer"
                    for node in ast.walk(ast.parse(code))
                ):
                    admitted = type(self._tools.get("final_answer")) is FinalAnswerTool
                if admitted:
                    statements = ast.parse(code).body
                    self._variable_names.update(
                        node.targets[0].id
                        for node in statements if isinstance(node, ast.Assign)
                    )
                    import_names = set(self._imports)
                    for statement in statements:
                        import_names.update(_json_import_bindings(statement))
                    try:
                        return self.local(code)
                    finally:
                        # Retain only bindings actually established before a local error.
                        self._imports = {
                            name: target for name in import_names
                            if (target := _json_import_target(self.local.state.get(name))) is not None
                        }
                executor = self._create_executor()
                try:
                    self._check_active()
                    executor.send_tools(self._tools)
                    executor.send_variables(self.export_user_variables())
                    self._check_active()
                    imports = self._active_imports()
                    if imports:
                        source = "\n".join(
                            f"import json as {name}" if target == "json"
                            else f"from json import {target.removeprefix('json.')} as {name}"
                            for name, target in sorted(imports.items())
                        )
                        _execute_with_tool_context(executor, source)
                        self._check_active()
                except BaseException:
                    self._release_executor(executor)
                    raise
                self.remote = executor
            return _execute_with_tool_context(self.remote, code)

    def cleanup(self) -> None:
        """Release initialized resources once; never initialize during cleanup."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self.remote is not None:
                self._release_executor(self.remote)
