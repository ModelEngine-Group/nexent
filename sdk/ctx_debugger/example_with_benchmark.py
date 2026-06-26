"""Run the existing benchmark with ContextDebugger attached, full layers,
without touching benchmark or SDK source.

Strategy: monkey-patch the smolagents agent class so every newly-created
agent auto-attaches a debugger after __init__. The compression-only entry
point (attaching to ContextManager directly) is no longer needed in this
example because attaching to the agent picks up the cm anyway.

Run from this directory (sdk/ctx_debugger); ../../ is the nexent repo root:
    ../../backend/.venv/bin/python example_with_benchmark.py

Trace lands at $NEXENT_CONTEXT_DEBUG or /tmp/nexent_ctx_trace.jsonl by default.
"""

import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.dirname(HERE)
BENCHMARK_DIR = os.path.join(SDK_DIR, "benchmark")

for p in (SDK_DIR, BENCHMARK_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

TRACE_PATH = os.environ.get(
    "NEXENT_CONTEXT_DEBUG", "/tmp/nexent_ctx_trace.jsonl"
)
os.environ["NEXENT_CONTEXT_DEBUG"] = TRACE_PATH


def _install_auto_attach():
    """Wrap CoreAgent.__init__ so every agent auto-attaches a debugger, AND
    CoreAgent.__setattr__ so a later assignment of `context_manager` wires the
    compression layer using the agent's existing debugger (single run_id).

    This avoids the dual-patch fragmentation: a ContextManager assigned to an
    agent that already has a debugger reuses that debugger's run_id, so
    compress_* events and llm_call(tag=compression) events live in the same
    run.
    """
    from nexent.core.agents.core_agent import CoreAgent
    from ctx_debugger import attach_debugger
    from ctx_debugger.debugger import _wrap_compress_if_needed
    import logging
    log = logging.getLogger(__name__)

    original_agent_init = CoreAgent.__init__

    def patched_agent_init(self, *args, **kwargs):
        original_agent_init(self, *args, **kwargs)
        try:
            attach_debugger(self, append=True)
        except Exception as exc:
            log.warning("Agent auto-attach failed: %s", exc, exc_info=True)

    def patched_setattr(self, name, value):
        object.__setattr__(self, name, value)
        if (
            name == "context_manager"
            and value is not None
            and getattr(value.config, "enabled", False)
        ):
            existing_dbg = getattr(self, "_debugger", None)
            if existing_dbg is None:
                return
            if getattr(value, "_debugger", None) is existing_dbg:
                return
            try:
                _wrap_compress_if_needed(value, existing_dbg)
            except Exception as exc:
                log.warning("Compression layer attach failed: %s", exc, exc_info=True)

    CoreAgent.__init__ = patched_agent_init
    CoreAgent.__setattr__ = patched_setattr


def main():
    _install_auto_attach()

    os.chdir(BENCHMARK_DIR)
    from test_benchmark import main as bench_main

    asyncio.run(bench_main())
    print(f"\n[ctx_debugger] Trace written to: {TRACE_PATH}")


if __name__ == "__main__":
    main()
