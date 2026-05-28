"""Code analysis utilities for extracting tool usage information from agent-generated code."""

import ast
import logging
from typing import List

logger = logging.getLogger("code_analysis")


def extract_invoked_tools(code_action: str, registered_tools: dict) -> List[str]:
    """Extract registered tool names called in code_action via AST analysis.

    Walks the AST to find all ``ast.Call`` nodes whose func is an ``ast.Name``,
    then intersects with the keys of *registered_tools* (typically
    ``self.tools`` on the agent).  Returns a **sorted** list of matched tool
    names (duplicates removed).

    Known limitations (acceptable gaps):
    - Variable aliases (``fn = tool; fn()``) — resolved at runtime, not in AST.
    - Dynamic dispatch (``globals()[name]()``) — same reason.
    These patterns are exceedingly rare in LLM-generated CodeAgent code.

    Args:
        code_action: The Python code string from ``action_step.code_action``.
        registered_tools: Dict mapping tool name -> tool object (e.g. ``self.tools``).
            Only the keys are used; values are ignored.

    Returns:
        Sorted list of tool names that are both called in *code_action* and
        present in *registered_tools*.  Empty list when no tools are called
        or *code_action* has syntax errors.
    """
    if not code_action:
        return []
    try:
        tree = ast.parse(code_action)
    except SyntaxError:
        logger.warning("Failed to parse code_action for invoked_tools extraction")
        return []
    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
    return sorted(name for name in called_names if name in registered_tools)
