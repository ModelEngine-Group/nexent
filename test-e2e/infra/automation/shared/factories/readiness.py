"""Bounded polling shared by asset producers, without importing test scenarios."""
import asyncio
import time
from shared.asset_registry import AssetTimeoutError, AssetDependencyError


async def wait_ready(read, *, ready, failed, timeout=300, interval=3,
                     section='asset', key='state'):
    if timeout <= 0 or interval <= 0:
        raise ValueError('timeout and interval must be positive')
    deadline = time.monotonic() + timeout
    while True:
        state, value = await read()
        if state in ready:
            return value
        if state in failed:
            raise AssetDependencyError(section, key, detail=f'producer terminal state={state}')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssetTimeoutError(f'{section}.{key} did not become ready in {timeout}s')
        await asyncio.sleep(min(interval, remaining))
