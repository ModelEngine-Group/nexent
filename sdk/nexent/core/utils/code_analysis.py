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


def _render_arg_value(node: ast.AST, max_value_len: int) -> str:
    """Render one call-argument value.

    The compression rule is deliberately **semantic-agnostic**: it never looks
    at the parameter *name* (we cannot know which tool's params matter). It
    decides purely by the *rendered size* of the value:

    - Numbers / bools / None -> always kept verbatim (tiny, often pivotal).
    - Strings <= ``max_value_len`` -> kept verbatim (quoted via ``repr``).
    - Strings  > ``max_value_len`` -> ``<str:N chars>`` placeholder.
    - Any other expression (variable, nested call, list/dict literal):
      unparsed to source, kept if short, else ``<kind:N chars>``.

    This means short scalars like ``file_path="a.txt"`` survive while big
    payloads like a 5KB ``content=...`` collapse to a self-describing hint,
    with no per-tool configuration.
    """
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, str):
            return repr(v) if len(v) <= max_value_len else f"<str:{len(v)} chars>"
        # int / float / bool / None: always compact and frequently the
        # decision-critical args (ids, flags, thresholds) -> keep verbatim.
        return repr(v)
    try:
        src = ast.unparse(node)  # Python 3.9+; project requires >=3.10
    except Exception:
        return "<expr>"
    if len(src) <= max_value_len:
        return src
    return f"<{type(node).__name__.lower()}:{len(src)} chars>"


def _render_call_signature(node: ast.Call, max_value_len: int, max_sig_len: int) -> str:
    """Render a single ``tool(...)`` call into a compact, length-bounded signature."""
    parts: List[str] = []
    for arg in node.args:  # positional
        parts.append(_render_arg_value(arg, max_value_len))
    for kw in node.keywords:  # keyword (kw.arg is None for ``**kwargs``)
        name = kw.arg if kw.arg is not None else "**"
        parts.append(f"{name}={_render_arg_value(kw.value, max_value_len)}")
    sig = f"{node.func.id}(" + ", ".join(parts) + ")"
    if len(sig) > max_sig_len:
        sig = sig[:max_sig_len] + f"...(+{len(parts)} args)"
    return sig


def extract_invoked_tool_signatures(
    code_action: str,
    registered_tools: dict,
    max_value_len: int = 60,
    max_sig_len: int = 200,
) -> List[str]:
    """Extract compact call *signatures* for registered tools invoked in code.

    Unlike :func:`extract_invoked_tools` (which returns bare names), this keeps
    the call shape -- e.g. ``write_file(file_path='ana.txt', content=analysis)``
    -- so that a compacted TOOL_CALL message preserves causal information
    (which file, which id) even if the assistant's ``<code>`` text is later
    truncated, while large argument values are replaced by size-describing
    placeholders to avoid duplicating the payload already present verbatim in
    ``model_output``.

    Nested calls that appear *as arguments* to another call are not emitted as
    separate top-level entries (they already show up inside the parent
    signature). Order of first appearance is preserved.

    Falls back to the bare tool name for any individual call whose signature
    rendering raises, and returns ``[]`` on syntax errors -- it must never
    raise into the rendering path.
    """
    if not code_action:
        return []
    try:
        tree = ast.parse(code_action)
    except SyntaxError:
        logger.warning("Failed to parse code_action for invoked_tool signatures")
        return []

    # Collect Call nodes that are themselves arguments of another Call, so we
    # can skip emitting them as standalone top-level signatures.
    nested_arg_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for sub in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(sub, ast.Call):
                    nested_arg_calls.add(id(sub))

    signatures: List[str] = []
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id not in registered_tools:
            continue
        if id(node) in nested_arg_calls:
            continue
        try:
            sig = _render_call_signature(node, max_value_len, max_sig_len)
        except Exception:
            sig = node.func.id
        if sig not in seen:
            seen.add(sig)
            signatures.append(sig)
    return signatures