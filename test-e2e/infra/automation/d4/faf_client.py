# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Create and clean only the current D4 journey's real-model FAF fixtures."""

import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.auth import sign_in
from shared.faf import prepare_faf_agents, cleanup_faf_agents


async def run(operation):
    identity = await sign_in('tenant_a_admin')
    path = Path(os.environ['RESULT_DIR']) / 'runtime/faf-fixtures.json'
    if operation == 'setup':
        fixtures = await prepare_faf_agents(identity, 'FAF-D4-001')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fixtures, indent=2), encoding='utf-8')
        return fixtures
    if operation != 'cleanup':
        raise ValueError('Expected setup or cleanup')
    if path.is_file():
        await cleanup_faf_agents(identity, json.loads(path.read_text(encoding='utf-8')))
    return {'cleaned': True}


if __name__ == '__main__':
    try:
        print(json.dumps(asyncio.run(run(sys.argv[1]))))
    except Exception as exc:
        # Requests may include credentials; expose only the error class.
        print(type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
