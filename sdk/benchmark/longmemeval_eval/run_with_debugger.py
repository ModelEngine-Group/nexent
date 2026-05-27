#!/usr/bin/env python3
"""Run LongMemEval benchmark with ContextDebugger attached for Langfuse export.

Usage:
    # Option 1: Smoke test (default schema)
    NEXENT_CONTEXT_DEBUG=/tmp/longmemeval_smoke.jsonl \
      python run_with_debugger.py \
        --dialogue_index 0 --limit 1 --max_ingest_sessions 20 \
        --token_threshold 200000 --baseline_context_chars 800000 \
        --sessions_per_batch 12 --keep_recent_pairs 10 --summary_schema default

    # Option 2: Single dialogue with 10 questions (multi_topic schema - recommended)
    NEXENT_CONTEXT_DEBUG=/tmp/longmemeval_q10_multi.jsonl \
      python run_with_debugger.py \
        --dialogue_index 0 --limit 10 \
        --token_threshold 200000 --baseline_context_chars 800000 \
        --sessions_per_batch 12 --keep_recent_pairs 10 --summary_schema multi_topic

    # Option 3: Full 60 questions (multi_topic schema)
    NEXENT_CONTEXT_DEBUG=/tmp/longmemeval_q60_multi.jsonl \
      python run_with_debugger.py \
        --dialogue_index 0 --limit 60 \
        --token_threshold 200000 --baseline_context_chars 800000 \
        --sessions_per_batch 12 --keep_recent_pairs 10 --summary_schema multi_topic

Export to Langfuse:
    python -m ctx_debugger.langfuse_export <trace.jsonl> \
      --session-id longmemeval-ctx0-question10-multi \
      --host http://localhost:3100
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCHMARK_DIR = os.path.dirname(HERE)
SDK_DIR = os.path.dirname(BENCHMARK_DIR)
CTX_DEBUGGER_DIR = os.path.join(SDK_DIR, "ctx_debugger")

for p in (SDK_DIR, BENCHMARK_DIR, HERE, CTX_DEBUGGER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

TRACE_PATH = os.environ.get(
    "NEXENT_CONTEXT_DEBUG", "/tmp/nexent_longmemeval_trace.jsonl"
)
os.environ["NEXENT_CONTEXT_DEBUG"] = TRACE_PATH


def _install_auto_attach():
    """Wrap CoreAgent.__init__ to auto-attach debugger."""
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

    os.chdir(HERE)
    from run_longmemeval import main as longmemeval_main, _build_arg_parser

    args = _build_arg_parser().parse_args()
    asyncio.run(longmemeval_main(args))
    print(f"\n[ctx_debugger] Trace written to: {TRACE_PATH}")


if __name__ == "__main__":
    main()