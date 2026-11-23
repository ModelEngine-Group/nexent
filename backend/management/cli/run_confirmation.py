# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run a locked suite on the trusted independent evaluator host."""

import argparse
import asyncio
import json
from pathlib import Path

from infrastructure.system_configuration.runtime import load_system_configuration
from management.services.evaluation.confirmation_runner import run_confirmation
from management.thread_management import config_thread_manager
from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager


async def execute(tenant, lock_id, path):
    load_system_configuration()
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        return await run_confirmation(tenant, lock_id, path)
    finally:
        clear_default_thread_manager(config_thread_manager)
        await config_thread_manager.shutdown(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_suite", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--lock", required=True, type=int)
    args = parser.parse_args()
    try:
        summary = asyncio.run(execute(args.tenant, args.lock, args.private_suite))
    except Exception as exc:
        parser.exit(2, f"Independent execution did not finalize ({type(exc).__name__}).\n")
    print(json.dumps(summary, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
