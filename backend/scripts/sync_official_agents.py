"""Run official agent synchronization after a deployment is already running."""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.official_agent_sync_service import sync_official_agents


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize mounted official Agent bundles")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--profiles", default=None)
    args = parser.parse_args()
    kwargs = {}
    if args.base_dir is not None:
        kwargs["base_dir"] = args.base_dir
    if args.profiles is not None:
        kwargs["profiles"] = args.profiles
    result = asyncio.run(sync_official_agents(**kwargs))
    print(f"Synchronized {len(result)} official agent bundle(s)")
