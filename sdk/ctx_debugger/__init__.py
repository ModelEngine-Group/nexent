"""External trace emitter for Nexent ContextManager.

Independent from Nexent runtime; only imports from nexent SDK. Zero changes
to SDK source code required.

Quick start:
    from ctx_debugger import attach_debugger
    from nexent.core.agents.agent_context import ContextManager

    cm = ContextManager(config=...)
    attach_debugger(cm, trace_path="/tmp/run.jsonl")
    # run the agent normally; events land in /tmp/run.jsonl

Or rely on the environment variable:
    export NEXENT_CONTEXT_DEBUG=/tmp/run.jsonl
    attach_debugger(cm)  # path auto-resolved from env
"""

from .debugger import ContextDebugger, attach_debugger

__all__ = ["ContextDebugger", "attach_debugger"]
