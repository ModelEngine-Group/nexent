# -*- coding: utf-8 -*-
"""Minimal smoke test for benchmark-on-refactor integration.

Goal: prove the refactor's ContextManager + component-based system prompt
assembly produces a working end-to-end agent run when driven from the
benchmark's agent_runner. Touches no production SDK code.

Run from this directory:

    LLM_API_KEY=... LLM_MODEL_NAME=... LLM_API_URL=... \
        ../../backend/.venv/bin/python smoke.py

Success criteria:
1. No ImportError / AttributeError at module load time.
2. agent_run returns at least one chunk and a non-empty final_answer.
3. The chosen LLM is actually called (i.e. we see model_output messages).

Failure here points at the smallest viable repro for adapting the rest of
the benchmark — the trail of exceptions IS the work list.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: F401 - side-effect: adds sdk/, backend/ to sys.path

from agent_runner import build_agent_run_info, run_agent_with_tracking


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smoke")


async def main():
    query = "中华人民共和国的首都是哪里？请用一句话回答。"

    agent_run_info = build_agent_run_info(
        query=query,
        history=[],
        duty_prompt="你是一个简明扼要的助手。",
        constraint_prompt="只回答用户问题，不要展开。",
        max_steps=3,
        temperature=0.0,
        agent_name="smoke_agent",
        agent_description="Smoke test agent",
        language="zh",
        is_manager=False,
    )

    logger.info("Running agent on query: %s", query)
    result = await run_agent_with_tracking(agent_run_info, debug=False)

    print("\n" + "=" * 60)
    print(f"final_answer ({len(result.final_answer)} chars):")
    print(result.final_answer)
    print("=" * 60)
    print(f"steps={result.step_count}  msg_counts={result.message_type_count}")
    if result.errors:
        print(f"errors={result.errors}")
    print("=" * 60)

    assert result.final_answer, "final_answer empty - smoke FAILED"
    assert not result.errors, f"errors during run: {result.errors}"
    print("\nSMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
