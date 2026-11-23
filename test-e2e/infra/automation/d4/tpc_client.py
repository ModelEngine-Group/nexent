# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prepare TPC browser assets without exposing authentication in stdout."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.tpc import setup


if __name__ == '__main__':
    try:
        fixture = asyncio.run(setup('TPC-D4-001'))
        print(json.dumps({key: value for key, value in fixture.items() if key != 'token'}))
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
