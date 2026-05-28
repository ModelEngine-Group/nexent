"""Run the EventQA benchmark with ContextDebugger attached (all layers).

Same auto-attach strategy as example_with_benchmark.py, but targets the
EventQA runner (sdk/benchmark/eventqa_eval/run_eventqa.py). Every CLI argument
after the script name is forwarded straight to run_eventqa.

Run from this directory (sdk/ctx_debugger); ../../ is the nexent repo root:

    NEXENT_CONTEXT_DEBUG=/tmp/eventqa_trace.jsonl \\
      ../../backend/.venv/bin/python example_with_eventqa.py \\
      --book_index 0 --limit 1 --max_ingest_chars 200000

The trace lands at $NEXENT_CONTEXT_DEBUG (default /tmp/nexent_eventqa_trace.jsonl).
Export it to Langfuse with:
    python -m ctx_debugger.langfuse_export <trace.jsonl>
"""

import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.dirname(HERE)
BENCHMARK_DIR = os.path.join(SDK_DIR, "benchmark")
EVENTQA_DIR = os.path.join(BENCHMARK_DIR, "eventqa_eval")

for p in (SDK_DIR, BENCHMARK_DIR, EVENTQA_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

TRACE_PATH = os.environ.get(
    "NEXENT_CONTEXT_DEBUG", "/tmp/nexent_eventqa_trace.jsonl"
)
os.environ["NEXENT_CONTEXT_DEBUG"] = TRACE_PATH

# Reuse the CoreAgent auto-attach monkey-patch from the sibling example.
from example_with_benchmark import _install_auto_attach


def main():
    _install_auto_attach()

    os.chdir(EVENTQA_DIR)
    from run_eventqa import main as eventqa_main, _build_arg_parser

    args = _build_arg_parser().parse_args()
    asyncio.run(eventqa_main(args))
    print(f"\n[ctx_debugger] Trace written to: {TRACE_PATH}")


if __name__ == "__main__":
    main()
