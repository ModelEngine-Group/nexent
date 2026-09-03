"""Run official agent synchronization after a deployment is already running."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.official_agent_sync_service import sync_official_agents


if __name__ == "__main__":
    result = asyncio.run(sync_official_agents())
    print(f"Synchronized {len(result)} official agent bundle(s)")
